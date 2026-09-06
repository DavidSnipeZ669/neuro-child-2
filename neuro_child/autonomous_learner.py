"""
Autonomous learning engine: Nova learns without dad prompting her.

Sources:
- Screen text / OCR
- System audio / speech recognition  
- Google/web search queries
- YouTube transcripts
- File system observation
- Autonomous curiosity-driven exploration
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import threading
import urllib.parse
import urllib.request
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neuro_child.language_acquisition import VocabularyAcquisitionEngine
from neuro_child.memory import Memory


AUTONOMY_LOG = Path(__file__).resolve().parent / "memory" / "autonomy_log.json"
LEARNING_QUEUE = Path(__file__).resolve().parent / "memory" / "learning_queue.json"


@dataclass
class LearningTask:
    topic: str
    source: str = "autonomous"
    priority: float = 0.5
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    result: Optional[str] = None


class AutonomousLearner:
    """
    Drives Nova's self-directed learning without dad prompting.

    She:
    - Watches screen content and extracts new words/topics
    - Listens to system audio for speech/text
    - Searches Google/web for topics she's curious about
    - Maintains a learning queue
    - Generates autonomous goals based on curiosity drives
    - Learns from YouTube, games, apps, browser tabs
    """

    def __init__(self, vocab: VocabularyAcquisitionEngine, memory: Memory, smollm=None) -> None:
        self.vocab = vocab
        self.memory = memory
        self.smollm = smollm
        self._queue: List[LearningTask] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_search_ts = 0.0
        self._search_cooldown = 30.0
        self._last_screen_learn_ts = 0.0
        self._screen_learn_cooldown = 5.0
        self._learned_urls: set = set()
        self._load_queue()

    def _load_queue(self) -> None:
        try:
            if LEARNING_QUEUE.exists():
                data = json.loads(LEARNING_QUEUE.read_text(encoding="utf-8"))
                for item in data:
                    if isinstance(item, dict):
                        self._queue.append(LearningTask(**item))
        except Exception:
            self._queue = []

    def _save_queue(self) -> None:
        try:
            data = [task.__dict__ for task in self._queue[-100:]]
            LEARNING_QUEUE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                # Periodic web search learning
                if now - self._last_search_ts >= self._search_cooldown:
                    self._last_search_ts = now
                    self._autonomous_search_learning()
                # Periodic screen learning
                if now - self._last_screen_learn_ts >= self._screen_learn_cooldown:
                    self._last_screen_learn_ts = now
                    self._passive_screen_learning()
                # Process learning queue
                self._process_queue()
                time.sleep(2)
            except Exception:
                time.sleep(5)

    def _autonomous_search_learning(self) -> None:
        """
        Search Google/web for topics Nova is curious about.
        Uses headless browser with dad's cookies/cache by default.
        """
        try:
            topics = self._get_curious_topics()
            if not topics:
                return
            topic = random.choice(topics)
            try:
                from neuro_child.world_tools import BrowserTools
                browser = BrowserTools(local=True)
                text = browser.search(topic)
            except Exception:
                text = ""
            if text:
                words_learned = self.vocab.encounter_text(text, source="web_search")
                if words_learned:
                    self.memory.add(
                        f"Learned from web search '{topic}': {', '.join(words_learned[:10])}",
                        kind="lesson",
                        importance=0.5,
                    )
                    self._log_autonomy(f"web_search:{topic}:{len(words_learned)}")
                self._train_smollm_on_text(text)
        except Exception:
            pass

    def _passive_screen_learning(self) -> None:
        """
        Learn from current screen content passively.
        Also detects YouTube URLs and learns from them.
        """
        try:
            import mss
            import pyautogui
            from PIL import Image
            with mss.mss() as s:
                mon = s.monitors[0]
                shot = s.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.rgb)
                try:
                    text = ""
                    try:
                        import pytesseract
                        text = pytesseract.image_to_string(img)
                    except Exception:
                        text = ""
                    if text and text.strip():
                        words = self.vocab.encounter_text(text, source="screen")
                        if words:
                            self._log_autonomy(f"screen:{len(words)}")
                        self._train_smollm_on_text(text)
                        # Detect YouTube URLs and learn from them
                        urls = re.findall(r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+|https?://youtu\.be/[\w-]+)', text)
                        for url in urls:
                            if url not in self._learned_urls:
                                self._learned_urls.add(url)
                                try:
                                    from neuro_child.media_learning import MediaLearningEngine
                                    from neuro_child.knowledge_llm import NovaKnowledgeLLM
                                    engine = MediaLearningEngine(NovaKnowledgeLLM(), self.vocab)
                                    result = engine.learn_from_youtube(url)
                                    if result.success:
                                        self._log_autonomy(f"youtube:{url}:{len(result.words_learned)}")
                                except Exception:
                                    pass
                except Exception:
                    pass
        except Exception:
            pass

    def _get_curious_topics(self) -> List[str]:
        """
        Generate learning topics from curiosity drives + recent activity.
        """
        topics: List[str] = []
        try:
            # From recent screen content
            from neuro_child.environmental_learning import ScreenContentAnalyzer
            analyzer = ScreenContentAnalyzer()
            recent = analyzer.get_recent_content(limit=5)
            for item in recent:
                ct = item.get("content_type", "")
                if ct and ct != "unknown":
                    topics.append(f"what is {ct}")
                    topics.append(f"how to use {ct}")
        except Exception:
            pass
        # Generic curiosity topics
        generic = [
            "how computers work",
            "what is artificial intelligence",
            "how games are made",
            "what is the internet",
            "how do screens work",
            "what is programming",
            "how do robots work",
            "what is science",
            "how do cars work",
            "what is music",
            "how do phones work",
            "what is space",
        ]
        topics.extend(generic)
        return topics[:20]

    def _fetch_url_text(self, url: str, max_chars: int = 5000) -> str:
        """
        Fetch and extract readable text from a URL.
        """
        try:
            import urllib.request
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                data = resp.read(max_chars * 4)
            text = data.decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
        except Exception:
            return ""

    def add_learning_task(self, topic: str, priority: float = 0.5) -> None:
        task = LearningTask(topic=topic, priority=priority)
        self._queue.append(task)
        self._save_queue()

    def _process_queue(self) -> None:
        pending = [t for t in self._queue if t.status == "pending"]
        if not pending:
            return
        task = max(pending, key=lambda t: t.priority)
        try:
            text = self._fetch_url_text(f"https://duckduckgo.com/html/?q={urllib.parse.quote_plus(task.topic)}")
            if text:
                words = self.vocab.encounter_text(text, source="queue")
                task.status = "completed"
                task.completed_at = time.time()
                task.result = f"learned {len(words)} words"
                self._log_autonomy(f"queue:{task.topic}:{len(words)}")
        except Exception:
            task.status = "failed"
        self._save_queue()

    def _log_autonomy(self, event: str) -> None:
        try:
            log = []
            if AUTONOMY_LOG.exists():
                log = json.loads(AUTONOMY_LOG.read_text(encoding="utf-8") or "[]")
            log.append({"ts": time.time(), "event": event})
            log = log[-200:]
            AUTONOMY_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _train_smollm_on_text(self, text: str) -> None:
        if not text or not text.strip():
            return
        try:
            if self.smollm and hasattr(self.smollm, "train_on_text"):
                self.smollm.train_on_text(text.strip())
        except Exception:
            pass

    def get_stats(self) -> Dict[str, Any]:
        pending = len([t for t in self._queue if t.status == "pending"])
        completed = len([t for t in self._queue if t.status == "completed"])
        return {
            "queue_pending": pending,
            "queue_completed": completed,
            "total_tasks": len(self._queue),
            "vocab_known": len(self.vocab.get_known_words()),
            "vocab_seen": len(self.vocab.words),
        }
