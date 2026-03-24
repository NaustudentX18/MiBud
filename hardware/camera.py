"""
MiBud Hardware - Camera Module
Raspberry Pi Camera + USB Camera Support
"""

import io
import logging
import platform
import asyncio
from typing import Optional, Callable, Tuple
from pathlib import Path
from dataclasses import dataclass

log = logging.getLogger("MiBud")

@dataclass
class CameraConfig:
    """Camera configuration"""
    type: str = "picamera2"
    resolution: Tuple[int, int] = (640, 480)
    framerate: int = 30
    rotation: int = 0
    h_flip: bool = False
    v_flip: bool = False


class CameraManager:
    """Manages camera input for MiBud"""
    
    def __init__(self, config: CameraConfig = None):
        self.config = config or CameraConfig()
        self.is_initialized = False
        self.is_streaming = False
        self.is_rpi = platform.machine().startswith(('arm', 'aarch'))
        self._camera = None
        self._stream_task = None
        self._frame_callback: Optional[Callable] = None
        self._jpeg_quality = 85
        
    async def initialize(self):
        """Initialize camera"""
        log.info("📷 Initializing camera...")
        
        if not self.is_rpi:
            log.info("📷 Non-RPi platform - simulation mode")
            self.is_initialized = True
            return
            
        try:
            camera_type = self.config.type.lower()
            
            if camera_type == "picamera2":
                await self._init_picamera2()
            elif camera_type == "picamera":
                await self._init_picamera()
            elif camera_type == "usb":
                await self._init_usb()
            else:
                log.warning(f"📷 Unknown camera type: {camera_type}")
                
        except Exception as e:
            log.warning(f"📷 Camera init warning: {e}")
            
        self.is_initialized = True
        log.info("✅ Camera initialized")
        
    async def _init_picamera2(self):
        """Initialize Picamera2"""
        try:
            from picamera2 import Picamera2
            
            self._camera = Picamera2()
            self._camera.configure(self._camera.create_preview_configuration(
                main={"size": self.config.resolution},
                controls={"FrameRate": self.config.framerate}
            ))
            self._camera.set_controls({
                "Rotation": self.config.rotation,
                "HFlip": self.config.h_flip,
                "VFlip": self.config.v_flip,
            })
            log.info("📷 Picamera2 initialized")
            
        except ImportError:
            log.warning("📷 picamera2 not available")
        except Exception as e:
            log.warning(f"📷 Picamera2 init failed: {e}")
            
    async def _init_picamera(self):
        """Initialize legacy Picamera"""
        try:
            import picamera
            
            self._camera = picamera.PiCamera()
            self._camera.rotation = self.config.rotation
            self._camera.hflip = self.config.h_flip
            self._camera.vflip = self.config.v_flip
            self._camera.resolution = self.config.resolution
            self._camera.framerate = self.config.framerate
            log.info("📷 PiCamera (legacy) initialized")
            
        except ImportError:
            log.warning("📷 picamera not available")
        except Exception as e:
            log.warning(f"📷 PiCamera init failed: {e}")
            
    async def _init_usb(self):
        """Initialize USB camera"""
        try:
            import cv2
            
            self._camera = cv2.VideoCapture(0)
            if self._camera.isOpened():
                self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.resolution[0])
                self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.resolution[1])
                self._camera.set(cv2.CAP_PROP_FPS, self.config.framerate)
                log.info("📷 USB camera initialized")
            else:
                self._camera = None
                log.warning("📷 USB camera failed to open")
                
        except ImportError:
            log.warning("📷 opencv-python not available")
        except Exception as e:
            log.warning(f"📷 USB camera init failed: {e}")
            
    async def capture(self) -> Optional[bytes]:
        """Capture a single frame"""
        if not self.is_initialized:
            return None
            
        try:
            if self.config.type == "picamera2" and self._camera:
                buffer = io.BytesIO()
                self._camera.capture(buffer, format='jpeg', use_video_port=True)
                buffer.seek(0)
                return buffer.getvalue()
                
            elif self.config.type == "picamera" and self._camera:
                stream = io.BytesIO()
                self._camera.capture(stream, format='jpeg', use_video_port=True)
                stream.seek(0)
                return stream.getvalue()
                
            elif self.config.type == "usb" and self._camera:
                import cv2
                ret, frame = self._camera.read()
                if ret:
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
                    return buffer.tobytes()
                    
        except Exception as e:
            log.debug(f"Camera capture: {e}")
            
        return None
        
    async def start_stream(self, callback: Callable[[bytes], None]):
        """Start continuous streaming"""
        if not self.is_initialized or self.is_streaming:
            return
            
        self._frame_callback = callback
        self.is_streaming = True
        self._stream_task = asyncio.create_task(self._stream_loop())
        log.info("📷 Camera streaming started")
        
    async def stop_stream(self):
        """Stop streaming"""
        self.is_streaming = False
        
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None
            
        log.info("📷 Camera streaming stopped")
        
    async def _stream_loop(self):
        """Streaming loop"""
        while self.is_streaming:
            try:
                frame = await self.capture()
                if frame and self._frame_callback:
                    await self._frame_callback(frame)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"Stream loop: {e}")
                
            await asyncio.sleep(1 / self.config.framerate)
            
    async def save_capture(self, filepath: str) -> bool:
        """Capture and save image to file"""
        frame = await self.capture()
        if frame:
            try:
                Path(filepath).parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'wb') as f:
                    f.write(frame)
                log.info(f"📷 Image saved: {filepath}")
                return True
            except Exception as e:
                log.error(f"Failed to save image: {e}")
        return False
        
    async def cleanup(self):
        """Cleanup camera resources"""
        log.info("📷 Camera cleanup")
        await self.stop_stream()
        
        if self._camera:
            if self.config.type == "picamera2":
                self._camera.close()
            elif self.config.type == "picamera":
                self._camera.close()
            elif self.config.type == "usb":
                self._camera.release()
            self._camera = None
