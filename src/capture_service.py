import os
import sys
import time
import asyncio
import numpy as np
import sounddevice as sd
import mss
import logging
from typing import Callable, Optional
from PIL import Image
from io import BytesIO

logger = logging.getLogger("capture-service")

class DesktopCaptureService:
    """
    Manages continuous or on-demand desktop screenshot capture and microphone audio capture.
    Supports native capture (mss + sounddevice) and provides hooks for Screenpipe integration.
    """
    def __init__(
        self,
        fps: float = 1.0,
        sample_rate: int = 16000,
        channels: int = 1,
        audio_chunk_duration_ms: int = 100,
        audio_callback: Optional[Callable[[bytes], None]] = None,
        frame_callback: Optional[Callable[[Image.Image], None]] = None,
    ):
        self.fps = fps
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = int(sample_rate * (audio_chunk_duration_ms / 1000.0))
        
        self.audio_callback = audio_callback
        self.frame_callback = frame_callback
        
        self._audio_stream: Optional[sd.InputStream] = None
        self._audio_running = False
        self._screen_running = False
        self._screen_task: Optional[asyncio.Task] = None

    # --- Screen Capture (mss) ---
    async def start_screen_capture(self):
        if self._screen_running:
            return
        self._screen_running = True
        self._screen_task = asyncio.create_task(self._screen_loop())
        logger.info("Screen capture loop started.")

    async def stop_screen_capture(self):
        self._screen_running = False
        if self._screen_task:
            self._screen_task.cancel()
            try:
                await self._screen_task
            except asyncio.CancelledError:
                pass
            self._screen_task = None
        logger.info("Screen capture loop stopped.")

    async def _screen_loop(self):
        interval = 1.0 / self.fps
        with mss.mss() as sct:
            # Focus primarily on monitor 1 (primary display)
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            
            while self._screen_running:
                start_time = time.perf_counter()
                try:
                    # Capture screen
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    
                    if self.frame_callback:
                        # Call frame callback in thread pool if needed, or directly
                        if asyncio.iscoroutinefunction(self.frame_callback):
                            await self.frame_callback(img)
                        else:
                            self.frame_callback(img)
                except Exception as e:
                    logger.error(f"Error capturing screen: {e}")
                
                # Pace the loop
                elapsed = time.perf_counter() - start_time
                sleep_time = max(0.0, interval - elapsed)
                await asyncio.sleep(sleep_time)

    # --- Audio Capture (sounddevice) ---
    def start_audio_capture(self):
        if self._audio_running:
            return
        self._audio_running = True
        
        def callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio input status warning: {status}")
            # Convert float32 array to 16-bit PCM bytes
            pcm_data = (indata * 32767.0).astype(np.int16).tobytes()
            if self.audio_callback:
                if asyncio.iscoroutinefunction(self.audio_callback):
                    asyncio.run_coroutine_threadsafe(self.audio_callback(pcm_data), asyncio.get_event_loop())
                else:
                    self.audio_callback(pcm_data)

        try:
            self._audio_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='float32',
                blocksize=self.chunk_size,
                callback=callback
            )
            self._audio_stream.start()
            logger.info("Microphone audio stream started successfully.")
        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}")
            self._audio_running = False

    def stop_audio_capture(self):
        self._audio_running = False
        if self._audio_stream:
            try:
                self._audio_stream.stop()
                self._audio_stream.close()
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            self._audio_stream = None
        logger.info("Microphone audio stream stopped.")

    # --- Screenpipe Integration Helper ---
    async def fetch_screenpipe_frame(self, host: str = "localhost", port: int = 3030) -> Optional[Image.Image]:
        """
        Pull the latest visual frame from the screenpipe REST API if it is active.
        """
        import httpx
        url = f"http://{host}:{port}/v1/screen"
        try:
            async with httpx.AsyncClient() as client:
                # Query screenpipe endpoint (typically returns latest OCR and image metadata)
                response = await client.get(url, timeout=1.0)
                if response.status_code == 200:
                    data = response.json()
                    # Parse image from screenpipe's returned payload if base64/url is available
                    # Note: Depending on screenpipe API version, image data can be returned in different structures
                    logger.info("Screenpipe frame queried successfully.")
                    return data
        except Exception as e:
            logger.debug(f"Screenpipe API not available or failed: {e}")
        return None
