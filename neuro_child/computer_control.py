"""
Computer Control — Nova controls the PC like a human would.

She can:
- Launch any installed app / game
- Find games on disk and learn to play them
- Control mouse/keyboard fast (pyautogui, low latency)
- Read game state from screen (OCR + vision)
- Remember game controls/objectives/strategy per game
- Play browser games via headless/visible browser
- Continuously improve at any game she plays

This is the bridge between "thinking" and "doing" — she decides to play,
finds the game, launches it, learns the controls, plays, remembers, improves.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pyautogui

# Fast input — minimal latency, no artificial delays
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.0
pyautogui.typewrite_interval = 0.0


@dataclass
class GameKnowledge:
    """Everything Nova knows about a specific game."""
    name: str
    path: Optional[str] = None
    launch_cmd: Optional[str] = None
    controls: Dict[str, str] = field(default_factory=dict)  # action -> key/click
    objective: str = ""
    strategy: str = ""
    difficulty_rating: float = 0.5
    play_count: int = 0
    last_played: float = field(default_factory=time.time)
    lessons: List[str] = field(default_factory=list)
    notes: str = ""


class GameMemory:
    """Persistent memory of games Nova has learned/played."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.games_file = memory_dir / "game_knowledge.json"
        self._games: Dict[str, GameKnowledge] = {}
        self._load()

    def _load(self) -> None:
        if self.games_file.exists():
            try:
                data = json.loads(self.games_file.read_text(encoding="utf-8"))
                for name, g in data.items():
                    self._games[name] = GameKnowledge(**g)
            except Exception:
                self._games = {}

    def save(self) -> None:
        data = {n: g.__dict__ for n, g in self._games.items()}
        self.games_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, name: str) -> Optional[GameKnowledge]:
        return self._games.get(name)

    def add(self, knowledge: GameKnowledge) -> None:
        self._games[knowledge.name] = knowledge
        self.save()

    def list_games(self) -> List[str]:
        return list(self._games.keys())

    def update_controls(self, game_name: str, controls: Dict[str, str]) -> None:
        g = self._games.get(game_name)
        if g:
            g.controls.update(controls)
            g.save()

    def learn_lesson(self, game_name: str, lesson: str) -> None:
        g = self._games.get(game_name)
        if g:
            if lesson not in g.lessons:
                g.lessons.append(lesson)
            g.save()


class ComputerControl:
    """
    Nova's hands and eyes on the PC — full computer control.

    She can find, launch, learn, and play any game on the system,
    browser or native, and remember how to play it.
    """

    # Common game install locations on Windows
    GAME_SEARCH_PATHS = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path("C:/Windows/Apps"),
        Path(os.environ.get("LOCALAPPDATA", ""), "Gaming"),
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
    ]

    GAME_EXTENSIONS = {".exe", ".bat", ".cmd", ".msi"}
    GAME_NAME_HINTS = [
        "game", "gamehouse", "steam", "epic", "battle", "minecraft", "valorant",
        "fortnite", "apex", "overwatch", "csgo", "counter-strike", "dota",
        "league", "rust", "ark", "subnautica", "stardew", "baldi", "among",
        "slither", "agar", "gems", "block", "pixel", "unity", "unreal",
        "shoot", "race", "fly", "jump", "platform", "puzzle", "card",
        "chess", "checkers", "snake", "tetris", "pacman", "mario",
        "roguelike", "fps", "rpg", "strategy", "simulator", "survival",
    ]

    BROWSER_GAME_HOSTS = [
        "crazygames.com", "notdoppler.com", "coolmathgames.com", "hoodamath.com",
        "armorgames.com", "kizgl.com", "silvergames.com", "gamesgames.com",
        "yum.com", "gameflare.com", "poki.com", "gameforge.com",
    ]

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.game_memory = GameMemory(memory_dir)
        self._running_apps: Dict[str, float] = {}  # app_name -> last_seen
        self._screenshot_cache: Optional[Path] = None
        self._last_screen_text: str = ""

    # ── App / Game Discovery ──────────────────────────────────────────

    def find_games_on_disk(self, hint: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Scan common game install locations for executable games.
        Returns list of {name, path, size_mb, is_game} dicts.
        """
        results: List[Dict[str, Any]] = []
        seen: set = set()
        paths_to_scan = self.GAME_SEARCH_PATHS
        if hint:
            hint_lower = hint.lower()
            paths_to_scan = [
                p for p in paths_to_scan
                if hint_lower in str(p).lower()
            ] or paths_to_scan

        for base in paths_to_scan:
            if not base.exists():
                continue
            try:
                for root, dirs, files in os.walk(str(base)):
                    # Skip huge dirs quickly
                    if len(files) > 5000:
                        continue
                    for fname in files:
                        fpath = Path(root) / fname
                        ext = fpath.suffix.lower()
                        if ext not in self.GAME_EXTENSIONS:
                            continue
                        name = fname.lower()
                        # Skip system/utility executables
                        if any(skip in name for skip in [
                            "uninstall", "helper", "update", "vcredist",
                            "msiexec", "schtasks", "reg", "cmd", "powershell",
                        ]):
                            continue
                        is_game = self._looks_like_game(name, fname)
                        size_mb = fpath.stat().st_size / (1024 * 1024)
                        key = str(fpath)
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append({
                            "name": fname,
                            "path": str(fpath),
                            "size_mb": round(size_mb, 1),
                            "is_game": is_game,
                            "scan_path": str(base),
                        })
            except PermissionError:
                continue
            except Exception:
                continue

        results.sort(key=lambda r: (r["is_game"], r["size_mb"]), reverse=True)
        return results[:50]

    def _looks_like_game(self, name_lower: str, original_name: str) -> bool:
        """Heuristic: does this executable look like a game?"""
        for hint in self.GAME_NAME_HINTS:
            if hint in name_lower:
                return True
        # Heuristic: size > 50MB and not a known non-game
        return False

    def find_installed_games_via_registry(self) -> List[Dict[str, Any]]:
        """
        Use Windows Registry to find installed apps (uninstall keys).
        Returns list of {name, publisher, install_location, version} dicts.
        """
        results: List[Dict[str, Any]] = []
        try:
            import winreg
            views = [
                (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ),
            ]
            for hkey, access in views:
                try:
                    key = winreg.OpenKey(hkey, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, access)
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            subkey = winreg.OpenKey(key, subkey_name)
                            name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                            pub = winreg.QueryValueEx(subkey, "Publisher")[0] if winreg.QueryValueEx(subkey, "Publisher")[1] else ""
                            loc = winreg.QueryValueEx(subkey, "InstallLocation")[0] if winreg.QueryValueEx(subkey, "InstallLocation")[1] else ""
                            ver = winreg.QueryValueEx(subkey, "DisplayVersion")[0] if winreg.QueryValueEx(subkey, "DisplayVersion")[1] else ""
                            is_game = any(h in (name + pub).lower() for h in self.GAME_NAME_HINTS)
                            results.append({
                                "name": name,
                                "publisher": pub,
                                "install_location": loc,
                                "version": ver,
                                "is_game": is_game,
                            })
                            winreg.CloseKey(subkey)
                            i += 1
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except OSError:
                    pass
        except ImportError:
            pass
        except Exception:
            pass
        results.sort(key=lambda r: r["is_game"], reverse=True)
        return results

    def find_browser_game(self, game_name_hint: str) -> Optional[Dict[str, Any]]:
        """
        Search for a browser-based game by name hint.
        Returns {url, title, host} if found, else None.
        """
        hint = game_name_hint.lower().strip()
        for host in self.BROWSER_GAME_HOSTS:
            url = f"https://www.{host}/search?q={hint.replace(' ', '+')}"
            return {
                "url": url,
                "title": f"{hint} - {host}",
                "host": host,
                "type": "browser",
            }
        return None

    def launch_app(self, app_path_or_name: str) -> Dict[str, Any]:
        """
        Launch an application or game by path or name.
        Returns {status, app, pid, window_title, error}.
        """
        path = app_path_or_name
        # If just a name, try to find it
        if not Path(path).is_file():
            # Try common locations
            for base in self.GAME_SEARCH_PATHS:
                candidate = base / path
                if candidate.is_file():
                    path = str(candidate)
                    break
            # Try relying on PATH
            if not Path(path).is_file():
                try:
                    subprocess.Popen(path, shell=True)
                    return {"status": "launched_by_name", "app": path}
                except Exception as e:
                    return {"status": "error", "app": path, "error": str(e)}

        try:
            proc = subprocess.Popen(path, shell=True)
            return {
                "status": "launched",
                "app": Path(path).name,
                "pid": proc.pid,
            }
        except Exception as e:
            return {"status": "error", "app": path, "error": str(e)}

    # ── Mouse / Keyboard Control ──────────────────────────────────────

    def move_cursor(self, x: int, y: int, duration: float = 0.05) -> str:
        """Move mouse cursor to (x, y) on screen."""
        pyautogui.moveTo(x, y, duration=duration)
        return f"moved cursor to ({x}, {y})"

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> str:
        """Click at current position or (x, y)."""
        if x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.03)
        pyautogui.click(button=button)
        pos = pyautogui.position()
        return f"clicked {button} at ({pos.x}, {pos.y})"

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> str:
        if x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.03)
        pyautogui.doubleClick()
        return "double clicked"

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> str:
        if x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.03)
        pyautogui.rightClick()
        return "right clicked"

    def press_key(self, key: str) -> str:
        """Press a single key."""
        # Normalize key names
        key_lower = key.lower().strip()
        mapped = self._normalize_key(key_lower)
        pyautogui.press(mapped)
        return f"pressed {mapped}"

    def hold_key(self, key: str) -> str:
        pyautogui.keyDown(self._normalize_key(key.lower().strip()))
        return f"held {key}"

    def release_key(self, key: str) -> str:
        pyautogui.keyUp(self._normalize_key(key.lower().strip()))
        return f"released {key}"

    def type_text(self, text: str, interval: float = 0.01) -> str:
        pyautogui.typewrite(text, interval=interval)
        return f"typed: {text[:30]}{'...' if len(text) > 30 else ''}"

    def hotkey(self, *keys: str) -> str:
        pyautogui.hotkey(*[self._normalize_key(k.lower().strip()) for k in keys])
        return f"hotkey: {'+'.join(keys)}"

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.2) -> str:
        pyautogui.moveTo(x1, y1, duration=0.03)
        pyautogui.mouseDown()
        pyautogui.moveTo(x2, y2, duration=duration)
        pyautogui.mouseUp()
        return f"dragged from ({x1},{y1}) to ({x2},{y2})"

    def scroll(self, clicks: int) -> str:
        pyautogui.scroll(clicks)
        return f"scrolled {clicks}"

    def get_cursor_pos(self) -> Tuple[int, int]:
        pos = pyautogui.position()
        return (pos.x, pos.y)

    def get_screen_size(self) -> Tuple[int, int]:
        size = pyautogui.size()
        return (size.width, size.height)

    def _normalize_key(self, key: str) -> str:
        """Normalize key names for pyautogui."""
        aliases = {
            "enter": "enter", "return": "enter", "returnkey": "enter",
            "space": "space", "tab": "tab", "esc": "esc", "escape": "esc",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
            "win": "win", "windows": "win", "command": "command",
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5",
            "f6": "f6", "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10",
            "f11": "f11", "f12": "f12",
            "delete": "delete", "del": "delete", "backspace": "backspace",
            "insert": "insert", "home": "home", "end": "end",
            "pageup": "pageup", "pagedown": "pagedown",
            "capslock": "capslock", "numlock": "numlock",
            "scrolllock": "scrolllock",
            "printscreen": "printscreen", "printscreenkey": "printscreen",
        }
        return aliases.get(key, key)

    # ── Screen / Game State Reading ───────────────────────────────────

    def capture_screen(self, save_path: Optional[Path] = None) -> Path:
        """Capture full screen screenshot. Returns path to saved image."""
        import mss
        from PIL import Image
        with mss.MSS() as s:
            mon = s.monitors[0]
            shot = s.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            path = save_path or self.memory_dir / "control_screenshot.png"
            img.save(str(path))
            self._screenshot_cache = path
            return path

    def read_screen_text(self, image_path: Optional[Path] = None) -> str:
        """OCR the screen or cached screenshot. Returns text."""
        import mss
        from PIL import Image
        try:
            import pytesseract
        except ImportError:
            return ""
        path = image_path or self._screenshot_cache
        if path and path.exists():
            img = Image.open(str(path))
        else:
            with mss.MSS() as s:
                mon = s.monitors[0]
                shot = s.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.rgb)
        text = pytesseract.image_to_string(img)
        self._last_screen_text = text
        return text

    def find_on_screen(self, image_template: Path, confidence: float = 0.8) -> Optional[Tuple[int, int]]:
        """Find a template image on screen (pixel matching). Returns (x, y) or None."""
        try:
            from PIL import Image
            import pyautogui
            location = pyautogui.locateOnScreen(str(image_template), confidence=confidence)
            if location:
                return (location.left, location.top)
        except Exception:
            pass
        return None

    def describe_screen(self) -> str:
        """Get a text description of what's on screen."""
        text = self._last_screen_text
        try:
            import pyautogui
            window = pyautogui.getActiveWindow()
            window_title = window.title if window else ""
        except Exception:
            window_title = ""
        cursor = self.get_cursor_pos()
        lines = []
        if window_title:
            lines.append(f"active window: {window_title}")
        if text.strip():
            # First few lines of OCR text
            lines.append("screen text: " + text.strip().replace("\n", " | ")[:200])
        lines.append(f"cursor: {cursor[0]},{cursor[1]}")
        return " | ".join(lines)

    # ── Game Learning ─────────────────────────────────────────────────

    def learn_game_controls(self, game_name: str, controls: Dict[str, str]) -> str:
        """Record the controls for a game (e.g. {'jump': 'space', 'attack': 'left_click'})."""
        self.game_memory.update_controls(game_name, controls)
        return f"Learned controls for {game_name}: {controls}"

    def remember_game_lesson(self, game_name: str, lesson: str) -> str:
        """Remember a lesson about how to play a game better."""
        self.game_memory.learn_lesson(game_name, lesson)
        return f"Learned lesson for {game_name}: {lesson}"

    def get_game_strategy(self, game_name: str) -> Optional[str]:
        """Retrieve stored strategy for a game."""
        g = self.game_memory.get(game_name)
        if g:
            return g.strategy or g.notes
        return None

    def set_game_strategy(self, game_name: str, strategy: str) -> str:
        """Store or update strategy notes for a game."""
        g = self.game_memory.get(game_name)
        if g:
            g.notes = strategy
            g.save()
            return f"Strategy saved for {game_name}"
        # Create new entry
        self.game_memory.add(GameKnowledge(name=game_name, notes=strategy))
        return f"Strategy saved for new game {game_name}"

    def increment_play_count(self, game_name: str) -> int:
        """Record that she played this game."""
        g = self.game_memory.get(game_name)
        if g:
            g.play_count += 1
            g.last_played = time.time()
            g.save()
            return g.play_count
        self.game_memory.add(GameKnowledge(name=game_name, play_count=1))
        return 1

    def evaluate_performance(self, game_name: str, score: float, outcome: str) -> str:
        """Remember how a game session went."""
        g = self.game_memory.get(game_name)
        if g:
            note = f"Played {game_name}: score={score}, outcome={outcome}"
            if outcome.lower() in ("win", "won", "success", "good"):
                g.difficulty_rating = max(0.0, g.difficulty_rating - 0.05)
            elif outcome.lower() in ("lose", "lost", "fail", "bad"):
                g.difficulty_rating = min(1.0, g.difficulty_rating + 0.05)
            g.save()
            return note
        return f"No memory for {game_name} yet"

    # ── Generic Action Execution ──────────────────────────────────────

    def execute_action(self, action_text: str) -> str:
        """
        Parse and execute a natural-language computer action.
        Examples:
          "click the play button"
          "press space"
          "type hello world"
          "move mouse to 500 300 and click"
          "minimize the game"
          "launch minecraft"
          "open browser to chess.com"
          "wait 2 seconds"
          "scroll down"
        """
        lower = action_text.lower().strip()

        # Strip inline comment from action strings like "press w  # forward"
        if "  #" in lower:
            lower = lower.split("  #")[0].strip()

        # Key/button press — check this FIRST so actions like
        # "press F1  # openManual" don't accidentally match "open" and
        # get routed to launch_app.
        if lower.startswith("press ") or lower.startswith("hit ") or lower.startswith("tap "):
            key = lower.replace("press", "").replace("hit", "").replace("tap", "").strip()
            if key:
                return self.press_key(key)

        # Hold key
        if "hold " in lower or "hold down" in lower:
            key = re.sub(r'hold\s*(down\s*)?', '', lower).strip()
            if key:
                return self.hold_key(key)

        # Release key
        if "release " in lower:
            key = re.sub(r'release\s*', '', lower).strip()
            if key:
                return self.release_key(key)

        # Launch an app/game — check AFTER press so "press F1  # openManual"
        # doesn't accidentally route here.
        if any(x in lower for x in ["launch", "open ", "start ", "run "]):
            app = lower.replace("launch", "").replace("open", "").replace("start", "").replace("run", "").strip()
            if app:
                result = self.launch_app(app)
                return f"launched {app}: {result.get('status')}"

        # Open browser to a URL/game
        if any(x in lower for x in ["open browser", "go to", "navigate to", "visit "]):
            url_match = re.search(r'https?://[^\s]+', action_text)
            if url_match:
                url = url_match.group(0)
                try:
                    from neuro_child.world_tools import BrowserTools
                    browser = BrowserTools(local=True)
                    browser.goto(url)
                    return f"opened browser to {url}"
                except Exception:
                    try:
                        subprocess.Popen(f'start "" "{url}"', shell=True)
                        return f"opened browser to {url}"
                    except Exception as e:
                        return f"couldn't open browser: {e}"
            else:
                site = lower.replace("open browser", "").replace("go to", "").replace("navigate to", "").replace("visit", "").strip()
                if site:
                    url = f"https://www.{site}.com" if "." not in site else site
                    try:
                        subprocess.Popen(f'start "" "{url}"', shell=True)
                        return f"opened browser to {url}"
                    except Exception as e:
                        return f"couldn't open browser: {e}"

        # Click action
        if lower.startswith("click"):
            coords = re.findall(r'\d+', lower)
            if len(coords) >= 2:
                x, y = int(coords[0]), int(coords[1])
                return self.click(x, y)
            return self.click()

        # Double click
        if "double click" in lower or "double-click" in lower:
            coords = re.findall(r'\d+', lower)
            if len(coords) >= 2:
                return self.double_click(int(coords[0]), int(coords[1]))
            return self.double_click()

        # Right click
        if "right click" in lower or "right-click" in lower:
            coords = re.findall(r'\d+', lower)
            if len(coords) >= 2:
                return self.right_click(int(coords[0]), int(coords[1]))
            return self.right_click()

        # Press key
        if lower.startswith("press ") or lower.startswith("hit ") or lower.startswith("tap "):
            key = lower.replace("press", "").replace("hit", "").replace("tap", "").strip()
            # strip inline comment like "press w  # forward"
            if "  #" in key:
                key = key.split("  #")[0].strip()
            if key:
                return self.press_key(key)

        # Hold key
        if "hold " in lower or "hold down" in lower:
            key = re.sub(r'hold\s*(down\s*)?', '', lower).strip()
            if key:
                return self.hold_key(key)

        # Release key
        if "release " in lower:
            key = re.sub(r'release\s*', '', lower).strip()
            if key:
                return self.release_key(key)

        # Type text
        if lower.startswith("type ") or lower.startswith("write ") or lower.startswith("input "):
            text = lower.replace("type", "").replace("write", "").replace("input", "").strip().strip('"').strip("'")
            if text:
                return self.type_text(text)

        # Move mouse
        if lower.startswith("move mouse") or lower.startswith("move cursor") or lower.startswith("go to "):
            coords = re.findall(r'\d+', lower)
            if len(coords) >= 2:
                return self.move_cursor(int(coords[0]), int(coords[1]))
            return "need coordinates to move mouse"

        # Drag
        if "drag" in lower:
            coords = re.findall(r'\d+', lower)
            if len(coords) >= 4:
                return self.drag(int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3]))
            return "need 4 coordinates to drag"

        # Scroll
        if "scroll" in lower:
            direction = "down" if "down" in lower else "up"
            clicks = 3 if "fast" in lower else 1
            sign = -clicks if direction == "down" else clicks
            return self.scroll(sign)

        # Hotkey
        if "hotkey" in lower or "press " in lower and "+" in lower:
            keys = re.findall(r'[a-zA-Z0-9]+(?:\+?[a-zA-Z0-9]+)*', lower)
            if len(keys) >= 2:
                return self.hotkey(*keys[:3])

        # Wait
        wait_match = re.search(r'wait\s+(\d+\.?\d*)\s*(seconds?|secs?)?', lower)
        if wait_match:
            secs = float(wait_match.group(1))
            time.sleep(secs)
            return f"waited {secs}s"

        # Minimize / maximize / close window
        if "minimize" in lower:
            try:
                import pyautogui
                win = pyautogui.getActiveWindow()
                if win:
                    win.minimize()
                    return "minimized active window"
            except Exception as e:
                return f"minimize failed: {e}"
        if "maximize" in lower:
            try:
                import pyautogui
                win = pyautogui.getActiveWindow()
                if win:
                    win.maximize()
                    return "maximized active window"
            except Exception as e:
                return f"maximize failed: {e}"
        if "close" in lower and ("window" in lower or "app" in lower or "game" in lower):
            try:
                import pyautogui
                win = pyautogui.getActiveWindow()
                if win:
                    win.close()
                    return "closed active window"
            except Exception as e:
                return f"close failed: {e}"

        return f"unknown action: {action_text}"
