"""
Minecraft keybind parser — reads Minecraft options.txt files and extracts
the keybindings into a structured control map that Nova can use to play.

Supports standard Minecraft controls + mod-specific keybinds (JEI, Create,
Mekanism, FTB, Ars Nouveau, SecurityCraft, Railcraft, Occultism, AE2, etc.)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Standard Minecraft control categories
CONTROL_CATEGORIES = {
    # Movement
    "key_key.forward": "movement",
    "key_key.left": "movement",
    "key_key.back": "movement",
    "key_key.right": "movement",
    "key_key.jump": "movement",
    "key_key.sneak": "movement",
    "key_key.sprint": "movement",
    "key_key.unmountVehicle": "movement",
    # Interaction
    "key_key.attack": "combat",
    "key_key.use": "interaction",
    "key_key.drop": "inventory",
    "key_key.pickItem": "inventory",
    "key_key.swapOffhand": "inventory",
    "key_key.inventory": "inventory",
    "key_key.chat": "communication",
    "key_key.playerlist": "communication",
    "key_key.command": "communication",
    "key_key.socialInteractions": "communication",
    # Toolbar
    "key_key.saveToolbarActivator": "toolbar",
    "key_key.loadToolbarActivator": "toolbar",
    "key_key.craftingGrid": "inventory",
    "key_key.hotbar": "inventory",
    # Camera / display
    "key_key.togglePerspective": "camera",
    "key_key.fullscreen": "display",
    "key_key.screenshot": "display",
    "key_key.smoothCamera": "camera",
    "key_key.spectatorOutlines": "display",
    # Menu
    "key_key.advancements": "menu",
    "key_key.openManual": "menu",
    "key_key.sfm.toggle_label_view_key": "menu",
    # Mod-specific categories
    "key_key.jei": "recipes",
    "key_key.mekanism": "machines",
    "key_key.ars_nouveau": "spells",
    "key_key.ars_additions": "spells",
    "key_key.ironjetpacks": "movement",
    "key_key.pneumaticcraft": "machines",
    "key_key.railcraft": "transport",
    "key_key.occultism": "magic",
    "key_key.securitycraft": "security",
    "key_key.create": "building",
    "key_key.ae2": "powers",
    "key_key.industrialforegoing": "machines",
    "key_key.silentgear": "inventory",
    "key_key.sophisticated": "inventory",
    "key_key.crystalix": "magic",
    "key_key.draconicevolution": "movement",
    "key_key.sfm": "inspection",
    "key_key.ftb": "quests",
    "key_key.findme": "navigation",
    "key_key.curios": "inventory",
    "key_key.trashslot": "inventory",
    "key_key.jade": "inspection",
    "key_key.kubejs": "scripts",
    "key_key.re liquary": "magic",
    "key_key.ars_elemental": "magic",
    "key_key.integrateddynamics": "logic",
    "key_key.integratedterminals": "machines",
    "key_key.constructionstick": "building",
    "key_key.bridge": "movement",
    "key_key.modularrouters": "routing",
    "key_key.loggingcompanion": "debug",
    "key_key.logisticsnetworks": "routing",
    "key_key.nolijium": "inspection",
    "key_key.moreoverlays": "inspection",
    "key_key.observable": "debug",
    "key_key.hostilenetworks": "magic",
    "key_key.zume": "optics",
    "key_key.modern_industrialization": "machines",
    "key_key.extended_industrialization": "machines",
    "key_key.advanced_ae": "powers",
    "key_key.easy_villagers": "trading",
    "key_key.buildinggadgets": "building",
    "key_key.apotheosis": "gear",
    "key_key.plonk": "building",
}

# Mod names that appear in keybind keys - extract the mod ID
MOD_KEY_PATTERNS = [
    ("jei", "Just Enough Items (JEI)"),
    ("craftingtweaks", "Crafting Tweaks"),
    ("create", "Create"),
    ("mekanism", "Mekanism"),
    ("ars_nouveau", "Ars Nouveau"),
    ("ard_additions", "Ars Additions"),
    ("ironjetpacks", "Iron Jetpacks"),
    ("pneumaticcraft", "PneumaticCraft"),
    ("railcraft", "Railcraft"),
    ("occultism", "Occultism"),
    ("securitycraft", "SecurityCraft"),
    ("silentgear", "Silent's Gear"),
    ("sophisticatedcore", "Sophisticated Backpacks/Core"),
    ("sophisticatedbackpacks", "Sophisticated Backpacks"),
    ("crystalix", "Crystalix"),
    ("draconicevolution", "Draconic Evolution"),
    ("sfm", "Security Craft / SFM"),
    ("ftbteams", "FTB Teams"),
    ("ftbchunks", "FTB Chunks"),
    ("ftbultimine", "FTB Ultimine"),
    ("ftbquests", "FTB Quests"),
    ("findme", "Find Me"),
    ("curios", "Curios API"),
    ("trashslot", "Trash Slot"),
    ("jade", "Jade"),
    ("kubejs", "KubeJS"),
    ("ae2", "Applied Energistics 2"),
    ("extendedae", "Extended AE"),
    ("modern_industrialization", "Modern Industrialization"),
    ("extended_industrialization", "Extended Industrialization"),
    ("advanced_ae", "Advanced AE"),
    ("integrateddynamics", "Integrated Dynamics"),
    ("integratedterminals", "Integrated Terminals"),
    ("constructionstick", "Construction Sticks"),
    ("bridgingmod", "Bridging Mod"),
    ("modulari Routers", "Modular Routers"),
    ("loggingcompanion", "Logging Companion"),
    ("logisticsnetworks", "Logistics Networks"),
    ("hostilenetworks", "Hostile Networks"),
    ("nolijium", "Nolijium"),
    ("moreoverlays", "More Overlays"),
    ("observable", "Observable"),
    ("placebo", "Placebo"),
    ("framedblocks", "Framed Blocks"),
    ("skyguis", "SkyGUIs"),
    ("supplementaries", "Supplementaries"),
    ("plonk", "Plonk"),
    ("refinedstorage", "Refined Storage"),
    ("reliquary", "Reliquary"),
    ("easy_villagers", "Easy Villagers"),
    ("zume", "Zume"),
    ("simplemagnets", "Simple Magnets"),
    ("gui", "GUI"),
    ("hostilenetworks", "Hostile Networks"),
]


class MinecraftKeybindParser:
    """
    Parse a Minecraft options.txt file and extract keybindings.

    Produces a dict: {action_name: key_name} e.g. {"attack": "key.mouse.left",
    "inventory": "key.keyboard.tab", "jump": "key.keyboard.space"}
    """

    # Key name normalization: map raw key names to readable labels
    KEY_NAME_MAP: Dict[str, str] = {
        "key.keyboard.esc": "Escape",
        "key.keyboard.tab": "Tab",
        "key.keyboard.space": "Space",
        "key.keyboard.a": "A",
        "key.keyboard.b": "B",
        "key.keyboard.c": "C",
        "key.keyboard.d": "D",
        "key.keyboard.e": "E",
        "key.keyboard.f": "F",
        "key.keyboard.g": "G",
        "key.keyboard.h": "H",
        "key.keyboard.i": "I",
        "key.keyboard.j": "J",
        "key.keyboard.k": "K",
        "key.keyboard.l": "L",
        "key.keyboard.m": "M",
        "key.keyboard.n": "N",
        "key.keyboard.o": "O",
        "key.keyboard.p": "P",
        "key.keyboard.q": "Q",
        "key.keyboard.r": "R",
        "key.keyboard.s": "S",
        "key.keyboard.t": "T",
        "key.keyboard.u": "U",
        "key.keyboard.v": "V",
        "key.keyboard.w": "W",
        "key.keyboard.x": "X",
        "key.keyboard.y": "Y",
        "key.keyboard.z": "Z",
        "key.keyboard.f1": "F1",
        "key.keyboard.f2": "F2",
        "key.keyboard.f3": "F3",
        "key.keyboard.f4": "F4",
        "key.keyboard.f5": "F5",
        "key.keyboard.f6": "F6",
        "key.keyboard.f7": "F7",
        "key.keyboard.f8": "F8",
        "key.keyboard.f9": "F9",
        "key.keyboard.f10": "F10",
        "key.keyboard.f11": "F11",
        "key.keyboard.f12": "F12",
        "key.keyboard.f13": "F13",
        "key.keyboard.f14": "F14",
        "key.keyboard.f15": "F15",
        "key.keyboard.f16": "F16",
        "key.keyboard.f17": "F17",
        "key.keyboard.f18": "F18",
        "key.keyboard.f19": "F19",
        "key.keyboard.f20": "F20",
        "key.keyboard.printScreen": "PrintScreen",
        "key.keyboard.scrollLock": "ScrollLock",
        "key.keyboard.pause": "Pause",
        "key.keyboard.insert": "Insert",
        "key.keyboard.home": "Home",
        "key.keyboard.pageUp": "PageUp",
        "key.keyboard.delete": "Delete",
        "key.keyboard.end": "End",
        "key.keyboard.pageDown": "PageDown",
        "key.keyboard.left": "LeftArrow",
        "key.keyboard.up": "UpArrow",
        "key.keyboard.right": "RightArrow",
        "key.keyboard.down": "DownArrow",
        "key.keyboard.numlock": "NumLock",
        "key.keyboard.divide": "Num/",
        "key.keyboard.multiply": "Num*",
        "key.keyboard.subtract": "Num-",
        "key.keyboard.add": "Num+",
        "key.keyboard.enter": "Enter",
        "key.keyboard.num0": "Num0",
        "key.keyboard.num1": "Num1",
        "key.keyboard.num2": "Num2",
        "key.keyboard.num3": "Num3",
        "key.keyboard.num4": "Num4",
        "key.keyboard.num5": "Num5",
        "key.keyboard.num6": "Num6",
        "key.keyboard.num7": "Num7",
        "key.keyboard.num8": "Num8",
        "key.keyboard.num9": "Num9",
        "key.keyboard.backspace": "Backspace",
        "key.keyboard.period": "Period",
        "key.keyboard.comma": "Comma",
        "key.keyboard.quote": "Quote",
        "key.keyboard.semicolon": "Semicolon",
        "key.keyboard.slash": "Slash",
        "key.keyboard.backslash": "Backslash",
        "key.keyboard.equal": "Equal",
        "key.keyboard.minus": "Minus",
        "key.keyboard.bracketleft": "Bracket[",
        "key.keyboard.bracketright": "Bracket]",
        "key.keyboard.quote": "Quote",
        "key.keyboard.backslash": "Backslash",
        "key.keyboard.backtick": "Backtick",
        "key.keyboard.tilde": "Tilde",
        "key.keyboard.lcontrol": "LeftCtrl",
        "key.keyboard.rcontrol": "RightCtrl",
        "key.keyboard.lshift": "LeftShift",
        "key.keyboard.rshift": "RightShift",
        "key.keyboard.lalt": "LeftAlt",
        "key.keyboard.ralt": "RightAlt",
        "key.keyboard.lsuper": "LeftWin",
        "key.keyboard.rsuper": "RightWin",
        "key.keyboard.left.shift": "LeftShift",
        "key.keyboard.right.shift": "RightShift",
        "key.keyboard.left.control": "LeftControl",
        "key.keyboard.right.control": "RightControl",
        "key.keyboard.left.alt": "LeftAlt",
        "key.keyboard.right.alt": "RightAlt",
        "key.keyboard.numpad0": "Numpad0",
        "key.keyboard.numpad1": "Numpad1",
        "key.keyboard.numpad2": "Numpad2",
        "key.keyboard.numpad3": "Numpad3",
        "key.keyboard.numpad4": "Numpad4",
        "key.keyboard.numpad5": "Numpad5",
        "key.keyboard.numpad6": "Numpad6",
        "key.keyboard.numpad7": "Numpad7",
        "key.keyboard.numpad8": "Numpad8",
        "key.keyboard.numpad9": "Numpad9",
        "key.keyboard.numpadDecimal": "Numpad.",
        "key.keyboard.numpadDivide": "Numpad/",
        "key.keyboard.numpadMultiply": "Numpad*",
        "key.keyboard.numpadSubtract": "Numpad-",
        "key.keyboard.numpadAdd": "Numpad+",
        "key.keyboard.numpadEnter": "NumpadEnter",
        "key.mouse.left": "LeftMouse",
        "key.mouse.right": "RightMouse",
        "key.mouse.middle": "MiddleMouse",
        "key.mouse.scrollUp": "MouseScrollUp",
        "key.mouse.scrollDown": "MouseScrollDown",
        "key.keyboard.unknown": "Unknown",
    }

    def __init__(self) -> None:
        self.controls: Dict[str, str] = {}  # action -> readable key name
        self.mod_controls: Dict[str, Dict[str, str]] = {}  # mod -> {action: key}
        self.categories: Dict[str, str] = {}  # action -> category
        self._raw_lines: List[str] = []

    def parse_file(self, path: Path) -> "MinecraftKeybindParser":
        """Parse a Minecraft options.txt file."""
        self._raw_lines = []
        self.controls = {}
        self.mod_controls = {}
        self.categories = {}

        if not path.exists():
            raise FileNotFoundError(f"options.txt not found: {path}")

        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            self._raw_lines.append(line)
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Categorize the keybind
            category = self._categorize_key(key)
            self.categories[key] = category

            # Normalize the key name
            readable_key = self._normalize_key(value)

            # Extract action name from key
            action = self._extract_action(key)
            if action:
                self.controls[action] = readable_key

            # Track mod-specific bindings
            mod_id = self._extract_mod(key)
            if mod_id and mod_id != "minecraft":
                if mod_id not in self.mod_controls:
                    self.mod_controls[mod_id] = {}
                mod_action = self._extract_mod_action(key)
                if mod_action:
                    self.mod_controls[mod_id][mod_action] = readable_key

        return self

    def _categorize_key(self, key: str) -> str:
        """Determine what category a keybind belongs to."""
        for pattern, category in CONTROL_CATEGORIES.items():
            if pattern in key.lower():
                return category
        # Infer from key name
        if "attack" in key:
            return "combat"
        if "use" in key:
            return "interaction"
        if "inventory" in key or "pick" in key or "drop" in key or "swap" in key:
            return "inventory"
        if "hotbar" in key or "toolbar" in key:
            return "inventory"
        if "craft" in key or "crafting" in key:
            return "inventory"
        if "chat" in key or "command" in key or "playerlist" in key or "social" in key:
            return "communication"
        if "perspective" in key or "smoothCamera" in key or "screenshot" in key or "fullscreen" in key:
            return "camera"
        if "advancements" in key or "menu" in key or "openManual" in key:
            return "menu"
        if "mod" in key.lower():
            return "mod"
        return "other"

    def _normalize_key(self, raw: str) -> str:
        """Convert raw key name to readable label."""
        return self.KEY_NAME_MAP.get(raw, raw.replace("key.", "").replace("keybind", ""))

    def _extract_action(self, key: str) -> Optional[str]:
        """Extract the action name from a keybind key."""
        # Standard: key_key.<action>
        m = re.match(r'key_key\.(\w+)', key)
        if m:
            return m.group(1)
        # Mod-specific: key_<mod>.<action>
        m = re.match(r'key_(\w+)\.(\w+)', key)
        if m:
            return f"{m.group(1)}_{m.group(2)}"
        return None

    def _extract_mod(self, key: str) -> str:
        """Extract the mod ID from a keybind key."""
        # key_key.<action> -> minecraft
        if key.startswith("key_key."):
            return "minecraft"
        # key_<mod>.<action>
        m = re.match(r'key_(\w+)\.', key)
        if m:
            return m.group(1)
        return "unknown"

    def _extract_mod_action(self, key: str) -> Optional[str]:
        """Extract the action name from a mod keybind."""
        m = re.match(r'key_(\w+)\.(\w+)', key)
        if m:
            return m.group(2)
        return None

    def get_control(self, action: str) -> Optional[str]:
        """Get the key bound to an action."""
        # Try direct match
        if action in self.controls:
            return self.controls[action]
        # Try with "key." prefix
        if f"key_{action}" in self.controls:
            return self.controls[f"key_{action}"]
        return None

    def get_actions_by_category(self, category: str) -> Dict[str, str]:
        """Get all actions in a category."""
        result = {}
        for key, cat in self.categories.items():
            if cat == category:
                action = self._extract_action(key)
                if action and action in self.controls:
                    result[action] = self.controls[action]
        return result

    def get_mod_controls(self, mod_id: str) -> Dict[str, str]:
        """Get all keybinds for a specific mod."""
        return self.mod_controls.get(mod_id, {})

    def list_mods(self) -> List[str]:
        """List all mods detected from keybinds."""
        return sorted(self.mod_controls.keys())

    def list_categories(self) -> Dict[str, List[str]]:
        """Group actions by category."""
        result: Dict[str, List[str]] = {}
        for key, cat in self.categories.items():
            action = self._extract_action(key)
            if action and action in self.controls:
                if cat not in result:
                    result[cat] = []
                result[cat].append(action)
        return result

    def summary(self) -> str:
        """Human-readable summary of all keybinds."""
        lines = []
        lines.append(f"=== Minecraft Keybinds ({len(self.controls)} total) ===")
        cats = self.list_categories()
        for cat in sorted(cats.keys()):
            lines.append(f"\n--- {cat} ---")
            for action in sorted(cats[cat]):
                lines.append(f"  {action}: {self.controls[action]}")
        if self.mod_controls:
            lines.append(f"\n=== Mods Detected ({len(self.mod_controls)} mods) ===")
            for mod in sorted(self.mod_controls.keys()):
                lines.append(f"\n  [{mod}]")
                for action, key in sorted(self.mod_controls[mod].items()):
                    lines.append(f"    {action}: {key}")
        return "\n".join(lines)


def import_keybinds_to_gameplay(options_path: Path, gameplay_learner: "GameplayLearner",
                                 game_name: str = "minecraft") -> Dict[str, Any]:
    """
    Parse a Minecraft options.txt and import the keybinds into the gameplay learner.

    Returns dict with: controls_imported, mods_detected, facts_added.
    """
    from neuro_child.gameplay_learner import GameplayLearner

    parser = MinecraftKeybindParser()
    parser.parse_file(options_path)

    gp = gameplay_learner.get_progress(game_name)

    # Import all keybinds as controls
    for action, key in parser.controls.items():
        if action not in gp.controls:
            gp.controls[action] = key

    # Store mod list as facts
    mods = parser.list_mods()
    mod_facts = [f"This Minecraft instance has mod: {mod}" for mod in mods[:50]]
    for fact in mod_facts:
        if fact not in gp.facts:
            gp.facts.append(fact)

    # Store keybind overview as facts
    cats = parser.list_categories()
    for cat, actions in cats.items():
        if cat in ("mouse", "other", "display"):
            continue
        action_list = ", ".join(f"{a}={parser.controls[a]}" for a in actions[:10])
        fact = f"Controls ({cat}): {action_list}"
        if fact not in gp.facts:
            gp.facts.append(fact)

    # Store mod-specific controls as strategies/knowledge
    for mod_id, mod_keys in parser.mod_controls.items():
        if mod_keys:
            mod_fact = f"Mod {mod_id} keybinds: {', '.join(f'{a}={k}' for a, k in list(mod_keys.items())[:5])}"
            if mod_fact not in gp.facts:
                gp.facts.append(mod_fact)

    gp.last_played = __import__('time').time()
    return {
        "controls_imported": len(parser.controls),
        "mods_detected": len(mods),
        "mods_list": mods,
        "facts_added": len(mod_facts),
        "categories": list(cats.keys()),
    }
