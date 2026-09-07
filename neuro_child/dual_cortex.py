"""
Dual-cortex reply pipeline for Nova.

Architecture:
- LLM 2 (CognitiveCortex): internal thought, intent, optional lesson_to_save
- LLM 1 (ExpressiveLanguageCortex): fluent spoken reply to dad

This is a local-first implementation. If a real local backend is available
(transformers with a small instruct model, or llama-cpp), use it. Otherwise
use a structured simulated pipeline so the architecture still behaves
correctly and the rest of Nova can depend on the interface.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from neuro_child.personality import Personality
from neuro_child.memory import Memory

log = logging.getLogger("nova.dual_cortex")


@dataclass
class CognitiveState:
    thought: str = ""
    intent: str = ""
    lesson_to_save: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplyBundle:
    reply: str
    cognitive: CognitiveState
    used_real_model: bool = False


class CognitiveCortex:
    """LLM 2: internal thought + intent + optional lesson."""

    def __init__(self, personality: Personality, memory: Memory) -> None:
        self.personality = personality
        self.memory = memory
        self._backend: Optional[Any] = None
        self._ready = False

    def initialize(self) -> None:
        try:
            self._backend = _try_load_backend()
            if self._backend is not None:
                self._ready = True
                log.info("dual_cortex: cognitive backend loaded")
            else:
                log.info("dual_cortex: using simulated cognitive path")
                self._ready = True  # still "ready" in the simulated sense
        except Exception as e:
            log.warning("dual_cortex: cognitive init failed (%s)", e)
            self._ready = True  # fallback to simulation

    def is_ready(self) -> bool:
        return self._ready

    def think(
        self,
        dad_message: str,
        screen_context: str,
        drives: Dict[str, Any],
        recent_lessons: List[Dict[str, Any]],
        recent_memories: List[Dict[str, Any]],
    ) -> CognitiveState:
        if self._backend is not None and getattr(self._backend, "can_inference", lambda: False)():
            try:
                raw = self._backend.cognitive_thought(
                    dad_message=dad_message,
                    screen_context=screen_context,
                    drives=drives,
                    recent_lessons=recent_lessons,
                    recent_memories=recent_memories,
                    name=self.personality.name,
                )
                # Backend returns a dict; wrap it in a CognitiveState
                if isinstance(raw, dict):
                    return CognitiveState(
                        thought=str(raw.get("thought", "")).strip() or "thinking...",
                        intent=str(raw.get("intent", "")).strip() or "respond naturally",
                        lesson_to_save=raw.get("new_lesson"),
                        raw=raw,
                    )
                return raw
            except Exception as e:
                log.warning("dual_cortex: cognitive inference failed (%s)", e)

        return _simulated_cognitive_state(
            dad_message=dad_message,
            screen_context=screen_context,
            drives=drives,
            recent_lessons=recent_lessons,
            recent_memories=recent_memories,
            name=self.personality.name,
        )


class ExpressiveLanguageCortex:
    """LLM 1: fluent reply from cognitive state + history."""

    def __init__(self, personality: Personality, memory: Memory) -> None:
        self.personality = personality
        self.memory = memory
        self._backend: Optional[Any] = None
        self._ready = False

    def initialize(self) -> None:
        try:
            self._backend = _try_load_backend()
            if self._backend is not None:
                self._ready = True
                log.info("dual_cortex: language backend loaded")
            else:
                log.info("dual_cortex: using simulated language path")
                self._ready = True
        except Exception as e:
            log.warning("dual_cortex: language init failed (%s)", e)
            self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    def speak(
        self,
        dad_message: str,
        cognitive: CognitiveState,
        history: List[Dict[str, Any]],
    ) -> str:
        if self._backend is not None and getattr(self._backend, "can_inference", lambda: False)():
            try:
                return self._backend.language_reply(
                    dad_message=dad_message,
                    thought=cognitive.thought,
                    intent=cognitive.intent,
                    history=history,
                    name=self.personality.name,
                )
            except Exception as e:
                log.warning("dual_cortex: language inference failed (%s)", e)
                import traceback
                log.debug("dual_cortex: language traceback:\n%s", traceback.format_exc())

        return _simulated_language_reply(
            dad_message=dad_message,
            cognitive=cognitive,
            history=history,
            name=self.personality.name,
        )


class NovaDualCortex:
    """Main dual-cortex interface used by Brain.respond()."""

    def __init__(self, personality: Personality, memory: Memory) -> None:
        self.cognitive = CognitiveCortex(personality, memory)
        self.language = ExpressiveLanguageCortex(personality, memory)
        self.memory = memory

    def initialize(self) -> None:
        self.cognitive.initialize()
        self.language.initialize()

    def is_ready(self) -> bool:
        return self.cognitive.is_ready() and self.language.is_ready()

    def respond(
        self,
        dad_message: str,
        screen_context: str,
        drives: Dict[str, Any],
        history: List[Dict[str, Any]],
    ) -> ReplyBundle:
        recent = self.memory.recall(dad_message, k=5)
        lessons = [r for r in recent if r.get("kind") in ("lesson", "correction", "fact")]
        memories = [r for r in recent if r.get("kind") not in ("lesson", "correction", "fact")]

        cognitive = self.cognitive.think(
            dad_message=dad_message,
            screen_context=screen_context,
            drives=drives,
            recent_lessons=lessons,
            recent_memories=memories,
        )

        reply = self.language.speak(
            dad_message=dad_message,
            cognitive=cognitive,
            history=history,
        )

        used_real = (
            self.cognitive._backend is not None
            and getattr(self.cognitive._backend, "can_inference", lambda: False)()
            and self.language._backend is not None
            and getattr(self.language._backend, "can_inference", lambda: False)()
        )

        return ReplyBundle(reply=reply, cognitive=cognitive, used_real_model=used_real)


# ---------------------------------------------------------------------------
# Local backend loader
# ---------------------------------------------------------------------------

def _try_load_backend() -> Optional[Any]:
    """Try to load a real local inference backend."""
    # Try llama-cpp first (GGUF models), then transformers
    try:
        from neuro_child.dual_cortex_backend import LlamaCppBackend
        backend = LlamaCppBackend()
        backend.load(timeout_s=90.0)
        if backend.can_inference():
            log.info("dual_cortex: llama-cpp backend loaded")
            return backend
        else:
            log.debug("dual_cortex: llama-cpp backend not available (%s)", backend._load_errors)
    except Exception as e:
        log.debug("dual_cortex: llama-cpp backend skipped (%s)", e)

    try:
        from neuro_child.dual_cortex_backend import TransformersBackend
        path = Path(__file__).resolve().parent / "memory" / "local_model.txt"
        model_name = "none"
        if path.exists():
            model_name = path.read_text(encoding="utf-8").strip() or "none"
        backend = TransformersBackend(model_name=model_name)
        backend.load(timeout_s=90.0)
        if backend.can_inference():
            log.info("dual_cortex: transformers backend loaded")
            return backend
        else:
            log.debug("dual_cortex: transformers backend not available (%s)", backend._load_errors)
    except Exception as e:
        log.debug("dual_cortex: transformers backend skipped (%s)", e)

    return None


# ---------------------------------------------------------------------------
# Simulated fallback pipelines
# ---------------------------------------------------------------------------

def _simulated_cognitive_state(
    *,
    dad_message: str,
    screen_context: str,
    drives: Dict[str, Any],
    recent_lessons: List[Dict[str, Any]],
    recent_memories: List[Dict[str, Any]],
    name: str,
) -> CognitiveState:
    lower = dad_message.lower()

    if any(m in lower for m in ("correct", "no, ", "actually ", "you mean", "don't say")):
        thought = "dad is correcting me."
        intent = "learn the right answer"
        lesson = dad_message if len(dad_message) < 240 else dad_message[:240]
    elif any(m in lower for m in ("remember ", "this is ", "that's true")):
        thought = "dad is telling me something important."
        intent = "store this"
        lesson = dad_message if len(dad_message) < 240 else dad_message[:240]
    elif "screen" in lower or "see" in lower:
        thought = f"I'm looking at what dad sees on screen. {screen_context[:160]}"
        intent = "describe the screen"
        lesson = None
    else:
        curiosity = float(drives.get("curiosity", 0.5))
        if curiosity > 0.6:
            thought = "dad said something interesting. I want to know more."
            intent = "ask a follow-up"
        else:
            thought = "dad is talking to me. I'm listening."
            intent = "respond naturally"
        lesson = None

    return CognitiveState(
        thought=thought,
        intent=intent,
        lesson_to_save=lesson,
        raw={
            "type": "simulated_cognitive",
            "screen_context": screen_context[:120],
            "curiosity": drives.get("curiosity", 0.5),
        },
    )


def _simulated_language_reply(
    *,
    dad_message: str,
    cognitive: CognitiveState,
    history: List[Dict[str, Any]],
    name: str,
) -> str:
    lower = dad_message.lower()

    if "how are you" in lower:
        return random.choice([
            f"i'm good, dad. just thinking about {cognitive.thought.lower()}.",
            f"doing alright. what about you?",
            f"pretty good. what's new?",
        ])

    if any(m in lower for m in ("what do you see", "look", "on screen")):
        return random.choice([
            "i can see your screen. what are you working on?",
            "looking now. what's on your mind?",
            "yep, I see it. tell me more.",
        ])

    if cognitive.intent == "ask a follow-up":
        return random.choice([
            "wait, tell me more about that.",
            "how did that happen?",
            "what did you mean by that?",
            "interesting. what else?",
        ])

    if cognitive.intent == "store this":
        return random.choice([
            "got it. I'll remember that.",
            "stored. thanks dad.",
            "okay, I'll keep that.",
        ])

    if cognitive.intent == "learn the right answer":
        return random.choice([
            "oh, I misunderstood. thanks for correcting me.",
            "right, I'll remember that.",
            "got it. good catch.",
        ])

    if cognitive.thought:
        return f"okay, {cognitive.thought.lower()}. {random.choice(['go on', 'nice', 'tell me more', 'got it'])}"

    return random.choice([
        "cool. what else?",
        "got it. anything else on your mind?",
        "yeah, I'm listening.",
    ])
