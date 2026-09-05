"""
Dual-LLM architecture for Nova:

1. EnglishLLM - pure language model, trained from zero to speak English
2. NovaKnowledgeLLM - Nova's own model that she trains herself with memories, observations, learnings

These are two separate brand-new LLMs built from scratch.
No third-party models. No wrappers around other LLMs.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neuro_child.language_center import LanguageCenter

MODEL_DIR = Path(__file__).resolve().parent / "memory"
ENGLISH_MODEL_PATH = MODEL_DIR / "english_llm_v2.json"
NOVA_MODEL_PATH = MODEL_DIR / "nova_knowledge_llm.json"
VOCAB_PATH = MODEL_DIR / "english_vocab.json"


class NovaKnowledgeLLM:
    """
    Nova's personal knowledge model.
    
    Stores everything Nova has learned:
    - Memories of conversations with dad
    - Observations from screen/audio
    - Facts learned from web searches
    - Skills and knowledge from YouTube/books
    - Personal preferences and values
    
    This is separate from the English LLM.
    English LLM = how to speak
    Nova Knowledge LLM = what she knows
    """

    def __init__(self, force_new: bool = False) -> None:
        self._lock = threading.Lock()
        self._knowledge_base: Dict[str, Any] = {
            "memories": [],
            "observations": [],
            "facts": [],
            "skills": [],
            "preferences": {},
            "values": [],
            "conversations": [],
            "lessons_learned": [],
        }
        self._embedding_cache: Dict[str, List[float]] = {}
        self._training_steps = 0
        if not force_new:
            self._load()

    def add_memory(self, memory: Dict[str, Any]) -> None:
        """Add a memory from conversation or observation."""
        with self._lock:
            memory["timestamp"] = time.time()
            memory["id"] = f"mem_{self._training_steps}"
            self._knowledge_base["memories"].append(memory)
            self._training_steps += 1
            if len(self._knowledge_base["memories"]) > 10000:
                self._knowledge_base["memories"] = self._knowledge_base["memories"][-10000:]
            self._save()

    def add_observation(self, observation: Dict[str, Any]) -> None:
        """Add an observation from screen/audio/web."""
        with self._lock:
            observation["timestamp"] = time.time()
            self._knowledge_base["observations"].append(observation)
            if len(self._knowledge_base["observations"]) > 5000:
                self._knowledge_base["observations"] = self._knowledge_base["observations"][-5000:]
            self._save()

    def add_fact(self, fact: str, source: str = "unknown") -> None:
        """Add a learned fact."""
        with self._lock:
            self._knowledge_base["facts"].append({
                "text": fact,
                "source": source,
                "timestamp": time.time(),
                "confidence": 1.0,
            })
            if len(self._knowledge_base["facts"]) > 5000:
                self._knowledge_base["facts"] = self._knowledge_base["facts"][-5000:]
            self._save()

    def add_skill(self, skill_name: str, skill_data: Dict[str, Any]) -> None:
        """Add a learned skill."""
        with self._lock:
            self._knowledge_base["skills"].append({
                "name": skill_name,
                "data": skill_data,
                "timestamp": time.time(),
                "mastery": 0.1,
            })
            self._save()

    def add_preference(self, key: str, value: Any) -> None:
        """Store a preference."""
        with self._lock:
            self._knowledge_base["preferences"][key] = {
                "value": value,
                "timestamp": time.time(),
            }
            self._save()

    def add_value(self, value: str) -> None:
        """Store a value/belief."""
        with self._lock:
            if value not in self._knowledge_base["values"]:
                self._knowledge_base["values"].append(value)
                self._save()

    def add_lesson(self, lesson: str) -> None:
        """Store a lesson learned."""
        with self._lock:
            self._knowledge_base["lessons_learned"].append({
                "text": lesson,
                "timestamp": time.time(),
            })
            self._save()

    def get_context_for_query(self, query: str, max_items: int = 10) -> str:
        """Get relevant knowledge context for a query."""
        with self._lock:
            # Simple keyword matching for now
            query_words = set(query.lower().split())
            relevant = []
            
            # Search memories
            for mem in self._knowledge_base["memories"][-100:]:
                text = str(mem.get("text", ""))
                if any(w in text.lower() for w in query_words):
                    relevant.append(f"[Memory] {text[:200]}")
            
            # Search facts
            for fact in self._knowledge_base["facts"][-50:]:
                text = fact.get("text", "")
                if any(w in text.lower() for w in query_words):
                    relevant.append(f"[Fact] {text[:200]}")
            
            # Search lessons
            for lesson in self._knowledge_base["lessons_learned"][-50:]:
                text = lesson.get("text", "")
                if any(w in text.lower() for w in query_words):
                    relevant.append(f"[Lesson] {text[:200]}")
            
            relevant = relevant[-max_items:]
            return "\n".join(reversed(relevant))

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_memories": len(self._knowledge_base["memories"]),
                "total_observations": len(self._knowledge_base["observations"]),
                "total_facts": len(self._knowledge_base["facts"]),
                "total_skills": len(self._knowledge_base["skills"]),
                "total_preferences": len(self._knowledge_base["preferences"]),
                "total_values": len(self._knowledge_base["values"]),
                "total_lessons": len(self._knowledge_base["lessons_learned"]),
                "training_steps": self._training_steps,
            }

    def _save(self) -> None:
        try:
            NOVA_MODEL_PATH.write_text(
                json.dumps(self._knowledge_base, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load(self) -> None:
        try:
            if NOVA_MODEL_PATH.exists():
                self._knowledge_base = json.loads(NOVA_MODEL_PATH.read_text(encoding="utf-8"))
                self._training_steps = len(self._knowledge_base.get("memories", []))
        except Exception:
            pass


class DualLLMBrain:
    """
    Dual-LLM system:
    - LanguageCenter: knows how to speak English, trains continually
    - NovaKnowledgeLLM: knows what Nova has learned
    """

    def __init__(self) -> None:
        # Language model - knows how to speak
        self.language_center = LanguageCenter()
        
        # Nova's knowledge - what she knows
        self.knowledge_llm = NovaKnowledgeLLM()
        
        # Training state
        self._training = False
        self._training_thread: Optional[threading.Thread] = None
        self._last_training = 0.0
        self._training_interval = 300  # train every 5 minutes

    def respond(self, user_text: str, context: Optional[str] = None) -> str:
        knowledge_context = self.knowledge_llm.get_context_for_query(user_text)
        if knowledge_context:
            prompt = f"{knowledge_context}\nDad: {user_text}\nNova:"
        else:
            prompt = f"Dad: {user_text}\nNova:"
        
        response = self.language_center.speak(prompt, max_new_tokens=60, temperature=0.8)
        
        response = response.split('\n')[0].strip()
        if not response:
            response = "I'm learning! Tell me more dad."
        
        return response

    def learn_from_text(self, text: str, source: str = "unknown") -> None:
        self.language_center.learn(text)
        self.knowledge_llm.add_observation({"text": text, "source": source})

    def learn_from_conversation(self, user_text: str, nova_response: str) -> None:
        self.knowledge_llm.add_memory({"type": "conversation", "user_text": user_text, "nova_response": nova_response})
        self.language_center.learn(f"Dad: {user_text}")
        self.language_center.learn(f"Nova: {nova_response}")

    def add_knowledge(self, fact: str, source: str = "web") -> None:
        self.knowledge_llm.add_fact(fact, source)
        self.language_center.learn(fact)

    def start_training_loop(self) -> None:
        if self._training:
            return
        self._training = True
        self._training_thread = threading.Thread(target=self._training_loop, daemon=True)
        self._training_thread.start()

    def stop_training_loop(self) -> None:
        self._training = False

    def _training_loop(self) -> None:
        while self._training:
            try:
                now = time.time()
                if now - self._last_training > self._training_interval:
                    self._last_training = now
                    stats = self.knowledge_llm.get_stats()
                    if stats["total_memories"] > 0:
                        recent = self.knowledge_llm._knowledge_base["memories"][-10:]
                        for mem in recent:
                            text = mem.get("text", "")
                            if text:
                                self.language_center.learn(text)
                time.sleep(60)
            except Exception:
                pass

    def get_stats(self) -> Dict[str, Any]:
        return {
            "language_center": self.language_center.get_stats(),
            "knowledge_llm": self.knowledge_llm.get_stats(),
        }

    def save(self) -> None:
        try:
            self.language_center.save()
            self.knowledge_llm._save()
        except Exception:
            pass
