"""
MiBud - Anomaly Detection
Monitor patterns and detect unusual activity
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable
from collections import deque
from datetime import datetime, timedelta
import statistics

log = logging.getLogger("MiBud")


class AnomalyType:
    """Types of detectable anomalies"""
    UNUSUAL_TIME = "unusual_time"
    RAPID_FIRE = "rapid_fire"
    UNUSUAL_VOLUME = "unusual_volume"
    PATTERN_BREAK = "pattern_break"
    SENSOR_ANOMALY = "sensor_anomaly"


class AnomalyAlert:
    """Anomaly alert data"""
    
    def __init__(self, anomaly_type: str, severity: str, message: str, data: Dict = None):
        self.type = anomaly_type
        self.severity = severity
        self.message = message
        self.data = data or {}
        self.timestamp = datetime.now()
        
    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }


class AnomalyDetector:
    """Detect anomalies in MiBud usage patterns"""
    
    def __init__(self, config=None):
        self.config = config
        self.is_enabled = config.get("features.anomaly_detection", False) if config else False
        self._callbacks: List[Callable] = []
        self._alert_history: deque = deque(maxlen=100)
        
        self._request_times: deque = deque(maxlen=1000)
        self._request_counts: deque = deque(maxlen=100)
        self._audio_levels: deque = deque(maxlen=100)
        self._battery_levels: deque = deque(maxlen=100)
        
        self._baseline_requests_per_minute = 5
        self._baseline_audio_level = 500
        self._request_cooldown = 2.0
        self._last_request_time = 0
        
        self._is_monitoring = False
        self._monitor_task = None
        
    async def initialize(self):
        """Initialize anomaly detector"""
        log.info("🔔 Initializing anomaly detection...")
        
        if not self.is_enabled:
            log.info("🔔 Anomaly detection disabled")
            return
            
        log.info("✅ Anomaly detection ready")
        
    async def start_monitoring(self):
        """Start continuous anomaly monitoring"""
        if self._is_monitoring:
            return
            
        self._is_monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        log.info("🔔 Anomaly monitoring started")
        
    async def stop_monitoring(self):
        """Stop anomaly monitoring"""
        self._is_monitoring = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
                
        log.info("🔔 Anomaly monitoring stopped")
        
    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self._is_monitoring:
            try:
                await self._check_request_rate()
                await self._check_audio_levels()
                await self._check_battery_levels()
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"Anomaly monitor: {e}")
                
    def register_callback(self, callback: Callable[[AnomalyAlert], None]):
        """Register callback for anomaly alerts"""
        self._callbacks.append(callback)
        
    def _emit_alert(self, alert: AnomalyAlert):
        """Emit an anomaly alert"""
        self._alert_history.append(alert)
        log.warning(f"🔔 ANOMALY [{alert.severity}]: {alert.message}")
        
        for callback in self._callbacks:
            try:
                callback(alert)
            except Exception as e:
                log.error(f"Alert callback failed: {e}")
                
    async def record_request(self, request_type: str = "chat"):
        """Record a request for pattern analysis"""
        import time
        
        current_time = time.time()
        
        self._request_times.append(current_time)
        
        if current_time - self._last_request_time < self._request_cooldown:
            alert = AnomalyAlert(
                AnomalyType.RAPID_FIRE,
                "medium",
                f"Rapid fire requests detected",
                {"time_since_last": current_time - self._last_request_time}
            )
            self._emit_alert(alert)
            
        self._last_request_time = current_time
        
    async def record_audio_level(self, level: float):
        """Record audio level for anomaly detection"""
        self._audio_levels.append(level)
        
    async def record_battery_level(self, level: int):
        """Record battery level for anomaly detection"""
        self._battery_levels.append(level)
        
        if len(self._battery_levels) >= 10:
            recent = list(self._battery_levels)[-10:]
            
            if all(b > recent[0] for b in recent):
                alert = AnomalyAlert(
                    AnomalyType.SENSOR_ANOMALY,
                    "high",
                    "Battery level continuously increasing (sensor error?)",
                    {"levels": recent}
                )
                self._emit_alert(alert)
                
    async def _check_request_rate(self):
        """Check for unusual request rates"""
        if len(self._request_times) < 10:
            return
            
        current_time = asyncio.get_event_loop().time()
        recent = [t for t in self._request_times if current_time - t < 60]
        
        if len(recent) > self._baseline_requests_per_minute * 3:
            alert = AnomalyAlert(
                AnomalyType.UNUSUAL_TIME,
                "medium",
                f"High request rate: {len(recent)}/minute (baseline: {self._baseline_requests_per_minute})",
                {"requests_per_minute": len(recent)}
            )
            self._emit_alert(alert)
            
    async def _check_audio_levels(self):
        """Check for unusual audio patterns"""
        if len(self._audio_levels) < 10:
            return
            
        levels = list(self._audio_levels)
        
        try:
            mean = statistics.mean(levels)
            stdev = statistics.stdev(levels)
            
            if levels[-1] > mean + 3 * stdev:
                alert = AnomalyAlert(
                    AnomalyType.UNUSUAL_VOLUME,
                    "low",
                    f"Unusually loud audio detected",
                    {"level": levels[-1], "mean": mean, "stdev": stdev}
                )
                self._emit_alert(alert)
                
        except statistics.StatisticsError:
            pass
            
    async def _check_battery_levels(self):
        """Check for unusual battery patterns"""
        if len(self._battery_levels) < 5:
            return
            
        levels = list(self._battery_levels)
        
        try:
            mean = statistics.mean(levels)
            stdev = statistics.stdev(levels) if len(levels) > 1 else 0
            
            if stdev > 0 and levels[-1] > mean + 3 * stdev:
                alert = AnomalyAlert(
                    AnomalyType.SENSOR_ANOMALY,
                    "medium",
                    f"Unusual battery reading",
                    {"level": levels[-1], "mean": mean}
                )
                self._emit_alert(alert)
                
        except statistics.StatisticsError:
            pass
            
    def get_alert_history(self, since: datetime = None) -> List[Dict]:
        """Get alert history"""
        if since is None:
            return [alert.to_dict() for alert in self._alert_history]
            
        return [
            alert.to_dict() for alert in self._alert_history
            if alert.timestamp >= since
        ]
        
    def clear_alerts(self):
        """Clear alert history"""
        self._alert_history.clear()
        
    def get_stats(self) -> Dict:
        """Get anomaly detection statistics"""
        return {
            "total_alerts": len(self._alert_history),
            "recent_requests": len(self._request_times),
            "audio_samples": len(self._audio_levels),
            "battery_samples": len(self._battery_levels),
            "is_monitoring": self._is_monitoring
        }
