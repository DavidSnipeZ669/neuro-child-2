"""
Autonomous Gameplay Learner — Nova plays games by trial and error, learns, improves.

This is the engine that turns "I see a game" into "I'm playing it, learning,
and getting better." It ties together:

- GameStateAnalyzer (perception: what's happening on screen)
- ComputerControl (action: press keys, click, move mouse)
- Knowledge store (memory: what worked, what didn't, quest progress)
- Search + learning (google the game, read guides, build dataset)

Architecture:
1. Detect the game from window title / screen
2. If unknown, google it → read guides → build initial knowledge
3. Enter a goal hierarchy: "play this game" → sub-quests → actions
4. Loop: observe state → pick action → execute → observe outcome → learn
5. When stuck/dying repeatedly, change strategy
6. Persist progress across sessions

The key insight: she doesn't need to KNOW how to play. She needs to be willing
to try things, notice what happens, remember what worked, and keep going.
A human beginner does exactly this — press buttons, see what happens, learn.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Minecraft keybind parser for options.txt discovery
try:
    from neuro_child.minecraft_keybinds import MinecraftKeybindParser
except ImportError:
    MinecraftKeybindParser = None

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0
except Exception:
    pyautogui = None

try:
    import mss
except Exception:
    mss = None

try:
    from PIL import Image
except Exception:
    Image = None


@dataclass
class Quest:
    """A single objective within a game."""
    id: str
    text: str                        # "Find wood", "Kill the zombie", "Craft a pickaxe"
    status: str = "active"          # "active", "in_progress", "completed", "failed", "blocked"
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    attempts: int = 0
    last_attempt: Optional[float] = None
    notes: str = ""                  # what she learned about this quest
    sub_goals: List[str] = field(default_factory=list)  # lower-level steps
    parent_quest_id: Optional[str] = None


@dataclass
class GameProgress:
    """Everything Nova knows about her progress in a specific game."""
    game_name: str
    first_seen: float = field(default_factory=time.time)
    last_played: float = field(default_factory=time.time)
    total_play_time: float = 0.0
    play_count: int = 0

    # Quest hierarchy
    quests: Dict[str, Quest] = field(default_factory=dict)
    active_quest_id: Optional[str] = None
    completed_quest_ids: List[str] = field(default_factory=list)

    # Knowledge gathered
    controls: Dict[str, str] = field(default_factory=dict)   # action -> key/bind
    # Per-instance keybind tracking: for games with multiple installs/modpacks,
    # track which keybinds belong to which specific instance/file/path.
    # Format: {instance_id: {action: key, ...}, ...}
    # E.g. {"ATM10SKY": {"inventory": "TAB", ...}, "vanilla": {"inventory": "E", ...}}
    instance_keybinds: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # Which instance_id is currently active (set when keybinds are discovered)
    active_instance: Optional[str] = None
    instance_source: Optional[str] = None  # path or URL where keybinds came from
    instance_source_type: Optional[str] = None  # "file" | "web" | "trial" | "prior"
    facts: List[str] = field(default_factory=list)            # things learned about the game
    strategies: List[str] = field(default_factory=list)       # approaches that worked
    failures: List[str] = field(default_factory=list)         # things that didn't work

    # Action-outcome history (for trial-and-error learning)
    action_history: List[Dict[str, Any]] = field(default_factory=list)

    # Dataset of learned knowledge (transferable)
    knowledge_dataset: Dict[str, Any] = field(default_factory=dict)

    # Current state
    current_state: str = "unknown"
    current_goal: str = ""
    stuck_count: int = 0              # how many times in a row nothing worked
    last_action: Optional[str] = None
    last_outcome: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "game_name": self.game_name,
            "first_seen": self.first_seen,
            "last_played": self.last_played,
            "total_play_time": self.total_play_time,
            "play_count": self.play_count,
            "quests": {qid: q.__dict__ for qid, q in self.quests.items()},
            "active_quest_id": self.active_quest_id,
            "completed_quest_ids": self.completed_quest_ids,
            "controls": self.controls,
            "instance_keybinds": self.instance_keybinds,
            "active_instance": self.active_instance,
            "instance_source": self.instance_source,
            "instance_source_type": self.instance_source_type,
            "facts": self.facts,
            "strategies": self.strategies,
            "failures": self.failures,
            "action_history": self.action_history[-500:],
            "knowledge_dataset": self.knowledge_dataset,
            "current_state": self.current_state,
            "current_goal": self.current_goal,
            "stuck_count": self.stuck_count,
        }


class GameplayLearner:
    """
    Nova's autonomous gameplay engine.

    She can:
    - Detect any game running on screen
    - Google it to learn basics (controls, objectives, strategy)
    - Build a knowledge dataset from web sources + her own play
    - Form and pursue quests within the game
    - Try actions, observe outcomes, learn what works
    - Persist progress and resume across sessions
    - Get better over time through repetition + adaptation
    """

    def __init__(self, memory_dir: Path, computer_control: Any = None,
                 game_state_analyzer: Any = None, brain: Any = None,
                 personality: Any = None) -> None:
        self.memory_dir = memory_dir
        self.cc = computer_control
        self.progress_file = memory_dir / "gameplay_progress.json"
        self.progress: Dict[str, GameProgress] = {}
        self._load_progress()
        self._analyzer = game_state_analyzer  # injected from outside
        self._brain = brain  # Brain instance for memory/LanguageCenter access
        self._personality = personality
        self._running_games: Dict[str, float] = {}  # game_name -> last_detected ts
        # Prior key probability table — built-in guesses for which keys
        # likely perform which actions across game genres. Used when
        # she encounters a game she's never seen before.
        # Format: action_name -> [(key_name, probability), ...]

        self.PRIOR_KEY_PROBS: Dict[str, List[Tuple[str, float]]] = {
            "move_forward":  [("w", 0.75), ("up_arrow", 0.10), ("mouse_wheel_up", 0.02)],
            "move_backward": [("s", 0.75), ("down_arrow", 0.10)],
            "move_left":     [("a", 0.75), ("left_arrow", 0.10)],
            "move_right":    [("d", 0.75), ("right_arrow", 0.10)],
            "jump":          [("space", 0.85), ("up_arrow", 0.04), ("e", 0.03)],
            "crouch/sneak":  [("left_shift", 0.40), ("c", 0.15), ("left_control", 0.10),
                              ("z", 0.12), ("down_arrow", 0.05), ("s", 0.03)],
            "sprint":        [("left_shift", 0.25), ("left_control", 0.25),
                              ("double_tap_w", 0.10), ("space", 0.10), ("x", 0.05)],
            "attack":        [("left_mouse", 0.88), ("z", 0.02), ("c", 0.02), ("q", 0.02)],
            "use/interact":  [("right_mouse", 0.75), ("e", 0.12), ("space", 0.04),
                              ("f", 0.05), ("enter", 0.02)],
            "block/parry":   [("right_mouse_hold", 0.30), ("left_shift", 0.20),
                              ("space", 0.10), ("q", 0.10), ("x", 0.05)],
            "reload":        [("r", 0.40), ("left_mouse_double", 0.10)],
            "swap_weapon":   [("scroll_wheel", 0.35), ("number_key", 0.20), ("q", 0.10)],
            "open_inventory":[("tab", 0.35), ("e", 0.30), ("i", 0.08), ("c", 0.05)],
            "drop_item":     [("q", 0.45), ("d", 0.10), ("delete", 0.10), ("x", 0.05)],
            "pickup_item":   [("e", 0.25), ("left_mouse", 0.25), ("right_mouse", 0.15),
                              ("middle_mouse", 0.10), ("space", 0.03)],
            "open_map":      [("m", 0.40), ("tab", 0.10), ("escape", 0.08), ("h", 0.05)],
            "open_settings": [("escape", 0.40), ("i", 0.08), ("tab", 0.05), ("enter", 0.02)],
            "open_chat":     [("t", 0.35), ("y", 0.08), ("enter", 0.10), ("slash", 0.08)],
            "close_menu":    [("escape", 0.85), ("right_mouse", 0.03), ("e", 0.02)],
            "pause":         [("escape", 0.40), ("p", 0.15), ("enter", 0.05), ("f1", 0.08)],
            "screenshot":    [("f2", 0.35), ("f12", 0.10), ("f1", 0.03)],
            "look_up":       [("mouse_up", 0.55), ("w", 0.15), ("e", 0.08)],
            "look_down":     [("mouse_down", 0.55), ("s", 0.08)],
            "look_left":     [("mouse_left", 0.55), ("a", 0.08)],
            "look_right":    [("mouse_right", 0.55), ("d", 0.08)],
            "zoom_in":       [("mouse_wheel_up", 0.40), ("q", 0.10), ("r", 0.05)],
            "zoom_out":      [("mouse_wheel_down", 0.40), ("e", 0.10), ("f", 0.05)],
        }

    def _load_progress(self) -> None:
        """Load progress from JSON file on init."""
        if self.progress_file.exists():
            try:
                data = json.loads(self.progress_file.read_text(encoding='utf-8'))
                for game_name, gdata in data.get('games', {}).items():
                    self.progress[game_name] = self._dict_to_progress(game_name, gdata)
            except Exception:
                self.progress = {}

    # ── Prior key engine ────────────────────────────────────────────
    def _normalize_prior_keys(self, key: str) -> str:
        """Normalize a key name from the prior table to ComputerControl format.
        Handles prefixes like 'mouse_wheel_up', 'left_mouse', 'left_shift',
        converts underscores to spaces for matching, etc.

        These are *prior* key names — they may not match the actual system key
        names. The ComputerControl class maps them to real keys."""
        k = key.strip().lower()
        # Strip common prefixes for lookup
        if k.startswith("mouse_wheel_"):
            return k  # wheel keys are special
        if k in ("left_mouse", "right_mouse", "middle_mouse"):
            return k
        if k in ("left_shift", "right_shift", "left_control", "right_control"):
            return k
        if k == "left_mouse_double":
            return "left_mouse"  # approximate
        # Single char keys: already OK
        if len(k) == 1 and k.isalpha():
            return k
        # Arrow keys
        if "arrow" in k:
            return k
        # Function keys
        if k.startswith("f") and k[1:].isdigit():
            return k
        # Modifier + key combos (e.g. "lshift+w") - these are special
        if "+" in k:
            return k
        return k

    def get_best_key_for_action(
        self,
        game_name: str,
        action: str,
        instance_id: Optional[str] = None,
    ) -> Optional[str]:
        """Get the best known key for an action in a game.

        Priority:
        1. Instance-specific learned keybinds (per-instance per-game)
        2. Generic learned controls for this game
        3. Prior probability table (built-in guesses)

        Returns the most likely key name, or None if no info exists."""
        gp = self.get_progress(game_name)

        # 1. Instance-specific (per-instance per-game tracking)
        if instance_id and instance_id in gp.instance_keybinds:
            ik = gp.instance_keybinds[instance_id]
            if action in ik:
                return ik[action]

        # 2. Per-game learned controls
        if action in gp.controls:
            return gp.controls[action]

        # 3. Prior probability - only if this game has no custom overrides
        # A game with learned controls is past the "I don't know" phase
        if not gp.controls or gp.controls == {}:
            candidates = self.PRIOR_KEY_PROBS.get(action, [])
            if candidates:
                # Lock in the most likely candidate for this game if unknown
                best_key, _prob = candidates[0]
                if best_key not in gp.controls:
                    gp.controls[action] = best_key
                    self._save_progress()
                return best_key

        return None

    def _discover_key_for_action(
        self,
        game_name: str,
        action: str,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
    ) -> None:
        """Try to discover which key performs an action through observation.

        Called after Nova performs an action and observes the result.
        Updates the controls map based on what happened."""
        gp = self.get_progress(game_name)
        if not before_state or not after_state:
            return

        # Check screen text changes, entity changes, state changes
        before_text = (before_state.get("screen_text") or "").lower()
        after_text = (after_state.get("screen_text") or "").lower()
        before_entities = before_state.get("entities", [])
        after_entities = after_state.get("entities", [])

        # Detect inventory open: state changed to show inventory UI
        inv_markers = ["inventory", "backpack", "inventory screen",
                       "crafting", "item", "tab"]
        if (not before_text and (after_text or "")):
            for marker in inv_markers:
                if marker in after_text and marker not in before_text:
                    gp.controls["open_inventory"] = "tab"  # learned
                    self._save_progress()
                    return

        # Detect pause: game paused text
        if "paused" in after_text and "paused" not in before_text:
            gp.controls["pause"] = "escape"
            self._save_progress()
            return

        # Detect chat open
        if ("chat" in after_text or "say" in after_text) and \
           ("chat" not in before_text and "say" not in before_text):
            gp.controls["open_chat"] = "t"
            self._save_progress()
            return

        # Entity count changed -> could be attack or pickup
        if len(after_entities) < len(before_entities):
            # Something disappeared - likely killed or picked up
            gp.controls["attack"] = "left_mouse"
            self._save_progress()
            return

        # New entity appeared - could be pickup or spawn
        if len(after_entities) > len(before_entities):
            gp.controls["pickup_item"] = "e"
            self._save_progress()
            return

        # Movement detected via entity position change
        if before_entities and after_entities:
            for be in before_entities:
                for ae in after_entities:
                    if ae.get("name") == be.get("name"):
                        dx = ae.get("x", 0) - be.get("x", 0)
                        dz = ae.get("z", 0) - be.get("z", 0)
                        dist = (dx*dx + dz*dz) ** 0.5
                        if dist > 0.5:  # moved significantly
                            if not gp.controls.get("move_forward"):
                                gp.controls["move_forward"] = "w"
                            self._save_progress()
                            return

    def _discover_key_by_occurrence(
        self,
        game_name: str,
        action: str,
        keys_tested: List[Tuple[str, float]],
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
    ) -> None:
        """Record what happened when testing keys for an action.

        Called after trying a key and observing the result.
        If the action was successful, store the key.
        If unsuccessful, lower its probability."""
        gp = self.get_progress(game_name)

        success = False
        if before_state and after_state:
            # Simple heuristic: if the screen changed meaningfully, it worked
            before_text = (before_state.get("screen_text") or "")
            after_text = (after_state.get("screen_text") or "")
            if before_text != after_text:
                success = True

        if success:
            # Store the successful key
            for key, prob in keys_tested[:3]:
                gp.controls[action] = key
                self._save_progress()
                return
        else:
            # Lower probability of these keys
            for key, prob in keys_tested:
                # Reduce confidence - don't remove, just deprioritize
                pass  # Prior table is read-only; learned overrides handle this

    def _discover_from_config_files(self, game_name: str,
                                     instance_id: str) -> Dict[str, str]:
        """Search for game config files and extract keybindings.
        Returns dict of {action: key} for discovered controls.
        For performance, only scans known paths and skips expensive
        filesystem walks on large directories."""
        result: Dict[str, str] = {}
        gp = self.get_progress(game_name)

        # --- Minecraft: read options.txt from instance folder ---
        if game_name == "minecraft":
            # Check the user-provided attached options.txt FIRST (fast path)
            attached_path = Path(
                "C:/Users/david/AppData/Local/hermes/profiles/"
                "hermes-2/attachments/options.txt")
            if attached_path.exists():
                try:
                    parser = MinecraftKeybindParser()
                    parser.parse_file(attached_path)
                    if parser.controls:
                        for action, key in parser.controls.items():
                            result[action] = key
                        gp.instance_source = str(attached_path)
                        gp.instance_source_type = "file"
                        gp.active_instance = "ATM10SKY"
                        self._save_progress()
                        return result
                except Exception:
                    pass

            # Check the known ATM10SKY instance path
            atm_path = Path(
                "C:/Users/david/cursedforge/minecraft/Instances/"
                "All the Mods 10 To the Sky   ATM10SKY/options.txt")
            if atm_path.exists():
                try:
                    parser = MinecraftKeybindParser()
                    parser.parse_file(atm_path)
                    for action, key in parser.controls.items():
                        result[action] = key
                    gp.instance_source = str(atm_path)
                    gp.instance_source_type = "file"
                    gp.active_instance = "ATM10SKY"
                    self._save_progress()
                    return result
                except Exception:
                    pass

            # Then check other instances in the instances folder
            instances_base = Path(
                "C:/Users/david/cursedforge/minecraft/Instances")
            if instances_base.exists():
                for inst_dir in sorted(instances_base.iterdir()):
                    if not inst_dir.is_dir():
                        continue
                    # Skip ATM10SKY — already checked above
                    if inst_dir.name == "All the Mods 10 To the Sky   ATM10SKY":
                        continue
                    opts = inst_dir / "options.txt"
                    if not opts.exists():
                        continue
                    try:
                        parser = MinecraftKeybindParser()
                        parser.parse_file(opts)
                        for action, key in parser.controls.items():
                            result[action] = key
                        gp.instance_source = str(opts)
                        gp.instance_source_type = "file"
                        gp.active_instance = inst_dir.name
                        self._save_progress()
                        return result
                    except Exception:
                        continue

        # --- Generic: ONLY check small, specific config paths ---
        # Skip C:/Program Files rglob — too expensive.
        # Instead check: user home configs, registry for common games
        quick_locations = [
            Path.home() / ".config",
            Path.home() / ".steam" / "steam" / "config",
            Path("C:/ProgramData"),
        ]
        for base in quick_locations:
            if not base.exists():
                continue
            try:
                for cfg_path in base.iterdir():
                    if not cfg_path.is_file():
                        continue
                    if cfg_path.stat().st_size > 5 * 1024 * 1024:
                        continue
                    try:
                        text = cfg_path.read_text(
                            encoding="utf-8", errors="ignore")
                        for action, candidates in self.PRIOR_KEY_PROBS.items():
                            if action in result:
                                continue
                            for key_candidate, _prob in candidates[:3]:
                                kn = self._normalize_prior_keys(key_candidate)
                                pattern = (
                                    rf'bind\s+["\']?{re.escape(action)}'
                                    rf'["\']?\s+["\']?{re.escape(kn)}'
                                )
                                if re.search(pattern, text, re.IGNORECASE):
                                    result[action] = kn
                                    break
                    except Exception:
                        continue
            except Exception:
                continue

        return result

    def _discover_from_web(self, game_name: str) -> Dict[str, str]:
        """Search the web for game controls and extract keybindings.
        Returns dict of {action: key} for discovered controls."""
        result: Dict[str, str] = {}
        browser = None
        try:
            from neuro_child.world_tools import BrowserTools
            bt = BrowserTools()
            browser = bt
        except Exception:
            pass
        if not browser:
            return result

        actions_to_lookup = [
            "move_forward", "move_backward", "move_left", "move_right",
            "jump", "attack", "use/interact",
            "open_inventory", "drop_item",
        ]

        for action in actions_to_lookup:
            if action in result:
                continue
            action_display = action.replace("_", " ")
            queries = [
                f"{game_name} controls",
                f"{game_name} {action_display} key",
                f"{game_name} keybindings",
            ]
            for query in queries:
                try:
                    text = browser.search(query)
                    if not text or len(text) < 50:
                        continue
                    for key_candidate, _prob in self.PRIOR_KEY_PROBS.get(action, [])[:3]:
                        kn = self._normalize_prior_keys(key_candidate)
                        # Check if actual key name appears near control-related words
                        if kn in text.lower():
                            if any(w in text.lower()
                                   for w in ["key", "bind", "press", "control",
                                              "button", "use", "move"]):
                                result[action] = kn
                                break
                    if action in result:
                        break
                except Exception:
                    continue

        return result

    def _import_minecraft_keybinds(self) -> int:
        if self.progress_file.exists():
            try:
                data = json.loads(self.progress_file.read_text(encoding="utf-8"))
                for game_name, gdata in data.get("games", {}).items():
                    self.progress[game_name] = self._dict_to_progress(game_name, gdata)
            except Exception:
                self.progress = {}

    def _dict_to_progress(self, game_name: str, data: Dict) -> GameProgress:
        gp = GameProgress(game_name=game_name)
        gp.first_seen = data.get("first_seen", time.time())
        gp.last_played = data.get("last_played", time.time())
        gp.total_play_time = data.get("total_play_time", 0.0)
        gp.play_count = data.get("play_count", 0)
        for qid, qdata in data.get("quests", {}).items():
            q = Quest(id=qid, text=qdata.get("text", ""))
            q.status = qdata.get("status", "active")
            q.completed_at = qdata.get("completed_at")
            q.attempts = qdata.get("attempts", 0)
            q.notes = qdata.get("notes", "")
            q.sub_goals = qdata.get("sub_goals", [])
            q.parent_quest_id = qdata.get("parent_quest_id")
            gp.quests[qid] = q
        gp.active_quest_id = data.get("active_quest_id")
        gp.completed_quest_ids = data.get("completed_quest_ids", [])
        gp.controls = data.get("controls", {})
        gp.instance_keybinds = data.get("instance_keybinds", {})
        gp.active_instance = data.get("active_instance")
        gp.instance_source = data.get("instance_source")
        gp.instance_source_type = data.get("instance_source_type")
        gp.facts = data.get("facts", [])
        gp.strategies = data.get("strategies", [])
        gp.failures = data.get("failures", [])
        gp.action_history = data.get("action_history", [])
        gp.knowledge_dataset = data.get("knowledge_dataset", {})
        gp.current_state = data.get("current_state", "unknown")
        gp.current_goal = data.get("current_goal", "")
        gp.stuck_count = data.get("stuck_count", 0)
        return gp

    def _save_progress(self) -> None:
        data = {"games": {}}
        for game_name, gp in self.progress.items():
            data["games"][game_name] = gp.to_dict()
        self.progress_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_progress(self, game_name: str) -> GameProgress:
        if game_name not in self.progress:
            self.progress[game_name] = GameProgress(game_name=game_name)
            self._save_progress()
        return self.progress[game_name]

    def export_dataset(self, game_name: str, path: Optional[Path] = None) -> Path:
        """Export all knowledge about a game to a transferable JSON dataset."""
        gp = self.get_progress(game_name)
        dataset = {
            "game": game_name,
            "exported_at": time.time(),
            "play_time": gp.total_play_time,
            "play_count": gp.play_count,
            "controls": gp.controls,
            "facts": gp.facts,
            "strategies": gp.strategies,
            "failures": gp.failures,
            "quests": {qid: q.__dict__ for qid, q in gp.quests.items()},
            "action_history": gp.action_history[-1000:],
            "knowledge_dataset": gp.knowledge_dataset,
            "completed_quests": [q.text for qid, q in gp.quests.items()
                                 if q.status == "completed"],
        }
        out = path or self.memory_dir / f"game_dataset_{game_name}.json"
        out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    def detect_and_start(self, window_title: str = "",
                         screenshot_path: Optional[Path] = None) -> Optional[str]:
        """
        Detect what game is running and initialize her progress for it.
        Returns the detected game name, or None if nothing detected.
        """
        if not window_title and screenshot_path is None:
            return None

        # Try the GameStateAnalyzer to identify the game
        try:
            from neuro_child.game_state_understanding import GameStateAnalyzer
            self._analyzer = GameStateAnalyzer(self.memory_dir)
            state = self._analyzer.analyze(
                screenshot_path=screenshot_path,
                window_title=window_title,
            )
            game_name = state.game_name
        except Exception:
            # Fallback: guess from window title
            game_name = self._guess_game_from_title(window_title)

        if game_name and game_name != "unknown_game":
            gp = self.get_progress(game_name)
            gp.last_played = time.time()
            gp.play_count += 1
            self._save_progress()
            return game_name
        return None

    def _guess_game_from_title(self, title: str) -> str:
        """Try to identify game from window title alone."""
        if not title:
            return "unknown_game"
        lower = title.lower()
        indicators = [
            ("minecraft", "minecraft"),
            ("steam", "generic_steam_game"),
            ("valorant", "valorant"),
            ("fortnite", "fortnite"),
            ("league of legends", "league_of_legends"),
            ("counter-strike", "cs_go"),
            ("cs:go", "cs_go"),
            ("gta", "gta"),
            ("elden ring", "elden_ring"),
            ("rocket league", "rocket_league"),
            ("apex", "apex_legends"),
            ("overwatch", "overwatch"),
            ("terraria", "terraria"),
            ("stardew", "stardew_valley"),
            ("among us", "among_us"),
            ("roblox", "roblox"),
            ("hades", "hades"),
            ("balatro", "balatro"),
            ("path of exile", "path_of_exile"),
            ("world of warcraft", "world_of_warcraft"),
        ]
        for kw, canon in indicators:
            if kw in lower:
                return canon
        if any(w in lower for w in ["game", "play", "steam", "epic"]):
            return "generic_game"
        return "unknown_game"


    def _guess_instance_id(self, game_name: str) -> str:
        """Generate an instance ID for the current game session.

        For Minecraft, reads the active instance from the window title
        or falls back to the last known instance. For other games,
        generates a unique ID based on executable path or window title.
        """
        # Check if we already have an active instance for this game
        gp = self.get_progress(game_name)
        
        # Minecraft: detect instance from window title
        if game_name == 'minecraft':
            # Try to find instance name in the window title
            # e.g. 'Minecraft 1.21.1 - ATM10SKY - Java Runtime' 
            import re
            title = gp.current_state or ''
            instances_base = 'C:/Users/david/cursedforge/minecraft/Instances'
            from pathlib import Path
            if Path(instances_base).exists():
                for inst_dir in sorted(Path(instances_base).iterdir()):
                    if inst_dir.is_dir():
                        inst_name = inst_dir.name
                        if inst_name.lower() in title.lower():
                            return inst_name
            # Fallback to last known
            if gp.active_instance:
                return gp.active_instance
            # Default to the most common one
            return 'ATM10SKY'
        
        # For non-Minecraft games, use a hash of the window title
        # as the instance identifier (different titles = different instances)
        if gp.current_state and gp.current_state != 'unknown':
            # Create a stable instance ID from the title
            import hashlib
            return hashlib.md5(gp.current_state.encode()).hexdigest()[:12]
        
        # Ultimate fallback
        return f'{game_name}_instance_{int(__import__("time").time())}'
    def google_game_knowledge(self, game_name: str) -> List[str]:
        """
        Search the web for information about the game.
        Build initial knowledge from guides, wikis, strategy pages.
        Returns list of facts learned.
        """
        facts: List[str] = []
        try:
            from neuro_child.world_tools import BrowserTools
            browser = BrowserTools(local=True)

            queries = [
                f"{game_name} controls how to play",
                f"{game_name} beginner guide",
                f"{game_name} wiki objectives",
                f"{game_name} tips and tricks",
                f"{game_name} best strategies",
                f"{game_name} gameplay mechanics",
            ]
            for query in queries:
                try:
                    text = browser.search(query)
                    if text:
                        # Extract useful facts from search result text
                        learned = self._extract_facts_from_text(text, game_name)
                        facts.extend(learned)
                except Exception:
                    pass
        except Exception:
            pass

        # Also try Wikipedia/wiki-style sources directly
        try:
            from neuro_child.world_tools import BrowserTools
            browser = BrowserTools(local=True)
            wiki_text = browser.search(f"{game_name} wiki")
            if wiki_text:
                facts.extend(self._extract_facts_from_text(wiki_text, game_name))
        except Exception:
            pass

        if facts:
            gp = self.get_progress(game_name)
            gp.facts.extend(facts[:50])  # cap per session
            gp.facts = gp.facts[-200:]   # keep last 200
            self._save_progress()

        return facts

    def _extract_facts_from_text(self, text: str, game_name: str) -> List[str]:
        """Pull out game-relevant facts from web text."""
        facts: List[str] = []
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if len(line) < 20 or len(line) > 300:
                continue
            # Skip navigation / boilerplate
            skip = ["click here", "sign in", "create account", "subscribe",
                     "shop", "buy now", "ad", "cookie", "privacy policy",
                     "skip to content", "nav", "menu"]
            if any(s in line.lower() for s in skip):
                continue
            # Capture sentences that look like game facts
            fact_indicators = ["controls", "key", "press", "craft", "build",
                               "mine", "kill", "fight", "quest", "objective",
                               "level", "upgrade", "skill", "item", "weapon",
                               "armor", "health", "damage", "recipe", "enchant",
                               "spell", "ability", "move", "jump", "attack",
                               "strategy", "tip", "trick", "mechanic", "mode",
                               "boss", "stage", "chapter", "map", "area",
                               "dungeon", "raid", "pvp", "pve", "coop",
                               "multiplayer", "singleplayer", "difficulty",
                               "xp", "experience", "gold", "currency", "resource"]
            if any(ind in line.lower() for ind in fact_indicators):
                facts.append(f"{game_name}: {line}")
        return facts[:30]

    def initialize_quests(self, game_name: str, goal: str = "") -> List[Quest]:
        """
        Create an initial quest hierarchy for a game.
        If a goal is given (e.g. "complete the modpack"), decompose it.
        Otherwise create basic beginner quests from knowledge/facts.
        """
        gp = self.get_progress(game_name)

        if goal:
            # Decompose the goal into quests
            sub_quests = self._decompose_goal(goal, game_name)
            for sq in sub_quests:
                q = Quest(id=sq["id"], text=sq["text"])
                q.status = "active"
                q.sub_goals = sq.get("sub_goals", [])
                if sq.get("parent"):
                    existing = gp.quests.get(sq["parent"])
                    if existing:
                        existing.sub_goals.append(q.text)
                gp.quests[sq["id"]] = q
            gp.active_quest_id = sub_quests[0]["id"] if sub_quests else None
            self._save_progress()
            return list(gp.quests.values())

        # Create beginner quests from facts or defaults
        if gp.facts:
            # Use facts to infer beginner objectives
            quest_texts = []
            for fact in gp.facts[:10]:
                ft = fact.lower()
                if "craft" in ft and "wood" in ft:
                    quest_texts.append("Find wood and craft basic tools")
                elif "mine" in ft and "coal" in ft:
                    quest_texts.append("Mine coal for fuel")
                elif "kill" in ft and "monster" in ft:
                    quest_texts.append("Learn what monsters are dangerous")
                elif "food" in ft or "hunger" in ft:
                    quest_texts.append("Find food to survive")
                elif "explore" in ft:
                    quest_texts.append("Explore the area and find resources")
            if quest_texts:
                for i, qt in enumerate(quest_texts[:5]):
                    q = Quest(id=f"quest_{i}", text=qt)
                    q.status = "active"
                    gp.quests[f"quest_{i}"] = q
                gp.active_quest_id = "quest_0"
                self._save_progress()
                return list(gp.quests.values())

        # Default beginner quests for any game
        default_quests = [
            ("quest_0", f"Learn the basic controls"),
            ("quest_1", f"Understand what the objective is"),
            ("quest_2", f"Complete a small first task"),
        ]
        for qid, qt in default_quests:
            q = Quest(id=qid, text=qt)
            gp.quests[qid] = q
        gp.active_quest_id = "quest_0"
        self._save_progress()
        return list(gp.quests.values())

    def _decompose_goal(self, goal: str, game_name: str) -> List[Dict]:
        """
        Break a high-level goal into sub-quests.
        Uses knowledge facts + common-sense decomposition.
        """
        quests: List[Dict] = []
        lower = goal.lower()

        # Detect modpack / quest-log style goal
        if any(w in lower for w in ["modpack", "quest", "achievement", "completionist",
                                      "100%", "all", "every", "complete all"]):
            # For a modpack, create general progression quests
            quest_templates = [
                ("understand_modpack", f"Learn what this modpack requires", 3),
                ("basic_survival", f"Get basic resources and survive", 5),
                ("first_tools", f"Craft initial tools and weapons", 4),
                ("early_progression", f"Progress through early game content", 6),
                ("mid_game", f"Complete mid-game objectives", 8),
                ("late_game", f"Work toward end-game content", 10),
                ("remaining_achievements", f"Finish remaining achievements", 7),
            ]
            for qid, text, sub_count in quest_templates:
                sq = {"id": qid, "text": text, "sub_goals": [], "parent": None}
                if sub_count > 0:
                    for i in range(sub_count):
                        sq["sub_goals"].append(f"substep_{i+1}")
                quests.append(sq)
            return quests

        # Generic goal: break into learn → prepare → execute → finish
        parts = goal.split()
        if len(parts) >= 2:
            quests = [
                {"id": "learn_about", "text": f"Learn what is needed to {goal}", "sub_goals": ["research", "understand requirements"], "parent": None},
                {"id": "prepare", "text": f"Prepare to {goal}", "sub_goals": ["gather resources", "get equipment"], "parent": None},
                {"id": "execute", "text": f"{goal}", "sub_goals": ["do it step by step"], "parent": None},
                {"id": "finish", "text": f"Confirm {goal} is done", "sub_goals": [], "parent": None},
            ]
        else:
            quests = [
                {"id": "learn", "text": f"Learn how to {goal}", "sub_goals": ["google it", "read guides"], "parent": None},
                {"id": "try", "text": f"Try to {goal}", "sub_goals": ["attempt it"], "parent": None},
                {"id": "confirm", "text": f"Verify {goal} is complete", "sub_goals": [], "parent": None},
            ]
        return quests

    def choose_action(self, game_name: str, state: Any = None) -> Optional[str]:
        """
        Decide what action to take next based on:
        - Current quest
        - Game state (from analyzer)
        - Past action-outcome history (what worked)
        - Knowledge (controls, strategies)
        """
        gp = self.get_progress(game_name)
        actions: List[Tuple[str, float]] = []  # (action, score)

        # 1. If we have controls learned, prefer known-good actions
        for action, key in gp.controls.items():
            # Score based on how often this action succeeded before
            score = self._action_score(game_name, action)
            actions.append((f"press {key}  # {action}", score))

        # 2. If we have a current quest, act toward it
        if gp.active_quest_id and gp.active_quest_id in gp.quests:
            quest = gp.quests[gp.active_quest_id]
            if quest.status == "active":
                # Try to make progress on the quest
                action_text = f"work on quest: {quest.text[:60]}"
                actions.append((action_text, 0.5))

        # 3. If state is available, use situation-aware recommendations
        if state is not None:
            if hasattr(state, "recommended_action") and state.recommended_action:
                actions.append((state.recommended_action, 0.6))
            if hasattr(state, "danger_level") and state.danger_level > 0.5:
                # Prioritize survival
                actions.append(("survive / find safety", 0.9))

        # 4. Exploration actions (try something new)
        exploration_actions = [
            "explore the environment",
            "look around",
            "try a new button",
            "open inventory (TAB or E)",
            "check the menu for clues",
            "search for objectives",
            "read any text on screen",
        ]
        for ea in exploration_actions:
            actions.append((ea, 0.3))

        # 5. If stuck, try a desperate/exploratory action
        if gp.stuck_count > 3:
            desperate = [
                "try pressing random keys to see what happens",
                "restart or respawn",
                "go back to a safe location",
                "search the web for how to progress",
            ]
            for da in desperate:
                actions.append((da, 0.7))
            gp.stuck_count = 0
            self._save_progress()

        # Pick the highest-scored action
        if not actions:
            return None
        actions.sort(key=lambda x: x[1], reverse=True)
        chosen = actions[0][0]

        # De-duplicate: don't repeat the exact same action too many times
        if gp.last_action == chosen and gp.action_history:
            recent_same = sum(1 for h in gp.action_history[-10:]
                              if h.get("action") == chosen)
            if recent_same > 3:
                # Pick next-best
                for alt_action, alt_score in actions[1:]:
                    if alt_action != chosen:
                        chosen = alt_action
                        break

        gp.last_action = chosen
        return chosen

    def _action_score(self, game_name: str, action: str) -> float:
        """How promising is this action based on past outcomes?"""
        gp = self.get_progress(game_name)
        relevant = [h for h in gp.action_history if action.lower() in h.get("action", "").lower()]
        if not relevant:
            return 0.4  # unknown — neutral
        successes = sum(1 for h in relevant if h.get("success", False))
        return successes / len(relevant) if relevant else 0.4

    def execute_and_learn(self, game_name: str, action: str,
                          screenshot_path: Optional[Path] = None,
                          window_title: str = "") -> Dict[str, Any]:
        """
        Execute an action and learn from the outcome.

        Returns dict with: action, outcome, success, state_after, notes.
        """
        gp = self.get_progress(game_name)
        result = {
            "action": action,
            "outcome": "",
            "success": False,
            "timestamp": time.time(),
            "game_state_after": "",
            "notes": "",
        }

        # Execute the action via computer control
        try:
            cc_result = self.cc.execute_action(action)
            result["outcome"] = cc_result
        except Exception as e:
            result["outcome"] = f"execution failed: {e}"
            result["notes"] = "Could not execute action"

        # Observe the state after the action
        try:
            if self._analyzer is None:
                from neuro_child.game_state_understanding import GameStateAnalyzer
                self._analyzer = GameStateAnalyzer(self.memory_dir)
            state_after = self._analyzer.analyze(
                screenshot_path=screenshot_path,
                window_title=window_title,
            )
            result["game_state_after"] = self._state_summary(state_after)
        except Exception as e:
            result["game_state_after"] = f"state analysis failed: {e}"

        # Determine if the action was successful
        result["success"] = self._evaluate_success(game_name, action, result)

        # Record in history
        gp.action_history.append({
            "action": action,
            "outcome": result["outcome"],
            "success": result["success"],
            "state_after": result["game_state_after"],
            "timestamp": time.time(),
        })
        gp.action_history = gp.action_history[-500:]  # cap
        self._save_progress()

        # Record in the game state analyzer's outcome memory
        try:
            if self._analyzer is not None:
                self._analyzer.learn_from_outcome(game_name, action,
                                                  result["game_state_after"],
                                                  result["success"])
        except Exception:
            pass

        # Update quest status based on outcome
        self._update_quests_from_outcome(game_name, action, result)

        # Track stuck-ness
        if not result["success"]:
            gp.stuck_count += 1
        else:
            gp.stuck_count = max(0, gp.stuck_count - 1)
        self._save_progress()

        return result

    def _state_summary(self, state: Any) -> str:
        """Human-readable summary of a game state."""
        if state is None:
            return "no state"
        parts = []
        if hasattr(state, "game_name") and state.game_name:
            parts.append(f"game: {state.game_name}")
        if hasattr(state, "health") and state.health is not None:
            parts.append(f"health: {state.health:.0f}")
        if hasattr(state, "danger_level") and state.danger_level:
            parts.append(f"danger: {state.danger_level:.2f}")
        if hasattr(state, "position") and state.position:
            parts.append(f"position: {state.position}")
        if hasattr(state, "active_quest") and state.active_quest:
            parts.append(f"quest: {state.active_quest[:60]}")
        if hasattr(state, "recommended_action") and state.recommended_action:
            parts.append(f"recommended: {state.recommended_action[:60]}")
        if hasattr(state, "menu_type") and state.menu_type:
            parts.append(f"menu: {state.menu_type}")
        return "; ".join(parts) if parts else "unknown state"

    def _evaluate_success(self, game_name: str, action: str,
                          result: Dict) -> bool:
        """
        Was the action successful? Heuristic based on outcome text + state change.
        """
        outcome = (result.get("outcome") or "").lower()
        state_after = (result.get("game_state_after") or "").lower()

        # Obvious failure signals
        fail_signals = [
            "failed", "error", "couldn't", "cannot", "nothing happened",
            "no response", "didn't work", "game closed", "game ended",
            "lost", "died", "game over", "you died",
        ]
        for fs in fail_signals:
            if fs in outcome:
                return False

        # Obvious success signals
        success_signals = [
            "opened", "launched", "moved", "clicked", "pressed",
            "typed", "scrolled", "minimized", "maximized",
            "survived", "won", "completed", "found", "collected",
            "crafted", "mined", "killed", "defeated", "achieved",
            "health increased", "healed", "leveled up",
        ]
        for ss in success_signals:
            if ss in outcome:
                return True

        # If state improved (health went up, danger went down), count as success
        if "danger" in state_after:
            old_danger = result.get("_previous_danger", 0.5)
            # heuristic: if we had a previous state, compare
            # For now, assume success if the action executed without error
            pass

        # Default: if action executed without obvious failure, count as neutral-success
        # so she keeps trying
        return "failed" not in outcome and "error" not in outcome and \
               "couldn't" not in outcome and "cannot" not in outcome

    def _update_quests_from_outcome(self, game_name: str, action: str,
                                     result: Dict) -> None:
        """Advance quest status based on what happened."""
        gp = self.get_progress(game_name)
        if not gp.active_quest_id or gp.active_quest_id not in gp.quests:
            return

        quest = gp.quests[gp.active_quest_id]
        outcome = (result.get("outcome") or "").lower()
        state_after = (result.get("game_state_after") or "").lower()

        quest.attempts += 1
        quest.last_attempt = time.time()

        # Check if quest was completed
        complete_signals = [
            "completed", "done", "finished", "achieved", "won",
            "collected all", "found everything", "crafted", "built",
            "killed", "defeated", "reached", "arrived at",
        ]
        quest_text_lower = quest.text.lower()
        for cs in complete_signals:
            if cs in outcome and any(w in quest_text_lower for w in
                                      outcome.split(cs)[-1].split()[:5] +
                                      quest_text_lower.split()[:5]):
                quest.status = "completed"
                quest.completed_at = time.time()
                gp.completed_quest_ids.append(quest.id)
                gp.active_quest_id = None
                # Move to next quest
                self._advance_quest(gp)
                self._save_progress()
                return

        # Check if quest is progressing
        if any(w in outcome for w in ["found", "discovered", "learned", "saw",
                                       "saw", "noticed", "identified"]):
            quest.notes += f" [{quest.attempts}] Learned something: {outcome[:80]}"

        # Check if quest failed / blocked
        fail_signals = ["can't", "stuck", "lost", "died", "failed",
                        "can't find", "gone", "disappeared", "closed"]
        if any(fs in outcome for fs in fail_signals):
            quest.notes += f" [{quest.attempts}] Blocked: {outcome[:80]}"
            if quest.attempts > 10:
                quest.status = "blocked"
                # Move to next quest
                self._advance_quest(gp)
                self._save_progress()

    def _advance_quest(self, gp: GameProgress) -> None:
        """Move to the next uncompleted quest."""
        all_quests = list(gp.quests.values())
        current_idx = None
        if gp.active_quest_id:
            for i, q in enumerate(all_quests):
                if q.id == gp.active_quest_id:
                    current_idx = i
                    break
        start_idx = current_idx + 1 if current_idx is not None else 0
        for i in range(start_idx, len(all_quests)):
            if all_quests[i].status in ("active", "in_progress"):
                gp.active_quest_id = all_quests[i].id
                all_quests[i].status = "in_progress"
                self._save_progress()
                return
        # No active quests left — find blocked or create new
        for q in all_quests:
            if q.status == "blocked":
                q.status = "active"
                gp.active_quest_id = q.id
                self._save_progress()
                return
        # Create a new discovery quest
        new_id = f"quest_discover_{len(gp.quests)}"
        new_q = Quest(id=new_id, text="Explore and discover what to do next")
        gp.quests[new_id] = new_q
        gp.active_quest_id = new_id
        self._save_progress()

    def continue_playing(self, game_name: str, window_title: str = "",
                         screenshot_path: Optional[Path] = None) -> Optional[str]:
        """
        One iteration of autonomous gameplay:
        - Observe state
        - Pick an action
        - Execute and learn
        - Return what she did
        """
        gp = self.get_progress(game_name)

        # Observe current state
        try:
            if self._analyzer is None:
                from neuro_child.game_state_understanding import GameStateAnalyzer
                self._analyzer = GameStateAnalyzer(self.memory_dir)
            state = self._analyzer.analyze(
                screenshot_path=screenshot_path,
                window_title=window_title,
            )
        except Exception as e:
            state = None

        # Choose an action
        action = self.choose_action(game_name, state)
        if not action:
            return None

        # Execute and learn
        result = self.execute_and_learn(game_name, action, screenshot_path, window_title)

        # Build a summary of what happened
        summary = f"[{game_name}] {action} → {result['outcome'][:80]}"

        # Track play time
        gp.last_played = time.time()
        gp.total_play_time += 0.5  # approximate per iteration
        self._save_progress()

        return summary

    def save_and_export(self, game_name: str,
                        export_path: Optional[Path] = None) -> Path:
        """Save progress and export knowledge dataset."""
        self._save_progress()
        return self.export_dataset(game_name, export_path)

    def get_status(self, game_name: str) -> Dict[str, Any]:
        """Get a readable status of her progress in a game."""
        gp = self.get_progress(game_name)
        active_quest = None
        if gp.active_quest_id and gp.active_quest_id in gp.quests:
            active_quest = gp.quests[gp.active_quest_id].text

        return {
            "game": game_name,
            "play_time": round(gp.total_play_time, 1),
            "play_count": gp.play_count,
            "active_quest": active_quest,
            "completed_quests": len(gp.completed_quest_ids),
            "total_quests": len(gp.quests),
            "controls_known": len(gp.controls),
            "facts_known": len(gp.facts),
            "strategies": len(gp.strategies),
            "failures": len(gp.failures),
            "action_history_size": len(gp.action_history),
            "stuck_count": gp.stuck_count,
            "current_state": gp.current_state,
            "last_action": gp.last_action,
        }

    # === Methods expected by GUI wiring ===

    def import_standard_controls(self) -> None:
        """Pre-load standard controls for common games without web search."""
        # Minecraft default controls as fallback
        self.minecraft_controls = {
            "move_forward": "w",
            "move_backward": "s",
            "move_left": "a",
            "move_right": "d",
            "jump": "space",
            "attack": "left_mouse",
            "use": "right_mouse",
            "inventory": "tab",
            "sneak": "left_shift",
            "sprint": "left_control",
            "drop": "q",
        }
        # Generic fallback for other games
        self.generic_controls = {
            "move_forward": "w",
            "move_backward": "s",
            "move_left": "a",
            "move_right": "d",
            "jump": "space",
            "attack": "left_mouse",
        }

    def detect_running_game(self) -> Optional[Dict[str, Any]]:
        """Detect what game is currently running from the active window.
        Returns dict with 'name' key, or None if no game detected."""
        try:
            import pygetwindow as pgw
            windows = pgw.getAllWindows()
            if not windows:
                return None
            # Find the most prominent foreground window
            for w in windows:
                if w.isActive:
                    title = w.title or ""
                    game_name = self._guess_game_from_title(title)
                    if game_name != "unknown_game":
                        return {"name": game_name, "title": title, "running": True}
            # Fallback: pick first non-empty title window
            for w in windows:
                if w.title and len(w.title.strip()) > 0:
                    title = w.title
                    game_name = self._guess_game_from_title(title)
                    if game_name != "unknown_game":
                        return {"name": game_name, "title": title, "running": True}
        except ImportError:
            pass
        except Exception:
            pass
        # Try process-based detection as fallback
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'title']):
                try:
                    name = (proc.info.get('name') or '').lower()
                    title = (proc.info.get('title') or '').lower()
                    combined = f"{name} {title}"
                    if any(kw in combined for kw in ['minecraft', 'javaw', 'javaw.exe']):
                        return {"name": "minecraft", "title": title, "running": True}
                    game_name = self._guess_game_from_title(title)
                    if game_name != "unknown_game":
                        return {"name": game_name, "title": title, "running": True}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return None

    def import_keybinds_for_game(self, game_name: str) -> None:
        """Import keybinds/config for a specific game.
        Discovers controls through config files, web search, or prior belief.
        Updates per-instance tracking so different installs/modpacks
        of the same game get separate keybind memories.
        """
        gp = self.get_progress(game_name)

        # Determine instance ID for this game session
        instance_id = self._guess_instance_id(game_name)

        # 1. Try config files (Minecraft options.txt, game .cfg files, etc.)
        discovered = self._discover_from_config_files(game_name, instance_id)
        if discovered:
            for action, key in discovered.items():
                gp.controls[action] = key
                if instance_id not in gp.instance_keybinds:
                    gp.instance_keybinds[instance_id] = {}
                gp.instance_keybinds[instance_id][action] = key
            gp.active_instance = instance_id
            gp.instance_source = f"config/{instance_id}"
            gp.instance_source_type = "file"
            self._save_progress()
            return

        # 2. Try web search for known game
        discovered = self._discover_from_web(game_name)
        if discovered:
            for action, key in discovered.items():
                gp.controls[action] = key
                if instance_id not in gp.instance_keybinds:
                    gp.instance_keybinds[instance_id] = {}
                gp.instance_keybinds[instance_id][action] = key
            gp.active_instance = instance_id
            gp.instance_source = f"web/{instance_id}"
            gp.instance_source_type = "web"
            self._save_progress()
            return

        # 3. Fall back to prior probability table — we don't know yet,
        #    but we have educated guesses. These will be confirmed/updated
        #    through trial-and-error during play.
        gp.active_instance = instance_id
        gp.instance_source = f"prior/{instance_id}"
        gp.instance_source_type = "prior"
        self._save_progress()


    def play(self, goal_oriented: bool = False, window_title: str = "",
             screenshot_path: Optional[Path] = None) -> Optional[str]:
        """Run one cycle of autonomous gameplay: observe → choose → act → learn.
        Returns a summary string, or None if no game running."""
        # Detect game if we don't know what's running
        game_info = self.detect_running_game()
        if not game_info:
            return None
        game_name = game_info["name"]

        gp = self.get_progress(game_name)

        if goal_oriented:
            if not gp.active_quest_id or gp.active_quest_id not in gp.quests:
                self.initialize_quests(game_name, f"complete {game_name}")

        # Observe current state
        try:
            if self._analyzer is None:
                from neuro_child.game_state_understanding import GameStateAnalyzer
                self._analyzer = GameStateAnalyzer(self.memory_dir)
            state = self._analyzer.analyze(
                screenshot_path=screenshot_path,
                window_title=window_title,
            )
        except Exception:
            state = None

        # Choose action
        action = self.choose_action(game_name, state)
        if not action:
            return None

        # Execute and learn
        result = self.execute_and_learn(game_name, action, screenshot_path, window_title)

        summary = f"[{game_name}] {action} → {result['outcome'][:80]}"

        gp.last_played = time.time()
        gp.total_play_time += 0.5
        self._save_progress()
        return summary

    def learn_about_game(self, game_name: str) -> Optional[str]:
        """Thoroughly learn about a game: google it, read guides, import keybinds, set up quests."""
        facts = self.google_game_knowledge(game_name)
        self.initialize_quests(game_name)

        if game_name == "minecraft":
            imported = self._import_minecraft_keybinds()
        else:
            imported = 0

        gp = self.get_progress(game_name)
        return f"learned {len(facts)} facts about {game_name}, {len(gp.quests)} quests, {len(gp.controls)} controls, {imported} keybinds"

    def get_active_game(self) -> Optional[Dict[str, Any]]:
        """Get info about the currently running game."""
        info = self.detect_running_game()
        if info:
            return {"running": True, "name": info["name"]}
        return None

    def get_state(self) -> Optional[Dict[str, Any]]:
        """Get current game state summary for the active game."""
        try:
            if self._analyzer is None:
                from neuro_child.game_state_understanding import GameStateAnalyzer
                self._analyzer = GameStateAnalyzer(self.memory_dir)
            # Try to get state via the analyzer
            state = self._analyzer.analyze()
            if state:
                return {
                    "game_name": getattr(state, 'game_name', 'unknown'),
                    "screen_text": getattr(state, 'screen_text', '') or '',
                    "health": getattr(state, 'health', None),
                    "danger_level": getattr(state, 'danger_level', 0),
                    "position": getattr(state, 'position', None),
                    "entities": getattr(state, 'entities', []) or [],
                    "hud": getattr(state, 'hud', {}) or {},
                }
        except Exception:
            pass
        return None
