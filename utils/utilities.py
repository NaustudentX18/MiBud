"""
MiBud Utilities
Timers, Reminders, Notes, and System Utilities
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
import uuid

log = logging.getLogger("MiBud")


@dataclass
class Timer:
    """Timer object"""
    id: str
    name: str
    duration_seconds: int
    created_at: datetime = field(default_factory=datetime.now)
    completed: bool = False
    callback: Optional[Callable] = None


@dataclass
class Reminder:
    """Reminder object"""
    id: str
    message: str
    trigger_time: datetime
    repeat: bool = False
    repeat_interval: timedelta = None
    completed: bool = False


@dataclass
class Note:
    """Voice note"""
    id: str
    content: str
    created_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)


class TimerManager:
    """Manages timers and alarms"""
    
    def __init__(self):
        self.timers: Dict[str, Timer] = {}
        self._timer_tasks: Dict[str, asyncio.Task] = {}
        self._event_callback: Optional[Callable] = None
        
    def set_event_callback(self, callback: Callable):
        """Set callback for timer events"""
        self._event_callback = callback
        
    def create_timer(self, name: str, seconds: int, callback: Callable = None) -> str:
        """Create a new timer"""
        timer_id = str(uuid.uuid4())[:8]
        
        timer = Timer(
            id=timer_id,
            name=name,
            duration_seconds=seconds,
            callback=callback
        )
        
        self.timers[timer_id] = timer
        self._start_timer_task(timer)
        
        log.info(f"⏱️ Timer created: {name} ({seconds}s)")
        return timer_id
        
    def _start_timer_task(self, timer: Timer):
        """Start timer task"""
        async def _timer_task():
            try:
                await asyncio.sleep(timer.duration_seconds)
                
                if not timer.completed:
                    timer.completed = True
                    
                    # Fire callback
                    if timer.callback:
                        timer.callback()
                        
                    # Fire event
                    if self._event_callback:
                        self._event_callback("timer_complete", timer)
                        
                    log.info(f"⏱️ Timer complete: {timer.name}")
                    
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error(f"Timer error: {e}")
                
        self._timer_tasks[timer.id] = asyncio.create_task(_timer_task())
        
    def cancel_timer(self, timer_id: str) -> bool:
        """Cancel a timer"""
        if timer_id in self.timers:
            timer = self.timers[timer_id]
            
            # Cancel task
            if timer_id in self._timer_tasks:
                self._timer_tasks[timer_id].cancel()
                del self._timer_tasks[timer_id]
                
            del self.timers[timer_id]
            log.info(f"⏱️ Timer cancelled: {timer.name}")
            return True
            
        return False
        
    def get_timer(self, timer_id: str) -> Optional[Timer]:
        """Get timer by ID"""
        return self.timers.get(timer_id)
        
    def get_active_timers(self) -> List[Timer]:
        """Get all active timers"""
        return [t for t in self.timers.values() if not t.completed]
        
    def get_remaining(self, timer_id: str) -> int:
        """Get remaining seconds for timer"""
        timer = self.timers.get(timer_id)
        if not timer:
            return 0
            
        elapsed = (datetime.now() - timer.created_at).total_seconds()
        remaining = timer.duration_seconds - elapsed
        
        return max(0, int(remaining))


class ReminderManager:
    """Manages reminders"""
    
    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path.home() / ".mibud"
        self.reminders_file = self.data_dir / "reminders.json"
        self.reminders: Dict[str, Reminder] = {}
        self._load()
        
    def _load(self):
        """Load reminders from file"""
        if self.reminders_file.exists():
            try:
                with open(self.reminders_file) as f:
                    data = json.load(f)
                    for r in data:
                        r['trigger_time'] = datetime.fromisoformat(r['trigger_time'])
                        self.reminders[r['id']] = Reminder(**r)
            except Exception as e:
                log.warning(f"Failed to load reminders: {e}")
                
    def _save(self):
        """Save reminders to file"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.reminders_file, 'w') as f:
                data = [
                    {
                        **vars(r),
                        'trigger_time': r.trigger_time.isoformat()
                    }
                    for r in self.reminders.values()
                ]
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save reminders: {e}")
            
    def create_reminder(self, message: str, trigger_time: datetime, 
                       repeat: bool = False, interval_minutes: int = 0) -> str:
        """Create a reminder"""
        reminder_id = str(uuid.uuid4())[:8]
        
        reminder = Reminder(
            id=reminder_id,
            message=message,
            trigger_time=trigger_time,
            repeat=repeat,
            repeat_interval=timedelta(minutes=interval_minutes) if repeat else None
        )
        
        self.reminders[reminder_id] = reminder
        self._save()
        
        log.info(f"🔔 Reminder created: {message}")
        return reminder_id
        
    def create_reminder_relative(self, message: str, minutes_from_now: int) -> str:
        """Create reminder X minutes from now"""
        trigger = datetime.now() + timedelta(minutes=minutes_from_now)
        return self.create_reminder(message, trigger)
        
    def complete_reminder(self, reminder_id: str) -> bool:
        """Mark reminder as completed"""
        if reminder_id in self.reminders:
            reminder = self.reminders[reminder_id]
            
            if reminder.repeat and reminder.repeat_interval:
                # Reschedule
                reminder.trigger_time = datetime.now() + reminder.repeat_interval
                self._save()
            else:
                # Remove
                del self.reminders[reminder_id]
                self._save()
                
            return True
            
        return False
        
    def get_upcoming_reminders(self, limit: int = 10) -> List[Reminder]:
        """Get upcoming reminders"""
        now = datetime.now()
        upcoming = [r for r in self.reminders.values() if r.trigger_time > now]
        upcoming.sort(key=lambda r: r.trigger_time)
        return upcoming[:limit]


class NoteManager:
    """Manages voice notes"""
    
    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path.home() / ".mibud"
        self.notes_file = self.data_dir / "notes.json"
        self.notes: Dict[str, Note] = {}
        self._load()
        
    def _load(self):
        """Load notes from file"""
        if self.notes_file.exists():
            try:
                with open(self.notes_file) as f:
                    data = json.load(f)
                    for n in data:
                        n['created_at'] = datetime.fromisoformat(n['created_at'])
                        self.notes[n['id']] = Note(**n)
            except Exception as e:
                log.warning(f"Failed to load notes: {e}")
                
    def _save(self):
        """Save notes to file"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.notes_file, 'w') as f:
                data = [
                    {
                        **vars(n),
                        'created_at': n.created_at.isoformat()
                    }
                    for n in self.notes.values()
                ]
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save notes: {e}")
            
    def create_note(self, content: str, tags: List[str] = None) -> str:
        """Create a new note"""
        note_id = str(uuid.uuid4())[:8]
        
        note = Note(
            id=note_id,
            content=content,
            tags=tags or []
        )
        
        self.notes[note_id] = note
        self._save()
        
        log.info(f"📝 Note created: {note_id}")
        return note_id
        
    def get_note(self, note_id: str) -> Optional[Note]:
        """Get note by ID"""
        return self.notes.get(note_id)
        
    def search_notes(self, query: str) -> List[Note]:
        """Search notes by content or tags"""
        query = query.lower()
        results = []
        
        for note in self.notes.values():
            if query in note.content.lower():
                results.append(note)
            elif any(query in tag.lower() for tag in note.tags):
                results.append(note)
                
        return results
        
    def delete_note(self, note_id: str) -> bool:
        """Delete a note"""
        if note_id in self.notes:
            del self.notes[note_id]
            self._save()
            return True
        return False
        
    def get_all_notes(self) -> List[Note]:
        """Get all notes"""
        return sorted(self.notes.values(), key=lambda n: n.created_at, reverse=True)


class SystemInfo:
    """System information utilities"""
    
    @staticmethod
    def get_uptime() -> str:
        """Get system uptime"""
        try:
            with open('/proc/uptime') as f:
                seconds = float(f.read().split()[0])
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                return f"{hours}h {minutes}m"
        except:
            return "Unknown"
            
    @staticmethod
    def get_memory_usage() -> Dict[str, int]:
        """Get memory usage"""
        try:
            with open('/proc/meminfo') as f:
                lines = f.readlines()
                
            mem = {}
            for line in lines:
                if ':' in line:
                    key = line.split(':')[0]
                    value = int(line.split(':')[1].strip().split()[0])  # KB
                    mem[key] = value
                    
            total = mem.get('MemTotal', 0)
            available = mem.get('MemAvailable', 0)
            used = total - available
            
            return {
                'total_kb': total,
                'used_kb': used,
                'available_kb': available,
                'percent': int(used / total * 100) if total else 0
            }
        except:
            return {'total_kb': 0, 'used_kb': 0, 'available_kb': 0, 'percent': 0}
            
    @staticmethod
    def get_cpu_temp() -> float:
        """Get CPU temperature"""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                return float(f.read()) / 1000
        except:
            return 0.0
            
    @staticmethod
    def get_disk_usage(path: str = "/") -> Dict[str, int]:
        """Get disk usage"""
        try:
            import shutil
            stat = shutil.disk_usage(path)
            return {
                'total_gb': round(stat.total / (1024**3), 2),
                'used_gb': round(stat.used / (1024**3), 2),
                'free_gb': round(stat.free / (1024**3), 2),
                'percent': int(stat.used / stat.total * 100)
            }
        except:
            return {'total_gb': 0, 'used_gb': 0, 'free_gb': 0, 'percent': 0}
