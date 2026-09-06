"""
Game Learning — Nova learns to play games by watching dad play.
Captures screen, detects game state, learns controls/patterns.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GameSession:
    game_name: str
    window_title: str
    start_time: float = field(default_factory=time.time)
    observations: List[str] = field(default_factory=list)
    controls_learned: List[str] = field(default_factory=list)
    strategies: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)


class GameLearningEngine:
    """
    Learns games by watching dad play:
    - Detects game window/state
    - Learns controls from observation
    - Builds strategy patterns
    - Practices when dad isn't playing
    """

    def __init__(self, knowledge: Any, language: Any) -> None:
        self.knowledge = knowledge
        self.language = language
        self.current_session: Optional[GameSession] = None
        self.sessions: List[GameSession] = []
        self._learning_cooldown = 2.0
        self._last_learn_ts = 0.0

    def detect_game(self, window_title: str = "") -> Optional[str]:
        """Detect if a game is running from window title."""
        if not window_title:
            return None
        lower = window_title.lower()
        game_indicators = [
            "steam", "game", "play", "xbox", "playstation", "rocket league",
            "fortnite", "minecraft", "valorant", "apex", "overwatch",
            "league of legends", "csgo", "counter-strike", "dota",
            "gta", "elden ring", "zelda", "mario", "halo",
        ]
        for indicator in game_indicators:
            if indicator in lower:
                return indicator
        return None

    def start_session(self, game_name: str, window_title: str) -> None:
        """Start tracking a game session."""
        self.current_session = GameSession(
            game_name=game_name,
            window_title=window_title,
        )
        self.sessions.append(self.current_session)

    def end_session(self) -> None:
        """End current game session."""
        if self.current_session:
            duration = time.time() - self.current_session.start_time
            self.knowledge.learn(
                f"game_session_{self.current_session.game_name}",
                f"Played {self.current_session.game_name} for {duration:.0f}s. "
                f"Learned {len(self.current_session.controls_learned)} controls, "
                f"{len(self.current_session.strategies)} strategies.",
                category="experience",
                importance=0.6,
            )
            self.current_session = None

    def learn_from_screen(self, screen_text: str, window_title: str = "") -> Optional[str]:
        """Learn from current game screen."""
        now = time.time()
        if now - self._last_learn_ts < self._learning_cooldown:
            return None
        self._last_learn_ts = now

        game = self.detect_game(window_title)
        if not game and self.current_session:
            game = self.current_session.game_name
        if not game:
            return None

        if not self.current_session or self.current_session.game_name != game:
            self.start_session(game, window_title)

        obs = screen_text[:200]
        self.current_session.observations.append(obs)
        try:
            words = self.language.encounter_text(obs, source="game")
            if words:
                self.current_session.controls_learned.extend(words[:5])
                return f"learned game words: {', '.join(words[:3])}"
        except Exception:
            pass
        return None

    def get_strategy_advice(self, game_name: str) -> str:
        """Get learned strategy for a game."""
        for session in reversed(self.sessions):
            if session.game_name == game_name and session.strategies:
                return "; ".join(session.strategies[-3:])
        return "watch and learn"

    def practice(self, game_name: str) -> str:
        """Practice a game in background."""
        return f"practicing {game_name} in background"


__all__ = ["GameLearningEngine", "GameSession"]
