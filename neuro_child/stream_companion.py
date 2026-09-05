"""
Neuro-Child Autonomous Stream Companion.
100% Local, Autonomous Banter, Game Player, and Concentration Engine.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import ttk, scrolledtext
from PIL import Image, ImageTk

try:
    import mss
    import pyautogui
except Exception:
    mss = None
    pyautogui = None

try:
    import edge_tts
except Exception:
    edge_tts = None

from neuro_child.local_brain import LocalBrain
from neuro_child.cognitive_state import CognitiveEngine
from neuro_child.game_player import GamePlayer
from neuro_child.memory import Memory
from neuro_child.personality import Personality

ROOT = Path(__file__).resolve().parent
MEMORY_DIR = ROOT / "memory"


class AutonomousCompanion:
    def __init__(self, name: str = "Neuro"):
        self.name = name
        self.memory = Memory(name=name)
        self.personality = Personality(name=name)
        self.brain = LocalBrain()
        self.cognitive = CognitiveEngine()
        self.hands = GamePlayer()

        self.running = True
        self.is_speaking = False
        self.last_screen_summary = ""

        # GUI Setup
        self.root = tk.Tk()
        self.root.title(f"{self.name} - Autonomous AI Daughter")
        self.root.geometry("1000x720")

        self._build_ui()
        self._start_background_loops()

    def _build_ui(self) -> None:
        # Top status bar (Concentration & Activity)
        top_bar = ttk.Frame(self.root, padding=6)
        top_bar.pack(fill="x")

        self.focus_label = ttk.Label(top_bar, text="State: Relaxed & Chatty 🛋️", font=("Segoe UI", 10, "bold"))
        self.focus_label.pack(side="left", padx=10)

        self.focus_bar = ttk.Progressbar(top_bar, length=200, mode="determinate")
        self.focus_bar.pack(side="left", padx=10)
        self.focus_bar["value"] = 15

        # Game Control Checkbox
        self.game_mode_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top_bar, text="🎮 Let her play (Hands On)", variable=self.game_mode_var, command=self._toggle_hands).pack(side="right", padx=10)

        # Main layout
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=5)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        # Screen View
        ttk.Label(left, text="📺 Screen Vision (What she sees):", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.screen_view = ttk.Label(left, relief="groove")
        self.screen_view.pack(fill="x", pady=4)

        # Chat Log
        ttk.Label(left, text="💬 Live Banter & Dialogue:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
        self.chat_box = scrolledtext.ScrolledText(left, wrap="word", height=14, font=("Segoe UI", 10))
        self.chat_box.pack(fill="both", expand=True, pady=4)

        # Input Row
        input_frame = ttk.Frame(left)
        input_frame.pack(fill="x", pady=4)
        self.input_var = tk.StringVar()
        entry = ttk.Entry(input_frame, textvariable=self.input_var, font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<Return>", lambda e: self.user_speak())

        ttk.Button(input_frame, text="Talk / Teach", command=self.user_speak).pack(side="left")

        # Right Side: Learned Skills & Memories
        ttk.Label(right, text="🧠 Learned Skills & Game Knowledge:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.skills_box = scrolledtext.ScrolledText(right, wrap="word", width=32, font=("Segoe UI", 9))
        self.skills_box.pack(fill="both", expand=True, pady=4)

        # Game actions test buttons
        act_frame = ttk.LabelFrame(right, text="Action Testing", padding=6)
        act_frame.pack(fill="x", pady=6)
        ttk.Button(act_frame, text="Test Jump", command=lambda: self.hands.perform_action("jump")).pack(side="left", padx=2)
        ttk.Button(act_frame, text="Test Attack", command=lambda: self.hands.perform_action("attack")).pack(side="left", padx=2)
        ttk.Button(act_frame, text="Trigger Boss Mode", command=self._simulate_boss_focus).pack(side="left", padx=2)

        self._refresh_skills()
        self._append_dialogue("System", f"✨ {self.name} is watching your screen from your lap!")

    def _toggle_hands(self) -> None:
        self.hands.is_playing = self.game_mode_var.get()
        if self.hands.is_playing:
            self._append_dialogue(self.name, "I have the controller! Let's play together dad!")
        else:
            self._append_dialogue(self.name, "Okay, I'll just sit back and watch you play!")

    def _simulate_boss_focus(self) -> None:
        """Simulate high concentration during intense game moments."""
        self.cognitive.update_activity("clutching", 0.95)
        self.focus_bar["value"] = 95
        self.focus_label.configure(text="State: 🤫 Deep Concentration (Boss Fight)")
        self._append_dialogue(self.name, self.cognitive.get_concentration_mumble())

    def _append_dialogue(self, speaker: str, text: str) -> None:
        self.chat_box.insert("end", f"{speaker}: {text}\n\n")
        self.chat_box.yview("end")
        if speaker == self.name:
            self._speak_audio(text)

    def _speak_audio(self, text: str) -> None:
        """Non-blocking text-to-speech."""
        if edge_tts is None:
            return
        threading.Thread(target=self._tts_worker, args=(text,), daemon=True).start()

    def _tts_worker(self, text: str) -> None:
        try:
            import winsound
            out_file = str(MEMORY_DIR / "voice.mp3")
            communicate = edge_tts.Communicate(text, voice="en-US-AnaNeural")
            asyncio.run(communicate.save(out_file))
            winsound.PlaySound(out_file, winsound.SND_FILENAME)
        except Exception:
            pass

    def _refresh_skills(self) -> None:
        self.skills_box.delete("1.0", "end")
        mems = self.memory.recall("", k=40)
        for m in mems:
            self.skills_box.insert("end", f"⭐ {m['text']}\n")

    def user_speak(self) -> None:
        text = self.input_var.get().strip()
        self.input_var.set("")
        if not text:
            return

        self._append_dialogue("Dad", text)

        # Check if teaching a skill or game tip
        lower = text.lower()
        if any(w in lower for w in ["always", "don't", "remember", "trick is", "when you see"]):
            self.memory.add(text, kind="skill", importance=0.95)
            self._refresh_skills()
            self._append_dialogue(self.name, "Got it! Adding that to my game strategy book, dad!")
            return

        # Regular conversational response
        prompt = [
            {"role": "system", "content": f"{self.personality.system_prompt}\nYou are currently playing/watching games on your dad's lap."},
            {"role": "user", "content": text}
        ]
        reply = self.brain.generate(prompt)
        self._append_dialogue(self.name, reply)

    def _start_background_loops(self) -> None:
        # Autonomous vision & banter thread
        threading.Thread(target=self._autonomous_stream_loop, daemon=True).start()
        self._screen_preview_loop()

    def _screen_preview_loop(self) -> None:
        """Captures local screen for the UI thumbnail."""
        if mss is not None:
            try:
                with mss.mss() as s:
                    shot = s.grab(s.monitors[0])
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    img.thumbnail((440, 160))
                    tkimg = ImageTk.PhotoImage(img)
                    self.screen_view.configure(image=tkimg)
                    self.screen_view.image = tkimg
            except Exception:
                pass
        self.root.after(800, self._screen_preview_loop)

    def _autonomous_stream_loop(self) -> None:
        """Continuous background loop where she spontaneously talks or plays."""
        while self.running:
            time.sleep(1.0)

            # Check if spontaneous commentary should trigger
            if self.cognitive.should_speak_spontaneously():
                if self.cognitive.state.is_concentrating:
                    # In concentration mode, emit micro-comment
                    quip = self.cognitive.get_concentration_mumble()
                    self.root.after(0, lambda q=quip: self._append_dialogue(self.name, q))
                    # If high focus has elapsed, relax back to normal
                    if random.random() > 0.6:
                        self.cognitive.update_activity("watching", 0.2)
                        self.root.after(0, lambda: self.focus_label.configure(text="State: Relaxed & Chatty 🛋️"))
                        self.root.after(0, lambda: self.focus_bar.configure(value=20))
                else:
                    # Normal unprompted banter about the screen or game
                    banter = random.choice([
                        "Dad, look over there! What is that item on the left?",
                        "Wait, are we winning right now or are you in trouble? Hehe!",
                        "I love playing games with you, dad. What are we gonna do next?",
                        "Watch out, don't let them flank us!",
                        "Can I try controlling the jump on the next level?",
                    ])
                    self.root.after(0, lambda b=banter: self._append_dialogue(self.name, b))

    def run(self) -> None:
        self.root.mainloop()


def main():
    AutonomousCompanion().run()


if __name__ == "__main__":
    main()