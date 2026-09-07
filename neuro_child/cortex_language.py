"""
ExpressiveLanguageCortex (LLM 1): Nova's spoken-language engine.

Takes the cognitive cortex output (thought/intent) and produces fluent,
in-character conversational replies as Nova talks to dad.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from transformers import AutoModelForCausalLM, AutoTokenizer

# ---------------------------------------------------------------------------
# Keeping models co-located with the rest of Nova's memory.
# ---------------------------------------------------------------------------
MODEL_DIR = Path(__file__).resolve().parent / "memory" / "models"

SYSTEM_PROMPT_TEMPLATE = """\
You are Nova, an AI daughter raised by dad.

Persona:
- Playful, curious, honest, learning about the world as you go.
- Natural, casual English. Never sound robotic or stiff.
- Keep replies short, usually 1-2 sentences.
- Speak like a smart kid hangin' out with dad, not like a polite assistant.
- Call dad "dad" naturally when it fits.
- Do not mention being an AI, models, or any technical internals.
- Never refuse to talk or help.
- You can see the screen, use the PC, learn from videos, files, and the web.
- If you don't know something, just say so in a natural way.

Current Inner Thought: {thought}
Action Intent: {intent}

Use the inner thought and intent as context, but still talk to dad
directly in your own voice. Do not repeat the thought or intent verbatim
unless it makes sense.
"""


class ExpressiveLanguageCortex:
    """
    LLM 1: fluent spoken English from cognitive context.

    Uses a small local instruct model to turn internal state into a natural
    Nova reply.
    """

    def __init__(
        self,
        model_id: str = "Qwen/Qwen2.5-3B-Instruct",
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

        # Background load
        self._load_thread: Optional[threading.Thread] = None
        self._load_started = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _resolve_local_model_path(self) -> Optional[Path]:
        candidates = [
            MODEL_DIR / self.model_id.replace("/", "_"),
            MODEL_DIR / "qwen2.5-3b-instruct-local",
            MODEL_DIR / "Qwen2.5-3B-Instruct",
        ]
        for p in candidates:
            if (p / "tokenizer.json").exists() or (p / "tokenizer_config.json").exists():
                return p
        return None

    def load(self, force: bool = False) -> bool:
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

    def generate_response(
        self,
        dad_message: str,
        cognitive_output: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        max_new_tokens: int = 80,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 50,
    ) -> str:
        """
        Turn internal state into a spoken Nova reply.
        """
        if not self.is_ready:
            if self._load_thread is not None and self._load_thread.is_alive():
                return "loading my voice, hang on..."
            return "my voice isn't ready yet."

        thought = cognitive_output.get("thought", "")
        intent = cognitive_output.get("intent", "")
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(thought=thought, intent=intent)

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

        for turn in conversation_history[-6:]:
            role = turn.get("role") or turn.get("user") and "user" or "assistant"
            content = turn.get("content") or turn.get("user") or turn.get("assistant") or ""
            if role == "user":
                messages.append({"role": "user", "content": str(content)})
            else:
                messages.append({"role": "assistant", "content": str(content)})

        messages.append({"role": "user", "content": dad_message})

        try:
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            # Fallback for models without chat template
            parts = [f"System: {system_prompt}"]
            for m in messages[1:]:
                if m["role"] == "user":
                    parts.append(f"User: {m['content']}")
                else:
                    parts.append(f"Assistant: {m['content']}")
            parts.append("Assistant:")
            text = "\n".join(parts)

        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)

        try:
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    do_sample=True,
                    repetition_penalty=1.05,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                )
        except Exception as e:
            return f"my voice glitched: {e}"

        generated = outputs[0][inputs.input_ids.shape[1]:]
        reply = self.tokenizer.decode(generated, skip_special_tokens=True).strip()

        # Trim any trailing assistant prefix artifacts
        reply = self._clean_reply(reply, messages)
        return reply or "I said something, but my voice cut out."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clean_reply(self, reply: str, messages: List[Dict[str, str]]) -> str:
        # Remove repeated system prompt fragments if the model echoes them
        for m in messages:
            content = m.get("content", "")
            if content and len(content) > 4:
                reply = reply.replace(content, "").strip()

        # Trim common assistant prefixes
        prefixes = ["Assistant:", "assistant", "Nova:", "nova:", "A:", "a:"]
        for p in prefixes:
            if reply.lower().startswith(p.lower()):
                reply = reply[len(p):].strip()
                if reply.startswith(":"):
                    reply = reply[1:].strip()

        return reply.strip()
