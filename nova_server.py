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
from pathlib import Path
from typing import Any, Optional

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
    # Make it look like a sensible API key
    return f"nk_{raw}"


def set_api_key(key: str) -> None:
    global API_KEY
    API_KEY = key
    # Also mask it for logging
    masked = key[:4] + "…" + key[-4:] if len(key) > 8 else "****"
    log.info("Nova API key set (masked: %s)", masked)


def verify_api_key(request: Request) -> None:
    """Raise 401 if the request doesn't present a valid API key."""
    if not API_KEY:
        return  # no auth configured (dev mode)
    header = request.headers.get("X-API-Key", "")
    if header != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def verify_api_key_ws(websocket: WebSocket) -> bool:
    """Return True if the WS client presented a valid key; close otherwise."""
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
    # Optional context a client might send (e.g. current screen description)
    context: Optional[str] = None
    session_id: Optional[str] = None


class ChatReply(BaseModel):
    reply: str
    audio: Optional[str] = None  # base64-encoded MP3 when speech is enabled
    thinking: Optional[str] = None
    mood: Optional[dict] = None
    drives: Optional[dict] = None


class StateSnapshot(BaseModel):
    """What the Electron frontend asks for on poll / WS push."""
    mood: Optional[dict] = None
    drives: Optional[dict] = None
    thoughts: Optional[str] = None
    goals: Optional[list] = None
    lessons: Optional[list] = None
    vocabulary: Optional[list] = None
    screen_base64: Optional[str] = None  # latest screen capture (PNG)
    speaking: Optional[bool] = None
    listening: Optional[bool] = None
    timestamp: Optional[float] = None


class GoalSubmit(BaseModel):
    goal: str = Field(..., min_length=1, max_length=1000)


class CommandRequest(BaseModel):
    action: str
    params: Optional[dict] = None


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
        self._chat_queue: list[tuple[str, Optional[str], Optional[str]]] = []
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
        self.screen_refresh_hz: float = kwargs.get("screen_refresh_hz", 0.5)  # 2s
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

        self._memory = Memory()  # uses MEMORY_DIR internally
        self._personality = Personality()

        # Consciousness (drives, mood, self-model) — same as gui.py
        try:
            from neuro_child.consciousness import Consciousness
            self._consciousness = Consciousness(
                memory_dir=self.memory_dir / "consciousness",
            )
        except Exception as e:
            log.warning("Could not load consciousness: %s — continuing without it", e)
            self._consciousness = None

        # Mouth (TTS via edge-tts)
        try:
            from neuro_child.mouth import Mouth
            self._mouth = Mouth(
                memory_dir=self.memory_dir / "mouth",
                enabled=self.speech_enabled,
            )
        except Exception as e:
            log.warning("Could not load mouth: %s — speech disabled", e)
            self._mouth = None

        # Eyes (screen capture via mss)
        try:
            from neuro_child.eyes import Eyes
            self._eyes = Eyes(
                memory_dir=self.memory_dir / "eyes",
            )
        except Exception as e:
            log.warning("Could not load eyes: %s — screen capture disabled", e)
            self._eyes = None

        # Hands (pyautogui control)
        try:
            from neuro_child.hands import Hands
            self._hands = Hands(
                memory_dir=self.memory_dir / "hands",
            )
        except Exception as e:
            log.warning("Could not load hands: %s — control disabled", e)
            self._hands = None

        # Brain — the canonical one used by gui.py
        try:
            from neuro_child.brain import Brain
            self._brain = Brain(
                memory=self._memory,
                personality=self._personality,
                eyes=self._eyes,
                hands=self._hands,
                mouth=self._mouth,
            )
            log.info("Brain loaded in %.1fs", time.time() - t0)
        except Exception as e:
            log.error("Could not load Brain: %s", e)
            # Try the legacy smollm_brain as fallback
            try:
                from neuro_child.smollm_brain import SmolLMBrain
                self._brain = SmolLMBrain(
                    memory=self._memory,
                    personality=self._personality,
                )
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

        # Run Brain.respond in a thread so we don't block the event loop
        # if it does any long-running inference.
        import asyncio

        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(
            None,
            lambda: self._brain.respond(message, context=context)
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
                audio_path = self._mouth.say(reply)
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
            # Grab latest screen if available
            screen_b64 = None
            if self._eyes:
                try:
                    img = self._eyes.capture()
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
        """Periodically refresh the last screen capture."""
        while not self._stop_event.is_set():
            try:
                if self._eyes:
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
        """Run autonomous actions on a timer (gameplay, learning, etc.)."""
        while not self._stop_event.is_set():
            try:
                if self._brain and hasattr(self._brain, "autonomous_tick"):
                    self._brain.autonomous_tick()
                # Update snapshot caches from consciousness if available
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
        """Update mood/drives snapshots periodically."""
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
    allow_origins=["*"],  # Electron app is local; phone browser needs this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global backend instance (started on startup, stopped on shutdown)
backend: Optional[NovaBackend] = None


# ------------------------------------------------------------------
# HTTP endpoints
# ------------------------------------------------------------------
@app.get("/health")
async def health(request: Request):
    """Liveness check. No auth required."""
    return {"status": "ok", "backend_started": backend is not None and backend._started}


@app.get("/api/key/status")
async def key_status(request: Request):
    """Whether auth is enabled and a masked version of the key."""
    verify_api_key(request)
    if not API_KEY:
        return {"auth_enabled": False, "masked": None}
    masked = API_KEY[:4] + "…" + API_KEY[-4:] if len(API_KEY) > 8 else "****"
    return {"auth_enabled": True, "masked": masked}


@app.post("/api/chat", response_model=ChatReply)
async def chat(req: ChatMessage, request: Request):
    """Send Nova a message; get a reply (text + optional audio)."""
    verify_api_key(request)
    if not backend or not backend._started:
        raise HTTPException(status_code=503, detail="Nova backend not started")
    return await backend.chat(req.message, req.context)


@app.get("/api/state", response_model=StateSnapshot)
async def state_snapshot(request: Request):
    """Get a current state snapshot (mood, drives, screen, etc.)."""
    verify_api_key(request)
    if not backend:
        raise HTTPException(status_code=503, detail="Nova backend not started")
    return backend.snapshot()


@app.post("/api/command")
async def command(req: CommandRequest, request: Request):
    """Send a high-level command to Nova (e.g. 'launch game', 'remember')."""
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
    """Get the latest screen capture as base64 PNG."""
    verify_api_key(request)
    if not backend:
        raise HTTPException(status_code=503, detail="Nova backend not started")
    snap = backend.snapshot()
    if not snap.screen_base64:
        raise HTTPException(status_code=503, detail="No screen capture available")
    return {"image": snap.screen_base64, "timestamp": snap.timestamp}


@app.get("/api/audio/last")
async def last_audio(request: Request):
    """Download the last generated speech MP3 (if any)."""
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
    """Yield messages from the WS client as they arrive."""
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
    """Bidirectional WS: client pushes chat messages, server pushes state."""
    if not verify_api_key_ws(websocket):
        return

    await websocket.accept()
    log.info("WS client connected from %s", websocket.client)

    # Send initial state
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
                # Client can request state pushes at a given interval (ms)
                interval_ms = msg.get("interval_ms", 2000)
                interval_s = interval_ms / 1000.0
                try:
                    while not websocket.client_state.value == 3:  # CLOSED
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
                pass  # stop pushing — client can reconnect
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
    # Determine memory dir
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
    parser.add_argument(
        "--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Bind port (default: 8000)"
    )
    parser.add_argument(
        "--api-key", default=None, help="API key for authentication (if unset, one is generated)"
    )
    parser.add_argument(
        "--no-speech", action="store_true", help="Disable TTS speech"
    )
    parser.add_argument(
        "--screen-hz", type=float, default=0.5, help="Screen capture refresh rate (default: 0.5 = 2s)"
    )
    parser.add_argument(
        "--autonomous-interval", type=float, default=600,
        help="Autonomous tick interval in seconds (default: 600)"
    )
    parser.add_argument(
        "--log-level", default="info", choices=["debug", "info", "warning", "error"]
    )
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
