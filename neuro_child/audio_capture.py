"""
System audio capture on Windows via WASAPI loopback.
Captures all PC audio: YouTube, games, music, etc.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    import pyaudio
except Exception:
    pyaudio = None  # type: ignore[assignment]


CHUNK = 1024
FORMAT = pyaudio.paInt16 if pyaudio else None
CHANNELS = 2
RATE = 44100
DEVICE_INDEX = None  # auto-detect loopback device


@dataclass
class AudioChunk:
    data: bytes
    timestamp: float
    source: str = "system"


class SystemAudioCapture:
    """
    Captures all system audio output using WASAPI loopback on Windows.
    Falls back gracefully if unavailable.
    """

    def __init__(self, device_index: Optional[int] = None) -> None:
        self.device_index = device_index
        self.audio = None
        self.stream = None
        self._queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=256)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._chunk_count = 0

    def start(self) -> None:
        if pyaudio is None:
            return
        try:
            self.audio = pyaudio.PyAudio()
            device = self._find_loopback_device()
            if device is None:
                return
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=device,
                frames_per_buffer=CHUNK,
                stream_callback=self._callback,
            )
            self.stream.start_stream()
            self._running = True
        except Exception:
            self._cleanup()

    def _find_loopback_device(self) -> Optional[int]:
        if self.audio is None:
            return None
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            name = info.get("name", "").lower()
            if "loopback" in name or "wasapi" in name or "立体声" in name or "stereo mix" in name:
                return i
        # Fallback: default input device
        try:
            return self.audio.get_default_input_device_info()["index"]
        except Exception:
            return None

    def _callback(self, in_data, frame_count, time_info, status):
        try:
            chunk = AudioChunk(data=in_data, timestamp=time.time(), source="system")
            self._queue.put_nowait(chunk)
            self._chunk_count += 1
        except queue.Full:
            pass
        return (None, pyaudio.paContinue if pyaudio else 0)

    def get_chunk(self, timeout: float = 0.5) -> Optional[AudioChunk]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._running = False
        self._cleanup()

    def _cleanup(self) -> None:
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
        except Exception:
            pass
        try:
            if self.audio:
                self.audio.terminate()
        except Exception:
            pass
        self.stream = None
        self.audio = None

    def is_running(self) -> bool:
        return self._running and self.stream is not None and self.stream.is_active()
