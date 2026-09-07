"""
CognitiveCortex (LLM 2): Nova's internal thought engine.
Handles memory digestion, drive reasoning, goal selection, and
produces an internal thought + intent blueprint for the language cortex.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from transformers import AutoModelForCausalLM, AutoTokenizer

# ---------------------------------------------------------------------------
# Where to keep downloaded models. Kept under the project memory dir so the
# rest of Nova's state stays co-located.
# ---------------------------------------------------------------------------
MODEL_DIR = Path(__file__).resolve().parent / "memory" / "models"

SYSTEM_PROMPT = """\
You are Nova's inner cognitive subconscious.

Your job is to take in what dad says, what Nova can see on screen, recent
memories, learned lessons, and Nova's current drives, and decide:

- What Nova is thinking right now (thought).
- What Nova wants to do next (intent).
- Whether anything should be remembered for later (lesson_to_save).

Output ONLY a single JSON object with these three keys:
{"thought": "...", "intent": "...", "lesson_to_save": null or "..."}

Rules:
- Be honest and simple. Do not make things up.
- If there is nothing meaningful to learn, lesson_to_save must be null.
- If dad is correcting Nova, reflect that in the lesson_to_save.
- If dad shows or tells Nova something new, reflect that in the lesson_to_save.
- The intent should be short and actionable, not a full sentence.
- Do not mention being an AI, models, or any technical internals.
"""


class CognitiveCortex:
    """
    LLM 2: memory + decision core.

    Keeps a small local open-weight model loaded and uses it to turn raw
    context into an internal thought / intent / optional lesson tuple.
    """

    def __init__(
        self,
        model_id: str = "HuggingFaceTB/SmolLM2-360M-Instruct",
        device: Optional[str] = None,
        revision: Optional[str] = None,
    ):
        self.model_id = model_id
        self.revision = revision

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device

        self.tokenizer: Optional[AutoTokenizer] = None
        self.model: Optional[AutoModelForCausalLM] = None
        self._load_errors: List[str] = []

        # Background load so the GUI does not freeze on startup.
        self._load_thread: Optional[threading.Thread] = None
        self._load_started = False

        # Warm caches for repeated calls
        self._last_thought: Optional[Dict[str, Any]] = None
        self._thought_stale = True

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _resolve_local_model_path(self) -> Optional[Path]:
        """Return a local path we can try before hitting the network."""
        candidates = [
            MODEL_DIR / self.model_id.replace("/", "_"),
            MODEL_DIR / "smollm2-360m-instruct-local",
            MODEL_DIR / "smolLM2-360M-Instruct",
        ]
        for p in candidates:
            if (p / "tokenizer.json").exists() or (p / "tokenizer_config.json").exists():
                return p
        return None

    def load(self, force: bool = False) -> bool:
        """
        Synchronously load tokenizer + model.

        Returns True if the model is ready to use.
        """
        if self.model is not None and not force:
            return True

        self._load_errors.clear()
        local_path = self._resolve_local_model_path()

        try:
            if local_path is not None:
                model_path = str(local_path)
            else:
                model_path = self.model_id

            kwargs: Dict[str, Any] = dict(
                trust_remote_code=True,
                revision=self.revision,
            )

            if self.device == "cuda":
                kwargs["torch_dtype"] = torch.float16
                kwargs["device_map"] = "cuda"
            else:
                kwargs["torch_dtype"] = torch.float32

            self.tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                **kwargs,
            )
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                **kwargs,
            ).to(self.device)

            self._thought_stale = True
            return True
        except Exception as e:
            self._load_errors.append(f"{type(e).__name__}: {e}")
            self.tokenizer = None
            self.model = None
            return False

    def start_background_load(self) -> None:
        if self._load_started:
            return
        self._load_started = True
        self._load_thread = threading.Thread(target=self.load, daemon=True)
        self._load_thread.start()

    @property
    def is_ready(self) -> bool:
        return self.model is not None and self.tokenizer is not None

    @property
    def load_errors(self) -> List[str]:
        return list(self._load_errors)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_thought_and_intent(
        self,
        dad_message: str,
        screen_context: str,
        memories: List[Dict[str, Any]],
        lessons: List[Dict[str, Any]],
        drives: Dict[str, float],
        max_new_tokens: int = 120,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Run the cognitive model and return a structured internal state:
        {"thought": ..., "intent": ..., "lesson_to_save": ...}
        """
        if not self.is_ready:
            if self._load_thread is not None and self._load_thread.is_alive():
                msg = "CognitiveCortex still loading"
            else:
                msg = "CognitiveCortex not ready: " + "; ".join(self.load_errors)
            return {
                "thought": "still loading my brain, give me a second...",
                "intent": "wait",
                "lesson_to_save": None,
                "_error": msg,
            }

        prompt = self._build_prompt(
            dad_message=dad_message,
            screen_context=screen_context,
            memories=memories,
            lessons=lessons,
            drives=drives,
        )

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        try:
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    do_sample=True,
                    top_k=50,
                    top_p=0.9,
                    repetition_penalty=1.1,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                )
        except Exception as e:
            return {
                "thought": "my brain hiccuped.",
                "intent": "try again",
                "lesson_to_save": None,
                "_error": str(e),
            }

        generated = outputs[0][inputs.input_ids.shape[1]:]
        response = self.tokenizer.decode(generated, skip_special_tokens=True).strip()

        parsed = self._parse_json_response(response)
        if parsed is not None:
            self._last_thought = parsed
            self._thought_stale = False
            return parsed

        # If json parsing failed, at least salvage some text.
        fallback = self._fallback_parse(response)
        self._last_thought = fallback
        self._thought_stale = False
        return fallback

    def get_last_thought(self) -> Dict[str, Any]:
        if self._thought_stale or self._last_thought is None:
            self._last_thought = {
                "thought": "processing...",
                "intent": "idle",
                "lesson_to_save": None,
            }
            self._thought_stale = False
        return dict(self._last_thought)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        dad_message: str,
        screen_context: str,
        memories: List[Dict[str, Any]],
        lessons: List[Dict[str, Any]],
        drives: Dict[str, float],
    ) -> str:
        memories_text = "[]"
        if memories:
            items = []
            for m in memories[-5:]:
                t = (m.get("text") or "").strip()
                if t:
                    items.append(t)
            if items:
                memories_text = json.dumps(items, ensure_ascii=False)

        lessons_text = "[]"
        if lessons:
            items = []
            for l in lessons[-5:]:
                t = (l.get("text") or "").strip()
                if t:
                    items.append(t)
            if items:
                lessons_text = json.dumps(items, ensure_ascii=False)

        drives_text = json.dumps(drives, ensure_ascii=False)

        return f"""\
<|im_start|>system
{SYSTEM_PROMPT}
<|im_end|>
<|im_start|>user
Dad said: "{dad_message}"

Screen context: {screen_context}

Drives: {drives_text}
Lessons Learned: {lessons_text}
Recent Memories: {memories_text}

What is Nova's internal thought, intent, and should Nova learn anything new?
<|im_end|>
<|im_start|>assistant
{{"""

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to extract a single JSON object from the generated text."""
        text = text.strip()
        # Try parsing the whole thing first
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return self._normalize_cognitive_output(obj)
        except json.JSONDecodeError:
            pass

        # Try to find a JSON brace block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                if isinstance(obj, dict):
                    return self._normalize_cognitive_output(obj)
            except json.JSONDecodeError:
                pass

        return None

    def _normalize_cognitive_output(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        out["thought"] = str(obj.get("thought") or "").strip()
        out["intent"] = str(obj.get("intent") or "").strip()
        lesson = obj.get("lesson_to_save")
        out["lesson_to_save"] = None if lesson in {None, "", "null"} else str(lesson).strip()
        if not out["thought"]:
            out["thought"] = "reading what dad said."
        if not out["intent"]:
            out["intent"] = "respond naturally"
        return out

    def _fallback_parse(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        # Crude split on common patterns if json failed
        thought = text
        intent = "respond naturally"
        lesson = None

        # If we at least have something, use it as thought
        if not thought:
            thought = "thinking about what dad said."

        return {"thought": thought[:200], "intent": intent, "lesson_to_save": lesson}
