"""main.py — the join code, the clock, and two phones on bad wifi.

The clock and the sockets are the parts game.py deliberately doesn't have, so
they're the parts with no coverage anywhere else.
"""
import asyncio
import json
import random

import pytest

import app.main as main
from app.game import Game
from app.main import Room, create_app
from tests.conftest import make_dataset


@pytest.fixture(autouse=True)
def quick_read_beat(monkeypatch):
    """main.READ_BEAT holds the reveal back so the read receipt can flip. It
    is 1.2s live and would add that to every round-closing test here."""
    monkeypatch.setattr(main, "READ_BEAT", 0.05)


class FakeSocket:
    """Records what was sent to it. Raises once `broken`, like a phone that
    walked into a lift."""

    def __init__(self):
        self.sent = []
        self.broken = False

    async def send_text(self, text):
        if self.broken:
            raise ConnectionError("gone")
        self.sent.append(json.loads(text))

    def last(self, t="state"):
        return next((m for m in reversed(self.sent) if m.get("t") == t), None)


def room(**kw):
    g = Game(make_dataset(rounds=3), rng=random.Random(4), **kw)
    return Room(g)


async def hello(r, ws, role="player", **kw):
    r.sockets[ws] = {"role": "unknown", "pid": None}
    await r.handle(ws, {"t": "hello", "role": role, **kw})
    return ws


async def join(r, ws, pid="a", name="Shray", code=None):
    await r.handle(r and ws, {"t": "join", "id": pid, "name": name,
                              "code": r.game.code if code is None else code})


# ── the join code (S2.3) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_right_code_gets_you_in():
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws)
    assert "a" in r.game.players


@pytest.mark.asyncio
async def test_the_wrong_code_is_denied_and_adds_no_player():
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws, code="ZZZZ")
    assert r.game.players == {}
    assert ws.last("denied")["why"] == "code"


@pytest.mark.asyncio
async def test_the_code_is_case_and_space_insensitive():
    """She is typing it on a phone, at night, from across a room."""
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws, code=f"  {r.game.code.lower()} ")
    assert "a" in r.game.players


@pytest.mark.asyncio
async def test_a_stranger_is_never_handed_the_code():
    """The whole point. A socket that hasn't proved it's the host gets a
    snapshot with the code stripped out."""
    r = room()
    ws = await hello(r, FakeSocket(), role="player")
    await r.broadcast()
    assert ws.last()["code"] is None


@pytest.mark.asyncio
async def test_the_host_screen_sees_the_code_because_it_has_to_show_it():
    r = room()
    ws = await hello(r, FakeSocket(), role="host")
    await r.broadcast()
    assert ws.last()["code"] == r.game.code
    assert ws.last("welcome")["code"] == r.game.code


@pytest.mark.asyncio
async def test_the_second_host_screen_is_only_a_spectator():
    r = room()
    await hello(r, FakeSocket(), role="host")
    other = await hello(r, FakeSocket(), role="host")
    assert r.sockets[other]["role"] == "watcher"
    assert other.last()["code"] is None


@pytest.mark.asyncio
async def test_the_host_reclaims_its_screen_after_a_reload():
    r = room()
    await hello(r, FakeSocket(), role="host")
    back = await hello(r, FakeSocket(), role="host", token=r.host_token)
    assert r.sockets[back]["role"] == "host"


@pytest.mark.asyncio
async def test_reading_the_code_off_the_screen_reclaims_the_host():
    """The recovery path when the token is gone with the browser profile."""
    r = room()
    await hello(r, FakeSocket(), role="host")
    back = await hello(r, FakeSocket(), role="host", code=r.game.code)
    assert r.sockets[back]["role"] == "host"


@pytest.mark.asyncio
async def test_a_spectator_cannot_start_or_reset_the_game():
    r = room()
    host = await hello(r, FakeSocket(), role="host")
    ws = await hello(r, FakeSocket(), role="player")
    await join(r, ws)

    await r.handle(ws, {"t": "start"})
    assert r.game.phase == "lobby"

    await r.handle(host, {"t": "start"})
    assert r.game.phase == "countdown"
    r.cancel()

    await r.handle(ws, {"t": "reset"})
    assert r.game.phase == "countdown"          # still not yours to reset


# ── client-timestamped answers (S2.4) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_an_answer_is_timed_by_the_players_own_clock():
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws)
    r.game.begin_round(0)
    r.game.open_question()
    started = r.game.question_started_at

    await r.handle(ws, {"t": "answer", "id": "a", "value": 0,
                        "at": started + 1.0})
    assert r.game.players["a"].answered_at == pytest.approx(started + 1.0)


@pytest.mark.asyncio
async def test_a_claim_from_before_the_question_is_clamped_not_believed():
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws)
    r.game.begin_round(0)
    r.game.open_question()

    await r.handle(ws, {"t": "answer", "id": "a", "value": 0, "at": 0.0})
    assert r.game.players["a"].answered_at == r.game.question_started_at


@pytest.mark.asyncio
async def test_a_claim_from_after_the_buzzer_is_clamped_too():
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws)
    r.game.begin_round(0)
    r.game.open_question()

    await r.handle(ws, {"t": "answer", "id": "a", "value": 0, "at": 1e12})
    assert r.game.players["a"].answered_at == r.game.ends_at


@pytest.mark.asyncio
async def test_a_missing_or_junk_timestamp_falls_back_to_now():
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws)
    r.game.begin_round(0)
    r.game.open_question()

    await r.handle(ws, {"t": "answer", "id": "a", "value": 0, "at": "soon"})
    assert r.game.players["a"].answered_at is not None


@pytest.mark.asyncio
async def test_you_cannot_answer_for_someone_else():
    r = room()
    mine = await hello(r, FakeSocket())
    await join(r, mine, pid="a")
    theirs = await hello(r, FakeSocket())
    await join(r, theirs, pid="b", name="Nilu")
    r.game.begin_round(0)
    r.game.open_question()

    await r.handle(mine, {"t": "answer", "id": "b", "value": 1})
    assert r.game.players["b"].answer is None


@pytest.mark.asyncio
async def test_a_socket_that_never_joined_cannot_answer():
    r = room()
    ws = await hello(r, FakeSocket())              # no join
    r.game.add_player("a", "Shray")
    r.game.begin_round(0)
    r.game.open_question()

    await r.handle(ws, {"t": "answer", "id": "a", "value": 0})
    assert r.game.players["a"].answer is None


# ── the heartbeat and the clock (S2.5) ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_ping_comes_back_with_both_timestamps():
    """The client needs its own t0 back to work out the round trip."""
    r = room()
    ws = await hello(r, FakeSocket())
    await r.handle(ws, {"t": "ping", "c0": 123.5})
    pong = ws.last("pong")
    assert pong["c0"] == 123.5 and pong["s"] > 0


@pytest.mark.asyncio
async def test_the_heartbeat_reaches_every_socket():
    r = room()
    a = await hello(r, FakeSocket())
    b = await hello(r, FakeSocket(), role="host")
    task = asyncio.create_task(r.beat())
    await asyncio.sleep(0)
    for ws in (a, b):
        await r.send(ws, {"t": "ping", "s": 1.0})     # what beat() sends
    task.cancel()
    assert a.last("ping") and b.last("ping")


@pytest.mark.asyncio
async def test_a_dead_socket_is_dropped_rather_than_broadcast_to_forever():
    r = room()
    good = await hello(r, FakeSocket())
    bad = await hello(r, FakeSocket())
    bad.broken = True
    await r.broadcast()
    assert bad not in r.sockets and good in r.sockets


# ── the round loop ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_round_closes_as_soon_as_everyone_has_answered():
    r = room(seconds=30)
    a = await hello(r, FakeSocket())
    await join(r, a, pid="a")
    b = await hello(r, FakeSocket())
    await join(r, b, pid="b", name="Nilu")

    r.game.deal()
    await r.start_round(0)
    r.cancel()                                   # skip the countdown
    await r.open_question()

    await r.handle(a, {"t": "answer", "id": "a", "value": 0})
    assert r.game.phase == "question"            # still waiting on her
    await r.handle(b, {"t": "answer", "id": "b", "value": 1})
    await asyncio.sleep(0.35)
    assert r.game.phase == "reveal"


@pytest.mark.asyncio
async def test_the_reveal_waits_for_the_read_receipt_to_land(monkeypatch):
    """The last answer must not close the round on the same tick. His phone
    still says `Delivered`, and the flip to `Read 9:42 PM` is the screen the
    game is named after (DESIGN 2.4)."""
    monkeypatch.setattr(main, "READ_BEAT", 0.4)
    r = room(seconds=30)
    a = await hello(r, FakeSocket())
    await join(r, a, pid="a")
    b = await hello(r, FakeSocket())
    await join(r, b, pid="b", name="Nilu")

    r.game.deal()
    await r.start_round(0)
    r.cancel()
    await r.open_question()
    await r.handle(a, {"t": "answer", "id": "a", "value": 0})
    await r.handle(b, {"t": "answer", "id": "b", "value": 1})

    await asyncio.sleep(0.15)
    assert r.game.phase == "question"             # the beat
    await asyncio.sleep(0.5)
    assert r.game.phase == "reveal"


@pytest.mark.asyncio
async def test_the_buzzer_does_not_wait_for_a_receipt_nobody_is_sending(monkeypatch):
    """If time ran out, whoever didn't answer never will. No beat."""
    monkeypatch.setattr(main, "READ_BEAT", 5.0)
    r = room(seconds=0.1)
    a = await hello(r, FakeSocket())
    await join(r, a, pid="a")
    b = await hello(r, FakeSocket())
    await join(r, b, pid="b", name="Nilu")

    r.game.deal()
    await r.start_round(0)
    r.cancel()
    await r.open_question()
    await asyncio.sleep(0.45)
    assert r.game.phase == "reveal"


@pytest.mark.asyncio
async def test_a_phone_that_drops_does_not_hold_the_round_to_the_buzzer():
    """Thirty seconds of dead air because one phone locked itself."""
    r = room(seconds=30)
    a = await hello(r, FakeSocket())
    await join(r, a, pid="a")
    b = await hello(r, FakeSocket())
    await join(r, b, pid="b", name="Nilu")

    r.game.deal()
    await r.start_round(0)
    r.cancel()
    await r.open_question()
    await r.handle(a, {"t": "answer", "id": "a", "value": 0})

    await r.drop(b)                              # she loses signal
    await asyncio.sleep(0.35)
    assert r.game.phase == "reveal"


@pytest.mark.asyncio
async def test_a_reconnecting_player_keeps_their_score_and_colour():
    r = room()
    ws = await hello(r, FakeSocket())
    await join(r, ws, pid="a")
    r.game.players["a"].score = 900
    colour = r.game.players["a"].color

    await r.drop(ws)
    assert r.game.players["a"].online is False

    again = await hello(r, FakeSocket())
    await join(r, again, pid="a")
    p = r.game.players["a"]
    assert p.online and p.score == 900 and p.color == colour


@pytest.mark.asyncio
async def test_playing_again_keeps_the_people_and_drops_the_scores():
    """Hosting and playing from the same browser, which is what happens the
    first time you test it alone. Joining must not cost you the controls."""
    r = room()
    ws = await hello(r, FakeSocket(), role="host")
    await r.handle(ws, {"t": "join", "id": "a", "name": "Shray",
                        "code": r.game.code})
    r.game.players["a"].score = 900

    await r.handle(ws, {"t": "reset"})
    assert r.game.phase == "lobby"
    assert r.game.players["a"].score == 0
    assert r.game.players["a"].name == "Shray"


@pytest.mark.asyncio
async def test_the_last_round_ends_the_game_rather_than_dealing_a_sixth():
    r = room()
    host = await hello(r, FakeSocket(), role="host")
    ws = await hello(r, FakeSocket())
    await join(r, ws)

    r.game.deal()
    r.game.round = len(r.game.deck) - 1
    r.game.phase = "reveal"
    await r.handle(host, {"t": "next"})
    assert r.game.phase == "final"


# ── the http surface ──────────────────────────────────────────────────────

def client():
    from fastapi.testclient import TestClient
    return TestClient(create_app(room()))


def test_the_pages_and_the_health_check_are_served():
    c = client()
    assert c.get("/").status_code == 200
    assert c.get("/play").status_code == 200
    assert c.get("/healthz").json()["ok"] is True


def test_the_qr_carries_the_code_so_a_scan_is_the_whole_journey():
    app = create_app(room())
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/qr.svg", params={"base": "https://example.fly.dev"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")
    assert len(r.content) > 500


def test_a_websocket_gets_a_snapshot_without_the_code_on_connect():
    c = client()
    with c.websocket_connect("/ws") as ws:
        first = ws.receive_json()
    assert first["t"] == "state" and first["code"] is None


@pytest.mark.asyncio
async def test_closing_the_host_tab_does_not_lock_the_controls_away():
    """Otherwise the only way back in is the code, which was on the screen
    you just closed."""
    r = room()
    ws = await hello(r, FakeSocket(), role="host")
    await r.drop(ws)
    again = await hello(r, FakeSocket(), role="host")
    assert r.sockets[again]["role"] == "host"


@pytest.mark.asyncio
async def test_a_second_screen_still_cannot_take_a_live_host_over():
    r = room()
    await hello(r, FakeSocket(), role="host")
    other = await hello(r, FakeSocket(), role="host")
    assert r.sockets[other]["role"] == "watcher"


# ── the photo route ───────────────────────────────────────────────────────

def test_the_photo_route_serves_only_the_round_on_screen(tmp_path):
    """There is deliberately no /photo/{id}: an id is the one thing that would
    let a player pull a picture out of a round that hasn't been played."""
    import base64
    import random

    from fastapi.testclient import TestClient

    from app.game import Game
    from tests.conftest import make_dataset, q as _q

    jpg = b"\xff\xd8\xff\xe0 not really a jpeg \xff\xd9"
    b64 = base64.b64encode(jpg).decode()
    qs = [_q(f"k{i}", kind=f"k{i}") for i in range(4)]
    qs.append(_q("pic", kind="Photo", format="photo", photo=b64))
    data = make_dataset(qs, rounds=5)

    g = Game(data, rounds=5, seconds=20.0, rng=random.Random(1))
    app = create_app(Room(g))
    with TestClient(app) as client:
        g.deal()
        # the lobby has no question on screen, so there is no picture to get
        assert client.get("/photo/current").status_code == 404

        ix = next(i for i, x in enumerate(g.deck) if x.id == "pic")
        g.begin_round(ix)
        g.open_question(now=1000.0)
        r = client.get("/photo/current")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content == jpg

        # a round without a picture serves nothing, rather than the last one
        other = next(i for i, x in enumerate(g.deck) if x.id != "pic")
        g.begin_round(other)
        g.open_question(now=1000.0)
        assert client.get("/photo/current").status_code == 404
