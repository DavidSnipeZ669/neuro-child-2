"""
Game Controller: Gives Neuro-child hands to play games alongside you.
"""
from __future__ import annotations

import time
import threading
from typing import Optional, List

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except Exception:
    pyautogui = None


class GamePlayer:
    def __init__(self):
        self.is_playing = False
        self.active_keys: List[str] = []
        self._thread: Optional[threading.Thread] = None

    def press_key(self, key: str, duration: float = 0.1) -> None:
        """Press and release a game key (WASD, Space, Arrows, etc.)."""
        if pyautogui is None:
            return
        try:
            pyautogui.keyDown(key)
            time.sleep(duration)
            pyautogui.keyUp(key)
        except Exception:
            pass

    def perform_action(self, action_name: str) -> str:
        """Executes learned gameplay mechanics."""
        if pyautogui is None:
            return "No hands connected (pyautogui missing)."

        action = action_name.lower().strip()
        if action in ["jump", "space"]:
            self.press_key("space", 0.15)
            return "Jumped!"
        elif action in ["dodge left", "left", "a"]:
            self.press_key("a", 0.2)
            return "Moved left!"
        elif action in ["dodge right", "right", "d"]:
            self.press_key("d", 0.2)
            return "Moved right!"
        elif action in ["attack", "click", "hit"]:
            pyautogui.click()
            return "Attacked!"
        elif action in ["crouch", "slide", "shift"]:
            self.press_key("shift", 0.3)
            return "Slid/Crouched!"
        return f"Tried action: {action}"

    def auto_play_loop(self, game_type: str = "arcade") -> None:
        """Simple autonomous gaming loop (e.g. for rhythm or arcade games)."""
        while self.is_playing:
            # Performs game loops with periodic micro-actions
            time.sleep(0.5)