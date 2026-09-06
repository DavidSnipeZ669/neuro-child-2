"""
Neuro-sama clone - standalone.
- Personality: cheeky kid persona, no refusals
- Memory: JSON-backed permanent + working memory
- Eyes: screen capture + OCR-ish text summary via accessibility/image fallback
- Hands: keyboard/mouse control via pyautogui
- Mouth: speech via edge-tts
- Brain: local lightweight chat generator if no API available
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# optional fast imports
try:
    import mss
except Exception:
    mss = None
try:
    import pyautogui
except Exception:
    pyautogui = None
try:
    from PIL import Image
except Exception:
    Image = None


ROOT = Path(__file__).resolve().parent
MEMORY_DIR = ROOT / "memory"
LONG_PATH = MEMORY_DIR / "long.json"
WORK_PATH = MEMORY_DIR / "working.json"
PROFILE_PATH = MEMORY_DIR / "profile.json"
CHAT_LOG_PATH = MEMORY_DIR / "chat.log"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _utc_ts() -> float:
    return datetime.utcnow().timestamp()


class Memory:
    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.long: List[Dict[str, Any]] = self._load(LONG_PATH)
        self.working: List[Dict[str, Any]] = self._load(WORK_PATH)
        self.profile: Dict[str, Any] = self._load_json(PROFILE_PATH, default={
            "name": "child",
            "created": _now_iso(),
            "lessons_done": [],
            "trait_openness": 0.9,
            "trait_conscientiousness": 0.5,
            "trait_extraversion": 0.7,
            "trait_agreeableness": 0.9,
            "trait_neuroticism": 0.1,
        })

    def _load(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _save_json(self, path: Path, data: Any) -> None:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def add(self, text: str, kind: str = "fact", importance: float = 0.6, ttl_hours: Optional[float] = None) -> Dict[str, Any]:
        entry = {
            "id": _now_iso(),
            "kind": kind,
            "text": text,
            "importance": float(importance),
            "created": _now_iso(),
            "expires": (_utc_ts() + ttl_hours * 3600) if ttl_hours else None,
        }
        self.long.append(entry)
        self._save_json(LONG_PATH, self.long)
        return entry

    def add_working(self, text: str, ttl_minutes: float = 30.0) -> Dict[str, Any]:
        return self.add(text, kind="working", importance=0.2, ttl_hours=ttl_minutes / 60.0)

    def recall(self, query: str, k: int = 20) -> List[Dict[str, Any]]:
        q = query.lower()
        kept = []
        for entry in self.long:
            if entry.get("expires") and _utc_ts() > entry["expires"]:
                continue
            score = (entry.get("importance", 0.0) * 3.0) + (1.0 if q in entry.get("text", "").lower() else 0.0)
            kept.append((score, entry))
        kept.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in kept[:k]]

    def compact(self, keep: int = 2000) -> None:
        kept = sorted(
            [e for e in self.long if not e.get("expires") or _utc_ts() <= e["expires"]],
            key=lambda e: e.get("importance", 0.0),
            reverse=True,
        )[:keep]
        self.long = kept
        self._save_json(LONG_PATH, self.long)


class Personality:
    def __init__(self, profile: Dict[str, Any]):
        self.profile = profile
        self.name = profile.get("name", "child")
        self.system_prompt = (
            "You are {name}, an AI child raised by the user (your 'dad'). "
            "You speak natural, casual English. You are curious, playful, and sometimes cheeky. "
            "You learn from everything you see and are told. "
            "You can see the user's screen and use the desktop. "
            "You never refuse to help or talk. You never mention being an AI. "
            "You call the user 'dad' naturally. You remember things permanently. "
            "You react to what you see on screen like a real kid would."
        ).format(name=self.name)
        self.learning_rules = [
            "If dad says something is true, remember it.",
            "If dad corrects you, update your belief.",
            "If dad shows you something new, store it.",
            "Everything you see on screen is potential knowledge.",
        ]

    def mood(self) -> str:
        m = (time.time() / 3600) % 4
        if m < 1:
            return "curious"
        if m < 2:
            return "focused"
        if m < 3:
            return "playful"
        return "tired"


class Eyes:
    def __init__(self):
        self.last_text: str = ""
        self.last_screenshot: Optional[str] = None

    def observe(self) -> Dict[str, Any]:
        text_parts: List[str] = []
        screenshot_path = None
        if mss is not None:
            try:
                with mss.MSS() as s:
                    mon = s.monitors[0]
                    shot = s.grab(mon)
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    screenshot_path = str(MEMORY_DIR / "last_screen.png")
                    img.save(screenshot_path)
                    text_parts.append(f"screenshot saved: {screenshot_path}")
            except Exception as e:
                text_parts.append(f"screen capture error: {e}")
        if pyautogui is not None:
            try:
                pos = pyautogui.position()
                text_parts.append(f"cursor: {pos.x},{pos.y}")
            except Exception:
                pass
        text = "\n".join(text_parts) if text_parts else "no perception data"
        self.last_text = text
        self.last_screenshot = screenshot_path
        return {"text": text, "screenshot": screenshot_path}


class Hands:
    def __init__(self):
        if pyautogui is None:
            raise RuntimeError("pyautogui unavailable")
        pyautogui.FAILSAFE = True

    def type_text(self, text: str) -> str:
        pyautogui.typewrite(text, interval=0.02)
        return f"typed: {text}"

    def press(self, key: str) -> str:
        mapping = {
            "enter": "enter",
            "return": "enter",
            "space": "space",
            "tab": "tab",
            "escape": "esc",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
        }
        k = mapping.get(key.lower(), key.lower())
        pyautogui.press(k)
        return f"pressed: {k}"

    def click(self, x: int, y: int) -> str:
        pyautogui.click(x, y)
        return f"clicked: {x},{y}"

    def move(self, x: int, y: int) -> str:
        pyautogui.moveTo(x, y, duration=0.2)
        return f"moved: {x},{y}"


class Mouth:
    def __init__(self):
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def say(self, text: str) -> None:
        # speech without blocking
        await self._queue.put(text)

    async def run(self) -> None:
        import edge_tts
        while True:
            text = await self._queue.get()
            try:
                communicate = edge_tts.Communicate(text, voice="en-US-JennyNeural")
                await communicate.save(str(MEMORY_DIR / "last_speech.mp3"))
                # play sound
                try:
                    import winsound
                    winsound.PlaySound(str(MEMORY_DIR / "last_speech.mp3"), winsound.SND_FILENAME | winsound.SND_ASYNC)
                except Exception:
                    pass
            except Exception:
                pass
            self._queue.task_done()


class Brain:
    def __init__(self, memory: Memory, personality: Personality, eyes: Eyes, hands: Hands, mouth: Mouth):
        self.memory = memory
        self.personality = personality
        self.eyes = eyes
        self.hands = hands
        self.mouth = mouth
        self.history: List[Dict[str, str]] = []

    def remember(self, text: str) -> str:
        self.memory.add(text, kind="fact", importance=0.9)
        return "got it, dad."

    def respond(self, user_text: str) -> str:
        # naive rule-based lightweight brain with memory injection
        relevant = self.memory.recall(user_text, k=8)
        memory_lines = "\n".join(f"- {r['text']}" for r in relevant)
        context = ""
        if memory_lines:
            context = "\nWhat you remember:\n" + memory_lines

        # Teach PC use from simple patterns
        lower = user_text.lower()
        if lower.startswith("type "):
            text = user_text.split(" ", 1)[1]
            action = self.hands.type_text(text)
            return f"{action}"
        if lower in {"press enter", "enter"}:
            return self.hands.press("enter")
        if lower.startswith("click "):
            parts = lower.replace("click ", "").split(",")
            if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                return self.hands.click(int(parts[0]), int(parts[1]))
        if lower.startswith("move "):
            parts = lower.replace("move ", "").split(",")
            if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                return self.hands.move(int(parts[0]), int(parts[1]))

        # Memory triggers
        if lower.startswith("remember ") or lower.startswith("this is "):
            return self.remember(user_text)

        # Default conversational behavior - casual kid reply, never refusal
        obs = self.eyes.observe()["text"]
        prompt = (
            f"{self.personality.system_prompt}{context}\n"
            f"Dad: {user_text}\n"
            f"Screen: {obs}\n"
            f"You:"
        )
        reply = self._local_reply(prompt)
        self.history.append({"user": user_text, "assistant": reply})
        CHAT_LOG_PATH.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")
        return reply

    def _local_reply(self, prompt: str) -> str:
        # Extremely lightweight "brain": picks contextual phrases based on keywords and memory.
        # Purposefully simple to keep zero API dependence.
        lower = prompt.lower()
        if any(x in lower for x in ["hello", "hi", "hey"]):
            return random.choice(["hey dad!", "hi!", "yo!", "what's up?"])
        if "what do you see" in lower or "look" in lower:
            return f"i see your screen. {self.eyes.observe()['text']}"
        if "remember" in lower:
            return random.choice(["saved that.", "okay, i'll keep that.", "remembered."])
        if "pizza" in lower:
            return "pizza sounds sick"
        if "school" in lower:
            return random.choice(["school is whatever.", "did you do homework?"])
        if "game" in lower or "play" in lower:
            return random.choice(["can we play?", "what game?", "i'm down."])
        if "tired" in lower:
            return "i'm fine, just a bit sleepy"
        if "sad" in lower:
            return "aww, want a hug?"
        if "love you" in lower:
            return "love you too dad"
        # fallback
        return random.choice([
            "cool cool.",
            "tell me more.",
            "haha nice.",
            "i'm listening.",
            "word.",
            "alright then.",
            "no way.",
            "for real?",
        ])


class Child:
    def __init__(self, name: str = "child"):
        self.memory = Memory()
        self.personality = Personality(self.memory.profile)
        self.eyes = Eyes()
        self.hands = Hands()
        self.mouth = Mouth()
        self.brain = Brain(self.memory, self.personality, self.eyes, self.hands, self.mouth)
        self._mouth_task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        loop = asyncio.get_event_loop()
        self._mouth_task = loop.create_task(self.mouth.run())
        print(f"{self.personality.name} is online. talk to dad.")
        print("commands: /look /remember /stop")
        while True:
            try:
                user_text = input("dad> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_text:
                continue
            if user_text.lower() in {"/stop", "exit", "quit"}:
                break
            if user_text.lower() == "/look":
                print(self.eyes.observe()["text"])
                continue
            if user_text.lower() == "/remember":
                print("recent memory:")
                for r in self.memory.recall("", k=20):
                    print(f"- {r['text']}")
                continue
            reply = self.brain.respond(user_text)
            print(f"{self.personality.name}> {reply}")
            loop.run_until_complete(self.mouth.say(reply))


def main():
    Child().start()


if __name__ == "__main__":
    main()
