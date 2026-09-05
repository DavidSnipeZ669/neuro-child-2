"""
Language Center - a minimal, from-scratch, NumPy-only character-level
language model meant to serve as the "language module" of a larger AI.

Design goals:
- Extremely lightweight (few hundred KB of parameters, no external ML deps)
- Trains and speaks English only; no reasoning, no bootstrap corpus required
- Learns continually from whatever text the parent AI feeds it via `.learn()`
- Stable online/continual learning via true BPTT + Adam + grad clipping
  + a small experience-replay buffer (to reduce catastrophic forgetting
  when training one short example at a time, forever)
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Optional

import numpy as np

MODEL_DIR = Path(__file__).resolve().parent / "memory"
MODEL_PATH = MODEL_DIR / "language_center_v1.json"


class LanguageCenterConfig:
    def __init__(
        self,
        vocab_size: int = 128,
        d_model: int = 64,
        hidden_size: int = 128,
        learning_rate: float = 3e-3,
        max_seq_len: int = 200,
        grad_clip: float = 5.0,
        replay_buffer_cap: int = 5000,
        replay_every: int = 4,
        replay_batch: int = 4,
        seed: int = 42,
    ):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.hidden_size = hidden_size
        self.learning_rate = learning_rate
        self.max_seq_len = max_seq_len
        self.grad_clip = grad_clip
        self.replay_buffer_cap = replay_buffer_cap
        self.replay_every = replay_every
        self.replay_batch = replay_batch
        self.seed = seed


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - np.max(x)
    e = np.exp(x)
    return e / (np.sum(e) + 1e-9)


class _AdamParam:
    __slots__ = ("value", "m", "v")

    def __init__(self, value: np.ndarray):
        self.value = value
        self.m = np.zeros_like(value)
        self.v = np.zeros_like(value)


class _CharRNN:
    def __init__(self, vocab_size: int, d_model: int, hidden_size: int, rng: np.random.Generator):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.hidden_size = hidden_size

        def scaled(*shape, fan_in):
            return rng.standard_normal(shape) / np.sqrt(fan_in)

        self.embedding = _AdamParam(scaled(vocab_size, d_model, fan_in=d_model))
        self.W_x = _AdamParam(scaled(d_model, hidden_size, fan_in=d_model))
        self.W_h = _AdamParam(scaled(hidden_size, hidden_size, fan_in=hidden_size))
        self.b_h = _AdamParam(np.zeros(hidden_size))
        self.W_out = _AdamParam(scaled(hidden_size, vocab_size, fan_in=hidden_size))
        self.b_out = _AdamParam(np.zeros(vocab_size))

        self._params = [
            self.embedding, self.W_x, self.W_h, self.b_h, self.W_out, self.b_out
        ]
        self._adam_t = 0

    def forward_sequence(self, tokens: List[int]):
        h = np.zeros(self.hidden_size)
        hs = [h]
        logits_list = []
        for tok in tokens:
            x = self.embedding.value[tok]
            h = np.tanh(x @ self.W_x.value + h @ self.W_h.value + self.b_h.value)
            hs.append(h)
            logits_list.append(h @ self.W_out.value + self.b_out.value)
        return hs, logits_list

    def step(self, h: np.ndarray, tok: int):
        x = self.embedding.value[tok]
        h_new = np.tanh(x @ self.W_x.value + h @ self.W_h.value + self.b_h.value)
        logits = h_new @ self.W_out.value + self.b_out.value
        return h_new, logits

    def train_on_tokens(self, tokens: List[int], lr: float, grad_clip: float) -> float:
        if len(tokens) < 2:
            return 0.0
        inputs = tokens[:-1]
        targets = tokens[1:]
        hs, logits_list = self.forward_sequence(inputs)

        d_embedding = np.zeros_like(self.embedding.value)
        d_W_x = np.zeros_like(self.W_x.value)
        d_W_h = np.zeros_like(self.W_h.value)
        d_b_h = np.zeros_like(self.b_h.value)
        d_W_out = np.zeros_like(self.W_out.value)
        d_b_out = np.zeros_like(self.b_out.value)

        dh_next = np.zeros(self.hidden_size)
        total_loss = 0.0
        n = len(inputs)

        for t in reversed(range(n)):
            tok = inputs[t]
            target = targets[t]
            h_t = hs[t + 1]
            h_prev = hs[t]
            probs = _softmax(logits_list[t])
            total_loss += -np.log(probs[target] + 1e-10)

            dlogits = probs.copy()
            dlogits[target] -= 1.0
            dlogits /= n

            d_W_out += np.outer(h_t, dlogits)
            d_b_out += dlogits

            dh = dlogits @ self.W_out.value.T + dh_next
            dtanh = (1.0 - h_t ** 2) * dh

            x = self.embedding.value[tok]
            d_W_x += np.outer(x, dtanh)
            d_W_h += np.outer(h_prev, dtanh)
            d_b_h += dtanh
            d_embedding[tok] += dtanh @ self.W_x.value.T

            dh_next = dtanh @ self.W_h.value.T

        grads = [d_embedding, d_W_x, d_W_h, d_b_h, d_W_out, d_b_out]

        total_norm = np.sqrt(sum(float(np.sum(g ** 2)) for g in grads))
        if total_norm > grad_clip:
            scale = grad_clip / (total_norm + 1e-9)
            grads = [g * scale for g in grads]

        self._adam_apply(grads, lr)
        return total_loss / n

    def _adam_apply(self, grads, lr, beta1=0.9, beta2=0.999, eps=1e-8):
        self._adam_t += 1
        t = self._adam_t
        for param, grad in zip(self._params, grads):
            param.m = beta1 * param.m + (1 - beta1) * grad
            param.v = beta2 * param.v + (1 - beta2) * (grad ** 2)
            m_hat = param.m / (1 - beta1 ** t)
            v_hat = param.v / (1 - beta2 ** t)
            param.value -= lr * m_hat / (np.sqrt(v_hat) + eps)

    def state_dict(self):
        return {
            "embedding": self.embedding.value.tolist(),
            "W_x": self.W_x.value.tolist(),
            "W_h": self.W_h.value.tolist(),
            "b_h": self.b_h.value.tolist(),
            "W_out": self.W_out.value.tolist(),
            "b_out": self.b_out.value.tolist(),
            "adam_t": self._adam_t,
        }

    def load_state_dict(self, data):
        mapping = {
            "embedding": self.embedding, "W_x": self.W_x, "W_h": self.W_h,
            "b_h": self.b_h, "W_out": self.W_out, "b_out": self.b_out,
        }
        for key, param in mapping.items():
            if key in data:
                arr = np.array(data[key])
                if arr.shape == param.value.shape:
                    param.value = arr
        self._adam_t = data.get("adam_t", 0)


class LanguageCenter:
    def __init__(self, config: Optional[LanguageCenterConfig] = None, force_new: bool = False):
        self.config = config or LanguageCenterConfig()
        cfg = self.config
        rng = np.random.default_rng(cfg.seed)
        self.model = _CharRNN(cfg.vocab_size, cfg.d_model, cfg.hidden_size, rng)

        self._replay_buffer: List[str] = []
        self._learn_calls = 0
        self._training_steps = 0
        self._loss_history: List[float] = []
        self._last_loss = 0.0

        if not force_new:
            self._load()

    def _encode(self, text: str) -> List[int]:
        vs = self.config.vocab_size
        return [ord(c) if ord(c) < vs else 0 for c in text]

    def _decode(self, tokens: List[int]) -> str:
        return "".join(chr(t) for t in tokens if 32 <= t < 127)

    def _train_text(self, text: str) -> float:
        tokens = self._encode(text)[: self.config.max_seq_len]
        if len(tokens) < 2:
            return 0.0
        loss = self.model.train_on_tokens(tokens, self.config.learning_rate, self.config.grad_clip)
        self._training_steps += 1
        self._loss_history.append(loss)
        if len(self._loss_history) > 10000:
            self._loss_history = self._loss_history[-10000:]
        self._last_loss = loss
        return loss

    def learn(self, text: str) -> float:
        text = (text or "").strip()
        if len(text) < 2:
            return 0.0
        loss = self._train_text(text)
        self._replay_buffer.append(text)
        if len(self._replay_buffer) > self.config.replay_buffer_cap:
            self._replay_buffer = self._replay_buffer[-self.config.replay_buffer_cap:]
        self._learn_calls += 1
        if (
            self._learn_calls % self.config.replay_every == 0
            and len(self._replay_buffer) > 1
        ):
            sample_size = min(self.config.replay_batch, len(self._replay_buffer))
            for old_text in random.sample(self._replay_buffer, sample_size):
                self._train_text(old_text)
        return loss

    def speak(self, prompt: str = "", max_new_tokens: int = 60, temperature: float = 0.8, top_k: int = 0) -> str:
        prompt_tokens = self._encode(prompt) if prompt else [ord(" ")]
        h = np.zeros(self.config.hidden_size)
        for tok in prompt_tokens[:-1]:
            h, _ = self.model.step(h, tok)

        generated = list(prompt_tokens)
        cur = prompt_tokens[-1]
        for _ in range(max_new_tokens):
            h, logits = self.model.step(h, cur)
            logits = logits / max(temperature, 1e-2)
            if top_k and top_k < len(logits):
                top_idx = np.argpartition(logits, -top_k)[-top_k:]
                mask = np.full_like(logits, -1e9)
                mask[top_idx] = logits[top_idx]
                logits = mask
            probs = _softmax(logits)
            next_tok = int(np.random.choice(len(probs), p=probs))
            if next_tok == 0:
                break
            generated.append(next_tok)
            cur = next_tok

        return self._decode(generated[len(prompt_tokens):]).strip()

    def get_stats(self) -> dict:
        recent = self._loss_history[-100:]
        return {
            "training_steps": self._training_steps,
            "replay_buffer_size": len(self._replay_buffer),
            "avg_recent_loss": round(float(np.mean(recent)), 4) if recent else 0.0,
            "last_loss": round(self._last_loss, 4),
            "approx_perplexity": round(float(np.exp(np.mean(recent))), 2) if recent else None,
        }

    def save(self):
        try:
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            state = {
                "config": vars(self.config),
                "model": self.model.state_dict(),
                "training_steps": self._training_steps,
                "learn_calls": self._learn_calls,
                "loss_history": self._loss_history[-200:],
                "replay_buffer": self._replay_buffer[-self.config.replay_buffer_cap:],
            }
            MODEL_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"Save failed: {e}")

    def _load(self):
        try:
            if not MODEL_PATH.exists():
                return
            data = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
            if "model" in data:
                self.model.load_state_dict(data["model"])
            self._training_steps = data.get("training_steps", 0)
            self._learn_calls = data.get("learn_calls", 0)
            self._loss_history = data.get("loss_history", [])
            self._replay_buffer = data.get("replay_buffer", [])
        except Exception as e:
            print(f"Load failed: {e}")
