#!/usr/bin/env python3
"""
server.py — the live game. Host screen on a laptop, players on their phones.

    python3 server.py --data game_data.json

Then open the printed URL on the laptop for the host screen; phones join at
the same address. To play from different places, leave this running and put a
tunnel in front of it (see README) — the data never leaves your machine.
"""

import argparse
import asyncio
import json
import os
import random
import socket
import string
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

COLORS = ["#F2A65A", "#8B8CE8", "#7BD389", "#E8709A", "#5FC9D6", "#D9C05A"]
COUNTDOWN = 3.0

app = FastAPI()


# --------------------------------------------------------------------- state


class Game:
    def __init__(self, data, rounds, seconds):
        self.data = data
        self.bank = data["questions"]
        self.meta = data["meta"]
        self.rounds = min(rounds or self.meta.get("rounds", 12), len(self.bank))
        self.seconds = seconds
        self.code = "".join(random.choices(string.ascii_uppercase, k=4))
        self.sockets = {}  # ws -> role
        self.reset()

    # ---- lifecycle

    def reset(self):
        self.phase = "lobby"
        self.round = -1
        self.deck = []
        self.players = {}
        self.ends_at = None
        self.timer = None

    def deal(self):
        bank = self.bank[:]
        random.shuffle(bank)
        buckets = {}
        for q in bank:
            buckets.setdefault(q["kind"], []).append(q)
        deck, lists = [], list(buckets.values())
        while len(deck) < self.rounds:
            dealt = False
            for lst in lists:
                if len(deck) >= self.rounds:
                    break
                if lst:
                    deck.append(lst.pop())
                    dealt = True
            if not dealt:
                break
        self.deck = deck

    # ---- players

    def add_player(self, pid, name):
        if pid in self.players:
            self.players[pid]["online"] = True
            return
        used = {p["color"] for p in self.players.values()}
        color = next((c for c in COLORS if c not in used), COLORS[0])
        self.players[pid] = {
            "id": pid,
            "name": name[:18] or "Player",
            "color": color,
            "score": 0,
            "answer": None,
            "answered_at": None,
            "last": None,
            "online": True,
        }

    @property
    def question(self):
        if 0 <= self.round < len(self.deck):
            return self.deck[self.round]
        return None

    def everyone_answered(self):
        live = [p for p in self.players.values() if p["online"]]
        return bool(live) and all(p["answer"] is not None for p in live)

    # ---- scoring

    def accuracy(self, q, guess):
        if guess is None:
            return 0.0
        if q["type"] in ("binary", "choice"):
            return 1.0 if guess == q["answer"] else 0.0
        if q["type"] == "number":
            off = abs(guess - q["answer"]) / max(q["answer"], 1)
            return max(0.0, 1.0 - off)
        if q["type"] == "month":
            span = max(len(self.meta["months"]), 6) / 3
            return max(0.0, 1.0 - abs(guess - q["answer"]) / span)
        return 0.0

    def grade(self):
        q = self.question
        started = (self.ends_at or 0) - self.seconds
        for p in self.players.values():
            acc = self.accuracy(q, p["answer"])
            if acc <= 0:
                pts = 0
            else:
                elapsed = max(0.0, (p["answered_at"] or self.ends_at) - started)
                speed = 1 - 0.5 * min(1.0, elapsed / self.seconds)
                pts = round(1000 * acc * speed)
            p["last"] = {"points": pts, "accuracy": round(acc, 3),
                         "answer": p["answer"]}
            p["score"] += pts

    # ---- snapshot

    def snapshot(self):
        q = self.question
        revealed = self.phase in ("reveal", "final")
        pub = None
        if q and self.phase in ("countdown", "question", "reveal"):
            pub = {k: q[k] for k in ("type", "kind", "prompt", "text", "options")
                   if k in q}
            if revealed:
                pub["answer"] = q["answer"]
                pub["reveal"] = q["reveal"]

        board = sorted(self.players.values(), key=lambda p: -p["score"])
        return {
            "t": "state",
            "phase": self.phase,
            "code": self.code,
            "round": self.round,
            "rounds": len(self.deck) or self.rounds,
            "seconds": self.seconds,
            "endsAt": self.ends_at,
            "now": time.time(),
            "question": pub,
            "answered": [p["id"] for p in self.players.values()
                         if p["answer"] is not None],
            "players": [
                {k: p[k] for k in ("id", "name", "color", "score", "online")}
                | ({"last": p["last"]} if revealed else {})
                for p in board
            ],
            "meta": {
                "p1": self.meta.get("p1"),
                "p2": self.meta.get("p2"),
                "months": self.meta.get("months", []),
                "total": self.meta.get("total"),
                "first": self.meta.get("first"),
                "last": self.meta.get("last"),
            },
        }


game: Game = None


# ----------------------------------------------------------------- broadcast


async def broadcast():
    payload = json.dumps(game.snapshot())
    dead = []
    for ws in list(game.sockets):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        game.sockets.pop(ws, None)


def cancel_timer():
    if game.timer and not game.timer.done():
        game.timer.cancel()
    game.timer = None


async def run_countdown():
    try:
        await asyncio.sleep(COUNTDOWN)
        await open_question()
    except asyncio.CancelledError:
        pass


async def run_question():
    try:
        while True:
            remaining = (game.ends_at or 0) - time.time()
            if remaining <= 0 or game.everyone_answered():
                break
            await asyncio.sleep(0.2)
        await close_question()
    except asyncio.CancelledError:
        pass


async def start_round(index):
    cancel_timer()
    game.round = index
    game.phase = "countdown"
    game.ends_at = None
    for p in game.players.values():
        p["answer"] = None
        p["answered_at"] = None
        p["last"] = None
    await broadcast()
    game.timer = asyncio.create_task(run_countdown())


async def open_question():
    game.phase = "question"
    game.ends_at = time.time() + game.seconds
    await broadcast()
    game.timer = asyncio.create_task(run_question())


async def close_question():
    cancel_timer()
    game.grade()
    game.phase = "reveal"
    game.ends_at = None
    await broadcast()


async def advance():
    if game.round + 1 >= len(game.deck):
        cancel_timer()
        game.phase = "final"
        await broadcast()
    else:
        await start_round(game.round + 1)


# --------------------------------------------------------------------- http


@app.get("/")
async def host_page():
    return FileResponse(os.path.join(STATIC, "host.html"))


@app.get("/play")
async def player_page():
    return FileResponse(os.path.join(STATIC, "player.html"))


@app.get("/qr.svg")
async def qr(base: str = ""):
    """QR for the join link. `base` lets the host page pass its own origin,
    so this still points somewhere reachable when you're behind a tunnel."""
    try:
        import segno
    except ImportError:
        return Response(status_code=404)
    import io

    origin = base.rstrip("/") or f"http://{local_ip()}:{PORT}"
    buf = io.BytesIO()
    # svg_inline() drops the xmlns, which breaks it as an <img> source.
    segno.make(f"{origin}/play", error="m").save(
        buf, kind="svg", scale=5, border=2,
        dark="#EFE7DE", light=None, xmldecl=False, svgns=True,
    )
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------------------------------------------------------------- websocket


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    game.sockets[ws] = "unknown"
    await ws.send_text(json.dumps(game.snapshot()))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("t")

            if kind == "hello":
                game.sockets[ws] = msg.get("role", "player")

            elif kind == "join":
                game.add_player(msg["id"], msg.get("name", ""))
                game.sockets[ws] = "player"
                await broadcast()

            elif kind == "answer" and game.phase == "question":
                p = game.players.get(msg["id"])
                if p and p["answer"] is None:
                    p["answer"] = msg.get("value")
                    p["answered_at"] = time.time()
                    await broadcast()

            elif kind == "start" and game.phase == "lobby":
                if game.players:
                    game.deal()
                    await start_round(0)

            elif kind == "next" and game.phase == "reveal":
                await advance()

            elif kind == "skip" and game.phase == "question":
                await close_question()

            elif kind == "reset":
                cancel_timer()
                names = {pid: (p["name"], p["color"])
                         for pid, p in game.players.items()}
                game.reset()
                for pid, (name, color) in names.items():
                    game.add_player(pid, name)
                    game.players[pid]["color"] = color
                await broadcast()

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        game.sockets.pop(ws, None)


# --------------------------------------------------------------------- boot


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


PORT = 8000


def main():
    global game, PORT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="game_data.json")
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--seconds", type=float, default=25.0)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    PORT = args.port

    path = os.path.abspath(os.path.expanduser(args.data))
    if not os.path.exists(path):
        raise SystemExit(
            f"No data file at {path}\n"
            "Run make_fake_data.py for a playable dummy set, or build_game.py "
            "for the real thing."
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    game = Game(data, args.rounds, args.seconds)

    ip = local_ip()
    print(f"""
  Read Receipts is live.

    Host screen (laptop/TV)   http://{ip}:{PORT}/
    Phones join at            http://{ip}:{PORT}/play

  {len(game.bank)} questions loaded · {game.rounds} rounds · {args.seconds:.0f}s each
""")

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
