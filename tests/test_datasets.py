"""datasets.py — the passphrase gate, and what it refuses to tell you."""
import json

import pytest

from app.datasets import Library, Locked
from app.main import Room, create_app
from app.schema import Dataset
from tests.conftest import make_dataset
from tests.test_server import FakeSocket, hello, join, room
from tools.seal import seal

PASS = "the words we type once a year"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A demo dataset in the clear and a real one sealed, as they ship."""
    monkeypatch.setattr("tools.seal.KDF", {"n": 1 << 12, "r": 8, "p": 1})
    demo = make_dataset(rounds=3)
    real = make_dataset(rounds=3, questions=[
        {"id": f"r{i}", "type": "binary", "kind": f"k{i % 3}", "prompt": "who?",
         "reveal": "them.", "answer": 0, "options": ["A", "B"], "origin": "mine"}
        for i in range(12)])

    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "demo.json").write_text(demo.model_dump_json())
    (tmp_path / "datasets" / "real.json.enc").write_bytes(
        seal(real.model_dump_json().encode(), PASS))
    return Library(root=str(tmp_path))


def test_the_demo_needs_no_passphrase(lib):
    assert isinstance(lib.load("demo"), Dataset)


def test_the_right_passphrase_opens_the_real_thing(lib):
    ds = lib.load("real", PASS)
    assert ds.by_origin["mine"] == 12


def test_the_wrong_passphrase_is_refused(lib):
    with pytest.raises(Locked):
        lib.load("real", "not the words")


def test_a_wrong_passphrase_and_a_missing_file_say_the_same_thing(tmp_path, lib):
    """There's nothing to learn from the difference and something to lose."""
    wrong = None
    try:
        lib.load("real", "not the words")
    except Locked as e:
        wrong = str(e)

    empty = Library(root=str(tmp_path / "nothing"))
    missing = None
    try:
        empty.load("real", PASS)
    except Locked as e:
        missing = str(e)
    assert wrong == missing == "could not open"


def test_it_only_asks_once_a_night(lib):
    lib.load("real", PASS)
    assert lib.load("real") is lib.cache["real"]      # no passphrase needed now


def test_guessing_is_rate_limited(lib):
    for _ in range(5):
        with pytest.raises(Locked, match="could not open"):
            lib.load("real", "wrong")
    with pytest.raises(Locked, match="too many"):
        lib.load("real", "wrong")


def test_the_limit_does_not_lock_out_the_right_passphrase_forever(lib):
    for _ in range(4):
        with pytest.raises(Locked):
            lib.load("real", "wrong")
    assert lib.load("real", PASS)                    # the fifth try is yours


def test_a_successful_unlock_clears_the_count(lib):
    for _ in range(3):
        with pytest.raises(Locked):
            lib.load("real", "wrong")
    lib.load("real", PASS)
    assert not lib.tries


def test_the_options_say_what_is_locked_and_what_is_open(lib):
    ids = {o["id"]: o for o in lib.options()}
    assert ids["demo"]["locked"] is False
    assert ids["real"]["locked"] is True and ids["real"]["ready"] is False
    lib.load("real", PASS)
    assert {o["id"]: o for o in lib.options()}["real"]["ready"] is True


def test_a_server_with_no_sealed_file_offers_no_real_option(tmp_path):
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "demo.json").write_text(
        make_dataset(rounds=3).model_dump_json())
    assert [o["id"] for o in Library(root=str(tmp_path)).options()] == ["demo"]


def test_forgetting_it_means_asking_again(lib):
    lib.load("real", PASS)
    lib.forget()
    with pytest.raises(Locked):
        lib.load("real")


# ── the toggle, over the wire ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_host_can_swap_the_dataset_in_the_lobby(lib):
    r = room()
    r.library = lib
    host = await hello(r, FakeSocket(), role="host")

    await r.handle(host, {"t": "dataset", "id": "real", "pass": PASS})
    assert r.library.current == "real"
    assert r.game.data.by_origin["mine"] == 12


@pytest.mark.asyncio
async def test_swapping_keeps_the_code_and_the_people_on_it(lib):
    """Her phone is already in her hand. Don't make her rejoin."""
    r = room()
    r.library = lib
    host = await hello(r, FakeSocket(), role="host")
    ws = await hello(r, FakeSocket())
    await join(r, ws, pid="a", name="Nilu")
    code, colour = r.game.code, r.game.players["a"].color

    await r.handle(host, {"t": "dataset", "id": "real", "pass": PASS})
    assert r.game.code == code
    assert r.game.players["a"].name == "Nilu"
    assert r.game.players["a"].color == colour


@pytest.mark.asyncio
async def test_the_wrong_passphrase_changes_nothing(lib):
    r = room()
    r.library = lib
    host = await hello(r, FakeSocket(), role="host")
    before = r.game

    await r.handle(host, {"t": "dataset", "id": "real", "pass": "nope"})
    assert r.game is before
    assert host.last("denied")["why"] == "could not open"


@pytest.mark.asyncio
async def test_you_cannot_change_the_deck_once_the_game_has_started(lib):
    r = room()
    r.library = lib
    host = await hello(r, FakeSocket(), role="host")
    ws = await hello(r, FakeSocket())
    await join(r, ws)
    r.game.deal()
    r.game.begin_round(0)

    await r.handle(host, {"t": "dataset", "id": "real", "pass": PASS})
    assert r.library.current == "demo"
    assert host.last("denied")["why"] == "not in the lobby"


@pytest.mark.asyncio
async def test_a_player_cannot_reach_the_passphrase_gate_at_all(lib):
    r = room()
    r.library = lib
    ws = await hello(r, FakeSocket(), role="player")
    await join(r, ws)

    await r.handle(ws, {"t": "dataset", "id": "real", "pass": PASS})
    assert r.library.current == "demo"


@pytest.mark.asyncio
async def test_only_the_host_is_told_which_datasets_exist(lib):
    r = room()
    r.library = lib
    host = await hello(r, FakeSocket(), role="host")
    ws = await hello(r, FakeSocket(), role="player")
    await r.broadcast()
    assert host.last()["datasets"]["current"] == "demo"
    assert "datasets" not in ws.last()
