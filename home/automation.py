"""
MiBud Home Automation Integration
GPIO Control & Home Assistant Integration
"""

import os
import logging
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger("MiBud")


class DeviceType(Enum):
    """Home automation device types"""
    LIGHT = "light"
    SWITCH = "switch"
    FAN = "fan"
    SENSOR = "sensor"
    LOCK = "lock"
    THERMOSTAT = "thermostat"
    COVER = "cover"


@dataclass
class Device:
    """Home automation device"""
    id: str
    name: str
    type: DeviceType
    state: bool = False
    brightness: int = 100
    entity_id: str = ""


class GPIOController:
    """Direct GPIO control for simple devices"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.is_initialized = False
        self._gpio = None
        
    async def initialize(self):
        """Initialize GPIO controller"""
        log.info("🏠 Initializing GPIO controller...")
        
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            
            # Setup default GPIO devices
            self._setup_default_devices()
            
            self.is_initialized = True
            log.info("✅ GPIO controller initialized")
            
        except ImportError:
            log.warning("🏠 RPi.GPIO not available")
        except Exception as e:
            log.warning(f"🏠 GPIO init error: {e}")
            
    def _setup_default_devices(self):
        """Setup default GPIO devices"""
        # LED on GPIO 18 (PWM)
        self.add_device(Device(
            id="status_led",
            name="Status LED",
            type=DeviceType.LIGHT,
            entity_id="gpio.18"
        ))
        
    def add_device(self, device: Device):
        """Add a device"""
        self.devices[device.id] = device
        
        if self._gpio and device.type == DeviceType.LIGHT:
            # Setup GPIO pin
            self._gpio.setup(device.entity_id.split('.')[-1], self._gpio.OUT)
            
        log.info(f"🏠 Added device: {device.name}")
        
    async def turn_on(self, device_id: str) -> bool:
        """Turn on a device"""
        device = self.devices.get(device_id)
        if not device:
            return False
            
        try:
            if self._gpio and device.type == DeviceType.LIGHT:
                pin = int(device.entity_id.split('.')[-1])
                self._gpio.output(pin, self._gpio.HIGH)
                
            device.state = True
            log.info(f"🏠 Turned on: {device.name}")
            return True
            
        except Exception as e:
            log.error(f"Failed to turn on {device_id}: {e}")
            return False
            
    async def turn_off(self, device_id: str) -> bool:
        """Turn off a device"""
        device = self.devices.get(device_id)
        if not device:
            return False
            
        try:
            if self._gpio and device.type == DeviceType.LIGHT:
                pin = int(device.entity_id.split('.')[-1])
                self._gpio.output(pin, self._gpio.LOW)
                
            device.state = False
            log.info(f"🏠 Turned off: {device.name}")
            return True
            
        except Exception as e:
            log.error(f"Failed to turn off {device_id}: {e}")
            return False
            
    async def set_brightness(self, device_id: str, brightness: int) -> bool:
        """Set device brightness (0-100)"""
        device = self.devices.get(device_id)
        if not device or device.type != DeviceType.LIGHT:
            return False
            
        try:
            if hasattr(self, '_led_pwm'):
                duty = int(brightness * 100 / 255)
                self._led_pwm.ChangeDutyCycle(duty)
                
            device.brightness = brightness
            log.info(f"🏠 Set brightness {device.name}: {brightness}%")
            return True
            
        except Exception as e:
            log.error(f"Failed to set brightness {device_id}: {e}")
            return False
            
    def get_device(self, device_id: str) -> Optional[Device]:
        """Get device by ID"""
        return self.devices.get(device_id)
        
    def get_all_devices(self) -> List[Device]:
        """Get all devices"""
        return list(self.devices.values())


class HomeAssistantClient:
    """Home Assistant API client"""
    
    def __init__(self, config):
        self.config = config
        self.base_url = os.environ.get("HA_URL", "http://homeassistant.local:8123")
        self.token = os.environ.get("HA_TOKEN", "")
        self.is_connected = False
        
    async def initialize(self):
        """Initialize Home Assistant client"""
        log.info("🏠 Initializing Home Assistant client...")
        
        # Get HA URL and token from config
        self.base_url = self.config.get("home_assistant.url", "http://homeassistant.local:8123")
        self.token = self.config.get("home_assistant.token", "")
        
        if not self.token:
            log.warning("🏠 No Home Assistant token configured")
            return
            
        try:
            # Test connection
            import requests
            response = requests.get(
                f"{self.base_url}/api/config",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=5
            )
            
            if response.status_code == 200:
                self.is_connected = True
                log.info("✅ Home Assistant connected")
            else:
                log.warning(f"🏠 HA connection failed: {response.status_code}")
                
        except Exception as e:
            log.warning(f"🏠 HA init error: {e}")
            
    async def call_service(self, domain: str, service: str, entity_id: str = None, data: Dict = None) -> bool:
        """Call a Home Assistant service"""
        if not self.is_connected:
            log.warning("🏠 Not connected to Home Assistant")
            return False
            
        try:
            import requests
            
            payload = {}
            if entity_id:
                payload["entity_id"] = entity_id
            if data:
                payload.update(data)
                
            response = requests.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                log.info(f"🏠 HA service called: {domain}.{service}")
                return True
            else:
                log.warning(f"🏠 HA service failed: {response.status_code}")
                return False
                
        except Exception as e:
            log.error(f"🏠 Service call error: {e}")
            return False
            
    async def turn_on_light(self, entity_id: str, brightness: int = 255) -> bool:
        """Turn on a light"""
        data = {"entity_id": entity_id}
        if brightness < 255:
            data["brightness"] = brightness
        return await self.call_service("light", "turn_on", data=data)
        
    async def turn_off_light(self, entity_id: str) -> bool:
        """Turn off a light"""
        return await self.call_service("light", "turn_off", entity_id)
        
    async def get_states(self) -> List[Dict]:
        """Get all entity states"""
        if not self.is_connected:
            return []
            
        try:
            import requests
            response = requests.get(
                f"{self.base_url}/api/states",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
                
        except Exception as e:
            log.error(f"🏠 Get states error: {e}")
            
        return []


class SmartHomeManager:
    """Unified smart home management"""
    
    def __init__(self, config):
        self.config = config
        self.gpio = GPIOController()
        self.ha = HomeAssistantClient(config)
        self.is_initialized = False
        
    async def initialize(self):
        """Initialize smart home system"""
        log.info("🏠 Initializing smart home system...")
        
        # Initialize GPIO
        await self.gpio.initialize()
        
        # Initialize Home Assistant
        await self.ha.initialize()
        
        self.is_initialized = True
        log.info("✅ Smart home system ready")
        
    async def control_device(self, command: str, device: str = None, value: Any = None) -> bool:
        """Control a device with natural language command"""
        command = command.lower()
        
        # Parse command
        if "turn on" in command or "switch on" in command or "enable" in command:
            if device:
                return await self._turn_on(device)
            else:
                # Try to find device in command
                return await self._handle_command("on", command)
                
        elif "turn off" in command or "switch off" in command or "disable" in command:
            if device:
                return await self._turn_off(device)
            else:
                return await self._handle_command("off", command)
                
        elif "dim" in command or "brightness" in command:
            return await self._handle_brightness(command, value)
            
        return False
        
    async def _turn_on(self, device: str) -> bool:
        """Turn on device"""
        # Try GPIO first
        gpio_device = self.gpio.get_device(device)
        if gpio_device:
            return await self.gpio.turn_on(device)
            
        # Try HA
        return await self.ha.turn_on_light(entity_id=device)
        
    async def _turn_off(self, device: str) -> bool:
        """Turn off device"""
        gpio_device = self.gpio.get_device(device)
        if gpio_device:
            return await self.gpio.turn_off(device)
            
        return await self.ha.turn_off_light(entity_id=device)
        
    async def _handle_command(self, action: str, command: str) -> bool:
        """Handle natural language command"""
        # Extract device from command
        if "light" in command or "lamp" in command:
            entity = "light.living_room"  # Would need entity matching
            if action == "on":
                return await self.ha.turn_on_light(entity)
            else:
                return await self.ha.turn_off_light(entity)
                
        log.warning(f"🏠 Could not understand command: {command}")
        return False
        
    async def _handle_brightness(self, command: str, value: int) -> bool:
        """Handle brightness command"""
        # Extract brightness level
        if value is None:
            # Parse from command
            import re
            match = re.search(r'(\d+)%?', command)
            if match:
                value = int(match.group(1))
            else:
                value = 100
                
        return await self.gpio.set_brightness("status_led", value)
