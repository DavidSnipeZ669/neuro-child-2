"""
English Language LLM - word-level LSTM.

Learns English vocabulary and grammar from real text.
Fast enough to train to coherent English on CPU/NumPy.
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

MODEL_DIR = Path(__file__).resolve().parent / "memory"
ENGLISH_MODEL_PATH = MODEL_DIR / "english_llm_v2.json"
VOCAB_PATH = MODEL_DIR / "english_vocab.json"


class EnglishLLMConfig:
    def __init__(self, vocab_size=500, d_model=128, n_heads=4, n_layers=2, d_ff=256, max_seq_len=32, learning_rate=0.005, dropout=0.1):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.d_ff = d_ff
        self.max_seq_len = max_seq_len
        self.learning_rate = learning_rate
        self.dropout = dropout


def _softmax(x, axis=-1, eps=1e-9):
    x = x - np.max(x, axis=axis, keepdims=True)
    e = np.exp(x)
    return e / (np.sum(e, axis=axis, keepdims=True) + eps)


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))


def _tanh(x):
    return np.tanh(x)


class _WordLSTM:
    def __init__(self, vocab_size, hidden_size, rng):
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.embedding = rng.standard_normal((vocab_size, hidden_size)) * 0.1
        self.lstm_W = np.zeros((hidden_size * 2, 4 * hidden_size))
        self.lstm_b = np.zeros(4 * hidden_size)
        self.W_out = rng.standard_normal((hidden_size, vocab_size)) * 0.1
        self.b_out = np.zeros(vocab_size)
        self.hidden_size = hidden_size
        self.cache: List[Any] = []

    def _lstm_forward(self, x, h, c):
        combined = np.concatenate([h.reshape(1, -1), x.reshape(1, -1)], axis=-1)
        gates = np.matmul(combined, self.lstm_W) + self.lstm_b
        i, f, c_candidate, o = np.split(gates, 4, axis=-1)
        i_gate = _sigmoid(i)
        f_gate = _sigmoid(f)
        c_new = f_gate * c.reshape(1, -1) + i_gate * _tanh(c_candidate)
        h_new = o * _tanh(c_new)
        self.cache.append((combined, i_gate, f_gate, c_candidate, o, c.copy(), h.copy(), x.copy()))
        return h_new.reshape(-1), c_new.reshape(-1)

    def _lstm_backward(self, grad_h, grad_c, lr):
        gh = grad_h
        gc = grad_c
        for combined, i_gate, f_gate, c_candidate, o_gate, c_prev, h_prev, x in reversed(self.cache):
            tanh_c = _tanh(c_new := f_gate * c_prev + i_gate * c_candidate)
            do = gh * tanh_c
            gc = gc + gh * o_gate * (1.0 - tanh_c ** 2)
            gc_prev = gc * f_gate
            gf = gc * c_prev
            gi = gc * c_candidate
            gc_cand = gc * i_gate
            di = gi * i_gate * (1.0 - i_gate)
            df = gf * f_gate * (1.0 - f_gate)
            dc = gc_cand * (1.0 - c_candidate ** 2)
            gates_grad = np.concatenate([di, df, dc, do], axis=-1)
            dW = np.matmul(combined.T, gates_grad)
            db = np.sum(gates_grad, axis=0)
            grad_combined = np.matmul(gates_grad, self.lstm_W.T)
            gh = grad_combined[:, :self.hidden_size].reshape(-1)
            gx = grad_combined[:, self.hidden_size:].reshape(-1)
            gc = gc_prev
            self.lstm_W -= lr * dW
            self.lstm_b -= lr * db
        return gx

    def forward_seq(self, word_ids):
        h = np.zeros(self.hidden_size)
        c = np.zeros(self.hidden_size)
        self.cache.clear()
        hiddens = []
        x = self.embedding[np.array(word_ids)]
        for t in range(len(word_ids)):
            h, c = self._lstm_forward(x[t], h, c)
            hiddens.append(h.copy())
        return hiddens

    def backward_seq(self, word_ids, hiddens, lr):
        targets = word_ids[1:]
        preds = hiddens[:-1]
        
        dlogits = np.zeros((len(preds), self.vocab_size))
        for t in range(len(preds)):
            probs = _softmax(np.matmul(preds[t], self.W_out) + self.b_out)
            dlogits[t] = probs
            dlogits[t, targets[t]] -= 1
            dlogits[t] /= len(targets)
        
        dW_out = np.matmul(np.stack(preds).T, dlogits)
        db_out = np.sum(dlogits, axis=0)
        self.W_out -= lr * dW_out
        self.b_out -= lr * db_out
        
        dh_next = np.zeros(self.hidden_size)
        dc_next = np.zeros(self.hidden_size)
        for t in reversed(range(len(preds))):
            dh = np.matmul(dlogits[t], self.W_out.T) + dh_next
            gx = self._lstm_backward(dh, dc_next, lr)
            dh_next = gx[:self.hidden_size]
            dc_next = np.zeros(self.hidden_size)


class EnglishLLM:
    """
    Word-level LSTM language model.
    Learns English vocabulary and sentence structure from text.
    """

    def __init__(self, config=None, force_new=False):
        loaded_config = None
        if not force_new:
            loaded_config = self._load_config()
        if isinstance(config, EnglishLLMConfig):
            self.config = config
        elif loaded_config is not None:
            self.config = loaded_config
        else:
            self.config = EnglishLLMConfig(**(config or {}))
        cfg = self.config
        self.vocab_size = cfg.vocab_size
        self.d_model = cfg.d_model
        self.n_heads = cfg.n_heads
        self.n_layers = cfg.n_layers
        self.d_ff = cfg.d_ff
        self.max_seq_len = cfg.max_seq_len
        self.learning_rate = cfg.learning_rate
        
        self.word_to_id: Dict[str, int] = {}
        self.id_to_word: Dict[int, str] = {}
        self.model = _WordLSTM(self.vocab_size, self.d_model, np.random.default_rng(42))
        self._training_steps = 0
        self._loss_history = []
        self._text_buffer = []
        self._last_loss = 0.0
        
        if not force_new:
            self._load_vocab()
            self._load_model()

    def _ensure_vocab(self, words: List[str]):
        for w in words:
            if w not in self.word_to_id and len(self.word_to_id) < self.vocab_size:
                idx = len(self.word_to_id)
                self.word_to_id[w] = idx
                self.id_to_word[idx] = w

    def tokenize(self, text: str) -> List[int]:
        words = text.lower().split()
        self._ensure_vocab(words)
        return [self.word_to_id.get(w, 0) for w in words if w in self.word_to_id]

    def detokenize(self, ids: List[int]) -> str:
        return " ".join(self.id_to_word.get(i, "") for i in ids if i in self.id_to_word)

    def train_step(self, text):
        tokens = self.tokenize(text)
        if len(tokens) < 2:
            return 0.0
        tokens = tokens[:self.max_seq_len]
        hiddens = self.model.forward_seq(tokens)
        targets = tokens[1:]
        preds = hiddens[:-1]
        
        logits = np.matmul(np.stack(preds), self.model.W_out) + self.model.b_out
        log_probs = np.log(_softmax(logits) + 1e-10)
        loss = -np.mean(log_probs[np.arange(len(targets)), targets])
        
        self.model.backward_seq(tokens, hiddens, self.learning_rate)
        self._training_steps += 1
        self._loss_history.append(float(loss))
        if len(self._loss_history) > 10000:
            self._loss_history = self._loss_history[-10000:]
        self._last_loss = float(loss)
        return float(loss)

    def generate(self, prompt, max_new_tokens=20, temperature=0.85):
        tokens = self.tokenize(prompt)
        if not tokens:
            return ""
        generated = list(tokens)
        h = np.zeros(self.d_model)
        c = np.zeros(self.d_model)
        x = self.model.embedding[np.array(tokens)]
        for t in range(len(tokens) - 1):
            h, c = self.model._lstm_forward(x[t], h, c)
        for _ in range(max_new_tokens):
            logits = np.matmul(h, self.model.W_out) + self.model.b_out
            logits = logits / max(temperature, 0.01)
            probs = _softmax(logits)
            next_token = int(np.random.choice(len(probs), p=probs))
            generated.append(next_token)
            x_t = self.model.embedding[next_token]
            h, c = self.model._lstm_forward(x_t, h, c)
        return self.detokenize(generated[len(tokens):])

    def add_text(self, text):
        if not text or len(text.strip()) < 3:
            return
        self._text_buffer.append(text.strip())
        if len(self._text_buffer) > 5000:
            self._text_buffer = self._text_buffer[-5000:]
        self.train_step(text.strip())

    def get_stats(self):
        return {
            "training_steps": self._training_steps,
            "buffer_size": len(self._text_buffer),
            "vocabulary_size": len(self.word_to_id),
            "avg_loss": round(float(np.mean(self._loss_history[-100:])), 4) if self._loss_history else 0.0,
            "last_loss": round(self._last_loss, 4),
        }

    def save(self):
        try:
            ENGLISH_MODEL_PATH.write_text(json.dumps({
                "config": {
                    "vocab_size": self.vocab_size,
                    "d_model": self.d_model,
                    "n_heads": self.n_heads,
                    "n_layers": self.n_layers,
                    "d_ff": self.d_ff,
                    "max_seq_len": self.max_seq_len,
                    "learning_rate": self.learning_rate,
                },
                "embedding": self.model.embedding.tolist(),
                "lstm_W": self.model.lstm_W.tolist(),
                "lstm_b": self.model.lstm_b.tolist(),
                "W_out": self.model.W_out.tolist(),
                "b_out": self.model.b_out.tolist(),
                "training_steps": self._training_steps,
                "loss_history": self._loss_history[-200:],
                "text_buffer": self._text_buffer[-200:],
            }, ensure_ascii=False), encoding="utf-8")
            VOCAB_PATH.write_text(json.dumps({
                "word_to_id": self.word_to_id,
                "id_to_word": {int(k): v for k, v in self.id_to_word.items()},
            }, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"Save failed: {e}")

    def _load_config(self):
        try:
            if not ENGLISH_MODEL_PATH.exists():
                return None
            data = json.loads(ENGLISH_MODEL_PATH.read_text(encoding="utf-8"))
            if "config" in data:
                return EnglishLLMConfig(**data["config"])
        except Exception:
            pass
        return None

    def _load_vocab(self):
        try:
            if VOCAB_PATH.exists():
                data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
                self.word_to_id = data.get("word_to_id", {})
                self.id_to_word = {int(k): v for k, v in data.get("id_to_word", {}).items()}
        except Exception:
            pass

    def _load_model(self):
        try:
            if not ENGLISH_MODEL_PATH.exists():
                return
            data = json.loads(ENGLISH_MODEL_PATH.read_text(encoding="utf-8"))
            if "config" in data:
                c = data["config"]
                self.d_model = c.get("d_model", self.d_model)
                self.n_heads = c.get("n_heads", self.n_heads)
                self.n_layers = c.get("n_layers", self.n_layers)
                self.d_ff = c.get("d_ff", self.d_ff)
                self.max_seq_len = c.get("max_seq_len", self.max_seq_len)
                self.learning_rate = c.get("learning_rate", self.learning_rate)
            for k, attr in [("embedding", "embedding"), ("W_out", "W_out"), ("b_out", "b_out")]:
                if k in data:
                    arr = np.array(data[k])
                    target = getattr(self.model, attr)
                    if arr.shape == target.shape:
                        setattr(self.model, attr, arr)
            for k, attr in [("lstm_W", "lstm_W"), ("lstm_b", "lstm_b")]:
                if k in data:
                    arr = np.array(data[k])
                    target = getattr(self.model, attr)
                    if arr.shape == target.shape:
                        setattr(self.model, attr, arr)
            for k in ["training_steps", "loss_history", "text_buffer"]:
                if k in data:
                    setattr(self, "_" + k, data[k])
        except Exception as e:
            print(f"Load failed: {e}")
