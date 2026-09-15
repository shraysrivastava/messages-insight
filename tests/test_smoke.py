"""S4.7 — one whole game, start to finish, in one test.

Every other test here holds one part still and pokes it. This one runs the
sequence nobody performs by hand more than once a week, and which therefore
breaks quietly: an empty lobby, a deal, every round answered, a podium with
awards and a curve, the game landing on the shelf, the reel replaying it, and
a lobby that now has a history.

It drives `Room` and the protocol directly rather than a browser. Playwright
is not installed, and a headless Chrome inside the unit suite would be minutes
and a standing flake budget. The rendering is verified with the CDP harness by
hand; everything below is the half that can regress without anyone noticing.
"""
import asyncio
import json
import random

import pytest

import app.main as main
from app.game import DealRules, Game
from app.history import History
from app.main import Room, create_app
from tests.conftest import make_dataset
from tests.test_server import FakeSocket

ROUNDS = 5


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(main, "COUNTDOWN", 0.01)
    monkeypatch.setattr(main, "READ_BEAT", 0.01)
    monkeypatch.setattr(main, "TICK", 0.01)


@pytest.fixture
def table(tmp_path):
    hist = History(path=str(tmp_path / "history.jsonl"))
    g = Game(make_dataset(rounds=ROUNDS), rounds=ROUNDS, seconds=30.0,
             rules=DealRules(), rng=random.Random(11))
    return Room(g, history=hist), hist


async def seat(room, role="player", pid=None, name="Shray"):
    ws = FakeSocket()
    room.sockets[ws] = {"role": "unknown", "pid": None}
    await room.handle(ws, {"t": "hello", "role": role})
    if pid:
        await room.handle(ws, {"t": "join", "id": pid, "name": name,
                               "code": room.game.code})
    return ws


def reply(room, q, pick):
    """A type-appropriate answer. The deck is dealt, not chosen, so no round
    can be assumed to be a binary."""
    if q.type in ("binary", "choice"):
        return pick % len(q.options)
    if q.type == "month":
        return pick
    return 100 * (pick + 1)


async def settle(room, phase, tries=300):
    for _ in range(tries):
        if room.game.phase == phase:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"stuck in {room.game.phase}, wanted {phase}")


@pytest.mark.asyncio
async def test_a_whole_game_end_to_end(table):
    room, hist = table
    host = await seat(room, role="host")
    a = await seat(room, pid="a", name="Shray")
    b = await seat(room, pid="b", name="Nilu")
    assert len(room.game.players) == 2

    await room.handle(host, {"t": "start"})

    for i in range(ROUNDS):
        await settle(room, "question")
        q = room.game.question
        await room.handle(a, {"t": "answer", "id": "a", "value": reply(room, q, 0)})
        await room.handle(b, {"t": "answer", "id": "b", "value": reply(room, q, 1)})
        await settle(room, "reveal")
        assert host.last()["question"]["answer"] is not None or q.type == "mutual"
        await room.handle(host, {"t": "next"})

    await settle(room, "final")
    end = host.last()

    # everything the end screens draw from
    assert end["curve"]["rounds"] == ROUNDS
    assert len(end["curve"]["lines"]) == 2
    assert all(len(l["points"]) == ROUNDS for l in end["curve"]["lines"])
    assert isinstance(end["awards"], list)
    assert end["game_id"]
    assert len(room.game.log) == ROUNDS

    # on the shelf, and replayable
    assert len(hist.shelf("demo")) == 1
    await room.handle(host, {"t": "reel", "id": end["game_id"]})
    reel = host.last("reel")
    assert reel and len(reel["game"]["rounds"]) == ROUNDS
    assert reel["game"]["rounds"][0]["prompt"]

    # a lobby that now remembers
    await room.handle(host, {"t": "reset"})
    await settle(room, "lobby")
    lobby = host.last()
    assert lobby["history"]["games"][0]["rounds"] == ROUNDS
    assert lobby["history"]["stats"]["games"] == 1
    assert {p["name"] for p in lobby["players"]} == {"Shray", "Nilu"}
    assert all(p["score"] == 0 for p in lobby["players"])


@pytest.mark.asyncio
async def test_a_player_is_never_told_the_code_the_shelf_or_the_datasets(table):
    room, _ = table
    a = await seat(room, pid="a")
    state = a.last()
    assert state["code"] is None
    assert "history" not in state and "datasets" not in state


@pytest.mark.asyncio
async def test_the_reel_refuses_a_game_that_is_not_on_the_shelf(table):
    room, _ = table
    host = await seat(room, role="host")
    await room.handle(host, {"t": "reel", "id": "nope-1999"})
    assert host.last("denied")["why"] == "no such game"


def test_the_app_still_builds_and_serves(table):
    from fastapi.testclient import TestClient
    room, _ = table
    with TestClient(create_app(room)) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/").status_code == 200
        assert c.get("/play").status_code == 200
        assert "function voice" in c.get("/static/sound.js").text
