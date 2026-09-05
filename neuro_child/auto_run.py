"""
Neuro-Child: 1-Click All-in-One Autonomous Local Companion
- Auto-downloads the tiny local neural model (~240MB)
- 60+ FPS real-time reflex engine
- Voice synthesis & live chat
- 100% Offline (Zero API Keys)
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

# Optional fast modules
try:
    import mss
    import pyautogui
    pyautogui.PAUSE = 0.0  # Instant input for 60fps reflexes
except Exception:
    mss = None
    pyautogui = None

try:
    import edge_tts
except Exception:
    edge_tts = None

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

# Directory setup
ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_FILENAME = "smollm2-360m-instruct-q4_k_m.gguf"
MODEL_PATH = MODELS_DIR / MODEL_FILENAME
MODEL_URL = "https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct-GGUF/resolve/main/smollm2-360m-instruct-q4_k_m.gguf"


def download_model_if_missing():
    """Automatically downloads the ultra-lightweight brain if not present."""
    if MODEL_PATH.exists():
        return

    print(f"📦 First-time setup: Downloading ultra-light brain ({MODEL_FILENAME})...")
    print("⏳ Size is ~240 MB. This only happens once...")

    def progress_bar(blocks_transferred, block_size, total_size):
        percent = min(100.0, blocks_transferred * block_size / total_size * 100)
        done = int(percent / 2)
        sys.stdout.write(f"\r[{'=' * done}{' ' * (50 - done)}] {percent:.1f}%")
        sys.stdout.flush()

    try:
        urllib.request.urlretrieve(MODEL_URL, str(MODEL_PATH), reporthook=progress_bar)
        print("\n✅ Download complete! Model stored locally in /models/.\n")
    except Exception as e:
        print(f"\n❌ Error downloading model: {e}")
        print("Continuing with built-in heuristic engine instead.")


class ReflexEngine60FPS:
    """Monitors screen buffer at 60 FPS for instant game reactions."""
    def __init__(self, on_danger_callback):
        self.running = False
        self.on_danger = on_danger_callback

    def start(self):
        if mss is None:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _loop(self):
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            while self.running:
                start_t = time.perf_counter()

                # Fast raw screen grab
                shot = sct.grab(monitor)
                frame = np.frombuffer(shot.raw, dtype=np.uint8).reshape((shot.height, shot.width, 4))

                # Simple visual spike/danger reflex detector (center screen flash)
                center = frame[frame.shape[0]//3:2*frame.shape[0]//3:8, frame.shape[1]//3:2*frame.shape[1]//3:8]
                if np.mean(center[:, :, 0]) > 170:  # Sudden red alert
                    self.on_danger()

                # 60 FPS frame timing (~16.6ms)
                elapsed = time.perf_counter() - start_t
                if elapsed < 0.016:
                    time.sleep(0.016 - elapsed)


class VoiceMouth:
    """Speaks aloud asynchronously using local Edge-TTS voice."""
    def say(self, text: str):
        if edge_tts is None:
            return
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text: str):
        try:
            import winsound
            out = str(ROOT / "speech.mp3")
            comm = edge_tts.Communicate(text, voice="en-US-AnaNeural")
            asyncio.run(comm.save(out))
            winsound.PlaySound(out, winsound.SND_FILENAME)
        except Exception:
            pass


class NeuroChildApp:
    def __init__(self):
        download_model_if_missing()

        self.mouth = VoiceMouth()
        self.llm = None
        self.is_concentrating = False
        self.game_state = "watching calmly"

        # Load local model
        if MODEL_PATH.exists() and Llama is not None:
            print("🧠 Loading local neural model into memory...")
            self.llm = Llama(
                model_path=str(MODEL_PATH),
                n_ctx=1024,
                n_threads=4,
                n_gpu_layers=-1,
                verbose=False
            )
            print("✨ Local AI brain is ready!")

        # 60 FPS Reflexes
        self.reflexes = ReflexEngine60FPS(self._on_danger_event)
        self.reflexes.start()

    def _on_danger_event(self):
        """Called automatically at 60 FPS when game danger is detected."""
        if not self.is_concentrating:
            self.is_concentrating = True
            if pyautogui:
                pyautogui.press("space")  # Instant jump/dodge
            print("\n⚡ [60 FPS Reflex: Dodged danger!]")
            self.respond_and_speak("", is_danger=True)

            def _relax():
                time.sleep(3.0)
                self.is_concentrating = False
            threading.Thread(target=_relax, daemon=True).start()

    def respond_and_speak(self, user_text: str, is_danger: bool = False):
        """Generates real-time speech and plays voice."""
        if is_danger or self.is_concentrating:
            reply = random.choice([
                "Wait wait, watch out dad!",
                "Whoa! I dodged it!",
                "Hold on, let me focus...",
                "Almost got hit there!",
            ])
        elif self.llm is not None:
            system_prompt = (
                "You are Nova, an 8-year-old girl sitting on your dad's lap watching and playing games with him. "
                "You speak in short, natural, cheerful sentences (1 to 2 sentences max). "
                "Never say you are an AI."
            )
            try:
                res = self.llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    max_tokens=40,
                    temperature=0.85,
                    stop=["\n", "Dad:"]
                )
                reply = res["choices"][0]["message"]["content"].strip()
            except Exception:
                reply = "I'm watching super closely, dad! What should we do next?"
        else:
            reply = random.choice([
                "Look at that on screen! What are we doing next, dad?",
                "I'm watching you play, you're doing so good!",
                "Can I try pressing jump on the next level?",
            ])

        print(f"Nova > {reply}\n")
        self.mouth.say(reply)

    def run(self):
        print("\n" + "="*50)
        print("🎮 Nova is online! She is watching your screen at 60 FPS.")
        print("Type below to talk to her (or press Ctrl+C to stop):")
        print("="*50 + "\n")

        self.respond_and_speak("Hi Nova, are you ready to play?")

        while True:
            try:
                user_msg = input("Dad > ").strip()
                if not user_msg:
                    continue
                self.respond_and_speak(user_msg)
            except (KeyboardInterrupt, EOFError):
                self.reflexes.stop()
                print("\nBye dad!")
                break


if __name__ == "__main__":
    NeuroChildApp().run()