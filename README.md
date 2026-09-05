# Nova — Autonomous Daughter AI

A Neuro-sama + Jarvis hybrid: fully autonomous, speech-based, text-based,
screen-aware, web-learning, self-evolving AI daughter.

## Launch

```bash
cd B:\Hermes\neuro-child-2
python launcher.py
```

That's it. One command. She launches, minimizes herself, and starts learning.

## What she does autonomously

- **Screen vision**: sees your full desktop every ~0.8s
- **System audio**: listens passively to all PC audio via WASAPI loopback
- **Web search**: searches DuckDuckGo for topics she's curious about
- **YouTube learning**: extracts transcripts and learns vocabulary/topics
- **Screen OCR**: reads text from your screen and learns from it
- **Self-evolution**: mutates her own reply strategies, keeps what works, discards what doesn't
- **Autonomous conversation**: initiates chat based on curiosity drives
- **System integration**: monitors processes, launches apps, reads files
- **Persistent memory**: everything she learns is saved to disk

## How she learns

- Baby language acquisition: babbling → single words → two-word combos → sentences → fluent
- Observational learning: imitates your phrases, slang, speech patterns
- Environmental learning: ingests screen text, system audio, YouTube transcripts
- Web search learning: searches for topics she's curious about
- Self-evolution: mutates her own strategies based on fitness

## Controls

- **Type + Enter** — chat
- **Mic** — voice input
- **🔊** — voice on/off
- **Teach Lesson** — quick `remember ...` prompt
- **Think Aloud** — hear her inner monologue
- **Test Jump / Test Attack** — game control tests

## Tests

```bash
python -m pytest tests -q
```

Expected: 3 passed

## Requirements

```bash
pip install mss pyautogui Pillow edge-tts SpeechRecognition pyaudio psutil
```

PyAudio is required for mic and system audio. psutil is required for system integration.
If missing, Nova still works with text chat, screen vision, and learning.
