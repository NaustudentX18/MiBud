"""
MiBud Hardware - Battery Manager
PiSugar 3 Battery Monitoring and Power Management
"""

import os
import logging
import platform
import asyncio
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("MiBud")

# PiSugar socket path
PISUGAR_SOCKET = "/tmp/pisugar-server.sock"
PISUGAR_I2C_ADDR = 0x69

@dataclass
class BatteryStatus:
    """Battery status information"""
    level: int = 100
    voltage: float = 4.2
    charging: bool = False
    low_battery: bool = False
    critical: bool = False
    temperature: float = 25.0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class BatteryManager:
    """Manages PiSugar 3 battery"""
    
    def __init__(self):
        self.is_initialized = False
        self.is_rpi = platform.machine().startswith(('arm', 'aarch'))
        self._i2c = None
        self._socket = None
        self._last_read = None
        self._cached_status: Optional[BatteryStatus] = None
        self._low_battery_threshold = 20
        self._critical_battery_threshold = 5
        
    async def initialize(self):
        """Initialize battery monitoring"""
        log.info("🔋 Initializing battery monitor...")
        
        if not self.is_rpi:
            log.info("🔋 Non-RPi platform - simulation mode")
            self.is_initialized = True
            return self._get_simulated_status()
            
        try:
            # Try I2C connection
            try:
                import smbus2
                self._i2c = smbus2.SMBus(1)
                self._i2c.read_byte_data(PISUGAR_I2C_ADDR, 0x0C)  # Test read
                log.info("🔋 PiSugar I2C initialized")
            except Exception as e:
                log.warning(f"🔋 I2C not available: {e}")
                
            # Try socket connection
            if os.path.exists(PISUGAR_SOCKET):
                try:
                    import socket
                    self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._socket.connect(PISUGAR_SOCKET)
                    log.info("🔋 PiSugar socket initialized")
                except Exception as e:
                    log.warning(f"🔋 Socket not available: {e}")
                    
        except Exception as e:
            log.warning(f"🔋 Battery init warning: {e}")
            
        self.is_initialized = True
        log.info("✅ Battery monitor initialized")
        
    def _get_simulated_status(self) -> BatteryStatus:
        """Get simulated battery status for non-RPi"""
        import random
        return BatteryStatus(
            level=random.randint(60, 95),
            voltage=3.7 + random.random() * 0.5,
            charging=False,
            timestamp=datetime.now()
        )
        
    def get_level(self) -> int:
        """Get battery percentage (0-100)"""
        status = self.get_status()
        return status.level
        
    def get_voltage(self) -> float:
        """Get battery voltage"""
        status = self.get_status()
        return status.voltage
        
    def get_status(self) -> BatteryStatus:
        """Get comprehensive battery status"""
        # Return cached if recent
        if self._cached_status:
            age = (datetime.now() - self._cached_status.timestamp).total_seconds()
            if age < 5:  # Cache for 5 seconds
                return self._cached_status
                
        status = self._read_status()
        self._cached_status = status
        return status
        
    def _read_status(self) -> BatteryStatus:
        """Read battery status from hardware"""
        if not self.is_rpi or self._i2c is None:
            return self._get_simulated_status()
            
        try:
            # Read battery level
            level = self._i2c.read_byte_data(PISUGAR_I2C_ADDR, 0x0C)
            
            # Read voltage
            voltage_data = self._i2c.read_word_data(PISUGAR_I2C_ADDR, 0x08)
            voltage = ((voltage_data & 0xFF) + ((voltage_data >> 8) & 0xFF)) / 100.0
            
            # Read status/charging
            status_byte = self._i2c.read_byte_data(PISUGAR_I2C_ADDR, 0x04)
            charging = (status_byte & 0x01) != 0
            
            return BatteryStatus(
                level=level if 0 <= level <= 100 else 50,
                voltage=voltage if 3.0 <= voltage <= 4.3 else 3.8,
                charging=charging,
                low_battery=level < self._low_battery_threshold,
                critical=level < self._critical_battery_threshold,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            log.debug(f"🔋 Battery read error: {e}")
            return self._get_simulated_status()
            
    def is_low(self) -> bool:
        """Check if battery is low"""
        return self.get_status().low_battery
        
    def is_critical(self) -> bool:
        """Check if battery is critical"""
        return self.get_status().critical
        
    def is_charging(self) -> bool:
        """Check if battery is charging"""
        return self.get_status().charging
        
    async def shutdown_if_needed(self):
        """Shutdown system if battery is critical"""
        if self.is_critical() and not self.is_charging():
            log.warning("🔋 Battery critical - initiating shutdown")
            # Could trigger graceful shutdown here
            os.system("sudo shutdown -h now")
            
    def get_formatted(self) -> str:
        """Get formatted battery string"""
        status = self.get_status()
        icon = "🔌" if status.charging else "🔋"
        return f"{icon}{status.level}%"
        
    async def cleanup(self):
        """Cleanup battery resources"""
        log.info("🔋 Battery cleanup")
        if self._i2c:
            try:
                self._i2c.close()
            except:
                pass
