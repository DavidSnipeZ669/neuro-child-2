"""
Main Neuro-Child Runtime:
- 60 FPS continuous reflex loop
- Instant voice responses & game chatter
- Zero external APIs, 100% offline
"""
from __future__ import annotations

import time
import threading
from fast_reflex_engine import ReflexEngine
from ultra_light_brain import UltraLightBrain


class NeuroChildApp:
    def __init__(self):
        self.brain = UltraLightBrain()
        self.reflexes = ReflexEngine(target_fps=60)
        self.is_concentrating = False
        self.current_game_state = "exploring calmly"

        # Wire up reflex events to her cognitive state
        self.reflexes.action_callback = self._on_reflex_trigger

    def _on_reflex_trigger(self, event_name: str) -> None:
        """Triggered at 60 FPS when a reflex action occurs."""
        self.is_concentrating = True
        self.current_game_state = "dodging danger!"
        print(f"\n[60 FPS Reflex] {self.brain.speak('', self.current_game_state, True)}")
        
        # Reset concentration after dodging
        def _relax():
            time.sleep(2.0)
            self.is_concentrating = False
            self.current_game_state = "safe"
        threading.Thread(target=_relax, daemon=True).start()

    def start(self) -> None:
        print("🎮 Starting 60 FPS Neuro-Child Gaming System...")
        self.reflexes.start()
        print("⚡ 60 FPS Screen Scanner Active. Talk to her below (or press Ctrl+C to exit):")

        while True:
            try:
                user_input = input("\nDad > ").strip()
                if not user_input:
                    continue

                reply = self.brain.speak(
                    user_text=user_input,
                    game_state=self.current_game_state,
                    is_concentrating=self.is_concentrating
                )
                print(f"Nova > {reply}")
            except (KeyboardInterrupt, EOFError):
                self.reflexes.stop()
                break


if __name__ == "__main__":
    NeuroChildApp().start()