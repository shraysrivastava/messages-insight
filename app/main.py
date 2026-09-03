#!/usr/bin/env python3
"""
main.py — the live game. Host screen on a laptop, two phones, one URL.

    python3 -m app.main --data datasets/demo.json
    python3 -m app.main --data datasets/demo.json --port 8000

`app/game.py` owns the rules and holds no framework imports. This file owns
everything it deliberately doesn't: the clock, the sockets, and the two people
on the other end of a network that is not going to be perfect.

Three things here that the POC didn't have:

**A join code** (`S2.3`). `Game.code` has always generated one; nothing used
it. Now a player has to present it to join, and it rides along in the QR so her
scan skips the typing. A stray visitor gets a join screen instead of five years
of your messages.

**Client-timestamped answers** (`S2.4`). You are in different states. Timing an
answer by when it *arrives* hands the higher-latency player a permanent
handicap, on a scoring model where speed is worth 2x. So each client estimates
its offset from server time with a ping/pong round trip, sends the answer
stamped with its own corrected clock, and the server clamps that into the
question window (`Game._clamp_time`). Clamping is the whole anti-cheat story:
you can claim you answered early, but not before the question existed.

**A heartbeat** (`S2.5`). Ping every 25 seconds, both directions. Fly's proxy
drops an idle WebSocket around 60, and a lobby sits idle for exactly as long as
it takes two people to settle onto a sofa.

## The protocol

Client → server

    {t:"hello", role:"host"|"player", token?}   claim the host screen
    {t:"join",  id, name, code}                 code must match, else denied
    {t:"answer", id, value, at}                 `at` is client-estimated server time
    {t:"start"|"next"|"skip"|"reset"}           host only
    {t:"ping", c0}                              clock sync + keepalive

Server → client

    {t:"state", ...}          Game.snapshot() — never leaks an answer early
    {t:"welcome", role, token, code?}           `code` only for the host
    {t:"denied", why}
    {t:"pong", c0, s}         c0 echoed back, s is server time
    {t:"ping", s}             heartbeat; the client answers with a pong

The host screen is claimed by the first socket that asks, and reclaimed after a
reload with the token it was given. Anyone who can read the join code off the
screen can also claim it — that's the recovery path, and it's printed at boot.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import secrets
import socket
import sys
import time
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.datasets import Library, Locked
from app.game import DealRules, Game
from app.schema import Dataset, load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")

COUNTDOWN = 3.0
HEARTBEAT = 25.0        # Fly drops an idle socket at ~60
TICK = 0.2              # how often the question loop checks the clock

G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


class Room:
    """One game, its sockets, and its clock.

    Every transition here is `await something` then `broadcast`. The rules live
    in Game; this class only decides *when*.
    """

    def __init__(self, game: Game, library: Library | None = None):
        self.game = game
        self.library = library
        self.sockets: dict[WebSocket, dict] = {}    # ws -> {role, pid}
        self.timer: asyncio.Task | None = None
        self.heart: asyncio.Task | None = None
        self.host_token = secrets.token_urlsafe(12)
        self.host_claimed = False

    # ── talking ───────────────────────────────────────────────────────────

    async def send(self, ws: WebSocket, msg: dict) -> bool:
        try:
            await ws.send_text(json.dumps(msg))
            return True
        except Exception:
            self.sockets.pop(ws, None)
            return False

    def view(self, meta: dict | None = None) -> dict:
        """What one socket may see.

        `Game.snapshot()` redacts by *phase* — no answer before the reveal.
        This redacts by *role*, which is a different question and belongs
        here, where the roles live. The join code is on the host screen and
        nowhere else; a socket that hasn't proved it's the host must not be
        handed the very thing that would let it join."""
        snap = self.game.snapshot()
        if not meta or meta.get("role") != "host":
            snap["code"] = None
            return snap
        if self.library:
            snap["datasets"] = self.library.state()
        return snap

    async def broadcast(self) -> None:
        host = json.dumps(self.view({"role": "host"}))
        rest = json.dumps(self.view())
        for ws, meta in list(self.sockets.items()):
            try:
                await ws.send_text(host if meta.get("role") == "host" else rest)
            except Exception:
                self.sockets.pop(ws, None)

    async def beat(self) -> None:
        """Keepalive. Also the thing that notices a phone that went away
        without closing its socket."""
        while True:
            await asyncio.sleep(HEARTBEAT)
            now = time.time()
            for ws in list(self.sockets):
                await self.send(ws, {"t": "ping", "s": now})

    # ── the clock ─────────────────────────────────────────────────────────

    def cancel(self) -> None:
        if self.timer and not self.timer.done():
            self.timer.cancel()
        self.timer = None

    async def _countdown(self) -> None:
        try:
            await asyncio.sleep(COUNTDOWN)
            await self.open_question()
        except asyncio.CancelledError:
            pass

    async def _question(self) -> None:
        """End on the buzzer, or as soon as everyone still connected has
        answered. `live()` is why a dropped phone doesn't hold the round."""
        try:
            while True:
                left = (self.game.ends_at or 0) - time.time()
                if left <= 0 or self.game.everyone_answered():
                    break
                await asyncio.sleep(TICK)
            await self.close_question()
        except asyncio.CancelledError:
            pass

    async def start_round(self, index: int) -> None:
        self.cancel()
        self.game.begin_round(index)
        await self.broadcast()
        self.timer = asyncio.create_task(self._countdown())

    async def open_question(self) -> None:
        self.game.open_question()
        await self.broadcast()
        self.timer = asyncio.create_task(self._question())

    async def close_question(self) -> None:
        self.cancel()
        self.game.close_question()
        await self.broadcast()

    async def advance(self) -> None:
        if self.game.has_next():
            await self.start_round(self.game.round + 1)
        else:
            self.cancel()
            self.game.finish()
            await self.broadcast()

    async def restart(self) -> None:
        """Play again with the same people, the same names, the same colours —
        and a fresh deck, because `deal()` re-rolls."""
        self.cancel()
        keep = {pid: (p.name, p.color) for pid, p in self.game.players.items()}
        self.game.reset()
        for pid, (name, color) in keep.items():
            self.game.add_player(pid, name).color = color
        await self.broadcast()

    def swap(self, data: Dataset, which: str) -> None:
        """Put a different dataset behind the same lobby.

        The join code and everyone already on it survive — the phones are in
        her hand and on the sofa, and making them rejoin because you changed
        your mind about which game to play would be its own small disaster.
        """
        old = self.game
        fresh = Game(data, rounds=old.rounds if old.rounds != len(old.bank) else None,
                     seconds=old.seconds, rules=old.rules, rng=old.rng)
        fresh.code = old.code
        for pid, p in old.players.items():
            fresh.add_player(pid, p.name).color = p.color
        self.game = fresh
        if self.library:
            self.library.current = which

    # ── one message ───────────────────────────────────────────────────────

    async def handle(self, ws: WebSocket, msg: dict) -> None:
        kind = msg.get("t")
        meta = self.sockets.setdefault(ws, {"role": "unknown", "pid": None})
        g = self.game

        if kind == "ping":
            await self.send(ws, {"t": "pong", "c0": msg.get("c0"),
                                 "s": time.time()})
            return
        if kind == "pong":
            return

        if kind == "hello":
            if msg.get("role") == "host" and self.may_host(msg):
                meta["role"] = "host"
                self.host_claimed = True
                await self.send(ws, {"t": "welcome", "role": "host",
                                     "token": self.host_token, "code": g.code})
            else:
                meta["role"] = "player" if msg.get("role") == "player" else "watcher"
                await self.send(ws, {"t": "welcome", "role": meta["role"]})
            await self.send(ws, self.view(meta))
            return

        if kind == "join":
            if not self.code_ok(msg.get("code")):
                await self.send(ws, {"t": "denied", "why": "code"})
                return
            pid = str(msg.get("id") or "")[:40]
            if not pid:
                return
            g.add_player(pid, msg.get("name", ""))
            meta["pid"] = pid
            if meta["role"] != "host":
                # Hosting and playing from one browser is a fair thing to do.
                # Joining shouldn't quietly cost you the controls.
                meta["role"] = "player"
            await self.send(ws, {"t": "welcome", "role": "player"})
            await self.broadcast()
            return

        if kind == "answer":
            # Only a socket that joined may answer, and only for itself.
            if meta["pid"] and meta["pid"] == msg.get("id"):
                if g.record_answer(meta["pid"], msg.get("value"),
                                   _number(msg.get("at"))):
                    await self.broadcast()
            return

        if meta["role"] != "host":
            return                                  # everything below is control

        if kind == "start" and g.phase == "lobby" and g.players:
            g.deal()
            await self.start_round(0)
        elif kind == "next" and g.phase == "reveal":
            await self.advance()
        elif kind == "skip" and g.phase == "question":
            await self.close_question()
        elif kind == "reset":
            await self.restart()
        elif kind == "dataset":
            await self.choose(ws, msg)

    async def choose(self, ws: WebSocket, msg: dict) -> None:
        """Switch datasets. Lobby only — swapping decks mid-game would rewrite
        the scoreboard's history under everyone."""
        if not self.library or self.game.phase != "lobby":
            await self.send(ws, {"t": "denied", "why": "not in the lobby"})
            return
        which = str(msg.get("id") or "demo")
        try:
            data = self.library.load(which, msg.get("pass"))
        except Locked as e:
            await self.send(ws, {"t": "denied", "why": str(e)})
            await self.send(ws, self.view(self.sockets.get(ws)))
            return
        self.swap(data, which)
        await self.broadcast()

    def may_host(self, msg: dict) -> bool:
        """First one in claims it; a reload reclaims it with the token; anyone
        reading the code off the screen can take it back."""
        if not self.host_claimed:
            return True
        if secrets.compare_digest(str(msg.get("token") or ""), self.host_token):
            return True
        return self.code_ok(msg.get("code"))

    def code_ok(self, given) -> bool:
        return secrets.compare_digest(
            str(given or "").strip().upper(), self.game.code)

    async def drop(self, ws: WebSocket) -> None:
        """A phone that goes away shouldn't hold the round open to the buzzer."""
        meta = self.sockets.pop(ws, None)
        if not meta:
            return

        # Let go of the host screen when nobody is holding it. Otherwise
        # closing the tab locks the controls away for the life of the process,
        # and the only way back in is the code — which was on the screen you
        # just closed. The token still wins the screen back either way.
        if meta.get("role") == "host" and not any(
                m.get("role") == "host" for m in self.sockets.values()):
            self.host_claimed = False

        if not meta.get("pid"):
            return
        p = self.game.players.get(meta["pid"])
        if p and not any(m.get("pid") == meta["pid"]
                         for m in self.sockets.values()):
            p.online = False
            await self.broadcast()


def _number(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) \
        else None


# ── the app ───────────────────────────────────────────────────────────────

def create_app(room: Room, static_dir: str = STATIC) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.room.heart = asyncio.create_task(app.state.room.beat())
        try:
            yield
        finally:
            app.state.room.heart.cancel()
            app.state.room.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.room = room

    @app.get("/")
    def host_page():
        return FileResponse(os.path.join(static_dir, "host.html"))

    @app.get("/play")
    def player_page():
        return FileResponse(os.path.join(static_dir, "player.html"))

    @app.get("/healthz")
    def healthz():
        g = app.state.room.game
        return {"ok": True, "phase": g.phase, "players": len(g.players),
                "sockets": len(app.state.room.sockets)}

    @app.get("/qr.svg")
    def qr(base: str = ""):
        """The join link with the code already in it, so her scan is the whole
        journey. `base` is the host page's own origin, which is what makes this
        point somewhere reachable from behind a tunnel."""
        try:
            import segno
        except ImportError:
            return Response(status_code=404)
        origin = base.rstrip("/") or f"http://{local_ip()}:8000"
        buf = io.BytesIO()
        # svg_inline() drops the xmlns, which breaks it as an <img> source.
        segno.make(f"{origin}/play?c={app.state.room.game.code}", error="m").save(
            buf, kind="svg", scale=5, border=2,
            dark="#EFE7DE", light=None, xmldecl=False, svgns=True)
        return Response(content=buf.getvalue(), media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        r = app.state.room
        await ws.accept()
        r.sockets[ws] = {"role": "unknown", "pid": None}
        await r.send(ws, r.view())
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict):
                    await r.handle(ws, msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await r.drop(ws)

    return app


# ── boot ──────────────────────────────────────────────────────────────────

def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def build_room(data: Dataset, rounds: int | None, seconds: float | None,
               library: Library | None = None) -> Room:
    return Room(Game(data, rounds=rounds, seconds=seconds, rules=DealRules()),
                library=library)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("## ")[0])
    ap.add_argument("--data", default="datasets/demo.json")
    ap.add_argument("--rounds", type=int)
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    path = args.data if os.path.isabs(args.data) else os.path.join(ROOT, args.data)
    if not os.path.exists(path):
        raise SystemExit(f"{R}No dataset at {path}{X}\n"
                         f"  make demo      builds the safe fake one\n"
                         f"  make compile   builds the real one")
    library = Library()
    room = build_room(load(path), args.rounds, args.seconds, library=library)
    g = room.game
    ip = local_ip()
    sealed = (f"    Real data                 {D}on the host screen, "
              f"behind the passphrase{X}\n"
              if any(o["id"] == "real" for o in library.options()) else "")

    print(f"""
  {B}Read Receipts{X} is live.

    Host screen (laptop/TV)   {G}http://{ip}:{args.port}/{X}
    Phones join at            {G}http://{ip}:{args.port}/play{X}

    Join code                 {B}{g.code}{X}   {D}(also in the QR){X}
{sealed}
  {len(g.bank)} questions · {g.rounds} rounds · {g.seconds:.0f}s each
  {D}yours {sum(1 for q in g.bank if q.origin == 'mine')} · """
          f"""generated {sum(1 for q in g.bank if q.origin != 'mine')}{X}
""", flush=True)      # unbuffered, or `fly logs` shows nothing for a minute

    import uvicorn
    uvicorn.run(create_app(room), host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
