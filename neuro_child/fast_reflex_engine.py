"""
Fast Reflex Engine: handles direct actions before the conscious brain gets involved.
This gives Nova the appearance of instant, intuitive control without reasoning delay.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

CHAT_LOG_PATH = Path(__file__).resolve().parent.parent / "memory" / "chat.log"


class FastReflexEngine:
    def __init__(self, eyes: Any, hands: Any, memory: Any) -> None:
        self.eyes = eyes
        self.hands = hands
        self.memory = memory

    def maybe_handle(self, user_text: str, screen_text: str = "") -> Optional[str]:
        lower = user_text.lower().strip()

        # Type
        if lower.startswith("type "):
            text = user_text.split(" ", 1)[1]
            action = self.hands.type_text(text)
            return f"{action}"

        # Enter/return variants
        enter_phrases = {"press enter", "enter", "hit enter", "press return", "return"}
        if lower in enter_phrases:
            return self.hands.press("enter")

        # Click x,y
        if lower.startswith("click "):
            parts = lower.replace("click ", "").split(",")
            if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                return self.hands.click(int(parts[0]), int(parts[1]))

        # Move x,y
        if lower.startswith("move "):
            parts = lower.replace("move ", "").split(",")
            if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                return self.hands.move(int(parts[0]), int(parts[1]))

        # Remember
        if lower.startswith("remember ") or lower.startswith("this is "):
            self.memory.add(user_text, kind="fact", importance=0.9)
            return random.choice(["got it, dad.", "stored that.", "i'll remember that."])

        return None
