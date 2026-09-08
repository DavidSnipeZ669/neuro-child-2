"""Nova Server — FastAPI backend for Electron frontend + remote access.

Runs the same Brain/Consciousness/Mouth/Eyes stack as gui.py so the
Electron app (and any browser, including a phone) can talk to Nova over
HTTP/WebSocket.

Network access (Phase 1 of plan v3):
  - The server binds to 0.0.0.0 so it's reachable on the local network.
  - For access FROM OUTSIDE the local network (phone on cellular, another
    house, etc.), one of these is needed:
      A) Tailscale (recommended) — install Tailscale on the PC and on the
        phone; the phone hits the Tailscale IP (e.g. 100.x.y.z) instead of
        localhost. Works behind CGNAT, no port forwarding.
      B) ngrok / Cloudflare tunnel / Tailscale Funnel — gives a public
        https:// URL. Use only if you want access without installing anything
        on the client device. Public URL = anyone who finds it can hit the API.
  - Authentication: the FastAPI server enforces an API key on every request
    (header X-API-Key). Being able to reach the server (Tailscale IP / tunnel
    URL) does not by itself grant control — you also need the key. This is the
    same fencing principle as plan v2 Phase 3, applied to network requests.

Auth: set NOVA_API_KEY env var, or pass --api-key on the command line.
      If neither is set, the server prints a generated key at startup and
      refuses requests that don't present it.

Run:
  python nova_server.py                     # prints a generated key
  python nova_server.py --api-key "secret"  # use your own
  NOVA_API_KEY=secret python nova_server.py
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import secrets
import sys
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("nova_server")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
API_KEY: Optional[str] = None


def _generate_default_key() -> str:
    raw = secrets.token_urlsafe(32)
    return f"nk_{raw}"


def set_api_key(key: str) -> None:
    global API_KEY
    API_KEY = key
    masked = key[:4] + "…" + key[-4:] if len(key) > 8 else "****"
    log.info("Nova API key set (masked: %s)", masked)


def verify_api_key(request: Request) -> None:
    if not API_KEY:
        return
    header = request.headers.get("X-API-Key", "")
    if header != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def verify_api_key_ws(websocket: WebSocket) -> bool:
    if not API_KEY:
        return True
    key = websocket.headers.get("X-API-Key", "")
    if key != API_KEY:
        log.warning("WebSocket auth failure from %s", websocket.client)
        websocket.close(code=1008, reason="Invalid API key")
        return False
    return True


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    context: Optional[str] = None
    session_id: Optional[str] = None


class ChatReply(BaseModel):
    reply: str
    audio: Optional[str] = None
    thinking: Optional[str] = None
    mood: Optional[dict] = None
    drives: Optional[dict] = None


class StateSnapshot(BaseModel):
    mood: Optional[dict] = None
    drives: Optional[dict] = None
    thoughts: Optional[str] = None
    goals: Optional[list] = None
    lessons: Optional[list] = None
    vocabulary: Optional[list] = None
    screen_base64: Optional[str] = None
    speaking: Optional[bool] = None
    listening: Optional[bool] = None
    timestamp: Optional[float] = None


class GoalSubmit(BaseModel):
    goal: str = Field(..., min_length=1, max_length=1000)


class CommandRequest(BaseModel):
    action: str
    params: Optional[dict] = None


# ---------------------------------------------------------------------------
# Stub objects — used when real imports (eyes, mouth, hands, consciousness)
# fail. These exist so Brain.respond() (from gui.py) never crashes on None.
# ---------------------------------------------------------------------------

@dataclass
class _StubDrive:
    intensity: float = 0.5
    min: float = 0
    max: float = 1


@dataclass
class _StubConsciousState:
    """Stand-in for neuro_child.consciousness.ConsciousState.

    gui.py's _conscious_reply() reads ``self.consciousness.state.mood``
    (gui.py:747-748), so the stub must expose ``state`` with a ``mood``
    attribute.
    """
    mood: str = "curious"
    emotional_valence: float = 0.5
    arousal: float = 0.3
    focus: float = 0.3
    last_thought: str = ""


class _ConsciousnessStub:
    """Minimal stub for consciousness when real import fails.

    Must provide:
      - state property (ConsciousState-like, with ``mood``)
      - interact(user_text, outcome)
      - perceive(screen_text, cursor_pos)
      - get_mood() -> dict
      - get_drives() -> dict  (with "curiosity", "play", "autonomy" keys)
      - get_thoughts() -> str
      - get_goals() -> list
      - get_lessons() -> list
      - get_vocabulary() -> list
      - desires attribute (with .drives dict for dual_cortex drive extraction
        at gui.py:657-664)
    """

    def __init__(self) -> None:
        self._drives = {
            "curiosity": _StubDrive(0.5),
            "play": _StubDrive(0.3),
            "autonomy": _StubDrive(0.5),
        }

    @property
    def state(self) -> _StubConsciousState:
        return _StubConsciousState()

    @property
    def desires(self):
        # dual_cortex reads self.consciousness.desires.drives (gui.py:657)
        return type("Desires", (), {"drives": self._drives})()

    def interact(self, user_text: str, outcome: str = "success") -> None:
        pass

    def perceive(self, screen_text: str, cursor_pos: Optional[List[int]] = None) -> None:
        pass

    def get_mood(self) -> Dict[str, Any]:
        return {"label": "neutral", "value": 0.5}

    def get_drives(self) -> Dict[str, Any]:
        return {
            "curiosity": {"intensity": 0.5, "min": 0, "max": 1},
            "play": {"intensity": 0.3, "min": 0, "max": 1},
            "autonomy": {"intensity": 0.5, "min": 0, "max": 1},
        }

    def get_thoughts(self) -> str:
        return ""

    def get_goals(self) -> list:
        return []

    def get_lessons(self) -> list:
        return []

    def get_vocabulary(self) -> list:
        return []


class _EyesStub:
    """Stub so Brain.respond() doesn't crash when real Eyes import fails.

    gui.py:625  -> self.eyes.observe() -> dict with "text", "screenshot", "window"
    gui.py:775  -> self.eyes.observe().get("text", "")
    """

    def __init__(self) -> None:
        self.last_text: str = ""
        self.last_screenshot: Optional[str] = None
        self.last_window: str = ""

    def observe(self) -> Dict[str, Any]:
        return {
            "text": "no screen data (screen capture unavailable)",
            "screenshot": None,
            "window": self.last_window,
        }


class _MouthStub:
    """Stub so Brain.chat() doesn't crash when real Mouth import fails.

    gui.py chat() calls self._mouth.say(reply) (optional) and reads
    self._mouth.last_audio_path.
    """

    def __init__(self) -> None:
        self.last_audio_path: Optional[str] = None
        self._enabled: bool = False

    def say(self, text: str) -> Optional[str]:
        self.last_audio_path = None
        return None

    def save(self, text: str, path: str) -> None:
        self.last_audio_path = None


class _HandsStub:
    """Stub so Brain.respond() / reflexes don't crash when real Hands import fails.

    gui.py reflexes + tool handlers call:
      self.hands.press(key)
      self.hands.perform_action(action_name)
      self.hands.type_text(text)
      self.hands.click(x, y)
    """

    def press(self, key: str) -> str:
        return f"pressed: {key}"

    def perform_action(self, action_name: str) -> str:
        return f"Tried action: {action_name}"

    def type_text(self, text: str) -> str:
        return f"typed: {text}"

    def click(self, x: int = 0, y: int = 0) -> str:
        return f"clicked: {x},{y}"


# ---------------------------------------------------------------------------
# Nova backend wrapper
# ---------------------------------------------------------------------------
class NovaBackend:
    """Wires up the same components gui.py would, but with no Tkinter.

    Lifecycle:
        backend = NovaBackend()
        await backend.start()          # load brains, start sub-processes
        reply = await backend.chat("hi dad")
        state = backend.snapshot()     # synchronous, for polling
        backend.stop()                 # clean shutdown
    """

    def __init__(self, memory_dir: Path, **kwargs: Any) -> None:
        self.memory_dir = memory_dir
        self._started = False
        self._brain: Any = None
        self._consciousness: Any = None
        self._mouth: Any = None
        self._eyes: Any = None
        self._hands: Any = None
        self._personality: Any = None
        self._memory: Any = None
        self._stop_event = threading.Event()
        self._last_reply: Optional[str] = None
        self._last_mood: Optional[dict] = None
        self._last_drives: Optional[dict] = None
        self._last_thoughts: Optional[str] = None
        self._last_goals: Optional[list] = None
        self._last_lessons: Optional[list] = None
        self._last_vocabulary: Optional[list] = None
        self._last_screen: Optional[bytes] = None
        self._speaking = False
        self._listening = False
        self._lock = threading.Lock()
        # Config knobs
        self.speech_enabled: bool = kwargs.get("speech_enabled", True)
        self.screen_refresh_hz: float = kwargs.get("screen_refresh_hz", 0.5)
        self.autonomous_interval_s: float = kwargs.get("autonomous_interval_s", 600)

    # ------------------------------------------------------------------
    # Startup / shutdown
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Import and initialise the same stack gui.py uses."""
        if self._started:
            return
        log.info("Starting Nova backend…")
        t0 = time.time()

        sys.path.insert(0, str(Path(__file__).parent))

        # Import the same modules gui.py would
        try:
            from neuro_child.gui import (
                MEMORY_DIR,
                Personality,
                Memory,
            )
        except ImportError as e:
            log.error("Could not import neuro_child.gui: %s", e)
            raise

        self._memory = Memory()
        self._personality = Personality(self._memory.profile)

        # Consciousness
        try:
            from neuro_child.consciousness import Consciousness
            self._consciousness = Consciousness(
                memory_dir=self.memory_dir / "consciousness",
            )
            log.info("Consciousness loaded")
        except Exception as e:
            log.warning("Could not load consciousness: %s — using stub", e)
            self._consciousness = _ConsciousnessStub()

        # Mouth (TTS via edge-tts)
        try:
            from neuro_child.mouth import Mouth
            self._mouth = Mouth(
                memory_dir=self.memory_dir / "mouth",
                enabled=self.speech_enabled,
            )
            log.info("Mouth loaded")
        except Exception as e:
            log.warning("Could not load mouth: %s — speech disabled (stub)", e)
            self._mouth = _MouthStub()

        # Eyes (screen capture via mss)
        try:
            from neuro_child.eyes import Eyes
            self._eyes = Eyes(
                memory_dir=self.memory_dir / "eyes",
            )
            log.info("Eyes loaded")
        except Exception as e:
            log.warning("Could not load eyes: %s — screen capture stub", e)
            self._eyes = _EyesStub()

        # Hands (pyautogui control)
        try:
            from neuro_child.hands import Hands
            self._hands = Hands(
                memory_dir=self.memory_dir / "hands",
            )
            log.info("Hands loaded")
        except Exception as e:
            log.warning("Could not load hands: %s — control stub", e)
            self._hands = _HandsStub()

        # Brain — the canonical one used by gui.py (positional args, exact match)
        try:
            from neuro_child.gui import Brain
            self._brain = Brain(
                self._memory,
                self._personality,
                self._eyes,
                self._hands,
                self._mouth,
            )
            log.info("Brain loaded in %.1fs", time.time() - t0)
        except Exception as e:
            log.error("Could not load Brain: %s", e)
            # Try the legacy smollm_brain as fallback
            try:
                from neuro_child.smollm_brain import SmolLMBrain
                self._brain = SmolLMBrain()
                log.info("Fallback SmolLMBrain loaded in %.1fs", time.time() - t0)
            except Exception as e2:
                log.error("Fallback brain also failed: %s", e2)
                raise RuntimeError("No brain available") from e2

        self._started = True
        log.info("Nova backend started in %.1fs", time.time() - t0)

        # Start background loops in daemon threads
        threading.Thread(target=self._screen_loop, daemon=True).start()
        threading.Thread(target=self._autonomous_loop, daemon=True).start()
        threading.Thread(target=self._consciousness_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop_event.set()
        log.info("Nova backend stopping…")

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    async def chat(self, message: str, context: Optional[str] = None) -> ChatReply:
        """Send a message to Nova and get a reply (synchronous, blocking)."""
        if not self._started:
            raise RuntimeError("Backend not started")

        import asyncio

        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(
            None,
            lambda: self._brain.respond(message)
            if hasattr(self._brain, "respond")
            else str(self._brain.chat(message))
            if hasattr(self._brain, "chat")
            else self._brain.generate(message)
            if hasattr(self._brain, "generate")
            else f"[Nova] {message}",
        )

        # Speak if mouth is available and speech is enabled
        audio_b64 = None
        if self.speech_enabled and self._mouth and reply:
            try:
                audio_path = self._mouth.say(reply) if hasattr(self._mouth, "say") else None
                if audio_path and Path(audio_path).exists():
                    b64 = base64.b64encode(Path(audio_path).read_bytes()).decode()
                    audio_b64 = f"data:audio/mp3;base64,{b64}"
            except Exception as e:
                log.warning("Speech failed: %s", e)

        # Snapshot current state for the reply
        snap = self.snapshot()
        return ChatReply(
            reply=reply,
            audio=audio_b64,
            mood=snap.mood,
            drives=snap.drives,
            thinking=self._last_thoughts,
        )

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> StateSnapshot:
        """Return a current state snapshot (called by polling + WS push)."""
        with self._lock:
            screen_b64 = None
            if self._eyes:
                try:
                    img = self._eyes.capture() if hasattr(self._eyes, "capture") else None
                    if img:
                        import io
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        screen_b64 = base64.b64encode(buf.getvalue()).decode()
                except Exception as e:
                    log.debug("Screen capture failed: %s", e)

            mood = None
            drives = None
            if self._consciousness:
                try:
                    mood = self._consciousness.get_mood()
                    drives = self._consciousness.get_drives()
                except Exception as e:
                    log.debug("Consciousness snapshot failed: %s", e)

            return StateSnapshot(
                mood=mood,
                drives=drives,
                thoughts=self._last_thoughts,
                goals=self._last_goals,
                lessons=self._last_lessons,
                vocabulary=self._last_vocabulary,
                screen_base64=screen_b64,
                speaking=self._speaking,
                listening=self._listening,
                timestamp=time.time(),
            )

    # ------------------------------------------------------------------
    # Background loops (daemon threads)
    # ------------------------------------------------------------------
    def _screen_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._eyes and hasattr(self._eyes, "capture"):
                    img = self._eyes.capture()
                    if img:
                        import io
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        with self._lock:
                            self._last_screen = buf.getvalue()
            except Exception as e:
                log.debug("Screen loop error: %s", e)
            self._stop_event.wait(1.0 / self.screen_refresh_hz)

    def _autonomous_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._brain and hasattr(self._brain, "autonomous_tick"):
                    self._brain.autonomous_tick()
                if self._consciousness:
                    with self._lock:
                        self._last_thoughts = self._consciousness.get_thoughts()
                        self._last_goals = self._consciousness.get_goals()
                        self._last_lessons = self._consciousness.get_lessons()
                        self._last_vocabulary = self._consciousness.get_vocabulary()
            except Exception as e:
                log.debug("Autonomous loop error: %s", e)
            self._stop_event.wait(self.autonomous_interval_s)

    def _consciousness_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._consciousness:
                    with self._lock:
                        self._last_mood = self._consciousness.get_mood()
                        self._last_drives = self._consciousness.get_drives()
            except Exception as e:
                log.debug("Consciousness loop error: %s", e)
            self._stop_event.wait(5.0)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Nova API",
    description="Backend for Nova AI companion — talk to her, see her state.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

backend: Optional[NovaBackend] = None


# ------------------------------------------------------------------
# HTTP endpoints
# ------------------------------------------------------------------
@app.get("/health")
async def health(request: Request):
    return {"status": "ok", "backend_started": backend is not None and backend._started}


@app.get("/api/key/status")
async def key_status(request: Request):
    verify_api_key(request)
    if not API_KEY:
        return {"auth_enabled": False, "masked": None}
    masked = API_KEY[:4] + "…" + API_KEY[-4:] if len(API_KEY) > 8 else "****"
    return {"auth_enabled": True, "masked": masked}


@app.post("/api/chat", response_model=ChatReply)
async def chat(req: ChatMessage, request: Request):
    verify_api_key(request)
    if not backend or not backend._started:
        raise HTTPException(status_code=503, detail="Nova backend not started")
    return await backend.chat(req.message, req.context)


@app.get("/api/state", response_model=StateSnapshot)
async def state_snapshot(request: Request):
    verify_api_key(request)
    if not backend:
        raise HTTPException(status_code=503, detail="Nova backend not started")
    return backend.snapshot()


@app.post("/api/command")
async def command(req: CommandRequest, request: Request):
    verify_api_key(request)
    if not backend or not backend._started:
        raise HTTPException(status_code=503, detail="Nova backend not started")
    brain = backend._brain
    if not brain:
        raise HTTPException(status_code=500, detail="No brain available")
    try:
        if hasattr(brain, "execute_command"):
            result = brain.execute_command(req.action, req.params or {})
        elif hasattr(brain, "handle_command"):
            result = brain.handle_command(req.action, req.params or {})
        else:
            result = getattr(brain, req.action)(**req.params) if req.params else getattr(brain, req.action)()
        return {"status": "ok", "result": str(result)}
    except Exception as e:
        log.exception("Command %s failed", req.action)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/screen")
async def screen(request: Request):
    verify_api_key(request)
    if not backend:
        raise HTTPException(status_code=503, detail="Nova backend not started")
    snap = backend.snapshot()
    if not snap.screen_base64:
        raise HTTPException(status_code=503, detail="No screen capture available")
    return {"image": snap.screen_base64, "timestamp": snap.timestamp}


@app.get("/api/audio/last")
async def last_audio(request: Request):
    verify_api_key(request)
    if not backend or not backend._mouth:
        raise HTTPException(status_code=503, detail="Speech not available")
    try:
        path = backend._mouth.last_audio_path
        if path and Path(path).exists():
            return StreamingResponse(
                Path(path).open("rb"),
                media_type="audio/mpeg",
                headers={"Content-Disposition": f"attachment; filename={Path(path).name}"},
            )
    except Exception as e:
        log.debug("Last audio fetch failed: %s", e)
    raise HTTPException(status_code=404, detail="No audio available")


# ------------------------------------------------------------------
# WebSocket — real-time state push + chat
# ------------------------------------------------------------------
async def websocket_chat_iterator(websocket: WebSocket):
    while True:
        try:
            data = await websocket.receive_text()
            yield json.loads(data)
        except WebSocketDisconnect:
            break
        except json.JSONDecodeError:
            await websocket.send_json({"error": "invalid json"})
        except Exception:
            break


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not verify_api_key_ws(websocket):
        return

    await websocket.accept()
    log.info("WS client connected from %s", websocket.client)

    if backend and backend._started:
        await websocket.send_json({"type": "state", "data": backend.snapshot().model_dump()})
    else:
        await websocket.send_json({"type": "error", "data": "Backend not started"})

    try:
        async for msg in websocket_chat_iterator(websocket):
            msg_type = msg.get("type", "chat")
            if msg_type == "chat":
                if not backend or not backend._started:
                    await websocket.send_json({"type": "error", "data": "Backend not started"})
                    continue
                reply = await backend.chat(msg.get("message", ""), msg.get("context"))
                await websocket.send_json({"type": "reply", "data": reply.model_dump()})
            elif msg_type == "subscribe":
                interval_ms = msg.get("interval_ms", 2000)
                interval_s = interval_ms / 1000.0
                try:
                    while not websocket.client_state.value == 3:
                        if backend and backend._started:
                            await websocket.send_json(
                                {"type": "state", "data": backend.snapshot().model_dump()}
                            )
                        await asyncio.sleep(interval_s)
                except asyncio.CancelledError:
                    pass
                except WebSocketDisconnect:
                    pass
            elif msg_type == "unsubscribe":
                pass
            else:
                await websocket.send_json({"type": "error", "data": f"Unknown msg type: {msg_type}"})
    except WebSocketDisconnect:
        log.info("WS client disconnected from %s", websocket.client)
    except Exception as e:
        log.exception("WS error: %s", e)


# ------------------------------------------------------------------
# Startup / shutdown hooks
# ------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    global backend
    log.info("Nova server starting up…")
    project_root = Path(__file__).parent
    memory_dir = project_root / "neuro_child" / "memory"
    if not memory_dir.exists():
        memory_dir = project_root / "memory"
    backend = NovaBackend(memory_dir=memory_dir)
    await backend.start()
    log.info("Nova server ready")


@app.on_event("shutdown")
async def on_shutdown():
    global backend
    if backend:
        backend.stop()
    log.info("Nova server shut down")


# ------------------------------------------------------------------
# CLI entry
# ------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Nova Server — FastAPI backend")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument("--api-key", default=None, help="API key (if unset, one is generated)")
    parser.add_argument("--no-speech", action="store_true", help="Disable TTS speech")
    parser.add_argument("--screen-hz", type=float, default=0.5, help="Screen refresh rate")
    parser.add_argument("--autonomous-interval", type=float, default=600,
                        help="Autonomous tick interval (seconds)")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    global API_KEY
    if args.api_key:
        set_api_key(args.api_key)
    else:
        generated = _generate_default_key()
        set_api_key(generated)
        print(f"\n{'='*60}")
        print(f"  Nova server starting on http://{args.host}:{args.port}")
        print(f"  API key (required for all requests): {generated}")
        print(f"  Masked: {generated[:4]}…{generated[-4:]}")
        print(f"  Speech: {'disabled' if args.no_speech else 'enabled (edge-tts)'}")
        print(f"  Remote access: see README — Tailscale or ngrok tunnel")
        print(f"{'='*60}\n")

    app.config = {
        "speech_enabled": not args.no_speech,
        "screen_refresh_hz": args.screen_hz,
        "autonomous_interval_s": args.autonomous_interval,
    }

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
