"""
Quick capability check for Nova.
Run this to verify each feature actually works on your machine.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print("=" * 60)
print("NOVA CAPABILITY CHECK")
print("=" * 60)

# 1. Core imports
print("\n[1/6] Core imports...")
try:
    from neuro_child.gui import Memory, Personality, Eyes, Hands, Brain
    from neuro_child.consciousness import ConsciousNova
    from neuro_child.observational_learning import ObservationMemory, SpeechPatternLearner
    from neuro_child.curriculum import Curriculum
    from neuro_child.language_acquisition import VocabularyAcquisitionEngine, BabyResponseGenerator
    print("  OK - all modules import")
except Exception as e:
    print(f"  FAIL - {e}")
    sys.exit(1)

# 2. Text chat
print("\n[2/6] Text chat...")
try:
    m = Memory()
    p = Personality(m.profile)
    e = Eyes()
    h = Hands()
    class FakeMouth:
        def __init__(self):
            self._loop = type('L', (), {'run_until_complete': lambda *a, **k: None})()
        async def say(self, text):
            pass
    mo = FakeMouth()
    b = Brain(m, p, e, h, mo)
    replies = []
    for msg in ["hi", "remember dad likes pizza", "how do you feel?", "what do you see"]:
        r = b.respond(msg)
        replies.append((msg, r))
        print(f"  dad: {msg}")
        print(f"  nova: {r}")
    print("  OK - text chat works")
except Exception as e:
    print(f"  FAIL - {e}")

# 3. Voice synthesis
print("\n[3/6] Voice synthesis (edge-tts)...")
try:
    import edge_tts
    print("  OK - edge_tts installed")
    # Quick test
    import asyncio
    async def test_tts():
        out_file = str(Path(__file__).resolve().parent / "neuro_child" / "memory" / "test_voice.mp3")
        c = edge_tts.Communicate("hi dad!", voice="en-US-JennyNeural")
        await c.save(out_file)
    asyncio.run(test_tts())
    print("  OK - generated test voice clip")
except Exception as e:
    print(f"  FAIL/WARN - {e}")

# 4. Microphone input
print("\n[4/6] Microphone input (SpeechRecognition)...")
try:
    import speech_recognition as sr
    print("  OK - speech_recognition installed")
    try:
        r = sr.Recognizer()
        with sr.Microphone() as source:
            print("  Microphone found (test will skip actual listen)")
    except Exception as e:
        print(f"  WARN - mic not available: {e}")
except ImportError:
    print("  FAIL - SpeechRecognition not installed")

# 5. Screen capture
print("\n[5/6] Screen capture (mss)...")
try:
    import mss
    with mss.mss() as s:
        shot = s.grab(s.monitors[0])
        print(f"  OK - captured screen: {shot.size}")
except Exception as e:
    print(f"  FAIL - {e}")

# 6. Learning systems
print("\n[6/6] Learning systems...")
try:
    obs = ObservationMemory()
    vocab = VocabularyAcquisitionEngine()
    baby = BabyResponseGenerator(vocab)
    
    # Simulate hearing words
    new_words = vocab.encounter_text("dad likes pizza and games", source="dad")
    print(f"  New words learned: {new_words}")
    
    summary = vocab.get_vocabulary_summary()
    print(f"  Stage: {summary['developmental_stage']}")
    print(f"  Words known: {summary['total_words_known']}")
    
    reply = baby.generate_response("hi")
    print(f"  Baby reply: {reply}")
    
    print("  OK - learning systems work")
except Exception as e:
    print(f"  FAIL - {e}")

print("\n" + "=" * 60)
print("CHECK COMPLETE")
print("=" * 60)
