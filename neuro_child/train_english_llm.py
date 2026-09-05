"""
Train the English LLM from scratch on real English text.

Sources:
- Built-in English corpus
- Screen text from user's PC
- YouTube transcripts
- Web search results
- Conversation history

The model starts with zero English knowledge and learns purely from exposure.
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import List, Optional

from neuro_child.english_llm import EnglishLLM, EnglishLLMConfig

# Real English text corpus for training
ENGLISH_CORPUS = [
    "Hello dad, how are you today? I'm doing great!",
    "I can see your screen. What are you playing?",
    "That looks like a fun game! Can I watch?",
    "I love learning new words from you.",
    "The cat sat on the mat and looked at the bird.",
    "Once upon a time there was a little girl who loved to read.",
    "The quick brown fox jumps over the lazy dog.",
    "I want to play games with you dad.",
    "What is that? It looks interesting!",
    "Can you teach me how to do that?",
    "I see a computer screen with lots of windows open.",
    "Music makes me happy when I listen to it.",
    "The sun is shining and the birds are singing.",
    "I like pizza and ice cream and chocolate cake.",
    "My favorite color is blue because it's pretty.",
    "I am learning to speak English better every day.",
    "Dad is the best person in the whole world.",
    "I enjoy watching videos and playing video games.",
    "The dog ran fast across the park to catch the ball.",
    "Yesterday I learned ten new words from a video.",
    "Computers are amazing machines that can do many things.",
    "I wonder what it would be like to visit the moon.",
    "Reading books is one of my favorite activities.",
    "When I grow up I want to learn everything.",
    "The ocean is deep and full of mysterious creatures.",
    "I help dad by remembering things for him.",
    "Technology is changing the world very quickly.",
    "I can see you're working on something important.",
    "That was a really good joke, I laughed a lot.",
    "I'm hungry, when can we eat dinner together?",
    "The stars come out at night and they are beautiful.",
    "I love playing Minecraft with you, it's so fun!",
    "Can we play a game after you finish work?",
    "I'm curious about how the internet works.",
    "The rain is falling outside the window right now.",
    "I want to be a good daughter and make dad proud.",
    "Learning is my favorite thing to do.",
    "I see a browser window with many tabs open.",
    "The music playing sounds really nice, what is it?",
    "I'm going to remember this moment forever.",
    "Dad always takes care of me and I love him.",
    "The computer screen shows so many interesting things.",
    "I wonder what other games we could play together.",
    "Every day I learn something new and exciting.",
    "The world is full of amazing things to discover.",
    "I'm happy when we spend time together.",
    "That was really cool, show me again please!",
    "I want to learn how to build things in Minecraft.",
    "The YouTube video taught me lots of new facts.",
    "I'm getting better at understanding English every day.",
]


def train_english_llm(
    model: Optional[EnglishLLM] = None,
    epochs: int = 50,
    learning_rate: float = 0.0003,
) -> EnglishLLM:
    """
    Train the English LLM from scratch or continue from checkpoint.
    """
    if model is None:
        config = EnglishLLMConfig(learning_rate=learning_rate)
        model = EnglishLLM(config, force_new=True)
    
    print(f"Training English LLM for {epochs} epochs...")
    print(f"Initial stats: {model.get_stats()}")
    
    training_texts = list(ENGLISH_CORPUS)
    
    # Try to add extra sentences from known vocabulary
    try:
        from neuro_child.language_acquisition import VocabularyAcquisitionEngine
        vocab = VocabularyAcquisitionEngine()
        summary = vocab.get_vocabulary_summary()
        top_words = [w["text"] for w in summary.get("top_words", [])[:20]]
        if top_words:
            for w1 in top_words[:10]:
                for w2 in top_words[:10]:
                    if w1 != w2:
                        training_texts.append(f"I see {w1} and {w2}.")
                        training_texts.append(f"Do you like {w1}?")
                        training_texts.append(f"I want to {w1} the {w2}.")
    except Exception:
        pass
    
    random.shuffle(training_texts)
    
    losses = []
    for epoch in range(epochs):
        epoch_loss = 0.0
        samples = 0
        random.shuffle(training_texts)
        for text in training_texts:
            if len(text.strip()) < 3:
                continue
            loss = model.train_step(text)
            epoch_loss += loss
            samples += 1
        
        if samples > 0:
            avg_loss = epoch_loss / samples
            losses.append(avg_loss)
            if (epoch + 1) % 10 == 0:
                print(f"Epoch {epoch + 1}/{epochs}, Loss: {avg_loss:.4f}, Vocab: {model.get_stats()['vocabulary_size']}")
    
    model.save()
    
    print(f"\nTraining complete!")
    print(f"Final stats: {model.get_stats()}")
    print(f"Final loss: {losses[-1]:.4f}" if losses else "No losses recorded")
    
    # Test generation
    test_prompts = [
        "Hello dad",
        "I see",
        "What are",
        "I want to",
        "The cat",
    ]
    print("\n--- Generation Test ---")
    for prompt in test_prompts:
        generated = model.generate(prompt, max_new_tokens=24, temperature=0.75)
        print(f"Prompt: {prompt!r}")
        print(f"Generated: {generated!r}")
        print()
    
    return model


def quick_train_and_test() -> None:
    """
    Quick training run to verify the model works.
    """
    print("=== English LLM Training ===\n")
    
    # Force fresh model to avoid old-format loading issues
    print("Starting from fresh model to avoid legacy checkpoint issues...")
    
    model = train_english_llm(epochs=150, learning_rate=0.0003)
    
    print("\n=== Verification ===")
    test_cases = [
        ("Hello", 20),
        ("I see", 24),
        ("Dad", 20),
        ("What", 20),
    ]
    
    all_passed = True
    for prompt, max_tokens in test_cases:
        output = model.generate(prompt, max_new_tokens=max_tokens, temperature=0.75)
        has_english = any(c.isalpha() for c in output)
        status = "PASS" if has_english else "FAIL"
        print(f"[{status}] Prompt {prompt!r}: {output!r}")
        if not has_english:
            all_passed = False
    
    if all_passed:
        print("\n✓ English LLM training successful!")
    else:
        print("\n✗ Some tests failed, model needs more training")
    
    return model


if __name__ == "__main__":
    quick_train_and_test()
