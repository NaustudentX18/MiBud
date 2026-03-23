"""
MiBud Core Package
Privacy-focused AI Companion
"""

from .config import Config, get_config
from .state import StateManager, MiBudState, MiBudMode
from .events import EventBus, Events

__version__ = "0.1.0"
__all__ = [
    "Config", "get_config",
    "StateManager", "MiBudState", "MiBudMode",
    "EventBus", "Events"
]
