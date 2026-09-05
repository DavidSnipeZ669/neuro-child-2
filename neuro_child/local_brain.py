"""
100% Local Brain - Runs completely on-device without any APIs.
Supports local GGUF models via llama-cpp-python or fast local fallback.
"""
from __future__ import annotations

import os
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"


class LocalBrain:
    def __init__(self, model_filename: Optional[str] = None):
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self.llm = None
        self.model_path = None

        # Automatically look for any .gguf model in ./models/
        if model_filename:
            self.model_path = MODELS_DIR / model_filename
        else:
            gguf_files = list(MODELS_DIR.glob("*.gguf"))
            if gguf_files:
                self.model_path = gguf_files[0]

        if self.model_path and self.model_path.exists() and Llama is not None:
            try:
                print(f"[Brain] Loading local model: {self.model_path.name}...")
                self.llm = Llama(
                    model_path=str(self.model_path),
                    n_ctx=2048,
                    n_gpu_layers=-1,  # Offload all layers to GPU if available
                    verbose=False,
                )
                print("[Brain] Local neural model loaded successfully!")
            except Exception as e:
                print(f"[Brain] Could not load GGUF ({e}). Using native local engine.")
        else:
            print("[Brain] No GGUF model found in ./models/ - Running in lightweight native offline mode.")

    def generate(self, messages: List[Dict[str, str]], max_tokens: int = 80, temperature: float = 0.88) -> str:
        """Generates real-time conversational responses locally."""
        if self.llm is not None:
            try:
                res = self.llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=["Dad:", "\nUser:", "<|im_end|>", "</s>"]
                )
                return res["choices"][0]["message"]["content"].strip()
            except Exception as e:
                return f"(brain hiccup: {e})"

        # Fast native local conversational generator
        user_msg = messages[-1]["content"] if messages else ""
        return self._native_child_generation(user_msg)

    def _native_child_generation(self, prompt: str) -> str:
        """Deterministic, rich local generation fallback."""
        lower = prompt.lower()
        if "jump" in lower or "spike" in lower or "trap" in lower:
            return random.choice([
                "Got it dad! I'm watching out for the spikes this time!",
                "Okay okay, timing the jump now... watch me!",
                "Jump on 3! One... two... jump!",
            ])
        if "boss" in lower or "enemy" in lower or "attack" in lower:
            return random.choice([
                "Wait, look at his attack pattern! Should I dodge left or right?",
                "Dad watch out! He's winding up a big hit!",
                "I'm hitting him! Don't let him back me into the corner!",
            ])
        if any(w in lower for w in ["good job", "nice", "proud", "well done"]):
            return random.choice([
                "Hehe, see that?! I learned that from you, dad!",
                "Let's gooo! We make the best team ever!",
                "Did you see that move?! I'm getting so good at this!",
            ])
        return random.choice([
            "Look at what's happening right there on screen! What do we do next?",
            "Wait wait, explain that move to me again! How did you do that?",
            "I'm watching super closely, teach me the trick!",
            "Dad, look! That open path over there looks suspicious, should we check it?",
        ])