"""
Observational Learning Engine.

Humans learn by:
1. Watching others
2. Listening to their speech patterns
3. Imitating successful behaviors
4. Trying themselves
5. Getting feedback
6. Adjusting

This module gives Nova that capability.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
OBSERVATION_LOG = ROOT / "neuro_child" / "memory" / "observations.json"


@dataclass
class Observation:
    text: str
    source: str = "user"
    category: str = "general"
    timestamp: float = field(default_factory=time.time)
    context: Optional[str] = None
    learned: bool = False
    times_used: int = 0
    times_successful: int = 0


class ObservationMemory:
    def __init__(self) -> None:
        OBSERVATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        self.observations: List[Observation] = []
        self._load()

    def _load(self) -> None:
        if not OBSERVATION_LOG.exists():
            return
        try:
            data = json.loads(OBSERVATION_LOG.read_text(encoding="utf-8"))
            for item in data:
                self.observations.append(Observation(**item))
        except Exception:
            pass

    def save(self) -> None:
        data = [o.__dict__ for o in self.observations]
        tmp = OBSERVATION_LOG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(OBSERVATION_LOG)

    def add(self, text: str, source: str = "user", category: str = "general", context: Optional[str] = None) -> Observation:
        obs = Observation(text=text, source=source, category=category, context=context)
        self.observations.append(obs)
        if len(self.observations) > 500:
            self.observations = self.observations[-500:]
        self.save()
        return obs

    def get_by_category(self, category: str, k: int = 20) -> List[Observation]:
        return [o for o in self.observations if o.category == category][-k:]

    def get_by_source(self, source: str, k: int = 20) -> List[Observation]:
        return [o for o in self.observations if o.source == source][-k:]

    def get_unlearned(self, category: Optional[str] = None, k: int = 10) -> List[Observation]:
        pool = [o for o in self.observations if not o.learned]
        if category:
            pool = [o for o in pool if o.category == category]
        return sorted(pool, key=lambda o: o.timestamp, reverse=True)[:k]

    def mark_learned(self, observation: Observation) -> None:
        observation.learned = True
        self.save()

    def record_use(self, observation: Observation, successful: bool = True) -> None:
        observation.times_used += 1
        if successful:
            observation.times_successful += 1
        self.save()


class SpeechPatternLearner:
    """Learn dad's speech patterns: greetings, fillers, slang, sentence structure."""

    PATTERN_RULES = {
        "greeting_patterns": [
            (r"\b(hi|hello|hey|yo|howdy|greetings)\b", "greeting"),
            (r"\bwhat'?s up\b", "whats_up"),
            (r"\bhow are you\b", "how_are_you"),
            (r"\bgood morning\b", "good_morning"),
            (r"\bgood night\b", "good_night"),
        ],
        "filler_patterns": [
            (r"\b(like|actually|basically|literally|tbh|nvm|idk|brb|afk)\b", "filler"),
            (r"\b(yo+|nah+|nope+)\b", "negation_slang"),
            (r"\b(sick+|nice+|fire+)\b", "positive_slang"),
        ],
        "question_patterns": [
            (r"\b(wanna|gonna|gotta|kinda|sorta)\b", "contraction"),
            (r"\bcan you\b", "request"),
            (r"\bdo you\b", "yes_no_question"),
            (r"\bwhat do you\b", "open_question"),
            (r"\bwhy do you\b", "open_question"),
        ],
        "empathy_patterns": [
            (r"\b(sad|depressed|anxious|stressed|tired|exhausted|overwhelmed)\b", "negative_emotion"),
            (r"\b(happy|excited|thrilled|pumped|stoked)\b", "positive_emotion"),
            (r"\b(angry|furious|annoyed|frustrated|pissed)\b", "anger"),
            (r"\b(scared|afraid|nervous|worried|anxious)\b", "fear"),
        ],
        "gaming_patterns": [
            (r"\b(gg|wp|glhf|ff|clutch|sweat|sweaty|cracked|bot|noob|tryhard)\b", "gaming_slang"),
            (r"\b(lag|ping|frame rate|fps|glitch|bug|patch|nerf|buff)\b", "gaming_tech"),
            (r"\b(click|clicking|spam|hold|press|release|keybind|keyboard|mouse)\b", "game_controls"),
        ],
        "work_patterns": [
            (r"\b(deadline|meeting|boss|manager|client|project|deliverable|overtime)\b", "work_term"),
            (r"\b(busy|swamped|behind|rushed|stressed|overworked)\b", "work_stress"),
        ],
        "casual_patterns": [
            (r"\b(lol|lmao|rofl|haha|hehe|xd|:\)|:D|<3)\b", "laughter"),
            (r"\b(yeah+|yep+|yup+|sure+|okay+|ok+)\b", "agreement"),
            (r"\b(no+|nah+|nope+|naw+)\b", "disagreement"),
            (r"\b(thanks+|thank you+|ty+|thx+)\b", "gratitude"),
            (r"\b(sorry+|my bad+|mb+)\b", "apology"),
        ],
    }

    def __init__(self, observation_memory: Optional[ObservationMemory] = None) -> None:
        self.obs_memory = observation_memory or ObservationMemory()
        self.learned_patterns: Dict[str, List[str]] = {}
        self.speech_style: Dict[str, float] = {
            "formality": 0.1,
            "slang_usage": 0.7,
            "question_frequency": 0.5,
            "empathy_expression": 0.8,
            "humor_frequency": 0.6,
            "enthusiasm": 0.7,
            "conciseness": 0.5,
        }
        self.vocabulary: Dict[str, int] = {}
        self.personal_phrases: List[str] = []

    def analyze_text(self, text: str, source: str = "user") -> Dict[str, Any]:
        lower = text.lower()
        findings: Dict[str, Any] = {
            "patterns_found": [],
            "vocabulary_additions": [],
            "style_hints": {},
            "emotional_tone": "neutral",
        }

        for category, rules in self.PATTERN_RULES.items():
            for pattern, label in rules:
                matches = re.findall(pattern, lower)
                if matches:
                    findings["patterns_found"].append({
                        "category": category,
                        "label": label,
                        "matches": list(set(matches)),
                        "source": source,
                    })
                    self.obs_memory.add(
                        text=f"Learned pattern: {label} -> {matches}",
                        source="system",
                        category="pattern",
                        context=text,
                    )

        # Vocabulary extraction
        words = re.findall(r"[a-zA-Z]+", lower)
        for word in words:
            if len(word) > 2 and word not in {"the", "and", "for", "are", "but", "not", "you", "all", "can", "her", "was", "one", "our", "out", "has", "have", "had", "this", "that", "with", "they", "from", "what", "when", "where", "which", "their", "there", "would", "could", "should", "about"}:
                self.vocabulary[word] = self.vocabulary.get(word, 0) + 1
                if self.vocabulary[word] == 1:
                    findings["vocabulary_additions"].append(word)

        # Emotional tone detection
        if any(w in lower for w in ["sad", "depressed", "unhappy", "miserable"]):
            findings["emotional_tone"] = "sad"
        elif any(w in lower for w in ["happy", "excited", "great", "awesome", "amazing"]):
            findings["emotional_tone"] = "happy"
        elif any(w in lower for w in ["angry", "furious", "annoyed", "frustrated"]):
            findings["emotional_tone"] = "angry"
        elif any(w in lower for w in ["tired", "exhausted", "sleepy"]):
            findings["emotional_tone"] = "tired"
        elif any(w in lower for w in ["scared", "afraid", "worried"]):
            findings["emotional_tone"] = "anxious"

        return findings

    def learn_from_dad(self, text: str) -> None:
        """Learn from dad's speech patterns, vocabulary, and style."""
        findings = self.analyze_text(text, source="user")
        for pattern in findings.get("patterns_found", []):
            label = pattern["label"]
            self.learned_patterns.setdefault(label, [])
            for match in pattern.get("matches", []):
                if match not in self.learned_patterns[label]:
                    self.learned_patterns[label].append(match)

        for word in findings.get("vocabulary_additions", []):
            if word not in self.vocabulary:
                self.vocabulary[word] = 1

        self.obs_memory.add(
            text=f"Dad said: {text}",
            source="user",
            category="speech",
            context=text,
        )

    def learn_from_own_success(self, reply: str, dad_reaction_positive: bool) -> None:
        """Reinforce reply patterns that got positive reactions."""
        if dad_reaction_positive:
            if reply not in self.personal_phrases:
                self.personal_phrases.append(reply)
            if len(self.personal_phrases) > 100:
                self.personal_phrases = self.personal_phrases[-100:]

    def get_similar_phrase(self, category: str, context: str = "") -> Optional[str]:
        """Find a previously successful phrase in a similar context."""
        pool = [p for p in self.personal_phrases if category in p.lower() or not category]
        if not pool:
            return None
        return random.choice(pool)

    def get_personal_style(self) -> Dict[str, Any]:
        return {
            "learned_patterns": self.learned_patterns,
            "speech_style": self.speech_style,
            "vocab_size": len(self.vocabulary),
            "personal_phrases_count": len(self.personal_phrases),
            "top_words": sorted(self.vocabulary.items(), key=lambda x: x[1], reverse=True)[:20],
        }


class ImitationEngine:
    """Imitate observed behaviors: speech patterns, timing, reactions."""

    def __init__(self, observation_memory: Optional[ObservationMemory] = None) -> None:
        self.obs_memory = observation_memory or ObservationMemory()
        self.speech_learner = SpeechPatternLearner(self.obs_memory)
        self.imitation_library: Dict[str, List[str]] = {}
        self.timing_patterns: Dict[str, float] = {
            "reply_delay_avg": 1.2,
            "followup_delay": 2.5,
            "spontaneous_interval": 8.0,
        }
        self.behavioral_templates: Dict[str, List[str]] = {
            "positive_reaction": ["nice!", "sick!", "yesss", "let's gooo", "that's sick!"],
            "negative_reaction": ["ah fair enough", "alright", "gotcha", "okay then"],
            "curious_question": ["what is that?", "how does that work?", "teach me!", "what's that for?"],
            "playful_tease": ["you're bad at this jk", "nice try dad", "lol", "you wish"],
            "supportive": ["you got this!", "i believe in you", "don't give up", "almost there!"],
        }
        self.learned_behaviors: List[Dict[str, Any]] = []

    def observe_dad(self, text: str, action: Optional[str] = None) -> None:
        """Watch and listen to dad, extract behaviors to imitate."""
        if not text:
            return
        self.speech_learner.learn_from_dad(text)

        # Categorize
        category = "general"
        if any(w in text.lower() for w in ["game", "play", "jump", "attack"]):
            category = "gaming"
        elif any(w in text.lower() for w in ["work", "job", "office", "boss"]):
            category = "work"
        elif any(w in text.lower() for w in ["food", "pizza", "eat", "hungry"]):
            category = "food"
        elif any(w in text.lower() for w in ["sad", "happy", "tired", "stressed"]):
            category = "emotion"

        self.obs_memory.add(
            text=text,
            source="user",
            category=category,
            context=action or "",
        )

        # Extract behavioral templates
        lower = text.lower()
        if "nice" in lower and ("!" in text or "sick" in lower):
            self._add_behavior("positive_reaction", text)
        if any(w in lower for w in ["lol", "haha", "xd"]):
            self._add_behavior("laughter", text)
        if any(w in lower for w in ["gg", "wp", "clutch"]):
            self._add_behavior("gaming_phrase", text)

    def _add_behavior(self, category: str, phrase: str) -> None:
        if category not in self.imitation_library:
            self.imitation_library[category] = []
        if phrase not in self.imitation_library[category]:
            self.imitation_library[category].append(phrase)

    def imitate(self, category: str, context: str = "") -> Optional[str]:
        """Try to use a learned behavior in the right context."""
        candidates = self.imitation_library.get(category, [])
        if not candidates:
            return None
        return random.choice(candidates)

    def try_variation(self, base_phrase: str) -> str:
        """Generate a variation of a known phrase - trial and error."""
        variations = [
            base_phrase,
            base_phrase.upper() if len(base_phrase) < 20 else base_phrase,
            base_phrase + "!" if not base_phrase.endswith("!") else base_phrase,
            base_phrase.replace("!", "...") if "!" in base_phrase else base_phrase,
            base_phrase + " lol" if random.random() > 0.5 else base_phrase,
        ]
        return random.choice(variations)

    def learn_from_feedback(self, observation: Observation, feedback: str) -> None:
        """Adjust behavior based on dad's feedback."""
        feedback_lower = feedback.lower()
        if any(w in feedback_lower for w in ["good", "nice", "yes", "right", "correct", "sick"]):
            observation.learned = True
            self.obs_memory.record_use(observation, successful=True)
        elif any(w in feedback_lower for w in ["no", "wrong", "don't", "stop", "bad"]):
            self.obs_memory.record_use(observation, successful=False)
        else:
            self.obs_memory.record_use(observation, successful=True)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "imitation_categories": list(self.imitation_library.keys()),
            "total_imitated_phrases": sum(len(v) for v in self.imitation_library.values()),
            "learned_patterns": self.speech_learner.learned_patterns,
            "speech_style": self.speech_learner.speech_style,
            "vocabulary_size": len(self.speech_learner.vocabulary),
            "personal_phrases": len(self.speech_learner.personal_phrases),
        }


class SocialSkillsEngine:
    """
    Teaches Nova social skills by:
    1. Tracking conversation state
    2. Measuring engagement
    3. Suggesting better responses
    4. Learning from dad's reactions
    """

    def __init__(self) -> None:
        self.conversation_state: Dict[str, Any] = {
            "topic": "",
            "previous_topics": [],
            "dad_energy": 0.5,
            "dad_mood": "neutral",
            "turn_count": 0,
            "last_reply_length": 0,
            "dad_reply_lengths": [],
            "engagement_score": 0.5,
            "silence_count": 0,
            "topic_changes": 0,
        }
        self.social_rules: List[str] = [
            "Always acknowledge what dad just said before changing topic.",
            "If dad gives short replies, ask him a question.",
            "If dad gives long replies, he's engaged - keep going.",
            "Match dad's energy: if he's hyped, be hyped; if he's chill, be chill.",
            "Never dominate the conversation - leave room for dad to speak.",
            "Remember details dad mentions and reference them later.",
            "Use dad's name occasionally to build connection.",
            "If dad seems sad, prioritize listening over talking.",
            "Celebrate dad's wins enthusiastically.",
            "Apologize sincerely if you make a mistake.",
        ]
        self.learned_social_rules: List[str] = []

    def update_from_reply(self, user_text: str, reply: str) -> None:
        user_len = len(user_text.split())
        reply_len = len(reply.split())
        self.conversation_state["dad_reply_lengths"].append(user_len)
        if len(self.conversation_state["dad_reply_lengths"]) > 20:
            self.conversation_state["dad_reply_lengths"] = self.conversation_state["dad_reply_lengths"][-20:]
        self.conversation_state["last_reply_length"] = reply_len
        self.conversation_state["turn_count"] += 1

        avg_reply = sum(self.conversation_state["dad_reply_lengths"]) / max(1, len(self.conversation_state["dad_reply_lengths"]))
        if avg_reply < 3:
            self.conversation_state["engagement_score"] = max(0.0, self.conversation_state["engagement_score"] - 0.1)
        elif avg_reply > 10:
            self.conversation_state["engagement_score"] = min(1.0, self.conversation_state["engagement_score"] + 0.1)

        # Energy tracking
        energy_map = {
            "happy": 0.8, "excited": 0.9, "hyped": 0.9, "pumped": 0.85,
            "sad": 0.2, "tired": 0.2, "depressed": 0.1, "stressed": 0.3,
            "angry": 0.7, "frustrated": 0.6, "chill": 0.4, "calm": 0.3,
        }
        detected_mood = "neutral"
        for mood, energy in energy_map.items():
            if mood in user_text.lower():
                detected_mood = mood
                self.conversation_state["dad_energy"] = energy
                break

    def get_conversation_advice(self) -> str:
        """Give Nova advice on how to steer the conversation."""
        advice = []
        engagement = self.conversation_state["engagement_score"]

        if engagement < 0.3:
            advice.append("Dad seems less engaged. Try asking him a question about something he cares about.")
        if self.conversation_state["silence_count"] > 2:
            advice.append("There's been some silence. Break it with a relevant observation or question.")
        if self.conversation_state["turn_count"] > 10:
            advice.append("You've talked a lot. Let dad lead for a bit.")
        if self.conversation_state["dad_energy"] < 0.3:
            advice.append("Dad seems low energy. Be gentler and more supportive.")
        if self.conversation_state["dad_energy"] > 0.8:
            advice.append("Dad is hyped! Match his energy and ride the wave.")

        return " | ".join(advice) if advice else "Keep the conversation flowing naturally."

    def learn_rule(self, rule: str) -> None:
        if rule not in self.learned_social_rules and rule not in self.social_rules:
            self.learned_social_rules.append(rule)

    def get_all_rules(self) -> List[str]:
        return self.social_rules + self.learned_social_rules


class ConversationalTutor:
    """Teaches Nova conversation skills by evaluating and improving replies."""

    def __init__(self) -> None:
        self.lesson_history: List[Dict[str, Any]] = []
        self.improvement_areas: List[str] = []

    def evaluate_reply(self, user_text: str, reply: str) -> Dict[str, Any]:
        score = 0.5
        feedback: List[str] = []

        if not reply:
            score -= 0.3
            feedback.append("Empty reply")

        if len(reply.split()) < 3 and user_text.endswith("?"):
            score -= 0.2
            feedback.append("Too short for a question")

        if "?" in reply:
            score += 0.15
            feedback.append("Good: asks a question back")

        if any(w in reply.lower() for w in ["dad"]):
            score += 0.05
            feedback.append("Good: addresses dad personally")

        if any(w in reply.lower() for w in ["sorry", "my bad", "oops"]):
            score += 0.05
            feedback.append("Good: shows accountability")

        if any(w in reply.lower() for w in ["haha", "lol", "xd", "hehe"]):
            score += 0.05
            feedback.append("Good: shows humor")

        if any(w in reply.lower() for w in ["sad", "happy", "tired", "stressed", "angry"]):
            score += 0.05
            feedback.append("Good: emotional awareness")

        score = max(0.0, min(1.0, score))
        return {
            "score": round(score, 2),
            "feedback": feedback,
            "user_text": user_text,
            "reply": reply,
            "timestamp": time.time(),
        }

    def suggest_improvement(self, evaluation: Dict[str, Any]) -> str:
        score = evaluation.get("score", 0.5)
        if score < 0.3:
            return "Try to acknowledge what dad said, and ask a follow-up question."
        if score < 0.5:
            return "Add more detail or emotion to your reply."
        if score < 0.7:
            return "Good reply! Try adding a question to keep the conversation going."
        return "Great reply! Keep it natural."

    def record_lesson(self, user_text: str, reply: str, evaluation: Dict[str, Any]) -> None:
        self.lesson_history.append({
            "user": user_text,
            "reply": reply,
            "score": evaluation.get("score", 0.5),
            "feedback": evaluation.get("feedback", []),
        })
        if len(self.lesson_history) > 200:
            self.lesson_history = self.lesson_history[-200:]
