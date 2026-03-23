"""
MiBud - Multi-Device Sync
Synchronize settings and state across multiple MiBud devices
"""

import asyncio
import json
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime

log = logging.getLogger("MiBud")


@dataclass
class DeviceInfo:
    """Information about a synced device"""
    device_id: str
    name: str
    ip_address: str
    last_seen: float
    is_online: bool
    personality: str
    battery: int


class SyncManager:
    """Manages multi-device synchronization"""
    
    def __init__(self, config, event_bus=None):
        self.config = config
        self.event_bus = event_bus
        self.device_id = self._get_device_id()
        self.device_name = config.get("network.hostname", "MiBud")
        self.is_server = False
        self._devices: Dict[str, DeviceInfo] = {}
        self._sync_tasks = []
        self._listeners: Dict[str, Callable] = {}
        self._sync_interval = 30
        self._discovery_port = 5253
        self._sync_port = 5254
        
    def _get_device_id(self) -> str:
        """Get or create unique device ID"""
        cache_dir = Path(__file__).parent.parent / "config"
        cache_dir.mkdir(parents=True, exist_ok=True)
        id_file = cache_dir / ".device_id"
        
        if id_file.exists():
            return id_file.read_text().strip()
        
        device_id = hashlib.sha256(
            f"{Path.home()}-{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]
        
        id_file.write_text(device_id)
        return device_id
        
    async def start_discovery(self):
        """Start device discovery on the network"""
        log.info("🔍 Starting device discovery...")
        
        try:
            import zeroconf
            from zeroconf.asyncio import AsyncZeroconf
            
            self._zeroconf = AsyncZeroconf()
            
            # Register our service
            service_info = zeroconf.ServiceInfo(
                "_mibud._tcp.local.",
                f"{self.device_name}._mibud._tcp.local.",
                addresses=[],
                port=self._sync_port,
                properties={
                    b"device_id": self.device_id.encode(),
                    b"version": "1.0"
                }
            )
            
            await self._zeroconf.async_register_service(service_info)
            
            # Browse for other devices
            log.info("🔍 Browsing for other MiBud devices...")
            
        except ImportError:
            log.warning("🔍 zeroconf not available - using manual sync")
        except Exception as e:
            log.warning(f"🔍 Discovery failed: {e}")
            
    async def discover_devices(self) -> List[DeviceInfo]:
        """Discover other MiBud devices on the network"""
        devices = []
        
        try:
            import socket
            
            # Broadcast discovery message
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(5)
            
            message = json.dumps({
                "type": "discovery",
                "device_id": self.device_id,
                "device_name": self.device_name,
                "port": self._sync_port
            })
            
            sock.sendto(message.encode(), ("<broadcast>", self._discovery_port))
            
            # Collect responses
            while True:
                try:
                    data, addr = sock.recvfrom(4096)
                    info = json.loads(data.decode())
                    
                    if info.get("type") == "discovery" and info.get("device_id") != self.device_id:
                        devices.append(DeviceInfo(
                            device_id=info["device_id"],
                            name=info["device_name"],
                            ip_address=addr[0],
                            last_seen=datetime.now().timestamp(),
                            is_online=True,
                            personality="assistant",
                            battery=100
                        ))
                except socket.timeout:
                    break
                    
            sock.close()
            
        except Exception as e:
            log.warning(f"🔍 Device discovery failed: {e}")
            
        return devices
        
    async def sync_to_peer(self, peer: DeviceInfo, data: Dict):
        """Sync data to a specific peer"""
        try:
            import socket
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((peer.ip_address, self._sync_port))
            
            message = json.dumps({
                "type": "sync",
                "from_device": self.device_id,
                "data": data,
                "timestamp": datetime.now().timestamp()
            })
            
            sock.send(message.encode())
            sock.close()
            
            log.info(f"🔄 Synced to {peer.name}")
            
        except Exception as e:
            log.warning(f"🔄 Sync to {peer.name} failed: {e}")
            
    async def receive_sync(self, data: Dict):
        """Receive and apply sync data from a peer"""
        log.info(f"🔄 Received sync data from {data.get('from_device')}")
        
        if "personality" in data.get("data", {}):
            new_personality = data["data"]["personality"]
            self.config.set("personality.current", new_personality)
            self.config.save()
            
        if self.event_bus:
            self.event_bus.dispatch("sync_received", data)
            
    def register_listener(self, key: str, callback: Callable):
        """Register a callback for sync events"""
        self._listeners[key] = callback
        
    def unregister_listener(self, key: str):
        """Unregister a sync listener"""
        if key in self._listeners:
            del self._listeners[key]
            
    async def sync_settings(self, settings: Dict):
        """Sync settings to all connected devices"""
        for device in self._devices.values():
            if device.is_online and device.device_id != self.device_id:
                await self.sync_to_peer(device, settings)
                
    async def request_sync_from_peer(self, peer: DeviceInfo) -> Optional[Dict]:
        """Request full sync data from a peer"""
        try:
            import socket
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((peer.ip_address, self._sync_port))
            
            message = json.dumps({
                "type": "sync_request",
                "from_device": self.device_id
            })
            
            sock.send(message.encode())
            
            data = sock.recv(4096)
            sock.close()
            
            return json.loads(data.decode())
            
        except Exception as e:
            log.warning(f"🔄 Sync request from {peer.name} failed: {e}")
            return None
            
    async def start_sync_server(self):
        """Start the sync server to handle incoming syncs"""
        log.info("🔄 Starting sync server...")
        self.is_server = True
        
        try:
            import socket
            
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", self._sync_port))
            server.listen(5)
            server.settimeout(30)
            
            while self.is_server:
                try:
                    client, addr = server.accept()
                    data = client.recv(4096)
                    
                    if data:
                        message = json.loads(data.decode())
                        
                        if message["type"] == "sync":
                            await self.receive_sync(message)
                        elif message["type"] == "sync_request":
                            response = {
                                "type": "sync_response",
                                "data": {
                                    "personality": self.config.get("personality.current"),
                                    "settings": self.config.data
                                }
                            }
                            client.send(json.dumps(response).encode())
                            
                    client.close()
                    
                except socket.timeout:
                    pass
                except Exception as e:
                    log.debug(f"Sync server: {e}")
                    
            server.close()
            
        except Exception as e:
            log.warning(f"🔄 Sync server failed: {e}")
            
    async def stop(self):
        """Stop sync services"""
        log.info("🔄 Stopping sync services...")
        self.is_server = False
        
        for task in self._sync_tasks:
            task.cancel()
            
    def get_devices(self) -> List[DeviceInfo]:
        """Get list of discovered devices"""
        return list(self._devices.values())
