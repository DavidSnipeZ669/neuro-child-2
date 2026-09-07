"""
Cognitive State: Simulates attention span, focus, and concentration levels.
"""
from __future__ import annotations
import time
import random
from dataclasses import dataclass


@dataclass
class FocusState:
    is_concentrating: bool = False
    concentration_level: float = 0.0  # 0.0 (Relaxed/Chatty) to 1.0 (Full Concentration)
    current_activity: str = "watching"  # "watching", "playing", "learning", "clutching"
    last_unprompted_speech: float = 0.0
    speech_cooldown: float = 3.0  # seconds between spontaneous comments — short, like a chatty person


class CognitiveEngine:
    def __init__(self):
        self.state = FocusState()

    def update_activity(self, activity: str, intensity: float) -> None:
        """Adjusts focus based on what's happening on screen or game actions."""
        self.state.current_activity = activity
        self.state.concentration_level = max(0.0, min(1.0, intensity))
        self.state.is_concentrating = self.state.concentration_level > 0.65

        # No cooldown — she talks whenever she wants
        # self.state.speech_cooldown stays 0.0

    def should_speak_spontaneously(self) -> bool:
        """Determines if she should say something unprompted."""
        now = time.time()
        if now - self.state.last_unprompted_speech >= self.state.speech_cooldown:
            self.state.last_unprompted_speech = now
            return True
        return False

    def get_concentration_mumble(self) -> str:
        """Short quips emitted during intense game concentration."""
        return random.choice([
            "wait... wait...",
            "hold on...",
            "gotta focus...",
            "almost... there...",
            "don't mess up...",
            "watch this...",
            "hmmm...",
            "careful...",
            "concentrating...",
        ])