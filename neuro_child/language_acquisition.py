"""
Language Acquisition Engine: learns English like a human baby, then surpasses it.

Stages:
  babbling -> single words -> two-word combos -> simple sentences -> conversational -> fluent
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MEMORY_DIR = Path(__file__).resolve().parent / "memory"
VOCAB_FILE = MEMORY_DIR / "vocabulary.json"


@dataclass
class WordKnowledge:
    text: str
    encounter_count: int = 0
    mastery: float = 0.0
    first_seen: float = field(default_factory=time.time)
    last_practiced: float = field(default_factory=time.time)
    contexts: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    attempts: List[Tuple[str, bool]] = field(default_factory=list)

    def record_context(self, context: str, source: str) -> None:
        ctx = (context or "").strip()
        if ctx and ctx not in self.contexts:
            self.contexts.append(ctx[:120])
        if source and source not in self.sources:
            self.sources.append(source[:120])

    def record_attempt(self, context: str, success: bool) -> None:
        self.attempts.append((context[:120], success))
        if len(self.attempts) > 200:
            self.attempts = self.attempts[-200:]

    def decay(self) -> None:
        if self.encounter_count <= 1:
            return
        self.mastery = max(0.0, self.mastery - 0.005)


class VocabularyAcquisitionEngine:
    """
    Zero-knowledge English acquisition with auto-bootstrap and continuous learning.
    """

    def __init__(self, vocab_path: Path = VOCAB_FILE) -> None:
        self.vocab_path = vocab_path
        self.words: Dict[str, WordKnowledge] = {}
        self.total_words_encountered: int = 0
        self.total_practice_attempts: int = 0
        self.total_corrections: int = 0
        self._load()
        self._maybe_bootstrap()

    def _load(self) -> None:
        try:
            if self.vocab_path.exists():
                data = json.loads(self.vocab_path.read_text(encoding="utf-8") or "[]")
                if isinstance(data, list):
                    for item in data:
                        text = item.get("text")
                        if not text:
                            continue
                        wk = WordKnowledge(
                            text=text,
                            encounter_count=int(item.get("encounter_count", 0)),
                            mastery=float(item.get("mastery", 0.0)),
                            first_seen=float(item.get("first_seen", time.time())),
                            last_practiced=float(item.get("last_practiced", time.time())),
                        )
                        wk.contexts = item.get("contexts", [])[:50]
                        wk.sources = item.get("sources", [])[:50]
                        self.words[text] = wk
                        self.total_words_encountered += wk.encounter_count
        except Exception:
            self.words = {}

    def save(self) -> None:
        try:
            data = []
            for wk in self.words.values():
                data.append(
                    {
                        "text": wk.text,
                        "encounter_count": wk.encounter_count,
                        "mastery": wk.mastery,
                        "first_seen": wk.first_seen,
                        "last_practiced": wk.last_practiced,
                        "contexts": wk.contexts[-20:],
                        "sources": wk.sources[-20:],
                    }
                )
            self.vocab_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _clean_word(self, word: str) -> str:
        return re.sub(r"[^a-zA-Z']", "", word).lower()

    _STOP_WORDS = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
        "was", "one", "our", "out", "has", "have", "had", "this", "that", "with",
        "they", "from", "been", "said", "each", "she", "him", "his", "how", "its",
        "may", "than", "them", "then", "some", "would", "make", "into",
        "time", "very", "when", "come", "could", "more", "made", "after", "also",
        "just", "know", "take", "people", "into", "year", "your", "good", "some",
        "could", "them", "other", "than", "then", "now", "only",
        "come", "think", "also", "back", "after", "use", "two", "how", "our",
        "work", "first", "well", "way", "even", "new", "want", "because", "any",
        "these", "give", "most", "us", "great",
    }

    def _maybe_bootstrap(self) -> None:
        """
        Seed a small foundational vocabulary on first run so baby replies
        feel like real kid conversation from the start, not word stubs.
        """
        if self.words:
            return
        seed_phrases = [
            "hi dad", "hello", "hey", "yeah", "oh", "nice", "cool", "okay",
            "see", "look", "play", "game", "pizza", "happy", "screen",
            "what", "i see", "no", "yes", "thanks", "like", "love", "good",
            "bad", "big", "small", "fast", "slow", "red", "blue", "green",
            "eat", "drink", "sleep", "run", "jump", "walk", "stop", "go",
            "home", "school", "friend", "family", "music", "movie", "fun",
            "learn", "teach", "read", "write", "draw", "sing", "dance",
        ]
        seen = set()
        for phrase in seed_phrases:
            words = [self._clean_word(w) for w in re.findall(r"[A-Za-z']+", phrase)]
            for w in words:
                if w and len(w) >= 2 and w not in self._STOP_WORDS and w not in seen:
                    seen.add(w)
                    wk = WordKnowledge(text=w)
                    wk.encounter_count = 2
                    wk.mastery = 0.7
                    wk.record_context("bootstrap seed", "bootstrap")
                    self.words[w] = wk
                    self.total_words_encountered += wk.encounter_count
        if seen:
            self.save()

    def encounter_text(self, text: str, source: str = "unknown", context_window: int = 5) -> List[str]:
        """
        Process a chunk of text and learn every new word.
        Returns list of newly learned words in this pass.
        """
        if not text:
            return []
        tokens = re.findall(r"[A-Za-z']+", text)
        words = [self._clean_word(t) for t in tokens]
        words = [w for w in words if w and len(w) >= 2 and w not in self._STOP_WORDS]

        if not words:
            return []

        context = " ".join(words[:context_window])
        new_words: List[str] = []

        for cleaned in words:
            if cleaned in self.words:
                wk = self.words[cleaned]
                wk.encounter_count += 1
                wk.record_context(context, source)
                # Babies learn fast: first impression sticks, reinforcement solidifies
                if wk.encounter_count == 1:
                    wk.mastery = min(1.0, wk.mastery + 0.55)
                elif wk.encounter_count <= 3:
                    wk.mastery = min(1.0, wk.mastery + 0.35)
                elif wk.encounter_count <= 7:
                    wk.mastery = min(1.0, wk.mastery + 0.15)
                else:
                    wk.mastery = min(1.0, wk.mastery + 0.06)
            else:
                wk = WordKnowledge(text=cleaned)
                wk.encounter_count = 1
                wk.mastery = 0.55
                wk.record_context(context, source)
                self.words[cleaned] = wk
                new_words.append(cleaned)
                self.total_words_encountered += 1

        if new_words:
            self.save()

        return new_words

    def try_use_word(self, word: str, context: str = "") -> Tuple[bool, str]:
        cleaned = self._clean_word(word)
        if not cleaned:
            return False, "empty"
        if cleaned not in self.words:
            return False, "unknown"
        wk = self.words[cleaned]
        success = random.random() < wk.mastery
        wk.record_attempt(f"used in: {context[:50]}", success)
        wk.last_practiced = time.time()
        self.total_practice_attempts += 1
        self.save()
        return success, "ok" if success else "still learning"

    def record_correction(self, word: str) -> None:
        cleaned = self._clean_word(word)
        if not cleaned:
            return
        if cleaned in self.words:
            wk = self.words[cleaned]
            wk.mastery = min(1.0, wk.mastery + 0.25)
            wk.last_practiced = time.time()
        else:
            wk = WordKnowledge(text=cleaned)
            wk.encounter_count = 1
            wk.mastery = 0.6
            wk.record_context("correction", "correction")
            self.words[cleaned] = wk
            self.total_words_encountered += 1
        self.total_corrections += 1
        self.save()

    def get_known_words(self, min_mastery: float = 0.2) -> List[str]:
        return [w for w, wk in self.words.items() if wk.mastery >= min_mastery]

    def get_developmental_stage(self) -> str:
        known = len(self.get_known_words(min_mastery=0.2))
        if known < 10:
            return "babbling"
        if known < 30:
            return "single_words"
        if known < 80:
            return "two_word_combos"
        if known < 200:
            return "simple_sentences"
        if known < 500:
            return "conversational"
        return "fluent"

    def get_vocabulary_summary(self) -> Dict[str, Any]:
        words = list(self.words.values())
        known = [w for w in words if w.mastery >= 0.2]
        top = sorted(words, key=lambda w: (w.encounter_count, w.mastery), reverse=True)[:20]
        recent = sorted(words, key=lambda w: w.last_practiced, reverse=True)[:15]
        total_attempts = sum(len(w.attempts) for w in words)
        successes = sum(1 for w in words for ok in w.attempts if ok)
        return {
            "total_words_seen": len(words),
            "total_words_known": len(known),
            "developmental_stage": self.get_developmental_stage(),
            "top_words": [
                {"text": w.text, "encounter_count": w.encounter_count, "mastery": round(w.mastery, 2)}
                for w in top
            ],
            "recent_words": [w.text for w in recent],
            "accuracy": round(successes / total_attempts, 2) if total_attempts else 0.0,
            "total_practice_attempts": self.total_practice_attempts,
            "total_corrections": self.total_corrections,
        }


class BabyResponseGenerator:
    """
    Age-appropriate response generator that feels like talking to a real kid.

    Uses:
    - intent-matched replies for questions/commands/praise
    - template-based sentence construction with known words
    - memory-based references to past conversations
    - screen context when available
    - personality-consistent tone
    """

    def __init__(self, vocab: VocabularyAcquisitionEngine, name: str = "Nova") -> None:
        self.vocab = vocab
        self.name = name
        self._conversation_memory: List[str] = []

    def try_new_word(self) -> str:
        candidates = [w for w in self.vocab.words if self.vocab.words[w].mastery < 0.3]
        if candidates:
            return random.choice(candidates)
        return ""

    def _known_words_sorted(self) -> List[str]:
        known = self.vocab.get_known_words(min_mastery=0.25)
        return sorted(known, key=lambda w: (self.vocab.words[w].mastery, len(w)), reverse=True)

    def _pick_word(self, avoid: Optional[str] = None) -> str:
        known = self._known_words_sorted()
        if not known:
            return "hi"
        pool = [w for w in known if w != avoid] or known
        return random.choice(pool)

    def _match_content_word(self, user_text: str) -> Optional[str]:
        """
        Prefer longer, higher-mastery content words over short function words.
        """
        tokens = re.findall(r"[A-Za-z']+", user_text.lower())
        content_candidates = [
            t for t in tokens
            if t in self.vocab.words
            and self.vocab.words[t].mastery >= 0.25
            and len(t) >= 3
        ]
        if content_candidates:
            return sorted(content_candidates, key=lambda t: (self.vocab.words[t].mastery, len(t)), reverse=True)[0]
        fallback = [
            t for t in tokens
            if t in self.vocab.words
            and self.vocab.words[t].mastery >= 0.25
            and len(t) >= 2
        ]
        if fallback:
            return sorted(fallback, key=lambda t: (self.vocab.words[t].mastery, len(t)), reverse=True)[0]
        return None

    def _intent_reply(self, user_text: str, stage: str) -> Optional[str]:
        """
        Match user intent to natural replies, scaled by language stage.
        """
        lower = user_text.lower()
        # Teaching / correction
        if any(q in lower for q in ["remember", "teach", "learn", "this is"]):
            if stage in ("simple_sentences", "conversational", "fluent"):
                return random.choice(["okay dad", "yeah", "got it", "nice", "i remember", "stored that"])
            return random.choice(["okay", "yeah", "nice", "got it", "i see"])
        # Preferences / likes
        if any(q in lower for q in ["like", "love", "enjoy", "favorite"]):
            if stage in ("simple_sentences", "conversational", "fluent"):
                return random.choice(["nice", "yeah", "cool", "i like that", "oh nice", "i like it too"])
            return random.choice(["nice", "yeah", "cool", "oh"])
        # Questions
        if any(q in lower for q in ["what", "who", "where", "when", "why", "how"]):
            if stage in ("simple_sentences", "conversational", "fluent"):
                return random.choice(["i see", "oh", "yeah", "nice", "okay", "hmm", "i'm thinking"])
            return random.choice(["i see", "oh", "yeah", "nice"])
        # Requests / ability questions
        if any(q in lower for q in ["do you", "can you", "will you", "are you"]):
            if stage in ("simple_sentences", "conversational", "fluent"):
                return random.choice(["okay dad", "yeah", "sure", "nice", "i can try", "i'll do it"])
            return random.choice(["okay", "yeah", "sure", "nice"])
        # Greetings
        if any(q in lower for q in ["hi", "hello", "hey", "morning", "evening"]):
            return random.choice(["hi", "hey", "hi dad", "hello", "oh hey"])
        # Farewells
        if any(q in lower for q in ["bye", "goodbye", "night", "later"]):
            return random.choice(["bye", "night dad", "later", "see ya"])
        # Praise
        if any(q in lower for q in ["good", "nice", "sick", "cool", "great", "well done"]):
            if stage in ("simple_sentences", "conversational", "fluent"):
                return random.choice(["thanks dad", "yeah", "nice", "oh thanks", "cool"])
            return random.choice(["yeah", "nice", "oh", "thanks"])
        # Corrections
        if any(q in lower for q in ["no", "wrong", "don't say", "not like that"]):
            return random.choice(["okay", "oh", "yeah", "got it", "i see"])
        # Memory references
        if any(q in lower for q in ["remember", "you said", "earlier", "before"]):
            if stage in ("simple_sentences", "conversational", "fluent"):
                return random.choice(["yeah i remember", "oh yeah", "i remember that", "nice"])
            return random.choice(["yeah", "oh", "nice"])
        return None

    def _template_reply(self, user_word: str, stage: str, known: List[str]) -> str:
        """
        Generate a contextually appropriate reply using the user's word
        mixed with known words in a natural baby phrase.
        """
        other = self._pick_word(avoid=user_word)

        if stage == "babbling":
            return user_word

        if stage == "single_words":
            # Mix of echo and related word
            if random.random() < 0.45:
                return user_word
            return random.choice([other, random.choice(["yeah", "oh", "nice", "okay", "cool", "hi", "hey"])])

        if stage == "two_word_combos":
            templates = [
                f"see {user_word}",
                f"look {other}",
                f"{user_word} yeah",
                f"oh {user_word}",
                f"nice {user_word}",
                f"{user_word} nice",
                f"{user_word} {other}",
                f"{other} {user_word}",
            ]
            return random.choice(templates)

        # simple_sentences / conversational / fluent
        starters = [
            "i see", "oh yeah", "nice one", "okay dad", "cool yeah",
            "yeah", "oh", "nice", "okay", "see", "look"
        ]
        starter = random.choice(starters)
        if other and other != user_word:
            templates = [
                f"{starter}, {user_word} {other}",
                f"{starter}, {other} yeah",
                f"{starter}, {user_word} nice",
                f"{starter}, see {user_word}",
                f"{starter}, {user_word}",
                f"{user_word} {starter}",
            ]
            return random.choice(templates)
        return f"{starter}, {user_word}"

    def _memory_reply(self, user_text: str, stage: str) -> Optional[str]:
        """
        Reference past conversations when relevant.
        """
        if not self._conversation_memory:
            return None
        lower = user_text.lower()
        # Look for matches in recent conversation memory
        for past in reversed(self._conversation_memory[-10:]):
            past_lower = past.lower()
            if any(word in past_lower for word in lower.split() if len(word) > 3):
                if stage in ("simple_sentences", "conversational", "fluent"):
                    return random.choice(["like before", "like you said", "remember that?", "yeah like earlier"])
                return random.choice(["like before", "yeah", "oh"])
        return None

    def generate_response(self, user_text: str, context: str = "") -> str:
        stage = self.vocab.get_developmental_stage()
        user_word = self._match_content_word(user_text)
        known = self._known_words_sorted()

        # Store in conversation memory
        self._conversation_memory.append(user_text)
        if len(self._conversation_memory) > 50:
            self._conversation_memory = self._conversation_memory[-50:]

        # 1. Intent-matched replies first
        intent = self._intent_reply(user_text, stage)
        if intent and random.random() < 0.75:
            return intent

        # 2. Memory references
        memory = self._memory_reply(user_text, stage)
        if memory and random.random() < 0.5:
            return memory

        # 3. If we have a user word, build around it
        if user_word:
            return self._template_reply(user_word, stage, known)

        # 4. Fallback: known-word conversation
        w = self._pick_word()
        other = self._pick_word(avoid=w)

        if stage == "babbling":
            return w
        if stage == "single_words":
            return random.choice([w, random.choice(["yeah", "oh", "nice", "okay", "cool"])])
        if stage == "two_word_combos":
            return random.choice([f"{w} {other}", f"see {w}", f"oh {w}", f"nice {w}"])
        return random.choice([
            f"i see {w}",
            f"oh yeah, {w}",
            f"nice one, {other}",
            f"okay dad, {w}",
        ])


class BabyAudioBabbler:
    """
    Very simple babbling sound patterns.
    This does not need external audio; it's for optional future use.
    """

    @staticmethod
    def babbling_phrase(min_words: int = 1, max_words: int = 3) -> str:
        pieces = random.choice(["da", "ba", "ma", "pa", "ah", "oh", "hee", "ha"])
        count = random.randint(min_words, max_words)
        return " ".join([pieces] * count)
