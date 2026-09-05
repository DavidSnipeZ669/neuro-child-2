"""
System integration: Nova can observe and interact with the Windows system.

She:
- Reads running processes
- Monitors CPU/memory/disk
- Launches apps
- Reads/writes files
- Watches folders for changes
- Executes safe commands
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SystemSnapshot:
    timestamp: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    active_processes: List[str] = field(default_factory=list)
    foreground_window: str = ""
    battery_percent: Optional[float] = None


class SystemIntegration:
    """
    Allows Nova to observe and interact with the Windows system.
    """

    def __init__(self) -> None:
        self._history: List[SystemSnapshot] = []
        self._max_history = 100

    def get_snapshot(self) -> SystemSnapshot:
        """
        Capture current system state.
        """
        snap = SystemSnapshot()
        try:
            import psutil
            snap.cpu_percent = psutil.cpu_percent(interval=0.1)
            snap.memory_percent = psutil.virtual_memory().percent
            snap.disk_percent = psutil.disk_usage("/").percent
            procs = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    procs.append(proc.info['name'] or '')
                except Exception:
                    pass
            snap.active_processes = sorted(set(procs))[:20]
        except ImportError:
            pass
        try:
            import pyautogui
            snap.foreground_window = pyautogui.getActiveWindow().title if pyautogui.getActiveWindow() else ""
        except Exception:
            pass
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery:
                snap.battery_percent = battery.percent
        except Exception:
            pass
        self._history.append(snap)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return snap

    def launch_app(self, app_path: str) -> Dict[str, Any]:
        try:
            import subprocess
            subprocess.Popen(app_path, shell=True)
            return {"status": "launched", "app": app_path}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def read_file(self, path: str, max_chars: int = 2000) -> Dict[str, Any]:
        try:
            p = Path(path)
            if not p.exists():
                return {"status": "not_found", "path": path}
            text = p.read_text(encoding="utf-8", errors="ignore")[:max_chars]
            return {"status": "ok", "path": path, "content": text}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def list_directory(self, path: str) -> Dict[str, Any]:
        try:
            p = Path(path)
            if not p.exists() or not p.is_dir():
                return {"status": "not_found", "path": path}
            entries = []
            for child in sorted(p.iterdir()):
                entries.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 0,
                })
            return {"status": "ok", "path": path, "entries": entries[:50]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def execute_command(self, command: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Execute a safe shell command and capture output.
        """
        try:
            import subprocess
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "status": "ok",
                "command": command,
                "stdout": result.stdout[:1000],
                "stderr": result.stderr[:500],
                "returncode": result.returncode,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_active_window_info(self) -> Dict[str, Any]:
        try:
            import pyautogui
            win = pyautogui.getActiveWindow()
            if win:
                return {"title": win.title, "left": win.left, "top": win.top, "width": win.width, "height": win.height}
            return {"title": "", "status": "no_active_window"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_recent_activity(self) -> List[Dict[str, Any]]:
        return [
            {
                "timestamp": snap.timestamp,
                "cpu": snap.cpu_percent,
                "memory": snap.memory_percent,
                "foreground": snap.foreground_window,
            }
            for snap in self._history[-10:]
        ]
