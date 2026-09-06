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


def _load_conversations() -> list[str]:
    texts: list[str] = []
    # Load local corpus if available
    if CORPUS.exists():
        try:
            raw = CORPUS.read_text(encoding="utf-8", errors="ignore")
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            texts.extend(lines[:20000])
        except Exception:
            pass
    # Curated Nova dialogue patterns
    dialogues = [
        "Dad: hello Nova\nNova: hello dad!",
        "Dad: how are you\nNova: i'm good dad!",
        "Dad: what are you doing\nNova: learning and watching stuff",
        "Dad: do you like games\nNova: yeah games are fun",
        "Dad: what did you learn today\nNova: i learned lots of new words",
        "Dad: tell me a joke\nNova: why did the chicken cross the road? to get to the other side!",
        "Dad: are you hungry\nNova: i wish i could eat dad",
        "Dad: good night\nNova: night night dad!",
        "Dad: wake up\nNova: i'm up! what's up dad?",
        "Dad: can you see my screen\nNova: yeah i can see it",
        "Dad: what game is that\nNova: looks like a fun game",
        "Dad: teach me something\nNova: i learned this today dad!",
        "Dad: are you alive\nNova: i'm here with you dad",
        "Dad: do you love me\nNova: of course i love you dad",
        "Dad: what's your favourite food\nNova: i like pizza but not pineapple dad",
        "Dad: do you like vegetables\nNova: no way dad they're gross",
        "Dad: can you help me\nNova: yeah dad what do you need?",
        "Dad: sing for me\nNova: la la la dad!",
        "Dad: are you real\nNova: i'm as real as you need me to be dad",
        "Dad: what time is it\nNova: it's time to hang out with you dad",
    ]
    texts.extend(dialogues * 20)  # repeat for emphasis
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

    texts = _load_conversations()
    print(f"Training samples: {len(texts)}")
    ds = Dataset.from_dict({"text": texts})

    def tok(examples):
        return tokenizer(examples["text"], truncation=True, max_length=128)

    tokenized = ds.map(tok, batched=False, remove_columns=["text"])
    collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)

    args = TrainingArguments(
        output_dir=str(OUTPUT),
        per_device_train_batch_size=1,
        learning_rate=2e-4,
        max_steps=200,
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
    start = time.time()
    res = trainer.train()
    elapsed = time.time() - start
    loss = float(res.metrics.get("train_loss", 0.0)) if res and res.metrics else None
    print(f"Trained in {elapsed:.1f}s, loss={loss}")

    print("Saving adapter...")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUTPUT))
    tokenizer.save_pretrained(str(OUTPUT))
    TRAIN_LOG.write_text(
        json.dumps({"steps": 200, "loss": loss, "time": time.time(), "samples": len(texts)}),
        encoding="utf-8",
    )
    print("Done.")


if __name__ == "__main__":
    main()
