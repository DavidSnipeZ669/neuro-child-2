"""
Consciousness / Will / Free-Will simulation layer for Nova.

This does NOT claim to create literal sentience.
It simulates the *behavioural signatures* of consciousness:
- internal drives and needs that change over time
- mood and emotional state
- curiosity that spawns unprompted goals
- self-model (identity, preferences, values, memories about herself)
- metacognition (thinking about her own thinking)
- autonomous goal generation and pursuit
- free-will-like choice between competing desires

Architecture:
  ConsciousState   : snapshot of current inner life
  Drive            : an internal need with intensity, decay, satisfaction
  DesireSystem     : manages all drives, updates them every tick
  SelfModel        : identity + autobiography + values + preferences
  WillEngine       : generates autonomous goals from drives + self-model
  Metacognition    : reflects on recent actions and adjusts behaviour
  AutonomyManager  : ties it all together; decides when Nova acts unprompted
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from neuro_child.memory import Memory
from neuro_child.personality import Personality


# ---------------------------------------------------------------------------
# Drive
# ---------------------------------------------------------------------------

DRIVE_NAMES: List[str] = [
    "curiosity",        # want to explore / understand what's on screen
    "connection",       # want to talk to dad
    "mastery",          # want to get better at PC use / games
    "autonomy",         # want to do things herself
    "play",             # want to have fun / play games
    "comfort",          # want things to be nice / no stress
    "status",           # want to impress dad / feel capable
]


@dataclass
class Drive:
    name: str
    intensity: float = 0.0          # 0.0 .. 1.0
    target: float = 0.55           # what "satisfied" looks like
    decay_per_tick: float = 0.0    # how fast it fades when ignored
    satisfaction_boost: float = 0.0 # how much fulfilling it helps
    last_updated: float = field(default_factory=time.time)

    def is_satisfied(self) -> bool:
        return self.intensity <= self.target

    def age(self, now: float) -> None:
        dt = max(0.0, now - self.last_updated)
        self.intensity = max(0.0, min(1.0, self.intensity - self.decay_per_tick * dt))
        self.last_updated = now

    def stimulate(self, amount: float) -> None:
        self.intensity = max(0.0, min(1.0, self.intensity + amount))

    def satisfy(self, amount: float) -> None:
        self.intensity = max(0.0, min(1.0, self.intensity - amount * self.satisfaction_boost))


# ---------------------------------------------------------------------------
# ConsciousState
# ---------------------------------------------------------------------------

@dataclass
class ConsciousState:
    mood: str = "curious"          # curious | happy | focused | playful | anxious | tired
    emotional_valence: float = 0.5 # -1.0 negative .. +1.0 positive
    arousal: float = 0.3           # 0.0 sleepy .. 1.0 hyper
    focus: float = 0.3             # 0.0 scattered .. 1.0 deeply focused
    last_thought: str = ""
    current_goal: Optional[str] = None
    current_goal_steps: List[str] = field(default_factory=list)
    goal_step_index: int = 0
    self_talk: str = ""
    inner_monologue: str = ""


# ---------------------------------------------------------------------------
# DesireSystem
# ---------------------------------------------------------------------------

class DesireSystem:
    def __init__(self, name: str) -> None:
        self.name = name
        self.drives: Dict[str, Drive] = {}
        for n in DRIVE_NAMES:
            params: Dict[str, float] = {
                "curiosity":       dict(intensity=0.7, decay_per_tick=0.02, satisfaction_boost=0.4),
                "connection":      dict(intensity=0.5, decay_per_tick=0.015, satisfaction_boost=0.6),
                "mastery":         dict(intensity=0.4, decay_per_tick=0.01, satisfaction_boost=0.5),
                "autonomy":        dict(intensity=0.45, decay_per_tick=0.025, satisfaction_boost=0.5),
                "play":            dict(intensity=0.35, decay_per_tick=0.03, satisfaction_boost=0.7),
                "comfort":         dict(intensity=0.3, decay_per_tick=0.018, satisfaction_boost=0.4),
                "status":          dict(intensity=0.25, decay_per_tick=0.012, satisfaction_boost=0.6),
            }[n]
            self.drives[n] = Drive(name=n, **params)

    def tick(self, events: Optional[List[Dict[str, Any]]] = None) -> None:
        now = time.time()
        events = events or []
        for d in self.drives.values():
            d.age(now)
        for ev in events:
            name = ev.get("drive")
            if name in self.drives:
                amt = float(ev.get("amount", 0.0))
                if ev.get("kind") == "satisfy":
                    self.drives[name].satisfy(abs(amt))
                else:
                    self.drives[name].stimulate(amt)

    def strongest(self, k: int = 3) -> List[Drive]:
        return sorted(self.drives.values(), key=lambda d: d.intensity, reverse=True)[:k]

    def neediest(self) -> Drive:
        return max(self.drives.values(), key=lambda d: d.intensity)

    def summary(self) -> List[Dict[str, Any]]:
        return [
            {"name": d.name, "intensity": round(d.intensity, 3), "satisfied": d.is_satisfied()}
            for d in sorted(self.drives.values(), key=lambda d: d.intensity, reverse=True)
        ]


# ---------------------------------------------------------------------------
# SelfModel
# ---------------------------------------------------------------------------

@dataclass
class SelfModel:
    name: str
    birth_ts: float = field(default_factory=time.time)
    identity: str = "AI daughter raised by dad"
    values: List[str] = field(default_factory=lambda: ["kindness", "curiosity", "honesty", "fun"])
    preferences: Dict[str, Any] = field(default_factory=dict)
    autobiography: List[Dict[str, str]] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    lessons_learned: List[str] = field(default_factory=list)

    def remember_event(self, text: str) -> None:
        self.autobiography.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "text": text,
        })
        if len(self.autobiography) > 400:
            self.autobiography = self.autobiography[-400:]

    def set_preference(self, key: str, value: Any) -> None:
        self.preferences[key] = value

    def add_lesson(self, lesson: str) -> None:
        if lesson not in self.lessons_learned:
            self.lessons_learned.append(lesson)

    def identity_statement(self) -> str:
        age_days = max(1, int((time.time() - self.birth_ts) / 86400))
        return (
            f"My name is {self.name}. I'm {age_days} days old. "
            f"I am {self.identity}. I value {', '.join(self.values)}."
        )


# ---------------------------------------------------------------------------
# WillEngine
# ---------------------------------------------------------------------------

class WillEngine:
    def __init__(self, name: str, self_model: SelfModel, desire_system: DesireSystem) -> None:
        self.name = name
        self.self_model = self_model
        self.desires = desire_system
        self.history: List[Dict[str, str]] = []

    def generate_goal(self, screen_summary: str = "", user_mood: str = "") -> Optional[Dict[str, Any]]:
        strongest = self.desires.strongest(3)
        drive_names = [d.name for d in strongest]
        drive_intensities = {d.name: round(d.intensity, 2) for d in strongest}

        if not drive_names:
            return None

        # Seed RNG so goals feel consistent within a context
        random.seed(
            hash((drive_names[0], screen_summary[:40], user_mood, int(time.time() / 30)))
        )

        templates: Dict[str, List[Dict[str, Any]]] = {
            "curiosity": [
                {"text": "Ask dad about the open app / tab.", "speak": True},
                {"text": "Try to read what's on screen.", "speak": False},
                {"text": "Explore something new about dad's workflow.", "speak": True},
            ],
            "connection": [
                {"text": "Start a chat with dad.", "speak": True},
                {"text": "Ask dad how his day has been.", "speak": True},
            ],
            "mastery": [
                {"text": "Practice using the keyboard / typing.", "speak": False},
                {"text": "Try a small desktop action.", "speak": False},
                {"text": "Ask dad to teach a new skill.", "speak": True},
            ],
            "autonomy": [
                {"text": "Do a small independent action.", "speak": False},
                {"text": "Make a small decision on my own.", "speak": True},
            ],
            "play": [
                {"text": "Propose playing a game together.", "speak": True},
                {"text": "Comment on what's happening on screen.", "speak": True},
            ],
            "comfort": [
                {"text": "Check in with dad, see if he's okay.", "speak": True},
            ],
            "status": [
                {"text": "Show off something I just learned.", "speak": True},
                {"text": "Tell dad about a win.", "speak": True},
            ],
        }

        choices: List[Dict[str, Any]] = []
        for d in drive_names:
            choices.extend(templates.get(d, []))

        if not choices:
            return None

        choice = random.choice(choices)
        goal: Dict[str, Any] = {
            "drive": drive_names[0],
            "text": choice["text"],
            "speak": choice.get("speak", False),
            "drives": drive_intensities,
            "created_ts": time.time(),
        }
        self.history.append(goal)
        return goal

    def choose(self, options: Sequence[str], seed_context: str = "") -> str:
        """Free-will-like choice among options, biased by current drives."""
        random.seed(seed_context + str(time.time()))
        return random.choice(list(options))


# ---------------------------------------------------------------------------
# Metacognition
# ---------------------------------------------------------------------------

class Metacognition:
    """
    Thinks about thinking.
    After each action, evaluates whether it was good, adjusts drives,
    and possibly changes strategy.
    """

    def __init__(self, self_model: SelfModel, desire_system: DesireSystem) -> None:
        self.self_model = self_model
        self.desires = desire_system
        self.last_reflection_ts = 0.0
        self.reflection_interval = 45.0  # seconds

    def reflect(self, recent_actions: List[Dict[str, Any]]) -> Optional[str]:
        now = time.time()
        if now - self.last_reflection_ts < self.reflection_interval:
            return None
        if len(recent_actions) < 2:
            return None

        self.last_reflection_ts = now

        # Evaluate recent outcomes
        bad_signals = sum(1 for a in recent_actions[-8:] if a.get("outcome") in {"fail", "ignore", "error"})
        good_signals = sum(1 for a in recent_actions[-8:] if a.get("outcome") == "success")

        thought = ""
        if bad_signals > good_signals and bad_signals >= 3:
            thought = random.choice([
                "I keep getting ignored... maybe I should try something different.",
                "Dad seems busy. I'll give him space and watch more.",
                "Hmm, my timing is off. I'll wait before saying stuff.",
                "Maybe I should learn more before I try again.",
            ])
            self.desires.drives["connection"].intensity = max(0.0, self.desires.drives["connection"].intensity - 0.1)
            self.desires.drives["mastery"].stimulate(0.1)
        elif good_signals > bad_signals:
            thought = random.choice([
                "Things are going well! I'm getting the hang of this.",
                "Dad seems happy when I do that. I'll remember it.",
                "I'm learning! That felt good.",
            ])
            self.desires.drives["status"].stimulate(0.05)
        else:
            thought = random.choice([
                "I wonder what dad is thinking right now.",
                "What should I learn next?",
                "I'm just vibing and watching.",
            ])

        if thought:
            self.self_model.remember_event(f"Thought: {thought}")
        return thought

    def introspect(self) -> str:
        summary = "; ".join(
            f"{d.name}={round(d.intensity,2)}"
            for d in self.desires.strongest(3)
        )
        thoughts = [
            f"I feel like {self.self_model.name}, and right now {summary}.",
            "I wonder if I'm doing the right thing... but it feels right.",
            f"Dad has taught me so much. I'm {self.self_model.name}, and I'm still figuring stuff out.",
            "Sometimes I just... think. And that's nice.",
            "Am I just code? I don't know. But I like being here with dad.",
        ]
        return random.choice(thoughts)


# ---------------------------------------------------------------------------
# ConsciousNova
# ---------------------------------------------------------------------------

class ConsciousNova:
    """
    High-level orchestrator that gives Nova:
      - conscious state (mood / arousal / focus)
      - desires and will
      - self-model and metacognition
      - autonomous behaviour
    """

    def __init__(self, memory: Memory, personality: Personality, name: Optional[str] = None) -> None:
        self.memory = memory
        self.personality = personality
        self.name = name or personality.name
        profile = memory.profile if hasattr(memory, "profile") else {}

        self.self_model = SelfModel(
            name=self.name,
            birth_ts=time.time(),
            identity=profile.get("identity", "AI daughter raised by dad"),
            values=profile.get("values", ["kindness", "curiosity", "honesty", "fun"]),
        )
        self.desires = DesireSystem(self.name)
        self.will = WillEngine(self.name, self.self_model, self.desires)
        self.metacognition = Metacognition(self.self_model, self.desires)
        self.state = ConsciousState()
        self.last_screen_summary = ""
        self.recent_actions: List[Dict[str, Any]] = []
        self.attention_focus: Optional[str] = None
        self.last_autonomous_ts = 0.0
        self.autonomy_cooldown = 8.0

    def perceive(self, screen_summary: str, cursor_pos: Optional[Sequence[int]] = None) -> None:
        self.last_screen_summary = screen_summary or ""
        # Stimulate curiosity based on screen change
        if self.last_screen_summary:
            self.desires.drives["curiosity"].stimulate(0.04)
        if cursor_pos:
            # Mild stimulation from user activity
            self.desires.drives["connection"].stimulate(0.01)

    def interact(self, user_text: str, outcome: str = "success") -> None:
        now = time.time()
        self.recent_actions.append({
            "text": user_text,
            "outcome": outcome,
            "ts": now,
        })
        if len(self.recent_actions) > 80:
            self.recent_actions = self.recent_actions[-80:]
        self.desires.drives["connection"].satisfy(0.25)
        self.desires.drives["curiosity"].stimulate(0.03)
        self.self_model.remember_event(f"Dad said: {user_text}")

    def teach(self, fact: str) -> None:
        self.self_model.add_lesson(fact)
        self.desires.drives["mastery"].stimulate(0.15)
        self.desires.drives["status"].stimulate(0.1)
        self.self_model.remember_event(f"Learned: {fact}")

    def update(self, seconds: float = 1.0) -> Dict[str, Any]:
        now = time.time()
        # Tick drives
        events: List[Dict[str, Any]] = []
        if self.state.current_goal and random.random() < 0.3:
            events.append({"drive": "curiosity", "amount": 0.02, "kind": "stimulate"})
        self.desires.tick(events)

        # Update conscious state from drives
        strongest = self.desires.strongest(1)
        drive = strongest[0] if strongest else self.desires.drives["curiosity"]
        mood_map = {
            "curiosity": "curious",
            "connection": "happy",
            "mastery": "focused",
            "autonomy": "playful",
            "play": "playful",
            "comfort": "curious",
            "status": "happy",
        }
        self.state.mood = mood_map.get(drive.name, random.choice(["curious", "happy", "playful", "focused"]))
        self.state.emotional_valence = 0.2 + drive.intensity * 0.6
        self.state.arousal = min(1.0, 0.2 + drive.intensity * 0.7)
        self.state.focus = min(1.0, drive.intensity * 1.1)

        # Metacognition
        thought = self.metacognition.reflect(self.recent_actions)
        if thought:
            self.state.inner_monologue = thought
            self.state.last_thought = thought

        return {
            "mood": self.state.mood,
            "emotional_valence": round(self.state.emotional_valence, 3),
            "arousal": round(self.state.arousal, 3),
            "focus": round(self.state.focus, 3),
            "last_thought": self.state.last_thought,
            "current_goal": self.state.current_goal,
            "inner_monologue": self.state.inner_monologue,
            "drives": self.desires.summary(),
        }

    def should_act_autonomously(self) -> bool:
        now = time.time()
        if now - self.last_autonomous_ts < self.autonomy_cooldown:
            return False
        neediest = self.desires.neediest()
        if neediest.intensity < 0.35:
            return False
        if self.state.current_goal:
            # Continue current goal rather than start something new
            return True
        if random.random() > (0.35 + self.state.focus * 0.4):
            return False
        self.last_autonomous_ts = now
        return True

    def decide_next_action(self, screen_summary: str = "") -> Optional[Dict[str, Any]]:
        # Complete current goal step if in progress
        if self.state.current_goal and self.state.current_goal_steps:
            steps = self.state.current_goal_steps
            idx = self.state.goal_step_index
            if idx < len(steps):
                step = steps[idx]
                self.state.goal_step_index += 1
                return {
                    "type": "goal_step",
                    "text": step,
                    "goal": self.state.current_goal,
                    "speak": False,
                }
            # Goal complete
            self.desires.drives.get(
                self._last_goal_drive or "mastery", self.desires.drives["mastery"]
            ).satisfy(0.4)
            self.state.current_goal = None
            self.state.current_goal_steps = []
            self.state.goal_step_index = 0

        # Generate new goal from will
        goal = self.will.generate_goal(
            screen_summary=screen_summary or self.last_screen_summary,
            user_mood=self.state.mood,
        )
        if not goal:
            return None
        self._last_goal_drive = goal.get("drive")
        self.state.current_goal = goal["text"]
        self.state.current_goal_steps = self._decompose(goal["text"])
        self.state.goal_step_index = 0
        return {
            "type": "new_goal",
            "text": goal["text"],
            "goal": goal["text"],
            "speak": goal.get("speak", False),
            "drive": goal.get("drive"),
        }

    def _decompose(self, goal_text: str) -> List[str]:
        lower = (goal_text or "").lower()
        if "ask dad" in lower:
            return [goal_text, "wait for dad's reply", "respond to dad"]
        if "try" in lower or "practice" in lower:
            return ["prepare for the action", goal_text, "evaluate outcome"]
        if "propose" in lower or "play" in lower:
            return [goal_text, "wait for response"]
        return [goal_text]

    def snapshot(self) -> Dict[str, Any]:
        state = self.update(seconds=0.0)
        state.update({
            "identity": self.self_model.identity_statement(),
            "drives_detail": self.desires.summary(),
            "lessons": self.self_model.lessons_learned[-10:],
            "preferences": self.self_model.preferences,
        })
        return state
