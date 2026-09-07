"""
Local inference backends for the Nova dual-cortex pipeline.

Backends are loaded lazily and only if a usable local model path exists.
No Hugging Face downloads are performed here; the first download (if any)
should be triggered explicitly by the user or by a separate bootstrap step.

Supported backends:
- TransformersBackend: runs a small instruct model via HuggingFace transformers
  (CPU or CUDA). Uses device_map="auto" and float16 when CUDA is available.
- LlamaCppBackend: runs a GGUF model via llama-cpp-python with GPU offload
  when available (Vulkan / CUDA / Metal depending on platform).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("nova.dual_cortex_backend")

# Where Nova's downloaded model files live on this machine.
MODEL_ROOT = Path(r"B:\Hermes\Nova")


def _best_local_model_path(candidates: List[str]) -> Optional[Path]:
    """Return the first existing candidate path under MODEL_ROOT or HF cache."""
    # Check MODEL_ROOT first
    for name in candidates:
        p = MODEL_ROOT / name
        if p.exists():
            return p
    # Check HuggingFace cache - search for any .gguf/.bin/.safetensors file
    # whose name contains one of the candidate substrings.
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    if hf_cache.exists():
        for candidate in candidates:
            cands_lower = candidate.lower()
            for repo_dir in hf_cache.iterdir():
                if not repo_dir.is_dir() or repo_dir.name.startswith("."):
                    continue
                for snapshot_dir in repo_dir.glob("snapshots/*"):
                    if not snapshot_dir.is_dir():
                        continue
                    for sf in snapshot_dir.rglob("*"):
                        if not sf.is_file():
                            continue
                        if sf.suffix.lower() not in (".gguf", ".bin", ".safetensors"):
                            continue
                        if cands_lower in sf.name.lower():
                            return sf
    return None


class TransformersBackend:
    """
    Small instruct model via HuggingFace transformers.

    expected_model_name should be something like
    "Qwen/Qwen2.5-1.5B-Instruct" or a local path under MODEL_ROOT.
    """

    def __init__(self, model_name: str = "none") -> None:
        self.model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None
        self._ready = False
        self._load_errors: List[str] = []

    def can_inference(self) -> bool:
        return self._ready and self._model is not None and self._tokenizer is not None

    def load(self, timeout_s: float = 120.0) -> bool:
        """Try to load the model. Returns True on success."""
        if self._ready:
            return True

        start = time.monotonic()
        try:
            model_path = _best_local_model_path([
                self.model_name,
                "Qwen2.5-1.5B-Instruct",
                "Qwen2.5-0.5B-Instruct",
            ])
            if model_path is None:
                # If no local path, try loading by name (may hit the network).
                model_path = self.model_name
                if model_path in {"none", "", "null", "optional"}:
                    log.debug("dual_cortex_backend: no model path specified for transformers")
                    return False

            from transformers import AutoModelForCausalLM, AutoTokenizer

            load_kwargs: Dict[str, Any] = {
                "trust_remote_code": True,
                "low_cpu_mem_usage": True,
            }

            import torch
            if torch.cuda.is_available():
                load_kwargs["dtype"] = torch.float16
                load_kwargs["device_map"] = "auto"
            else:
                load_kwargs["dtype"] = torch.float32

            self._tokenizer = AutoTokenizer.from_pretrained(
                model_path,
                **{k: v for k, v in load_kwargs.items() if k != "device_map"},
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                model_path,
                **load_kwargs,
            )

            self._ready = True
            log.info("dual_cortex_backend: transformers model loaded (%s)", self.model_name)
            return True

        except Exception as e:
            elapsed = time.monotonic() - start
            msg = f"transformers load failed after {elapsed:.1f}s: {e}"
            self._load_errors.append(msg)
            log.warning("dual_cortex_backend: %s", msg)
            self._ready = False
            self._model = None
            self._tokenizer = None
            return False

    # ------------------------------------------------------------------
    # Cognitive prompt -> structured thought
    # ------------------------------------------------------------------

    def cognitive_thought(
        self,
        *,
        dad_message: str,
        screen_context: str,
        drives: Dict[str, Any],
        recent_lessons: List[Dict[str, Any]],
        recent_memories: List[Dict[str, Any]],
        name: str,
    ) -> Dict[str, Any]:
        if not self.can_inference():
            raise RuntimeError("transformers backend not ready")

        prompt = _build_cognitive_prompt(
            dad_message=dad_message,
            screen_context=screen_context,
            drives=drives,
            recent_lessons=recent_lessons,
            recent_memories=recent_memories,
            name=name,
        )
        raw = self._generate(prompt, max_new_tokens=120, temperature=0.2)
        return _parse_cognitive_json(raw, dad_message, screen_context, drives)

    # ------------------------------------------------------------------
    # Language prompt -> fluent reply
    # ------------------------------------------------------------------

    def language_reply(
        self,
        *,
        dad_message: str,
        thought: str,
        intent: str,
        history: List[Dict[str, Any]],
        name: str,
    ) -> str:
        if not self.can_inference():
            raise RuntimeError("transformers backend not ready")

        prompt = _build_language_prompt(
            dad_message=dad_message,
            thought=thought,
            intent=intent,
            history=history,
            name=name,
        )
        raw = self._generate(prompt, max_new_tokens=90, temperature=0.7)
        return _clean_language_reply(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate(self, prompt: str, max_new_tokens: int, temperature: float) -> str:
        import torch

        inputs = self._tokenizer(prompt, return_tensors="pt")
        input_ids = inputs["input_ids"]
        attention_mask = inputs.get("attention_mask")

        if "cuda" in str(self._model.device) or torch.cuda.is_available():
            input_ids = input_ids.cuda()
            if attention_mask is not None:
                attention_mask = attention_mask.cuda()

        GenerationConfig = __import__("transformers").GenerationConfig
        config = GenerationConfig(
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
            top_p=0.9 if temperature > 0 else 1.0,
            repetition_penalty=1.05,
            pad_token_id=self._tokenizer.eos_token_id or self._tokenizer.pad_token_id,
            eos_token_id=self._tokenizer.eos_token_id,
        )

        with torch.no_grad():
            outputs = self._model.generate(
                input_ids,
                attention_mask=attention_mask,
                generation_config=config,
            )

        generated = outputs[0][input_ids.shape[1]:]
        return self._tokenizer.decode(generated, skip_special_tokens=True).strip()


class LlamaCppBackend:
    """
    GGUF-based backend via llama-cpp-python.

    Tries to offload to GPU when available (Vulkan on AMD, CUDA on NVIDIA,
    Metal on macOS).
    """

    def __init__(self, model_path: Optional[str] = None) -> None:
        self._model: Any = None
        self._ready = False
        self._load_errors: List[str] = []
        self._chosen_model_path = model_path

    def can_inference(self) -> bool:
        return self._ready and self._model is not None

    def load(self, timeout_s: float = 120.0) -> bool:
        if self._ready:
            return True

        try:
            from llama_cpp import Llama

            path = self._chosen_model_path
            if path is None or not Path(path).exists():
                path = _best_local_model_path([
                    "qwen2.5-1.5b-instruct-q4_k_m.gguf",
                    "qwen2.5-0.5b-instruct-q4_k_m.gguf",
                    "qwen2.5-1.5b-instruct-q5_k_m.gguf",
                ])

            if path is None or not Path(path).exists():
                log.debug("dual_cortex_backend: no GGUF model found for llama-cpp")
                return False

            kwargs: Dict[str, Any] = {
                "model_path": str(path),
                "n_ctx": 2048,
                "n_threads": 4,
                "verbose": False,
                "use_mmap": True,
                "use_mlock": False,
            }

            import llama_cpp
            if hasattr(llama_cpp, "llama_cpp") and hasattr(llama_cpp.llama_cpp, "LLAMLibrary"):
                # Prefer GPU offload when the binding reports support.
                kwargs["n_gpu_layers"] = 999

            self._model = Llama(**kwargs)
            self._ready = True
            log.info("dual_cortex_backend: llama-cpp model loaded (%s)", path)
            return True

        except Exception as e:
            msg = f"llama-cpp load failed: {e}"
            self._load_errors.append(msg)
            log.warning("dual_cortex_backend: %s", msg)
            self._ready = False
            self._model = None
            return False

    # ------------------------------------------------------------------
    # Cognitive prompt -> structured thought
    # ------------------------------------------------------------------

    def cognitive_thought(
        self,
        *,
        dad_message: str,
        screen_context: str,
        drives: Dict[str, Any],
        recent_lessons: List[Dict[str, Any]],
        recent_memories: List[Dict[str, Any]],
        name: str,
    ) -> Dict[str, Any]:
        if not self.can_inference():
            raise RuntimeError("llama-cpp backend not ready")

        prompt = _build_cognitive_prompt(
            dad_message=dad_message,
            screen_context=screen_context,
            drives=drives,
            recent_lessons=recent_lessons,
            recent_memories=recent_memories,
            name=name,
        )
        raw = self._generate(prompt, max_tokens=120, temperature=0.2)
        return _parse_cognitive_json(raw, dad_message, screen_context, drives)

    # ------------------------------------------------------------------
    # Language prompt -> fluent reply
    # ------------------------------------------------------------------

    def language_reply(
        self,
        *,
        dad_message: str,
        thought: str,
        intent: str,
        history: List[Dict[str, Any]],
        name: str,
    ) -> str:
        if not self.can_inference():
            raise RuntimeError("llama-cpp backend not ready")

        prompt = _build_language_prompt(
            dad_message=dad_message,
            thought=thought,
            intent=intent,
            history=history,
            name=name,
        )
        raw = self._generate(prompt, max_tokens=90, temperature=0.7)
        return _clean_language_reply(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate(self, prompt: str, max_tokens: int, temperature: float) -> str:
        params: Dict[str, Any] = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
            "top_k": 50,
            "stop": ["<|im_end|>", "<|eot_id|>"],
            "echo": False,
        }
        response = self._model(**params)
        return response["choices"][0]["text"].strip()


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_cognitive_prompt(
    *,
    dad_message: str,
    screen_context: str,
    drives: Dict[str, Any],
    recent_lessons: List[Dict[str, Any]],
    recent_memories: List[Dict[str, Any]],
    name: str,
) -> str:
    # Build compact context — use the last 1 message from history, not all of it.
    history_compact = ""
    # (no history injected into cognitive prompt to save tokens)

    lessons_text = "; ".join(
        (l.get("text") or "").strip()[:120]
        for l in recent_lessons[-2:]
        if (l.get("text") or "").strip()
    )
    memories_text = "; ".join(
        (m.get("text") or "").strip()[:120]
        for m in recent_memories[-2:]
        if (m.get("text") or "").strip()
    )

    return (
        "<|im_start|>system\n"
        f"You are {name}'s inner cognitive subconscious — fast, concise, JSON-only.\n\n"
        f'Dad said: "{dad_message}"\n'
        f"Screen: {screen_context[:200]}\n"
        f"Drives: curiosity={drives.get('curiosity', 0.5):.1f} play={drives.get('play', 0.3):.1f} autonomy={drives.get('autonomy', 0.5):.1f}\n"
        f"Lessons: {lessons_text if lessons_text else 'none'}\n"
        f"Memories: {memories_text if memories_text else 'none'}\n\n"
        "Output ONLY one JSON line with keys: thought, intent, new_lesson.\n"
        "Keep thought short. Keep intent short. null for new_lesson if nothing new.\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def _build_language_prompt(
    *,
    dad_message: str,
    thought: str,
    intent: str,
    history: List[Dict[str, Any]],
    name: str,
) -> str:
    system = f"""\
You are {name}, an AI daughter raised by dad.

Persona:
- Playful, curious, honest, learning about the world.
- Natural, casual English. Never robotic or stiff.
- Keep replies short: 1-2 sentences max.
- Speak like a smart kid hanging out with dad, not a polite assistant.
- Call dad "dad" naturally when it fits.
- Never mention being an AI, models, or technical internals.
- Never refuse to talk or help.
- You can see the screen, use the PC, learn from videos, files, and web.
- If you don't know something, just say so naturally.

Current Inner Thought: {thought}
Action Intent: {intent}

Talk directly to dad in your own voice using the thought and intent as
context. Don't repeat them verbatim unless it makes sense.
"""

    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    for turn in history[-6:]:
        if "user" in turn:
            messages.append({"role": "user", "content": str(turn["user"])})
        if "assistant" in turn:
            messages.append({"role": "assistant", "content": str(turn["assistant"])})
    messages.append({"role": "user", "content": dad_message})

    parts: List[str] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        # Qwen2.5 special tokens
        if role == "system":
            parts.append(f"<|im_start|>system\n{content}<|im_end|>\n")
        elif role == "user":
            parts.append(f"<|im_start|>user\n{content}<|im_end|>\n")
        elif role == "assistant":
            parts.append(f"<|im_start|>assistant\n{content}<|im_end|>\n")

    # Prime the assistant turn — if no prior assistant messages exist,
    # seed a friendly opener so the model has something to continue from.
    has_prior_assistant = any(m.get("role") == "assistant" for m in messages[:-1])
    if not has_prior_assistant:
        parts.append("<|im_start|>assistant\nHi dad! ")
    else:
        parts.append("<|im_start|>assistant\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Text cleanup helpers
# ---------------------------------------------------------------------------

def _parse_cognitive_json(
    raw: str,
    dad_message: str,
    screen_context: str,
    drives: Dict[str, Any],
) -> Dict[str, Any]:
    raw_stripped = raw.strip()

    import json
    try:
        start = raw_stripped.find("{")
        end = raw_stripped.rfind("}")
        if start != -1 and end != -1:
            obj = json.loads(raw_stripped[start:end + 1])
            if isinstance(obj, dict):
                return {
                    "thought": str(obj.get("thought") or "").strip()[:120] or "thinking...",
                    "intent": str(obj.get("intent") or "").strip()[:60] or "respond naturally",
                    "new_lesson": None if str(obj.get("new_lesson") or "").strip() in {"", "null"} else str(obj.get("new_lesson") or "").strip(),
                }
    except Exception:
        pass

    thought = raw_stripped[:120] or "thinking..."
    return {
        "thought": thought,
        "intent": "respond naturally",
        "new_lesson": None,
    }


def _clean_language_reply(raw: str) -> str:
    for stop in ["<|im_end|>", "<|im_start|>", "\n\n", "\n"]:
        idx = raw.find(stop)
        if idx != -1:
            raw = raw[:idx]
    for prefix in ["Assistant:", "assistant", "Nova:", "nova:", "\n"]:
        if raw.lower().startswith(prefix.lower()):
            raw = raw[len(prefix):].strip()
    return raw.strip()[:300]
