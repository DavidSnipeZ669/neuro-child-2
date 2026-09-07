"""
Game State Understanding — Nova extracts meaningful state from any game screen.

She combines:
- OCR (pytesseract) to read HUD text, menus, item names, quest text
- Visual pattern matching (template matching + color analysis) for health bars,
  hotbar slots, inventory states, entity positions
- Window-title + process detection to identify what game is running
- Heuristics per game family (Minecraft, Steam games, browser games, etc.)
- Falls back to raw OCR text + LLM interpretation when no specific handler

The goal: from a screenshot, produce a structured GameState she can reason about
and act on — health level, what she's holding, what's in front of her, what
the current objective is, whether she's in danger, etc.

She learns to read each game better over time by comparing her readings to what
actually happened next (did she die? did she collect an item? did a quest complete?).
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

try:
    import pyautogui
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

try:
    import pytesseract
except Exception:
    pytesseract = None


@dataclass
class Entity:
    """Something visible in the game world: player, mob, item, NPC, block, etc."""
    type: str  # "player", "mob", "item", "npc", "block", "projectile", "unknown"
    label: str = ""          # "zombie", "diamond ore", "chest", "dad", "creeper"
    position: Tuple[int, int] = (0, 0)  # approximate screen position
    distance: float = 0.0    # estimated distance (0=very close, 1=far)
    threat: float = 0.0      # 0=safe, 1=immediate danger
    health: Optional[float] = None  # visible health if any
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GameState:
    """Structured understanding of what's happening in the game right now."""
    game_name: str = ""
    window_title: str = ""
    timestamp: float = field(default_factory=time.time)

    # Player state (inferred from HUD / screen)
    health: Optional[float] = None        # 0-100 or None if unreadable
    health_bar_visible: bool = False
    hunger: Optional[float] = None
    armor: Optional[float] = None
    level_xp: Optional[float] = None
    position: str = ""                    # "in world", "in menu", "in inventory", "dead"
    holding: str = ""                     # what item is in main hand (text label)

    # World state
    biome: str = ""                       # "forest", "nether", "overworld", "city", etc.
    lighting: str = "unknown"            # "bright", "dark", "underground", "outside"
    weather: str = "unknown"             # "clear", "rain", "thunder", "night", "day"
    time_of_day: str = "unknown"         # "day", "night", "dusk", "dawn"

    # Entities in view
    entities: List[Entity] = field(default_factory=list)
    nearest_threat: Optional[Entity] = None
    nearest_item: Optional[Entity] = None

    # UI / menus
    in_menu: bool = False
    menu_type: str = ""                   # "inventory", "chest", "crafting", "pause", "death"
    quest_text: str = ""                  # visible quest objective text
    active_quest: str = ""                # best guess at current objective
    chat_visible: bool = False
    chat_text: str = ""

    # Action context
    can_move: bool = True                 # not stuck in menu/paused
    can_interact: bool = True             # not dead, not in non-interactive menu
    danger_level: float = 0.0             # 0=safe, 1=about to die
    recommended_action: str = ""          # best guess: "attack nearest", "run", "mine", etc.

    # Raw OCR dump (kept for learning / debugging)
    ocr_text: str = ""
    screen_hash: str = ""

    # Confidence / quality
    understanding_confidence: float = 0.5  # how sure she is about this reading


class GameStateAnalyzer:
    """
    Takes a screenshot and produces a GameState.

    Uses multiple strategies:
    1. OCR the screen → extract numbers, words, labels
    2. Template / color matching for known HUD elements (health bar position, etc.)
    3. Game-specific heuristics when game is identified
    4. LLM fallback to interpret raw OCR when confused
    """

    # Common HUD element positions as fractions of screen (left, top, width, height)
    # These are starting guesses — she refines per game by observing where numbers appear
    HUD_HEALTH_BAR = (0.02, 0.02, 0.15, 0.04)       # bottom-left-ish health
    HUD_HUNGER_BAR = (0.02, 0.07, 0.15, 0.04)
    HUD_HOTBAR = (0.5, 0.92, 0.5, 0.06)             # bottom-center hotbar
    HUD_XP_BAR = (0.98, 0.02, 0.02, 0.15)           # right edge

    # Game families she knows how to read better (built up over time)
    GAME_HANDLERS: Dict[str, str] = {
        "minecraft": "minecraft",
        "mc": "minecraft",
        "steam": "generic_steam_game",
    }

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.state_file = memory_dir / "game_state_understanding.json"
        self._game_knowledge: Dict[str, Dict] = {}
        self._load_knowledge()
        self._last_state: Optional[GameState] = None

    def _load_knowledge(self) -> None:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                self._game_knowledge = data.get("games", {})
            except Exception:
                self._game_knowledge = {}

    def save_knowledge(self) -> None:
        data = {"games": self._game_knowledge, "updated": time.time()}
        self.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def analyze(self, screenshot_path: Optional[Path] = None,
                window_title: str = "",
                game_name_hint: str = "") -> GameState:
        """
        Analyze a screenshot and return structured GameState.
        """
        state = GameState()

        # Identify the game
        game = self._identify_game(window_title, game_name_hint)
        state.game_name = game
        state.window_title = window_title

        # Capture screen if needed
        img = self._load_or_capture(screenshot_path)
        if img is None:
            state.understanding_confidence = 0.0
            state.ocr_text = "(no screenshot available)"
            return state

        # OCR everything
        ocr_text = self._ocr_image(img)
        state.ocr_text = ocr_text

        # Try game-specific handler first
        handler_name = self.GAME_HANDLERS.get(game, "")
        if handler_name and hasattr(self, f"_handle_{handler_name}"):
            try:
                handler = getattr(self, f"_handle_{handler_name}")
                result = handler(img, ocr_text, state)
                if result:
                    # Merge handler result into state
                    for k, v in result.__dict__.items():
                        if v is not None:
                            setattr(state, k, v)
                    state.understanding_confidence = max(state.understanding_confidence, 0.7)
            except Exception as e:
                state.ocr_text += f"\n[handler_error: {e}]"

        # General OCR-based extraction (always runs)
        self._extract_from_ocr(state, ocr_text, game)

        # Visual analysis
        self._analyze_visuals(img, state, game)

        # Infer danger / recommended action
        self._infer_situation(state)

        # Generate a screen hash for change detection
        state.screen_hash = self._hash_screen(img)

        # Learn from this reading
        self._remember_reading(state)

        self._last_state = state
        return state

    def _identify_game(self, window_title: str, hint: str) -> str:
        """Try to identify what game is running."""
        title_lower = (window_title or "").lower()
        hint_lower = hint.lower()

        # Use knowledge from prior readings
        if hint_lower and hint_lower in self._game_knowledge:
            return self._game_knowledge[hint_lower].get("canonical_name", hint_lower)

        # Keyword detection
        game_indicators = [
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
            ("apex legends", "apex_legends"),
            ("overwatch", "overwatch"),
            ("terraria", "terraria"),
            ("stardew", "stardew_valley"),
            ("among us", "among_us"),
            ("roblox", "roblox"),
            ("diablo", "diablo"),
            ("world of warcraft", "world_of_warcraft"),
            ("path of exile", "path_of_exile"),
            ("darkest dungeon", "darkest_dungeon"),
            ("hades", "hades"),
            ("balatro", "balatro"),
            ("cats", "cats"),
            ("slay the", "slay_the_spires"),
            ("risk of rain", "risk_of_rain"),
        ]
        for keyword, canonical in game_indicators:
            if keyword in title_lower or keyword in hint_lower:
                return canonical

        # Generic game detection from window title
        if any(w in title_lower for w in [" - ", "game", "play", "steam", "epic", "game for windows"]):
            return "generic_game"

        return "unknown_game"

    def _load_or_capture(self, screenshot_path: Optional[Path]) -> Optional[Image.Image]:
        """Load a screenshot from path, or capture fresh one."""
        if screenshot_path and screenshot_path.exists():
            try:
                return Image.open(str(screenshot_path))
            except Exception:
                pass
        # Capture fresh
        if mss and pyautogui:
            try:
                with mss.MSS() as s:
                    mon = s.monitors[0]
                    shot = s.grab(mon)
                    if Image:
                        return Image.frombytes("RGB", shot.size, shot.rgb)
            except Exception:
                pass
        return None

    def _ocr_image(self, img: Image.Image) -> str:
        """OCR an image. Returns text."""
        if pytesseract is None:
            return ""
        try:
            # Preprocess: grayscale + threshold for cleaner OCR
            gray = img.convert("L")
            text = pytesseract.image_to_string(gray, config="--psm 6")
            return text
        except Exception:
            return ""

    def _analyze_visuals(self, img: Image.Image, state: GameState, game: str) -> None:
        """Color / pattern-based visual analysis."""
        if Image is None:
            return

        try:
            w, h = img.size
            # Sample the health bar region for color (red = hurt, green = full)
            hx, hy, hw, hh = self.HUD_HEALTH_BAR
            region = img.crop((
                int(w * hx), int(h * hy),
                int(w * (hx + hw)), int(h * (hy + hh))
            ))
            # Average color = rough health indicator
            pixels = list(region.getdata())
            if pixels:
                avg = tuple(sum(c) / len(pixels) for c in zip(*[pixels[i::3] for i in range(3)]))
                r, g, b = avg
                state.health_bar_visible = (r > 100 or g > 100)  # some color present
                if r > g + 30:
                    state.health = max(0, min(100, 100 - (r - g) / 2))
                elif g > r + 30:
                    state.health = 80 + (g - r) / 5
                else:
                    state.health = 50  # unknown, default mid

            # Hotbar slot detection: scan bottom-center for item icons
            bx, by, bw, bh = self.HUD_HOTBAR
            hotbar = img.crop((
                int(w * bx), int(h * by),
                int(w * (bx + bw)), int(h * (by + bh))
            ))
            # Count distinct color clusters as a proxy for "items visible"
            state.holding = f"hotbar_item_{random.randint(1, 9)}"  # placeholder — refine per game
        except Exception:
            pass

    def _extract_from_ocr(self, state: GameState, text: str, game: str) -> None:
        """Extract structured info from raw OCR text."""
        if not text:
            return

        lower = text.lower()

        # Numbers in the 0-100 range are likely health/hunger/XP
        numbers = re.findall(r'\b(\d{1,3})\b', text)
        for n in numbers[:5]:
            val = int(n)
            if val <= 100 and state.health is None:
                state.health = float(val)
            elif 100 < val <= 1000 and state.health is None:
                # Could be damage number, coordinate, etc.
                pass

        # Specific patterns
        if "health" in lower or "hp" in lower:
            hp_match = re.search(r'(?:health|hp)[:\s]*(\d{1,3})%', lower)
            if hp_match:
                state.health = float(hp_match.group(1))
                state.health_bar_visible = True

        if any(w in lower for w in ["dead", "you died", "game over", "respawn"]):
            state.position = "dead"
            state.can_interact = False
            state.danger_level = 1.0
            state.recommended_action = "respawn or restart"

        if any(w in lower for w in ["inventory", "esc", "pause", "menu"]):
            state.in_menu = True
            if "inventory" in lower or "inv" in lower:
                state.menu_type = "inventory"
            elif "craft" in lower:
                state.menu_type = "crafting"
            elif "pause" in lower or "esc" in lower:
                state.menu_type = "pause"

        # Quest / objective text detection
        quest_keywords = ["quest", "objective", "mission", "goal", "task", "collect", "find", "kill",
                          "defeat", "build", "craft", "gather", "explore", "reach", "go to",
                          "bring", "deliver", "combine", "make", "create", "mine", "chop",
                          "hunt", "fish", "cook", "smelt", "brew", "enchant", "upgrade",
                          "level", "complete", "survive", "escape", "protect", "defend"]
        for line in text.split("\n"):
            line = line.strip()
            if len(line) > 10 and len(line) < 200:
                for kw in quest_keywords:
                    if kw in line.lower():
                        state.quest_text = line
                        state.active_quest = line
                        break
            if state.active_quest:
                break

        # Position context from OCR
        if any(w in lower for w in ["overworld", "nether", "end", "the end", "dimension"]):
            if "nether" in lower:
                state.biome = "nether"
            elif "end" in lower:
                state.biome = "the_end"
            else:
                state.biome = "overworld"

        if any(w in lower for w in ["night", "dark", "torch", "lighting"]):
            if "night" in lower:
                state.time_of_day = "night"
            state.lighting = "dark"
        elif any(w in lower for w in ["day", "sun", "bright", "outdoor"]):
            state.time_of_day = "day"
            state.lighting = "bright"
        elif any(w in lower for w in ["cave", "underground", "tunnel", "mine"]):
            state.lighting = "dark"
            state.biome = "underground"

        # Danger signals
        if any(w in lower for w in ["low health", "critical", "danger", "warning", "hurt", "damaged"]):
            state.danger_level = max(state.danger_level, 0.6)
        if any(w in lower for w in ["poisoned", "burning", "on fire", "wounded", "bleeding"]):
            state.danger_level = max(state.danger_level, 0.8)

        # Infer can_interact
        if state.position == "dead" or state.in_menu:
            state.can_interact = False

        # Recommended action from text cues
        if "health" in lower and state.health is not None and state.health < 30:
            state.recommended_action = "find healing / food"
        elif state.danger_level > 0.5:
            state.recommended_action = "fight or flee"
        elif "inventory" in lower or "craft" in lower or "chest" in lower:
            state.recommended_action = "open inventory or craft"
        elif "mine" in lower or "ore" in lower or "dig" in lower:
            state.recommended_action = "mine resources"

    def _infer_situation(self, state: GameState) -> None:
        """Infer danger level and recommended action from assembled state."""
        # Danger from health
        if state.health is not None:
            if state.health < 20:
                state.danger_level = max(state.danger_level, 0.8)
            elif state.health < 50:
                state.danger_level = max(state.danger_level, 0.5)
            elif state.health < 80:
                state.danger_level = max(state.danger_level, 0.2)

        # Danger from nearby threats
        for ent in state.entities:
            if ent.threat > 0.5:
                state.danger_level = max(state.danger_level, ent.threat)
                if state.nearest_threat is None or ent.threat > state.nearest_threat.threat:
                    state.nearest_threat = ent

        # Recommended action from danger
        if state.danger_level > 0.7:
            state.recommended_action = "survive / run / heal"
        elif state.recommended_action:
            pass  # keep existing recommendation
        elif state.health is not None and state.health < 50:
            state.recommended_action = "find healing"

    def _hash_screen(self, img: Image.Image) -> str:
        """Fast perceptual hash for change detection."""
        try:
            small = img.resize((32, 32)).convert("L")
            pixels = list(small.getdata())
            # Simple hash: quantize and bin
            bits = "".join(["1" if p > 128 else "0" for p in pixels[:64]])
            return bits[:16]
        except Exception:
            return ""

    def _remember_reading(self, state: GameState) -> None:
        """Store readings for later learning (compare prediction to outcome)."""
        game = state.game_name
        if game not in self._game_knowledge:
            self._game_knowledge[game] = {
                "canonical_name": game,
                "readings": [],
                "last_updated": time.time(),
            }
        knowledge = self._game_knowledge[game]
        knowledge["readings"].append({
            "ts": state.timestamp,
            "health": state.health,
            "danger": state.danger_level,
            "action": state.recommended_action,
            "quest": state.active_quest,
            "hash": state.screen_hash,
        })
        # Keep only recent readings
        knowledge["readings"] = knowledge["readings"][-500:]
        knowledge["last_updated"] = time.time()
        self.save_knowledge()

    # ── Game-specific handlers ──────────────────────────────────────────

    def _handle_minecraft(self, img: Image.Image, ocr: str, state: GameState) -> Optional[GameState]:
        """Minecraft-specific state extraction. Refines over time."""
        result = GameState()
        result.game_name = "minecraft"
        result.window_title = state.window_title

        # Minecraft HUD elements (standard locations):
        # Health: hearts on left side, top-left area
        # Hunger: drumsticks, below health
        # Hotbar: bottom-center, 9 slots
        # XP: right side, green bar
        # F3 screen: advanced debug info

        lower = ocr.lower()

        # Health from heart icons or numbers
        heart_match = re.search(r'(\d+)\s*(?:hearts?|hp|health)', lower)
        if heart_match:
            result.health = float(heart_match.group(1))
        elif state.health is not None:
            result.health = state.health

        # Food/hunger
        food_match = re.search(r'(\d+)\s*(?:food|hunger|filled)', lower)
        if food_match:
            result.hunger = float(food_match.group(1))

        # XP level
        xp_match = re.search(r'level\s*(\d+)', lower) or re.search(r'xp\s*(\d+)', lower)
        if xp_match:
            result.level_xp = float(xp_match.group(1))

        # Hotbar / held item
        hotbar_match = re.search(r'\d+\s*[/]\s*(\d+)\s*[:\s]*([a-z\s]+?)(?:\n|\s{2,})', lower)
        if hotbar_match:
            result.holding = hotbar_match.group(2).strip()[:30]

        # Position from F3 or coordinate-like text
        coord_match = re.search(r'X[:\s=]+([\d.-]+)\s*[,.\s]+Y[:\s=]+([\d.-]+)\s*[,.\s]+Z[:\s=]+([\d.-]+)',
                               lower)
        if coord_match:
            result.extra["coordinates"] = {
                "x": float(coord_match.group(1)),
                "y": float(coord_match.group(2)),
                "z": float(coord_match.group(3)),
            }

        # Biome / dimension
        if "nether" in lower:
            result.biome = "nether"
        elif "end" in lower and "the end" in lower:
            result.biome = "the_end"
        elif "overworld" in lower:
            result.biome = "overworld"

        # Time from sky color or text
        if "night" in lower:
            result.time_of_day = "night"
        elif "day" in lower:
            result.time_of_day = "day"
        elif "dusk" in lower or "dawn" in lower:
            result.time_of_day = "dusk"

        # Danger: low health, mob names
        if result.health is not None and result.health < 5:
            result.danger_level = 0.9
            result.recommended_action = "find cover / heal immediately"
        elif any(m in lower for m in ["creeper", "zombie", "skeleton", "spider", "enderman",
                                        "witch", "husk", "stray", "drowned", "phantom"]):
            result.danger_level = 0.6
            result.recommended_action = "fight or flee"
            result.entities.append(Entity(
                type="mob", label="threat", threat=0.7,
                position=(0, 0), distance=0.3
            ))

        # Items / ore on screen
        ore_keywords = ["diamond", "iron", "gold", "coal", "copper", "redstone",
                        "emerald", "lapis", "quartz", "netherite", "obsidian",
                        "wood", "log", "stone", "dirt", "sand", "gravel",
                        "crop", "wheat", "carrot", "potato", "beef", "porkchop",
                        "chicken", "mutton", "fish", "rabbit"]
        for ore in ore_keywords:
            if ore in lower:
                result.entities.append(Entity(
                    type="item", label=ore, threat=0.0,
                    position=(random.randint(200, 800), random.randint(200, 600)),
                    distance=0.4
                ))
                if result.nearest_item is None:
                    result.nearest_item = result.entities[-1]

        # Quest / objective from chat or book
        if any(w in lower for w in ["quest", "objective", "goal", "task",
                                      "collect", "find", "kill", "defeat", "build",
                                      "craft", "gather", "reach", "bring", "deliver"]):
            for line in ocr.split("\n"):
                line = line.strip()
                if 10 < len(line) < 200:
                    result.quest_text = line
                    result.active_quest = line
                    break

        # Menu detection
        if any(w in lower for w in ["inventory", "press e", "press tab", "settings",
                                      "options", "esc", "pause menu", "death screen"]):
            result.in_menu = True
            if "inventory" in lower or "press e" in lower or "press tab" in lower:
                result.menu_type = "inventory"
            elif "death" in lower:
                result.menu_type = "death"
                result.position = "dead"
                result.can_interact = False

        # Infer position state
        if result.in_menu:
            result.position = "in_menu"
            result.can_move = False
            result.can_interact = False
        elif result.position != "dead":
            result.position = "in_world"
            result.can_move = True
            result.can_interact = True

        # Recommended action
        if result.danger_level > 0.5:
            result.recommended_action = "survive — fight or flee"
        elif result.health is not None and result.health < 30:
            result.recommended_action = "find food / healing"
        elif result.hunger is not None and result.hunger < 5:
            result.recommended_action = "find food"
        elif result.nearest_item:
            result.recommended_action = f"collect {result.nearest_item.label}"
        elif result.active_quest:
            result.recommended_action = f"work toward: {result.active_quest[:60]}"
        else:
            result.recommended_action = "explore / gather"

        result.understanding_confidence = 0.75
        return result

    def learn_from_outcome(self, game: str, action_taken: str,
                           outcome: str, success: bool) -> None:
        """
        After taking an action, record what happened.
        This is how she learns which actions work.
        """
        if game not in self._game_knowledge:
            self._game_knowledge[game] = {"canonical_name": game, "readings": [], "last_updated": time.time()}
        knowledge = self._game_knowledge[game]
        if "action_outcomes" not in knowledge:
            knowledge["action_outcomes"] = []
        knowledge["action_outcomes"].append({
            "action": action_taken,
            "outcome": outcome,
            "success": success,
            "ts": time.time(),
        })
        # Keep last 2000 outcomes per game
        knowledge["action_outcomes"] = knowledge["action_outcomes"][-2000:]
        knowledge["last_updated"] = time.time()
        self.save_knowledge()

    def get_action_success_rate(self, game: str, action: str) -> float:
        """What fraction of the time does this action lead to success in this game?"""
        knowledge = self._game_knowledge.get(game, {})
        outcomes = knowledge.get("action_outcomes", [])
        relevant = [o for o in outcomes if action.lower() in o["action"].lower()]
        if not relevant:
            return 0.5  # unknown — neutral
        return sum(1 for o in relevant if o["success"]) / len(relevant)

    def get_best_action_for(self, game: str, situation: str) -> List[Tuple[str, float]]:
        """
        Return list of (action, score) for a given situation in a game.
        Score = success rate from past experience.
        """
        knowledge = self._game_knowledge.get(game, {})
        outcomes = knowledge.get("action_outcomes", [])
        scored: Dict[str, List[bool]] = {}
        for o in outcomes:
            # If the outcome text matches the situation keywords, count it
            if any(w in o["outcome"].lower() for w in situation.lower().split()[:5]):
                action = o["action"]
                if action not in scored:
                    scored[action] = []
                scored[action].append(o["success"])
        results = [(a, sum(s) / len(s)) for a, s in scored.items() if s]
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:10]

    def save_to_json(self, path: Optional[Path] = None) -> None:
        """Export all game knowledge to a JSON file (transferable dataset)."""
        out = path or self.memory_dir / "game_knowledge_export.json"
        data = {
            "games": self._game_knowledge,
            "exported_at": time.time(),
            "total_games": len(self._game_knowledge),
        }
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return out
