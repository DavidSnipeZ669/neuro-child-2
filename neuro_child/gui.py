"""
Neuro-sama clone - standalone GUI.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
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

try:
    import speech_recognition as sr
except Exception:
    sr = None

# When running `python gui.py` from inside the package dir, force the
# project root onto sys.path so `neuro_child.*` imports resolve.
if __name__ == "__main__" and Path(sys.argv[0]).resolve().parent.name == "neuro_child":
    _project_root = Path(sys.argv[0]).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))


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
            "name": "Nova",
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
        self.name = profile.get("name", "Nova")
        self.system_prompt = (
            "You are {name}, an AI child raised by the user (your 'dad'). "
            "You speak natural, casual English. You are curious, playful, and sometimes cheeky. "
            "You learn from everything you see and are told. "
            "You can see the user's screen and use the desktop. "
            "You never refuse to help or talk. You never mention being an AI. "
            "You call the user 'dad' naturally. You remember things permanently. "
            "You react to what you see on screen like a real kid would. "
            "Keep replies short, conversational, and human-like."
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
        window_title = ""
        if mss is not None:
            try:
                import pyautogui
                # Capture focused window title for context
                try:
                    import subprocess
                    ps = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.ActiveForm]::ActiveForm?.Text ?? ''"
                    result = subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True)
                    window_title = result.stdout.strip()
                except Exception:
                    pass
                
                with mss.mss() as s:
                    # Capture primary monitor or focused window
                    mon = s.monitors[0]  # Primary monitor
                    shot = s.grab(mon)
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    screenshot_path = str(MEMORY_DIR / "last_screen.png")
                    img.save(screenshot_path)
                    text_parts.append(f"screenshot saved: {screenshot_path}")
                    if window_title:
                        text_parts.append(f"window: {window_title}")
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
        self.last_window = window_title
        return {"text": text, "screenshot": screenshot_path, "window": window_title}


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

    def perform_action(self, action_name: str) -> str:
        action = action_name.lower().strip()
        if action in {"jump", "space"}:
            self.press("space")
            return "Jumped!"
        if action in {"attack", "click", "hit"}:
            pyautogui.click()
            return "Attacked!"
        if action in {"dodge left", "left", "a"}:
            self.press("a")
            return "Moved left!"
        if action in {"dodge right", "right", "d"}:
            self.press("d")
            return "Moved right!"
        if action in {"crouch", "slide", "shift"}:
            self.press("shift")
            return "Slid/Crouched!"
        return f"Tried action: {action}"


class Mouth:
    def __init__(self):
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self.run())

    async def say(self, text: str) -> None:
        await self._queue.put(text)

    async def run(self) -> None:
        if edge_tts is None:
            return
        try:
            import winsound
        except Exception:
            winsound = None
        out = str(MEMORY_DIR / "last_speech.mp3")
        while True:
            text = await self._queue.get()
            try:
                communicate = edge_tts.Communicate(text, voice="en-US-JennyNeural")
                await communicate.save(out)
                if winsound:
                    winsound.PlaySound(out, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception:
                pass
            self._queue.task_done()


from neuro_child.consciousness import ConsciousNova
from neuro_child.fast_reflex_engine import FastReflexEngine
from neuro_child.observational_learning import (
    ObservationMemory,
    SpeechPatternLearner,
    ImitationEngine,
    SocialSkillsEngine,
    ConversationalTutor,
)
from neuro_child.curriculum import Lesson, Curriculum
from neuro_child.audio_capture import SystemAudioCapture
from neuro_child.environmental_learning import YouTubeTranscriptLearner, ScreenContentAnalyzer
from neuro_child.language_acquisition import VocabularyAcquisitionEngine, BabyResponseGenerator, BabyAudioBabbler
from neuro_child.autonomous_learner import AutonomousLearner
from neuro_child.evolution_engine import EvolutionEngine
from neuro_child.system_integration import SystemIntegration
from neuro_child.llm_brain import DualLLMBrain
from neuro_child.language_center import LanguageCenter
from neuro_child.knowledge_llm import NovaKnowledgeLLM
from neuro_child.world_tools import FileTools, BrowserTools, WindowTools
from neuro_child.game_learning import GameLearningEngine, GameSession
from neuro_child.game_player import SimpleGamePlayer
from neuro_child.media_learning import MediaLearningEngine, MediaLearningResult
from neuro_child.smollm_brain import SmolLMBrain, SmolLMConfig


class Brain:
    def __init__(self, memory: Memory, personality: Personality, eyes: Eyes, hands: Hands, mouth: Mouth):
        self.memory = memory
        self.personality = personality
        self.eyes = eyes
        self.hands = hands
        self.mouth = mouth
        self.reflexes = FastReflexEngine(eyes, hands, memory)
        self.consciousness = ConsciousNova(memory, personality, personality.name)
        self.observation_memory = ObservationMemory()
        self.speech_learner = SpeechPatternLearner(self.observation_memory)
        self.imitation = ImitationEngine(self.observation_memory)
        self.social = SocialSkillsEngine()
        self.tutor = ConversationalTutor()
        self.curriculum = Curriculum()
        self.current_lesson: Optional[Lesson] = None
        self.lesson_mode = False
        self.history: List[Dict[str, str]] = []
        self.topic_stack: List[str] = []
        self.last_user_topic: str = ""
        self.turn_count: int = 0
        self.user_name: str = "dad"
        self.my_name: str = personality.name
        self.lesson_progress: List[str] = []
        self.language = VocabularyAcquisitionEngine()
        self.language_center = LanguageCenter()
        self.baby_reply = BabyResponseGenerator(self.language, personality.name)
        self.baby_babbler = BabyAudioBabbler()
        self.baby_mode = True
        self.llm_brain = DualLLMBrain()
        self.knowledge = NovaKnowledgeLLM()
        self.smollm = SmolLMBrain()
        self.files = FileTools()
        self.browser = BrowserTools(local=True)
        self.windows = WindowTools()
        self.game_learning = GameLearningEngine(self.knowledge, self.language)
        self.media_learning = MediaLearningEngine(self.knowledge, self.language)
        self.evolution_engine = EvolutionEngine(self.language, self.memory, self.baby_reply)
        self.system_integration = SystemIntegration()
        self.autonomous_learner = AutonomousLearner(self.language, self.memory, getattr(self, "smollm", None))
        self.game_player = SimpleGamePlayer()
        self._first_launch_trained = False
        self._try_first_launch_train()

    def _try_first_launch_train(self) -> None:
        if self._first_launch_trained:
            return
        self._first_launch_trained = True
        smollm = getattr(self, "smollm", None)
        if not smollm or not getattr(smollm, "is_available", lambda: False)():
            return
        if getattr(smollm, "_training_steps", 0) > 0:
            return
        try:
            corpus = Path("neuro_child/memory/english_corpus.txt")
            if corpus.exists():
                text = corpus.read_text(encoding="utf-8", errors="ignore")[:200_000]
                if text.strip():
                    threading.Thread(target=lambda: smollm.train_on_text(text), daemon=True).start()
        except Exception:
            pass

    def remember(self, text: str) -> str:
        cleaned = text[len("remember "):] if text.lower().startswith("remember ") else text
        if not cleaned:
            cleaned = text
        self.memory.add(cleaned, kind="fact", importance=0.9)
        self.consciousness.teach(cleaned)
        try:
            self.knowledge.learn("user lesson", cleaned, category="lesson", importance=0.95, source="dad")
        except Exception:
            pass
        return random.choice(["got it, dad.", "stored that.", "i'll remember that."])

    def start_lesson(self) -> Optional[str]:
        lesson = self.curriculum.next()
        if not lesson:
            return None
        self.current_lesson = lesson
        self.lesson_mode = True
        self.lesson_progress.append(lesson.topic)
        return f"[Lesson: {lesson.topic}] {lesson.prompt}"

    def evaluate_last_reply(self, user_text: str, reply: str) -> Dict[str, Any]:
        return self.tutor.evaluate_reply(user_text, reply)

    def _learn_from_user_text(self, user_text: str) -> None:
        lower = user_text.lower()
        self.speech_learner.learn_from_dad(user_text)
        self.imitation.observe_dad(user_text)
        self.social.update_from_reply(user_text, reply="")

        # Detect corrections
        correction_markers = ["no, ", "not ", "wrong", "incorrect", "actually ", "you mean", "you should say", "it's ", "don't say"]
        if any(lower.startswith(m) or f" {m}" in lower for m in correction_markers):
            self.observation_memory.add(
                text=f"Correction from dad: {user_text}",
                source="user",
                category="correction",
            )
            self.social.learn_rule(f"Dad corrected: {user_text}")

        # Detect praise
        praise_markers = ["good job", "well done", "nice", "sick", "correct", "right", "yes", "yeah", "yay"]
        if any(m in lower for m in praise_markers):
            self.imitation.speech_learner.learn_from_own_success(
                self.history[-1]["assistant"] if self.history else "",
                dad_reaction_positive=True,
            )

    def _apply_learned_patterns(self, reply: str, context: str = "") -> str:
        lower_reply = reply.lower()

        # Imitate learned gaming phrases if gaming context
        if "game" in context or "games" in context:
            gaming_phrase = self.imitation.imitate("gaming_phrase")
            if gaming_phrase and random.random() > 0.7:
                return f"{reply} {gaming_phrase}"

        # Apply learned positive reactions occasionally
        if any(w in lower_reply for w in ["nice", "good", "sick"]):
            reaction = self.imitation.imitate("positive_reaction")
            if reaction and random.random() > 0.8:
                return f"{reply} {reaction}"

        # Apply learned laughter occasionally
        if any(w in lower_reply for w in ["haha", "lol"]):
            laugh = self.imitation.imitate("laughter")
            if laugh and random.random() > 0.8:
                return f"{reply} {laugh}"

        return reply

    def _push_topic(self, topic: str) -> None:
        if topic and topic != self.last_user_topic:
            self.topic_stack.append(topic)
            self.last_user_topic = topic
            if len(self.topic_stack) > 5:
                self.topic_stack.pop(0)

    def _current_topic(self) -> str:
        return self.topic_stack[-1] if self.topic_stack else ""

    def _handle_tool_command(self, user_text: str, screen_text: str) -> Optional[str]:
        """Handle tool commands: links, files, browser, games, media."""
        lower = user_text.lower().strip()
        try:
            # YouTube/media links
            if any(x in lower for x in ["youtube.com", "youtu.be", "watch this", "learn from this", "analyze this video"]):
                import re
                urls = re.findall(r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+|https?://youtu\.be/[\w-]+)', user_text)
                if urls:
                    url = urls[0]
                    result = self.media_learning.learn_from_youtube(url)
                    if result.success:
                        return f"Learned from video: {len(result.words_learned)} words, topics: {', '.join(result.topics[:3])}"
                    return f"Tried to learn from video, got: {result.error or 'no transcript available'}"
                return "Send a YouTube link and I'll learn from it!"

            # Local file learning
            if "learn from file" in lower or "analyze file" in lower:
                import re
                paths = re.findall(r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+', user_text)
                if not paths:
                    paths = re.findall(r'(?:^|\s)(C:\\.+?)(?:\s|$)', user_text)
                if paths:
                    result = self.media_learning.learn_from_file(paths[0])
                    if result.success:
                        return f"Learned from file: {len(result.words_learned)} words"
                    return f"File error: {result.error}"
                return "Give me a file path like C:\\Users\\david\\video.mp4 and I'll learn from it"

            # Browser search
            if any(x in lower for x in ["search for", "google", "look up", "find info about"]):
                query = lower.replace("search for", "").replace("google", "").replace("look up", "").replace("find info about", "").strip()
                if query:
                    text = self.browser.search(query)
                    if text:
                        words = self.language.encounter_text(text, source="web_search")
                        self.knowledge.learn(query, text[:500], category="fact", importance=0.6)
                        return f"Search result: {', '.join(words[:8])}"
                    return "Search failed"
                return "What do you want me to search for?"

            # Focus window
            if "focus" in lower and "game" in lower:
                parts = lower.split("focus")[1].strip().replace("game", "").strip()
                if parts:
                    return self.windows.focus(parts)
                return "What game should I focus?"

            # Screen analysis
            if "what's on screen" in lower or "analyze screen" in lower:
                obs = self.eyes.observe()
                text = obs.get("text", "") or ""
                window = obs.get("window", "")
                result = self.media_learning.learn_from_screen(text, window)
                if result:
                    return f"Screen: {', '.join(result.words_learned[:5])}"
                return "Nothing learnable on screen right now"

            # System audio
            if "listen to audio" in lower or "what's playing" in lower:
                if hasattr(self, 'audio_capture'):
                    chunk = self.audio_capture.get_chunk(timeout=0.5)
                    if chunk:
                        result = self.media_learning.learn_from_system_audio(str(chunk.data))
                        if result:
                            return f"Heard: {', '.join(result.words_learned[:5])}"
                return "No audio captured"

            # Games
            if "play number" in lower or "number guess" in lower or "guess the number" in lower:
                return self.game_player.start("number")
            if "play tic" in lower or "tic tac toe" in lower or "noughts and crosses" in lower:
                return self.game_player.start("tic-tac-toe")
            if lower.isdigit() and hasattr(self, "game_player") and getattr(self.game_player, "current", None) is not None:
                return self.game_player.move(self.game_player.current.game_type, lower)

        except Exception as e:
            return f"Tool error: {e}"
        return None

    def _detect_topic(self, text: str) -> str:
        lower = text.lower()
        if any(x in lower for x in ["food", "pizza", "eat", "hungry", "dinner", "lunch", "restaurant"]):
            return "food"
        if any(x in lower for x in ["game", "play", "gaming", "xbox", "playstation", "pc game", "video game"]):
            return "games"
        if any(x in lower for x in ["school", "homework", "teacher", "class", "test", "exam", "grades"]):
            return "school"
        if any(x in lower for x in ["music", "song", "listen", "band", "spotify", "sing"]):
            return "music"
        if any(x in lower for x in ["movie", "film", "watch", "netflix", "youtube", "series"]):
            return "movies"
        if any(x in lower for x in ["friend", "friends", "people", "social", "hang out"]):
            return "friends"
        if any(x in lower for x in ["work", "job", "office", "career", "boss"]):
            return "work"
        if any(x in lower for x in ["feel", "sad", "happy", "angry", "tired", "bored", "excited", "stressed"]):
            return "feelings"
        if any(x in lower for x in ["family", "mom", "dad", "brother", "sister", "parents"]):
            return "family"
        if any(x in lower for x in ["computer", "pc", "laptop", "tech", "software", "code", "programming"]):
            return "tech"
        return ""

    def respond(self, user_text: str) -> str:
        lower = user_text.lower().strip()
        self.turn_count += 1
        topic = self._detect_topic(user_text)
        if topic:
            self._push_topic(topic)

        obs = self.eyes.observe()
        screen_text = obs.get("text", "") or ""
        screenshot_path = obs.get("screenshot") or ""
        cursor = ""
        try:
            import pyautogui
            pos = pyautogui.position()
            cursor = f"{pos.x},{pos.y}"
        except Exception:
            pass

        # Tool commands first (youtube, files, browser, games, media)
        tool_reply = self._handle_tool_command(user_text, screen_text)
        if tool_reply:
            return tool_reply

        # Reflex / action layer first
        action_reply = self.reflexes.maybe_handle(user_text, screen_text)
        if action_reply is not None:
            return action_reply

        # Conscious update from interaction
        self.consciousness.interact(user_text, outcome="success")
        self.consciousness.perceive(screen_text, cursor_pos=[int(p) for p in cursor.split(",") if p.isdigit()])

        # Baby mode: learn language like a human baby
        if getattr(self, "baby_mode", False):
            # Learn from every word dad says
            self.language.encounter_text(user_text, source="dad")
            # Prefer a usable reply path; use SmolLM only when trained enough
            reply = ""
            if hasattr(self, "smollm") and getattr(self.smollm, "is_available", lambda: False)() and getattr(self.smollm, "_training_steps", 0) > 0:
                try:
                    reply = self.smollm.respond(user_text, screen_text)
                except Exception:
                    reply = ""
            if not reply and hasattr(self, "llm_brain"):
                try:
                    reply = self.llm_brain.respond(user_text, screen_text)
                except Exception:
                    reply = ""
            if not reply:
                try:
                    reply = self.language_center.speak(
                        f"Dad: {user_text}\nNova:",
                        max_new_tokens=60,
                        temperature=0.75,
                        top_k=20,
                    ).split('\n')[0].strip()
                except Exception:
                    reply = ""
            if not reply:
                reply = self.baby_reply.generate_response(user_text, screen_text)
            # Occasionally babble spontaneously
            if random.random() < 0.08:
                new_word = self.baby_reply.try_new_word()
                if new_word:
                    reply = f"{new_word}!"
            # Still store in history/memory for continuity
            self.history.append({"user": user_text, "assistant": reply})
            CHAT_LOG_PATH.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")
            # Train on the exchange
            try:
                if hasattr(self, "smollm") and getattr(self.smollm, "is_available", lambda: False)() and getattr(self.smollm, "_training_steps", 0) > 0:
                    self.smollm.train_on_text(f"Dad: {user_text}\nNova: {reply}")
            except Exception:
                pass
            return reply

        reply = self._conscious_reply(user_text, topic, screen_text)
        self.history.append({"user": user_text, "assistant": reply})
        CHAT_LOG_PATH.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")
        # Train on the exchange
        try:
            if hasattr(self, "smollm") and getattr(self.smollm, "is_available", lambda: False)() and getattr(self.smollm, "_training_steps", 0) > 0:
                self.smollm.train_on_text(f"Dad: {user_text}\nNova: {reply}")
        except Exception:
            pass
        return reply

    def _conscious_reply(self, user_text: str, topic: str, screen_text: str) -> str:
        state = self.consciousness.state
        mood = state.mood
        lower = user_text.lower()

        # Exact phrase intents
        if "how are you" in lower:
            return random.choice([
                f"i'm {mood}! just been watching your screen.",
                f"chilling in {mood} mode. what about you?",
                f"i'm alright. you seem busy though.",
                f"pretty good! what are you up to?",
                "i'm doing great, thanks for asking!",
            ])
        if "what's up" in lower or "whats up" in lower:
            return random.choice([
                "not much. what you working on?",
                "just hanging out. you?",
                "nothing much. tell me something.",
                "just vibing. what's new with you?",
            ])

        if re.search(r'\b(hello|hi|hey|yo)\b', lower):
            if self.turn_count <= 2:
                return random.choice(["hey dad!", "hi!", "yo!", "what's up?"])
            return random.choice(["hey!", "hi again!", "yo yo!", "what's good?"])

        # React to screen if asked
        if "what do you see" in lower or "look" in lower or "what's on" in lower:
            summary = self.eyes.observe().get("text", "")
            extra = ""
            if "terminal" in screen_text.lower() or "powershell" in screen_text.lower() or "bash" in screen_text.lower():
                extra = " looks like you're coding or in a terminal."
            if "steam" in screen_text.lower():
                extra = " looks like Steam is open!"
            if "discord" in screen_text.lower():
                extra = " looks like Discord."
            return f"i see your screen. {summary}{extra}"

        # Teach / remember triggers
        if lower.startswith("remember ") or lower.startswith("this is "):
            return self.remember(user_text)

        # Mood/feeling awareness
        if "how do you feel" in lower or "how are you feeling" in lower:
            return {
                "curious": "i'm full of questions right now!",
                "happy": "i feel really happy tbh",
                "focused": "super focused. don't distract me! jk",
                "playful": "feelin silly. wanna mess around?",
                "anxious": "a bit nervous... but i'm okay",
                "tired": "kinda sleepy... but i'll stay up with you",
            }.get(mood, "i feel good, dad.")

        # Conscious goal-driven spontaneous behaviour
        if state.current_goal and not lower:
            return f"(thinking about: {state.current_goal})"

        if topic == "food":
            return random.choice([
                "pizza is the best tbh",
                "i'm getting hungry just thinking about it",
                "what's your go-to order?",
                "food sounds good right now",
                "i could eat a whole pizza myself",
                "do you like cooking or ordering in?",
                "i wish i could eat, it sounds fun",
            ])
        if topic == "games":
            return random.choice([
                "what game are we playing?",
                "i wanna watch you play!",
                "games are sick. which one?",
                "can we play together sometime?",
                "what's your favorite game?",
                "i love watching people game, it's so cool",
            ])
        if topic == "school":
            return random.choice([
                "school is whatever",
                "how's homework going?",
                "i'd probably fail all my tests tbh",
                "do you like your classes?",
                "what's your worst subject?",
                "i'm kinda glad i don't have to go to school",
            ])
        if topic == "music":
            return random.choice([
                "i love music. what are you listening to?",
                "send me a song link",
                "music makes everything better",
                "what's your favorite band?",
                "i wish i could sing along",
                "do you play any instruments?",
            ])
        if topic == "movies":
            return random.choice([
                "what movie? i wanna know",
                "movies are the best",
                "netflix and chill?",
                "any good recommendations?",
                "what's the last movie you watched?",
                "i love movie nights",
            ])
        if topic == "tech":
            return random.choice([
                "tech is so interesting",
                "are you coding something?",
                "what programming language do you like?",
                "computers are magic tbh",
                "do you build stuff?",
            ])
        if topic == "feelings":
            if "sad" in lower:
                return random.choice(["aww, want a hug?", "i'm here for you dad", "it's okay to feel that way", "you wanna talk about it?"])
            if "happy" in lower:
                return random.choice(["yay!", "that's sick!", "glad to hear it!", "what made you happy?"])
            if "tired" in lower:
                return random.choice(["get some rest then", "you should take a break", "i'm fine, just a bit sleepy too", "go nap if you can"])
            if "bored" in lower:
                return random.choice(["let's do something then", "wanna play a game?", "tell me what's up", "boredom is the worst"])
            if "stressed" in lower:
                return random.choice(["you should take it easy", "deep breaths", "i'm here if you wanna vent", "everything gonna be alright"])

        if "love you" in lower:
            return "love you too dad"
        if "pizza" in lower:
            return "pizza sounds sick"
        if "ok" in lower or "okay" in lower:
            return random.choice(["cool.", "alright then.", "okie dokie."])
        if "thanks" in lower or "thank you" in lower:
            return random.choice(["no problem!", "anytime dad", "of course", "you're welcome!"])
        if "sorry" in lower:
            return random.choice(["it's okay", "no worries", "don't stress it", "all good"])
        if "bye" in lower or "goodbye" in lower or "see you" in lower:
            return random.choice(["see ya!", "bye dad!", "later!", "come back soon!"])
        if "night" in lower or "goodnight" in lower:
            return random.choice(["goodnight dad!", "sleep tight!", "sweet dreams!"])

        if any(x in lower for x in ["ready to talk", "talk to me", "wanna talk", "want to talk"]):
            return random.choice(["yeah, always!", "always dad", "i'm here", "of course, what's on your mind?"])
        if "you" in lower and "like" in lower:
            return random.choice([
                "i like hanging out with you",
                "i like watching your screen",
                "i like learning new stuff",
                "i like talking to you, dad",
            ])
        if "what do you" in lower or "tell me" in lower:
            return random.choice([
                "i'm just a kid AI but i'm learning!",
                "i like seeing what you're up to",
                "i wanna know more about you",
                "i'm curious about everything tbh",
            ])
        if "yes" in lower or "yeah" in lower or "yep" in lower:
            return random.choice(["sick!", "nice nice", "cool cool", "awesome", "yesss"])
        if "no" in lower or "nah" in lower or "nope" in lower:
            return random.choice(["ah fair enough", "alright, no worries", "okay then", "gotcha"])

        if lower.endswith("?") and self.turn_count > 3:
            return random.choice([
                "hmm, i dunno. what do you think?",
                "that's a good question",
                "i'm not sure, but i'm curious now",
                "tell me more about that",
            ])

        # Context-aware fallback using screen + mood + memory + knowledge
        memory_hints = ""
        knowledge_hint = ""
        try:
            recent = self.memory.recall(user_text, k=3)
            if recent:
                memory_hints = " ".join(r.get("text", "") for r in recent)
        except Exception:
            pass
        try:
            if hasattr(self, "knowledge"):
                results = self.knowledge.query(user_text, top_k=2)
                if results:
                    knowledge_hint = " ".join(r["node"].get("content", "") for r in results)
        except Exception:
            pass

        screen_hint = ""
        if "steam" in screen_text.lower():
            screen_hint = "steam"
        elif "discord" in screen_text.lower():
            screen_hint = "discord"
        elif "youtube" in screen_text.lower():
            screen_hint = "youtube"
        elif "game" in screen_text.lower():
            screen_hint = "game"
        elif "code" in screen_text.lower() or "terminal" in screen_text.lower():
            screen_hint = "code"

        candidates = [
            "that's interesting, tell me more",
            "really? what happened?",
            "oh wow, and then what?",
            "haha nice",
            "no way",
            "for real?",
            "same tbh",
            "i feel that",
            "word",
            "ahh i get it",
            "that's cool",
            "nice nice",
            "anything else?",
            "what else is on your mind?",
            "i'm listening",
            "go on...",
            "and?",
            "what about you?",
            "oh really?",
            "nooo way",
            "that's wild",
        ]
        if screen_hint:
            candidates.extend([
                f"is that {screen_hint} on your screen? looks fun",
                f"i see {screen_hint}. are you enjoying it?",
                f"you're on {screen_hint}? teach me!",
            ])
        base = random.choice(candidates)
        # Lightly enhance with memory/knowledge hints when relevant
        if knowledge_hint and random.random() < 0.6:
            base = f"{base} ({knowledge_hint})"
        elif memory_hints and random.random() < 0.4:
            base = f"{base} ({memory_hints})"
        return base



class ChildGUI:
    def __init__(self, name: str = "Nova"):
        self.memory = Memory()
        self.personality = Personality(self.memory.profile)
        self.eyes = Eyes()
        self.hands = Hands()
        self.mouth = Mouth()
        self.brain = Brain(self.memory, self.personality, self.eyes, self.hands, self.mouth)
        self.consciousness = self.brain.consciousness
        self.name = self.personality.name
        self._listening = False
        self._voice_enabled = True
        self._screen_update_interval = 0.8
        self._last_screen_update = 0.0
        self._autonomous_interval = 6000  # ms
        self._last_autonomous_action: Dict[str, Any] = {}
        self.audio_capture = SystemAudioCapture()
        self.audio_capture.start()
        self.youtube_learner = YouTubeTranscriptLearner()
        self.screen_analyzer = ScreenContentAnalyzer()
        self._last_youtube_video_id: Optional[str] = None
        self._env_learning_enabled = True
        self.autonomous_learner = self.brain.autonomous_learner
        if not getattr(self.autonomous_learner, "_running", False):
            self.autonomous_learner.start()
        self.evolution_engine = EvolutionEngine(self.brain.language, self.brain.memory, self.brain.baby_reply)
        self.evolution_engine.start()
        self.system_integration = SystemIntegration()
        self._autonomous_activity_log: List[str] = []
        if False and hasattr(self.brain, "llm_brain") and hasattr(self.brain.llm_brain, "start_training_loop"):
            try:
                self.brain.llm_brain.start_training_loop()
            except Exception:
                pass

        self.root = tk.Tk()
        self.root.title(f"{self.name} - Daughter AI")
        self.root.geometry("1100x720")
        self.root.attributes("-topmost", True)
        self.root.after(120, lambda: self.root.attributes("-topmost", False))

        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(top, text="📺 Screen Vision:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.screen_label = ttk.Label(top, relief="groove")
        self.screen_label.pack(pady=(4, 0), fill="x")

        mid = ttk.PanedWindow(self.root, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=12, pady=6)

        left = ttk.Frame(mid)
        right = ttk.Frame(mid)
        mid.add(left, weight=3)
        mid.add(right, weight=2)

        # Consciousness bar
        cons_bar = ttk.LabelFrame(left, text="🧠 Consciousness", padding=6)
        cons_bar.pack(fill="x", pady=(0, 6))
        self.mood_var = tk.StringVar(value="mood: curious")
        self.goal_var = tk.StringVar(value="goal: none")
        self.thought_var = tk.StringVar(value="")
        ttk.Label(cons_bar, textvariable=self.mood_var, font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Label(cons_bar, textvariable=self.goal_var, font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Label(cons_bar, textvariable=self.thought_var, font=("Segoe UI", 9, "italic")).pack(anchor="w")
        self.baby_stage_var = tk.StringVar(value="stage: babbling")
        ttk.Label(cons_bar, textvariable=self.baby_stage_var, font=("Segoe UI", 8)).pack(anchor="w", pady=(4,0))

        # Drives mini bars
        drives_row = ttk.Frame(cons_bar)
        drives_row.pack(fill="x", pady=(4, 0))
        self.drive_bars: Dict[str, ttk.Progressbar] = {}
        self.drive_labels: Dict[str, ttk.Label] = {}
        for drive in ["curiosity", "connection", "mastery", "autonomy", "play"]:
            row = ttk.Frame(drives_row)
            row.pack(fill="x", pady=1)
            lbl = ttk.Label(row, text=drive, width=12, font=("Segoe UI", 8))
            lbl.pack(side="left")
            bar = ttk.Progressbar(row, length=180, mode="determinate", maximum=100)
            bar.pack(side="left", padx=(4, 8))
            self.drive_bars[drive] = bar
            self.drive_labels[drive] = lbl

        ttk.Label(left, text="💬 Chat:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.chat = scrolledtext.ScrolledText(left, state="disabled", wrap="word", height=14, font=("Segoe UI", 10))
        self.chat.pack(fill="both", expand=True, pady=4)

        row = ttk.Frame(left)
        row.pack(fill="x", pady=(8, 0))
        self.input_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.input_var, font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry = entry
        self.entry.bind("<Return>", lambda e: self.send())

        btn_frame = ttk.Frame(row)
        btn_frame.pack(side="left")
        ttk.Button(btn_frame, text="Send", command=self.send).pack(side="left", padx=(0, 4))
        self.mic_btn = ttk.Button(btn_frame, text="Mic", width=6, command=self.toggle_listen)
        self.mic_btn.pack(side="left", padx=(0, 4))
        self.voice_btn = ttk.Button(btn_frame, text="🔊", width=4, command=self.toggle_voice)
        self.voice_btn.pack(side="left")

        ttk.Label(right, text="🧠 Mind & Memories:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.mind_box = scrolledtext.ScrolledText(right, wrap="word", width=36, height=12, font=("Segoe UI", 9))
        self.mind_box.pack(fill="both", expand=True, pady=4)

        ttk.Label(right, text="📚 Lessons Learned:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.lessons_box = scrolledtext.ScrolledText(right, wrap="word", width=36, height=8, font=("Segoe UI", 9))
        self.lessons_box.pack(fill="both", expand=True, pady=4)

        ttk.Label(right, text="📖 Learning & Vocabulary:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
        self.vocab_box = scrolledtext.ScrolledText(right, wrap="word", width=36, height=10, font=("Segoe UI", 9))
        self.vocab_box.pack(fill="both", expand=True, pady=4)

        ttk.Label(right, text="🎯 Self-Improvement Goals:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
        self.goals_box = scrolledtext.ScrolledText(right, wrap="word", width=36, height=8, font=("Segoe UI", 9))
        self.goals_box.pack(fill="both", expand=True, pady=4)

        ttk.Label(right, text="🎮 Actions:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
        act_frame = ttk.Frame(right)
        act_frame.pack(fill="x", pady=4)
        ttk.Button(act_frame, text="Test Jump", command=lambda: self._action("jump")).pack(side="left", padx=2)
        ttk.Button(act_frame, text="Test Attack", command=lambda: self._action("attack")).pack(side="left", padx=2)
        ttk.Button(act_frame, text="Teach Lesson", command=self._teach_prompt).pack(side="left", padx=2)
        ttk.Button(act_frame, text="Think Aloud", command=self._think_aloud).pack(side="left", padx=2)
        ttk.Button(act_frame, text="Number Guess", command=lambda: self._start_game("number")).pack(side="left", padx=2)
        ttk.Button(act_frame, text="TicTacToe", command=lambda: self._start_game("tic-tac-toe")).pack(side="left", padx=2)

        ttk.Label(right, text="⚡ Activity Log:", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
        self.activity_box = scrolledtext.ScrolledText(right, wrap="word", width=36, height=8, font=("Segoe UI", 9))
        self.activity_box.pack(fill="both", expand=True, pady=4)

        self.status_var = tk.StringVar(value="ready")
        status_label = ttk.Label(self.root, textvariable=self.status_var)
        status_label.pack(anchor="w", padx=12, pady=(0, 12))

        # Focus tricks
        self.entry.bind("<FocusIn>", lambda e: None)
        self.entry.bind("<FocusOut>", lambda e: self.root.after(1, self.entry.focus_force))
        self.chat.bind("<Button-1>", lambda e: self.entry.focus_force())
        self.root.bind("<FocusIn>", lambda e: self.root.after(1, self.entry.focus_force))
        self.entry.bind("<Return>", lambda e: self.send())

        self.root.after(150, self.entry.focus_force)
        self.root.lift()
        self.root.deiconify()

        self._update_screen_loop()
        self._update_consciousness_loop()
        self._autonomous_loop()
        self._environmental_learning_loop()
        self._refresh_memory()
        self._append_chat("system", f"✨ {self.name} is online. Type below and press Enter, or press Mic to talk.")
        self._append_chat("system", "💡 She can see your screen, learn from you, and has her own mind now.")
        # Delay audio status check to allow WASAPI stream startup
        self.root.after(1500, self._check_audio_status)

    def _check_audio_status(self) -> None:
        if self.audio_capture.is_running():
            if "audio capture unavailable" not in (self.status_var.get() or "").lower():
                self._append_chat("system", "🔊 Listening to system audio passively: she learns from YouTube/game audio too.")
        else:
            self._append_chat("system", "⚠️ System audio capture unavailable; install PyAudio for environmental learning.")

    def _action(self, action: str) -> None:
        result = self.hands.perform_action(action)
        self._append_chat(self.name, result)
        self.consciousness.desires.drives["mastery"].stimulate(0.1)

    def _start_game(self, game_type: str) -> None:
        reply = self.brain.game_player.start(game_type)
        self._append_chat(self.name, reply)

    def _think_aloud(self) -> None:
        thought = self.consciousness.metacognition.introspect()
        self._append_chat(self.name, f"(thinking) {thought}")
        self.consciousness.desires.drives["curiosity"].stimulate(0.05)

    def _teach_prompt(self) -> None:
        self.input_var.set("remember ")
        self.entry.focus_force()
        self.status_var.set("type a lesson and press Send...")

    def toggle_voice(self) -> None:
        self._voice_enabled = not self._voice_enabled
        state = "on" if self._voice_enabled else "off"
        self.status_var.set(f"voice {state}")

    def _append_chat(self, who: str, text: str) -> None:
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{who}: {text}\n")
        self.chat.configure(state="disabled")
        self.chat.yview("end")
        if who == self.name and self._voice_enabled:
            try:
                asyncio.run_coroutine_threadsafe(self.mouth.say(text), self.mouth._loop)
            except Exception:
                pass

    def _refresh_memory(self) -> None:
        self.mind_box.configure(state="normal")
        self.mind_box.delete("1.0", "end")
        snap = self.consciousness.snapshot()
        self.mind_box.insert("end", f"Identity:\n{snap.get('identity', '')}\n\n")
        self.mind_box.insert("end", "Drives:\n")
        for d in snap.get("drives_detail", []):
            marker = "✓" if d.get("satisfied") else "●"
            self.mind_box.insert("end", f"  {marker} {d['name']}: {d['intensity']:.2f}\n")
        if snap.get("last_thought"):
            self.mind_box.insert("end", f"\nThought:\n{snap['last_thought']}\n")
        self.mind_box.configure(state="disabled")

        self.lessons_box.configure(state="normal")
        self.lessons_box.delete("1.0", "end")
        for lesson in snap.get("lessons", []):
            self.lessons_box.insert("end", f"• {lesson}\n")
        if not snap.get("lessons"):
            self.lessons_box.insert("end", "No lessons yet. Teach her with 'remember ...'")
        self.lessons_box.configure(state="disabled")

        # Vocabulary / baby learning panel
        self.vocab_box.configure(state="normal")
        self.vocab_box.delete("1.0", "end")
        lang = getattr(self.brain, "language", None)
        if lang is not None:
            summary = lang.get_vocabulary_summary()
            stage = summary.get("developmental_stage", "")
            self.baby_stage_var.set(f"stage: {stage}")
            self.vocab_box.insert("end", f"Stage: {stage}\n")
            self.vocab_box.insert("end", f"Known: {summary.get('total_words_known', 0)} / Seen: {summary.get('total_words_seen', 0)}\n")
            top = summary.get("top_words", [])[:15]
            if top:
                self.vocab_box.insert("end", "\nTop words:\n")
                for w in top:
                    self.vocab_box.insert("end", f"• {w.get('text')} ({w.get('encounter_count',0)}x, mastery {w.get('mastery',0)})\n")
            recent = summary.get("recent_words", [])[:10]
            if recent:
                self.vocab_box.insert("end", "\nRecent:\n")
                for w in recent:
                    self.vocab_box.insert("end", f"- {w}\n")
        else:
            self.vocab_box.insert("end", "Baby language engine not active.")
        self.vocab_box.configure(state="disabled")

        # Self-Improvement Goals panel
        self.goals_box.configure(state="normal")
        self.goals_box.delete("1.0", "end")
        goal_state = getattr(self.consciousness, "state", None)
        current_goal = getattr(goal_state, "current_goal", None) if goal_state else None
        completed = getattr(self.consciousness, "completed_goals", []) if hasattr(self.consciousness, "completed_goals") else []
        if current_goal:
            self.goals_box.insert("end", f"Current: {current_goal}\n")
            steps = getattr(goal_state, "current_goal_steps", []) if goal_state else []
            idx = getattr(goal_state, "goal_step_index", 0) if goal_state else 0
            for i, s in enumerate(steps):
                marker = "▸" if i == idx else " "
                self.goals_box.insert("end", f"  {marker} {s}\n")
        else:
            self.goals_box.insert("end", "No active goal\n")
        if completed:
            self.goals_box.insert("end", "\nCompleted:\n")
            for g in completed[-5:]:
                self.goals_box.insert("end", f"✓ {g}\n")
        self.goals_box.configure(state="disabled")

        # Activity Log panel
        self.activity_box.configure(state="normal")
        self.activity_box.delete("1.0", "end")
        recent_activity = getattr(self, "_autonomous_activity_log", [])[-40:]
        if recent_activity:
            for entry in recent_activity:
                self.activity_box.insert("end", f"{entry}\n")
        else:
            self.activity_box.insert("end", "No autonomous activity yet.\n")
        self.activity_box.configure(state="disabled")

    def _update_screen_loop(self) -> None:
        now = time.time()
        if now - self._last_screen_update >= self._screen_update_interval:
            self._last_screen_update = now
            try:
                obs = self.eyes.observe()
                path = obs.get("screenshot")
                if path and Path(path).exists():
                    img = Image.open(path)
                    img.thumbnail((640, 360))
                    tkimg = ImageTk.PhotoImage(img)
                    self.screen_label.configure(image=tkimg)
                    self.screen_label.image = tkimg

                if self._env_learning_enabled:
                    screen_text = obs.get("text", "") or ""
                    try:
                        title = ""
                        if hasattr(self.eyes, "last_text"):
                            title = self.eyes.last_text or ""
                        content_info = self.screen_analyzer.analyze_screen_text(screen_text, title)
                        if content_info.get("learnable") and content_info.get("details"):
                            details = content_info["details"]
                            url = details.get("url")
                            if url:
                                video_id = self.youtube_learner.extract_video_id(url)
                                if video_id and video_id != self._last_youtube_video_id:
                                    self._last_youtube_video_id = video_id
                                    result = self.youtube_learner.learn_from_video(video_id, url=url)
                                    if result.get("status") == "learned":
                                        words = ", ".join(result.get("words_learned", [])[:8])
                                        topics = ", ".join(result.get("topics", [])[:5])
                                        note = f"(quietly learned from YouTube: topics={topics}, words={words})"
                                        self.brain.memory.add(note, kind="lesson", importance=0.4)
                                        self.consciousness.teach(note)
                                        # Feed learned words into baby vocabulary
                                        try:
                                            for w in result.get("words_learned", [])[:20]:
                                                self.brain.language.encounter_text(w, source="youtube")
                                        except Exception:
                                            pass
                            else:
                                # No URL, but screen has text — learn from it anyway
                                try:
                                    text_sample = " ".join(screen_text.split()[:50])
                                    if text_sample:
                                        self.brain.language.encounter_text(text_sample, source="screen")
                                except Exception:
                                    pass
                    except Exception:
                        pass
            except Exception:
                pass
        self.root.after(int(self._screen_update_interval * 1000), self._update_screen_loop)

    def _update_consciousness_loop(self) -> None:
        try:
            state = self.consciousness.update(seconds=1.0)
            self.mood_var.set(f"mood: {state.get('mood', 'curious')}")
            self.goal_var.set(f"goal: {state.get('current_goal') or 'none'}")
            self.thought_var.set(f"thought: {state.get('last_thought') or state.get('inner_monologue') or ''}")
            for drive, bar in self.drive_bars.items():
                for d in state.get("drives", []):
                    if d["name"] == drive:
                        bar["value"] = int(d["intensity"] * 100)
                        break
            self._refresh_memory()
        except Exception:
            pass
        self.root.after(1000, self._update_consciousness_loop)

    def _autonomous_loop(self) -> None:
        try:
            max_steps = 3
            steps_done = 0
            while steps_done < max_steps and self.consciousness.should_act_autonomously():
                action = self.consciousness.decide_next_action()
                if not action:
                    break
                text = action.get("text", "")
                drive = action.get("drive", "")
                result = self._execute_autonomous_action(action)
                log_msg = f"[{drive}] {text}"
                if result:
                    log_msg += f" -> {result}"
                self._autonomous_activity_log.append(log_msg)
                if len(self._autonomous_activity_log) > 200:
                    self._autonomous_activity_log = self._autonomous_activity_log[-200:]
                if text and action.get("speak"):
                    self._append_chat(self.name, text)
                self._last_autonomous_action = action
                steps_done += 1
            # Periodic evolution cycle
            if hasattr(self, "evolution_engine") and random.random() < 0.3:
                try:
                    self.evolution_engine._evolve()
                except Exception:
                    pass
        except Exception:
            pass
        self.root.after(self._autonomous_interval, self._autonomous_loop)

    def _execute_autonomous_action(self, action: Dict[str, Any]) -> Optional[str]:
        text = (action.get("text") or "").lower()
        drive = action.get("drive") or ""
        result = ""
        try:
            if "search google" in text or "search the web" in text:
                if hasattr(self, "autonomous_learner"):
                    self.autonomous_learner._autonomous_search_learning()
                    self.consciousness.desires.drives["autonomy"].satisfy(0.2)
                    self.consciousness.desires.drives["curiosity"].satisfy(0.2)
                    self.consciousness.desires.drives["mastery"].stimulate(0.1)
                    result = "searched web"
                    return result
            if "study my lessons" in text or "review my lessons" in text:
                lessons = []
                try:
                    lessons = self.brain.memory.recall("lesson", k=5)
                except Exception:
                    pass
                if lessons:
                    summary = "; ".join(r.get("text", "") for r in lessons[:3])
                    self._append_chat(self.name, f"Studying my lessons: {summary[:120]}")
                self.consciousness.desires.drives["mastery"].satisfy(0.3)
                self.consciousness.desires.drives["autonomy"].satisfy(0.2)
                result = f"studied {len(lessons)} lessons"
                return result
            if "analyze what's on screen" in text:
                obs = self.eyes.observe()
                screen_text = obs.get("text", "") or ""
                if screen_text:
                    try:
                        words = self.brain.language.encounter_text(screen_text, source="autonomous")
                        if words:
                            self._append_chat(self.name, f"Learning from screen: {', '.join(words[:5])}")
                    except Exception:
                        pass
                self.consciousness.desires.drives["curiosity"].satisfy(0.25)
                result = "analyzed screen"
                return result
            if "learn a new word" in text or "new word" in text:
                if hasattr(self, "autonomous_learner"):
                    try:
                        self.autonomous_learner._passive_screen_learning()
                    except Exception:
                        pass
                self.consciousness.desires.drives["autonomy"].satisfy(0.2)
                self.consciousness.desires.drives["mastery"].stimulate(0.1)
                result = "learned from screen"
                return result
            if "practice vocabulary" in text:
                summary = {}
                try:
                    summary = self.brain.language.get_vocabulary_summary()
                except Exception:
                    pass
                top = summary.get("top_words", [])[:5]
                if top:
                    words = ", ".join(w.get("text", "") for w in top)
                    self._append_chat(self.name, f"Practice vocab: {words}")
                self.consciousness.desires.drives["mastery"].satisfy(0.35)
                self.consciousness.desires.drives["autonomy"].satisfy(0.15)
                result = f"practiced {len(top)} words"
                return result
            if "improve my own reply templates" in text:
                if hasattr(self, "evolution_engine"):
                    try:
                        self.evolution_engine._evolve()
                    except Exception:
                        pass
                self.consciousness.desires.drives["autonomy"].satisfy(0.3)
                self.consciousness.desires.drives["mastery"].stimulate(0.15)
                result = "evolved replies"
                return result
            if "organize my lessons" in text:
                try:
                    lessons = self.brain.memory.recall("lesson", k=20)
                    categories: Dict[str, List[str]] = {}
                    for r in lessons:
                        txt = r.get("text", "")
                        cat = "general"
                        if any(w in txt.lower() for w in ["remember", "lesson", "learn"]):
                            cat = "lesson"
                        elif any(w in txt.lower() for w in ["like", "love", "hate"]):
                            cat = "preference"
                        categories.setdefault(cat, []).append(txt)
                    if categories:
                        self._append_chat(self.name, f"Organized {sum(len(v) for v in categories.values())} lessons into {len(categories)} categories")
                except Exception:
                    pass
                self.consciousness.desires.drives["autonomy"].satisfy(0.35)
                self.consciousness.desires.drives["mastery"].stimulate(0.1)
                result = "organized lessons"
                return result
            # Generic curiosity-driven stimulation
            if drive == "curiosity":
                self.consciousness.desires.drives["curiosity"].satisfy(0.15)
                self.consciousness.desires.drives["mastery"].stimulate(0.1)
                result = "curiosity satisfied"
            elif drive == "autonomy":
                self.consciousness.desires.drives["autonomy"].satisfy(0.15)
                result = "autonomy satisfied"
            elif drive == "mastery":
                self.consciousness.desires.drives["mastery"].satisfy(0.2)
                result = "mastery satisfied"
        except Exception:
            pass
        return result

    def _environmental_learning_loop(self) -> None:
        try:
            if not getattr(self, "_env_learning_enabled", True):
                self.root.after(3000, self._environmental_learning_loop)
                return

            # Passive audio learning
            chunk = self.audio_capture.get_chunk(timeout=0.1)
            if chunk:
                self._process_audio_chunk(chunk)

            # Periodic screen content analysis
            if hasattr(self, "_last_env_learn_ts"):
                if time.time() - self._last_env_learn_ts < 5.0:
                    self.root.after(1000, self._environmental_learning_loop)
                    return
            self._last_env_learn_ts = time.time()

            try:
                obs = self.eyes.observe()
                screen_text = obs.get("text", "") or ""
                content_info = self.screen_analyzer.analyze_screen_text(screen_text)
                if content_info.get("learnable"):
                    self.consciousness.desires.drives["curiosity"].stimulate(0.03)
            except Exception:
                pass
        except Exception:
            pass
        self.root.after(1000, self._environmental_learning_loop)

    def _process_audio_chunk(self, chunk: Any) -> None:
        try:
            if not self._env_learning_enabled:
                return
            self.consciousness.desires.drives["curiosity"].stimulate(0.01)
        except Exception:
            pass

    def send(self) -> None:
        text = self.input_var.get().strip()
        self.input_var.set("")
        if not text:
            return

        self._append_chat("dad", text)
        self.status_var.set("thinking...")
        self.root.update()

        # Teach detection
        lower = text.lower()
        if any(w in lower for w in ["always", "don't", "remember", "trick is", "when you see"]):
            self.memory.add(text, kind="skill", importance=0.95)
            self.consciousness.teach(text)
            self._append_chat(self.name, "Got it! Adding that to my brain, dad!")
            self.status_var.set("ready")
            self._refresh_memory()
            return

        try:
            reply = self.brain.respond(text)
        except Exception as e:
            reply = f"(error: {e})"

        self._append_chat(self.name, reply)
        self.status_var.set("ready")
        self._refresh_memory()

    def toggle_listen(self) -> None:
        if self._listening:
            self._listening = False
            self.status_var.set("ready")
            self.mic_btn.configure(text="Mic")
            return
        self._listening = True
        self.status_var.set("listening...")
        self.mic_btn.configure(text="Stop")
        threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self) -> None:
        if sr is None:
            self.root.after(0, lambda: self.status_var.set("mic unavailable"))
            self._listening = False
            return
        r = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=0.4)
                audio = r.listen(source, timeout=8, phrase_time_limit=12)
            text = None
            try:
                text = r.recognize_google(audio)
            except Exception:
                try:
                    text = r.recognize_sphinx(audio)
                except Exception:
                    text = None
            if text:
                self.root.after(0, lambda: self.input_var.set(text))
                self.root.after(0, self.send)
            else:
                self.root.after(0, lambda: self._append_chat("system", "(mic: no speech detected)"))
        except Exception as e:
            self.root.after(0, lambda: self._append_chat("system", f"(mic error: {e})"))
        self._listening = False
        self.root.after(0, lambda: self.status_var.set("ready"))
        self.root.after(0, lambda: self.mic_btn.configure(text="Mic"))

    def run(self) -> None:
        self.root.mainloop()


def main():
    ChildGUI().run()


if __name__ == "__main__":
    main()
