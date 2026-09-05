"""
Autonomous evolution engine: Nova evolves herself without dad prompting.

She:
- Tracks what response strategies work/fail
- Mutates her own reply templates
- Rewrites her own code/config
- Self-improves based on fitness
- Evolves personality, learning strategies, and behavior
"""
from __future__ import annotations

import copy
import json
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from neuro_child.language_acquisition import BabyResponseGenerator
from neuro_child.memory import Memory


EVOLUTION_LOG = Path(__file__).resolve().parent / "memory" / "evolution_log.json"
STRATEGY_POOL = Path(__file__).resolve().parent / "memory" / "strategy_pool.json"


@dataclass
class Strategy:
    """
    A response strategy Nova can use.
    She mutates, combines, and selects these over time.
    """
    id: str
    name: str
    strategy_type: str  # "reply_template", "learning_mode", "personality_trait"
    payload: Dict[str, Any] = field(default_factory=dict)
    fitness: float = 0.0
    uses: int = 0
    successes: int = 0
    failures: int = 0
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    generation: int = 0
    parent_ids: List[str] = field(default_factory=list)


class EvolutionEngine:
    """
    Nova's self-evolution system.

    She evaluates her own strategies, keeps what works, discards what doesn't,
    and mutates successful strategies to create improved variants.
    """

    def __init__(self, vocab: Any, memory: Memory, reply_generator: BabyResponseGenerator) -> None:
        self.vocab = vocab
        self.memory = memory
        self.reply_generator = reply_generator
        self.strategies: Dict[str, Strategy] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_evolution_ts = 0.0
        self._evolution_cooldown = 60.0  # evolve every minute
        self._load_strategies()

    def _load_strategies(self) -> None:
        try:
            if STRATEGY_POOL.exists():
                # Guard against huge/corrupt strategy files that block startup.
                size = STRATEGY_POOL.stat().st_size
                if size > 2 * 1024 * 1024:
                    backup = STRATEGY_POOL.with_suffix(".json.bak")
                    try:
                        STRATEGY_POOL.rename(backup)
                    except Exception:
                        STRATEGY_POOL.write_text("[]", encoding="utf-8")
                    self.strategies = {}
                else:
                    limit = min(size, 1024 * 1024)
                    raw = STRATEGY_POOL.read_bytes()[:limit]
                    data = json.loads(raw.decode("utf-8", "ignore")) if raw else []
                    if not isinstance(data, list):
                        data = []
                    for item in data:
                        if isinstance(item, dict):
                            s = Strategy(**item)
                            self.strategies[s.id] = s
        except Exception:
            self.strategies = {}
        if not self.strategies:
            self._seed_initial_strategies()

    def _seed_initial_strategies(self) -> None:
        seed_strategies = [
            Strategy(id="reply_template_v1", name="Basic templates", strategy_type="reply_template",
                     payload={"templates": ["i see {w}", "oh {w}", "nice {w}", "see {w}"]}, fitness=0.5),
            Strategy(id="reply_template_v2", name="Advanced templates", strategy_type="reply_template",
                     payload={"templates": ["i see {w} yeah", "oh nice {w}", "cool {w}", "see {w} nice"]}, fitness=0.3),
            Strategy(id="reply_template_v3", name="Simple templates", strategy_type="reply_template",
                     payload={"templates": ["{w}", "yeah", "oh", "nice"]}, fitness=0.4),
            Strategy(id="learning_mode_passive", name="Passive learning", strategy_type="learning_mode",
                     payload={"mode": "passive", "rate": 1.0}, fitness=0.6),
            Strategy(id="learning_mode_active", name="Active learning", strategy_type="learning_mode",
                     payload={"mode": "active", "rate": 2.0}, fitness=0.4),
            Strategy(id="personality_friendly", name="Friendly", strategy_type="personality_trait",
                     payload={"tone": "friendly", "greetings": ["hi dad", "hey", "oh hey"]}, fitness=0.7),
            Strategy(id="personality_curious", name="Curious", strategy_type="personality_trait",
                     payload={"tone": "curious", "greetings": ["what's that?", "oh cool", "nice"]}, fitness=0.5),
        ]
        for s in seed_strategies:
            self.strategies[s.id] = s
        self._save_strategies()

    def _save_strategies(self) -> None:
        try:
            data = []
            for s in self.strategies.values():
                data.append({
                    "id": s.id,
                    "name": s.name,
                    "strategy_type": s.strategy_type,
                    "payload": s.payload,
                    "fitness": s.fitness,
                    "uses": s.uses,
                    "successes": s.successes,
                    "failures": s.failures,
                    "created_at": s.created_at,
                    "last_used": s.last_used,
                    "generation": s.generation,
                    "parent_ids": s.parent_ids,
                })
            STRATEGY_POOL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._evolution_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _evolution_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                if now - self._last_evolution_ts >= self._evolution_cooldown:
                    self._last_evolution_ts = now
                    self._evolve()
                time.sleep(10)
            except Exception:
                time.sleep(15)

    def record_outcome(self, strategy_id: str, success: bool) -> None:
        with self._lock:
            s = self.strategies.get(strategy_id)
            if not s:
                return
            s.uses += 1
            s.last_used = time.time()
            if success:
                s.successes += 1
                s.fitness = min(1.0, s.fitness + 0.1)
            else:
                s.failures += 1
                s.fitness = max(0.0, s.fitness - 0.05)
            self._save_strategies()

    def _evolve(self) -> None:
        with self._lock:
            # 1. Cull weak strategies
            to_remove = [sid for sid, s in self.strategies.items() if s.fitness < 0.1 and s.uses > 10]
            for sid in to_remove:
                del self.strategies[sid]

            # 2. Select top performers
            ranked = sorted(self.strategies.values(), key=lambda s: s.fitness, reverse=True)
            top = ranked[:max(2, len(ranked) // 3)]
            if len(top) < 2:
                return

            # 3. Mutate: create variants of successful strategies
            new_strategies = []
            for parent in top:
                if random.random() < 0.6:  # 60% chance to mutate each top strategy
                    child = self._mutate_strategy(parent)
                    new_strategies.append(child)

            # 4. Occasionally crossover two parents
            if len(top) >= 2 and random.random() < 0.4:
                p1, p2 = random.sample(top, 2)
                child = self._crossover_strategies(p1, p2)
                new_strategies.append(child)

            for s in new_strategies:
                if s.id not in self.strategies:
                    self.strategies[s.id] = s

            self._save_strategies()
            self._log_evolution(f"evolved:{len(new_strategies)} new strategies")

    def _mutate_strategy(self, parent: Strategy) -> Strategy:
        child_id = f"{parent.id}_g{parent.generation + 1}_{random.randint(1000,9999)}"
        child = copy.deepcopy(parent)
        child.id = child_id
        child.generation = parent.generation + 1
        child.parent_ids = [parent.id]
        child.fitness = 0.5  # start neutral
        child.uses = 0
        child.successes = 0
        child.failures = 0

        if parent.strategy_type == "reply_template":
            templates = child.payload.get("templates", [])
            if templates and random.random() < 0.7:
                # Mutate one template
                idx = random.randrange(len(templates))
                t = templates[idx]
                # Add word substitution slots
                if "{w}" not in t and random.random() < 0.6:
                    templates[idx] = f"{t} {{w}}"
                elif random.random() < 0.4:
                    templates[idx] = f"{t} yeah"
                # Occasionally add a new template
                if random.random() < 0.3:
                    templates.append(f"oh {{w}}")
                child.payload["templates"] = templates[:8]

        elif parent.strategy_type == "learning_mode":
            rate = child.payload.get("rate", 1.0)
            child.payload["rate"] = max(0.5, min(5.0, rate + random.uniform(-0.3, 0.3)))

        elif parent.strategy_type == "personality_trait":
            tone = child.payload.get("tone", parent.payload.get("tone", "friendly"))
            child.payload["tone"] = random.choice([tone, "curious", "playful", "friendly", "thoughtful"])

        return child

    def _crossover_strategies(self, p1: Strategy, p2: Strategy) -> Strategy:
        if p1.strategy_type != p2.strategy_type:
            return self._mutate_strategy(p1)  # fallback to mutation
        child_id = f"crossover_{p1.id}_{p2.id}_{random.randint(1000,9999)}"
        child = Strategy(
            id=child_id,
            name=f"Crossover: {p1.name} + {p2.name}",
            strategy_type=p1.strategy_type,
            payload=copy.deepcopy(p1.payload),
            fitness=0.5,
            generation=max(p1.generation, p2.generation) + 1,
            parent_ids=[p1.id, p2.id],
        )
        # Mix payloads
        if p1.strategy_type == "reply_template":
            t1 = p1.payload.get("templates", [])
            t2 = p2.payload.get("templates", [])
            child.payload["templates"] = (t1[:3] + t2[:3])[:6]
        elif p1.strategy_type == "personality_trait":
            child.payload["tone"] = random.choice([p1.payload.get("tone"), p2.payload.get("tone")])
        return child

    def get_best_strategy(self, strategy_type: str) -> Optional[Strategy]:
        candidates = [s for s in self.strategies.values() if s.strategy_type == strategy_type]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.fitness)

    def apply_best_strategies(self, reply_generator: BabyResponseGenerator) -> None:
        """
        Apply evolved strategies to the reply generator.
        """
        best_reply = self.get_best_strategy("reply_template")
        if best_reply and hasattr(reply_generator, "_evolved_templates"):
            reply_generator._evolved_templates = best_reply.payload.get("templates", [])

        best_personality = self.get_best_strategy("personality_trait")
        if best_personality and hasattr(reply_generator, "_evolved_personality"):
            reply_generator._evolved_personality = best_personality.payload

    def get_stats(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        for s in self.strategies.values():
            by_type[s.strategy_type] = by_type.get(s.strategy_type, 0) + 1
        top = sorted(self.strategies.values(), key=lambda s: s.fitness, reverse=True)[:5]
        return {
            "total_strategies": len(self.strategies),
            "by_type": by_type,
            "top_strategies": [{"id": s.id, "name": s.name, "fitness": round(s.fitness, 2), "uses": s.uses} for s in top],
        }

    def _log_autonomy(self, event: str) -> None:
        try:
            log = []
            if AUTONOMY_LOG.exists():
                log = json.loads(AUTONOMY_LOG.read_text(encoding="utf-8") or "[]")
            log.append({"ts": time.time(), "event": event})
            log = log[-200:]
            AUTONOMY_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _log_evolution(self, event: str) -> None:
        self._log_autonomy(f"evolution:{event}")


# Monkey-patch reply generator with evolution support
original_init = BabyResponseGenerator.__init__

def evolved_init(self, vocab, name="Nova"):
    original_init(self, vocab, name)
    self._evolved_templates: List[str] = []
    self._evolved_personality: Dict[str, Any] = {}

BabyResponseGenerator.__init__ = evolved_init
