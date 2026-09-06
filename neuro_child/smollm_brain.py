"""
SmolLM Brain — Nova's primary language/knowledge LLM.
Uses HuggingFace SmolLM-135M with 4-bit quantization and LoRA adapters.
Trains continuously on everything Nova sees, hears, reads, and learns.
"""
from __future__ import annotations

import gc
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TextIteratorStreamer
    from peft import LoraConfig, get_peft_model, TaskType, PeftModel
    from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling
    from datasets import Dataset
    HAS_TRANSFORMERS = True
except Exception:
    HAS_TRANSFORMERS = False

MODEL_NAME = "HuggingFaceTB/SmolLM-135M"
ADAPTER_PATH = Path(__file__).resolve().parent / "memory" / "smollm_adapter"
TRAIN_LOG = Path(__file__).resolve().parent / "memory" / "smollm_train.log"


@dataclass
class SmolLMConfig:
    model_name: str = MODEL_NAME
    adapter_path: Path = ADAPTER_PATH
    max_seq_len: int = 256
    load_in_4bit: bool = True
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    train_batch_size: int = 2
    learning_rate: float = 2e-4
    max_steps: int = 20
    warmup_steps: int = 5


class SmolLMBrain:
    """
    Nova's primary LLM. Uses SmolLM-135M with LoRA for efficient training.
    Continuously fine-tunes on new text from screen, audio, web, and chat.
    """

    def __init__(self, config: Optional[SmolLMConfig] = None) -> None:
        self.config = config or SmolLMConfig()
        self.model = None
        self.tokenizer = None
        self.peft_model = None
        self._training = False
        self._lock = threading.RLock()
        self._recent_loss: Optional[float] = None
        self._training_steps: int = 0
        self._load()

    def _load(self) -> None:
        if not HAS_TRANSFORMERS:
            self._load_error = "transformers not installed"
            return
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.config.model_name)
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            use_4bit = self.config.load_in_4bit and (torch.cuda.is_available() or getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
            if use_4bit:
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.config.model_name,
                    quantization_config=quant_config,
                    device_map="auto",
                    torch_dtype=torch.float16,
                )
            else:
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.config.model_name,
                    device_map="cpu",
                    torch_dtype=torch.float32,
                )

            lora_config = LoraConfig(
                r=self.config.lora_r,
                lora_alpha=self.config.lora_alpha,
                lora_dropout=self.config.lora_dropout,
                task_type=TaskType.CAUSAL_LM,
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            )
            if self.config.adapter_path.exists():
                self.peft_model = PeftModel.from_pretrained(self.model, str(self.config.adapter_path))
            else:
                self.peft_model = get_peft_model(self.model, lora_config)
            self.peft_model.eval()
            try:
                if TRAIN_LOG.exists():
                    data = json.loads(TRAIN_LOG.read_text(encoding="utf-8"))
                    self._training_steps = int(data.get("steps", 0))
                    self._recent_loss = data.get("loss")
            except Exception:
                pass
            self._load_error = None
        except Exception as e:
            self.model = None
            self.tokenizer = None
            self.peft_model = None
            self._load_error = repr(e)

    def is_available(self) -> bool:
        return self.peft_model is not None and self.tokenizer is not None

    def generate(self, prompt: str, max_new_tokens: int = 60, temperature: float = 0.7, top_k: int = 20) -> str:
        if not self.is_available():
            return ""
        try:
            inputs = self.tokenizer(prompt, return_tensors="pt")
            device = next(self.peft_model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}
            gen_kwargs = dict(
                max_new_tokens=max_new_tokens,
                pad_token_id=self.tokenizer.eos_token_id,
                do_sample=True,
            )
            if device.type != "cpu":
                gen_kwargs.update(dict(temperature=temperature, top_k=top_k))
            else:
                gen_kwargs.update(dict(temperature=min(float(temperature), 0.8), top_k=min(int(top_k), 10)))
            with torch.no_grad():
                out = self.peft_model.generate(**inputs, **gen_kwargs)
            result = self.tokenizer.decode(out[0], skip_special_tokens=True)
            return result[len(prompt):].strip()
        except Exception:
            return ""

    def train_on_text(self, text: str) -> Optional[float]:
        if not self.is_available() or not text or not text.strip():
            return None
        text = text.strip()
        if len(text) < 5:
            return None
        with self._lock:
            if self._training:
                return None
            self._training = True
        try:
            dataset = Dataset.from_dict({"text": [text]})
            def tokenize(examples):
                return self.tokenizer(examples["text"], truncation=True, max_length=self.config.max_seq_len)
            tokenized = dataset.map(tokenize, batched=False, remove_columns=["text"])
            data_collator = DataCollatorForLanguageModeling(self.tokenizer, mlm=False)

            training_args = TrainingArguments(
                output_dir=str(self.config.adapter_path),
                per_device_train_batch_size=self.config.train_batch_size,
                learning_rate=self.config.learning_rate,
                max_steps=self.config.max_steps,
                warmup_steps=self.config.warmup_steps,
                logging_steps=1,
                save_strategy="no",
                report_to="none",
                fp16=True,
                optim="paged_adamw_8bit",
            )
            trainer = Trainer(
                model=self.peft_model,
                args=training_args,
                train_dataset=tokenized,
                data_collator=data_collator,
            )
            result = trainer.train()
            loss = float(result.metrics.get("train_loss", 0.0)) if result and result.metrics else None
            self._recent_loss = loss
            self._training_steps += self.config.max_steps
            try:
                self.peft_model.save_pretrained(str(self.config.adapter_path))
            except Exception:
                pass
            try:
                TRAIN_LOG.parent.mkdir(parents=True, exist_ok=True)
                TRAIN_LOG.write_text(
                    json.dumps({"steps": self._training_steps, "last_loss": loss, "time": time.time()}),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return loss
        except Exception:
            return None
        finally:
            self._training = False
            gc.collect()
            torch.cuda.empty_cache() if torch.cuda.is_available() else None

    def respond(self, user_text: str, context: Optional[str] = None) -> str:
        prompt = f"Dad: {user_text}\nNova:"
        if context:
            prompt = f"Context: {context[:200]}\n{prompt}"
        reply = self.generate(prompt, max_new_tokens=80, temperature=0.75, top_k=20)
        if not reply:
            return ""
        return reply.split("\n")[0].strip()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "available": self.is_available(),
            "training_steps": self._training_steps,
            "recent_loss": self._recent_loss,
            "model": self.config.model_name,
            "load_error": getattr(self, "_load_error", None),
        }


__all__ = ["SmolLMBrain", "SmolLMConfig"]
