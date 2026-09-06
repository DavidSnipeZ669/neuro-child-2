"""
Fine-tune SmolLM-135M on conversational English for Nova.
Uses local corpus + curated dialogue pairs.
CPU-friendly with LoRA.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)

ROOT = Path(__file__).resolve().parent.parent
MEMORY = ROOT / "neuro_child" / "memory"
CORPUS = MEMORY / "english_corpus.txt"
OUTPUT = MEMORY / "smollm_adapter"
TRAIN_LOG = MEMORY / "smollm_train.log"
MODEL_NAME = "HuggingFaceTB/SmolLM-135M"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_conversations() -> list[str]:
    try:
        from neuro_child.conversational_data import get_dialogues
        base = get_dialogues()
    except Exception:
        base = []
    texts: list[str] = list(base)
    for corpus_fn, label in [
        ("oasst1_dialogues.txt", "OASST1"),
        ("openorca_dialogues.txt", "OpenOrca"),
    ]:
        try:
            corpus = Path(__file__).resolve().parent / "memory" / corpus_fn
            if corpus.exists():
                lines = [ln.strip() for ln in corpus.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
                print(f"Loaded {len(lines)} {label} dialogues")
                texts.extend(lines)
        except Exception:
            pass
    if not texts:
        return base
    return texts


def main() -> None:
    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print("Loading base model (CPU)...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        device_map="cpu",
        torch_dtype=torch.float32,
    )

    print("Applying LoRA...")
    lora = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        task_type=TaskType.CAUSAL_LM,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    # Resume from existing adapter if present
    if OUTPUT.exists() and (OUTPUT / "adapter_model.safetensors").exists():
        try:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, str(OUTPUT), is_trainable=True)
            model.print_trainable_parameters()
            print("Resumed from existing adapter")
        except Exception:
            pass

    model.train()
    for p in model.parameters():
        if p.requires_grad:
            p.requires_grad_(True)

    texts = _load_conversations()
    print(f"Training samples: {len(texts)}")
    ds = Dataset.from_dict({"text": texts})

    def tok(examples):
        return tokenizer(examples["text"], truncation=True, max_length=128)

    tokenized = ds.map(tok, batched=False, remove_columns=["text"])
    collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)

    # Detect completed training
    completed = False
    if TRAIN_LOG.exists():
        try:
            completed = json.loads(TRAIN_LOG.read_text(encoding="utf-8")).get("completed", False)
        except Exception:
            pass

    max_steps = 0 if completed else 200

    args = TrainingArguments(
        output_dir=str(OUTPUT),
        per_device_train_batch_size=1,
        learning_rate=2e-4,
        max_steps=max_steps,
        warmup_steps=20,
        logging_steps=10,
        save_strategy="no",
        report_to="none",
        fp16=False,
        optim="adamw_torch",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized,
        data_collator=collator,
    )
    if max_steps > 0:
        start = time.time()
        res = trainer.train()
        elapsed = time.time() - start
        loss = float(res.metrics.get("train_loss", 0.0)) if res and res.metrics else None
        print(f"Trained in {elapsed:.1f}s, loss={loss}")
    else:
        print("Training already completed, skipping")

    print("Saving adapter...")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUTPUT))
    tokenizer.save_pretrained(str(OUTPUT))
    TRAIN_LOG.write_text(
        json.dumps({"steps": 200, "loss": loss if max_steps > 0 else None, "time": time.time(), "samples": len(texts), "completed": True}),
        encoding="utf-8",
    )
    print("Done.")


if __name__ == "__main__":
    main()
