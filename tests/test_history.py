"""history.py — the shelf, and the two rules that keep it honest.

Real games persist encrypted; demo games never touch the disk. Both matter:
one is the privacy property seal.py exists for, the other is why a week of
test runs doesn't bury the three games that actually happened.
"""
import json
import os
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from app.game import PlayerResult, RoundRecord
from app.history import CAP, GameSummary, History, slug, summarise

KEY = Fernet.generate_key()


class P:
    def __init__(self, name, color, score):
        self.name, self.color, self.score = name, color, score


PLAYERS = {"a": P("Shray", "#f0a", 2200), "b": P("Nilu", "#0af", 1400)}


def rec(i=0, points=(900, 100), kind="Receipts", qid=None):
    return RoundRecord(
        index=i, question_id=qid or f"q{i}", kind=kind, type="binary",
        prompt="p?", reveal="r.", correct=0,
        results={"a": PlayerResult(0, points[0], 1.0, 2.0, 1),
                 "b": PlayerResult(1, points[1], 0.0, 8.0, 2)})


def a_game(dataset="real", players=None, log=None, when=None, awards=None):
    return summarise(log if log is not None else [rec(0), rec(1)],
                     players or PLAYERS, dataset, awards or [], {},
                     when=when or datetime.now(timezone.utc))


@pytest.fixture
def hist(tmp_path):
    return History(path=str(tmp_path / "data" / "history.jsonl"))


# ── what a summary is ─────────────────────────────────────────────────────

def test_a_summary_keeps_enough_to_redraw_the_end_screens():
    g = a_game()
    assert g.scores == {"a": 2200, "b": 1400}
    assert g.winner == "a"
    assert len(g.rounds) == 2 and g.rounds[0]["results"]["a"]["points"] == 900
    assert g.names["b"] == "Nilu"


def test_a_tie_has_no_winner():
    """Naming one would make the shelf lie about a game that was level."""
    level = {"a": P("Shray", "#f0a", 1500), "b": P("Nilu", "#0af", 1500)}
    assert a_game(players=level).winner is None


def test_the_id_reads_like_a_date():
    assert slug(datetime(2026, 9, 14)) == "sep14-2026"


# ── the disk ──────────────────────────────────────────────────────────────

def test_a_real_game_is_written_encrypted(hist):
    hist.unlock(KEY)
    hist.remember(a_game())
    with open(hist.path, "rb") as f:
        raw = f.read().strip()
    assert b"Shray" not in raw and b"Receipts" not in raw      # ciphertext
    assert json.loads(Fernet(KEY).decrypt(raw))["names"]["a"] == "Shray"


def test_a_demo_game_never_touches_the_disk(hist):
    """A week of test runs must not bury the games that actually happened."""
    hist.unlock(KEY)
    hist.remember(a_game(dataset="demo"))
    assert not os.path.exists(hist.path)
    assert len(hist.shelf("demo")) == 1


def test_a_real_game_played_before_the_unlock_is_flushed_on_it(hist):
    """Demo first, unlock later is a real sequence on game night."""
    hist.remember(a_game())
    assert not os.path.exists(hist.path)
    hist.unlock(KEY)
    assert os.path.exists(hist.path)
    assert len(Fernet(KEY).decrypt(open(hist.path, "rb").read().strip())) > 0


def test_the_shelf_is_read_back_on_unlock(tmp_path):
    p = str(tmp_path / "data" / "history.jsonl")
    first = History(path=p)
    first.unlock(KEY)
    first.remember(a_game(when=datetime(2026, 9, 1, tzinfo=timezone.utc)))
    first.remember(a_game(when=datetime(2026, 9, 8, tzinfo=timezone.utc)))

    second = History(path=p)
    assert second.shelf("real") == []          # cold, still locked
    assert second.unlock(KEY) == 2
    assert [g.played_at[:10] for g in second.shelf("real")] == \
           ["2026-09-08", "2026-09-01"]        # newest first


def test_a_line_written_under_another_passphrase_is_skipped_not_fatal(hist):
    """A history from an older passphrase must not stop tonight's game."""
    hist.unlock(KEY)
    hist.remember(a_game())
    with open(hist.path, "ab") as f:
        f.write(Fernet(Fernet.generate_key()).encrypt(b'{"id":"x"}') + b"\n")
    fresh = History(path=hist.path)
    assert fresh.unlock(KEY) == 1              # ours, not theirs


def test_nothing_is_readable_without_the_key(hist):
    hist.unlock(KEY)
    hist.remember(a_game())
    locked = History(path=hist.path)
    assert locked.shelf("real") == []
    assert locked._read() == 0


def test_reading_twice_does_not_double_the_shelf(hist):
    hist.unlock(KEY)
    hist.remember(a_game())
    before = len(hist.shelf("real"))
    hist._read()
    assert len(hist.shelf("real")) == before


def test_the_shelf_is_capped(hist):
    hist.unlock(KEY)
    for i in range(CAP + 6):
        hist.remember(a_game(when=datetime(2026, 1, 1, 0, 0, i, tzinfo=timezone.utc)))
    assert len(hist.games) == CAP


def test_demo_and_real_never_mix(hist):
    hist.unlock(KEY)
    hist.remember(a_game(dataset="real"))
    hist.remember(a_game(dataset="demo"))
    assert len(hist.shelf("real")) == 1 and len(hist.shelf("demo")) == 1


# ── the numbers the lobby shows ───────────────────────────────────────────

def test_stats_on_an_empty_shelf_say_so(hist):
    assert hist.stats("real") == {"games": 0}


def test_the_head_to_head_record_counts_wins_and_draws(hist):
    hist.unlock(KEY)
    level = {"a": P("Shray", "#f0a", 900), "b": P("Nilu", "#0af", 900)}
    hist.remember(a_game())                                   # a wins
    hist.remember(a_game())                                   # a wins
    hist.remember(a_game(players={"a": P("Shray", "#f0a", 100),
                                  "b": P("Nilu", "#0af", 9000)}))
    hist.remember(a_game(players=level))                      # draw
    st = hist.stats("real")
    assert st["games"] == 4 and st["draws"] == 1
    assert {r["name"]: r["wins"] for r in st["record"]} == {"Shray": 2, "Nilu": 1}


def test_the_best_game_and_the_best_round_are_found(hist):
    hist.unlock(KEY)
    hist.remember(a_game(log=[rec(0, points=(300, 100)),
                              rec(1, points=(120, 990), kind="Petty grievances")]))
    st = hist.stats("real")
    assert st["best_game"]["score"] == 2200
    assert st["best_round"]["points"] == 990
    assert st["best_round"]["kind"] == "Petty grievances"


def test_questions_seen_counts_the_bank_going_stale(hist):
    hist.unlock(KEY)
    hist.remember(a_game(log=[rec(0, qid="q1"), rec(1, qid="q2")]))
    hist.remember(a_game(log=[rec(0, qid="q2"), rec(1, qid="q3")]))
    assert hist.stats("real")["questions_seen"] == 3


def test_a_repeated_award_is_worth_saying_and_a_single_one_is_not(hist):
    hist.unlock(KEY)
    ff = [{"key": "fastest_finger", "title": "Fastest Finger", "winners": ["b"],
           "evidence": "e"}]
    once = [{"key": "on_fire", "title": "On Fire", "winners": ["a"], "evidence": "e"}]
    hist.remember(a_game(awards=ff))
    hist.remember(a_game(awards=ff))
    hist.remember(a_game(awards=once))
    reps = hist.stats("real")["repeats"]
    assert len(reps) == 1
    assert reps[0]["name"] == "Nilu" and reps[0]["times"] == 2


def test_cards_carry_a_card_and_not_the_whole_log(hist):
    hist.unlock(KEY)
    hist.remember(a_game())
    card = hist.cards("real")[0]
    assert card["rounds"] == 2 and "results" not in json.dumps(card)
    json.dumps(card)


# ── freshness ─────────────────────────────────────────────────────────────

def test_seen_counts_questions_across_recent_games():
    """`config.toml [deal] freshness` promised replays would differ and nothing
    delivered it: Game.deal() takes a `seen` map and main.py passed none, so
    every replay re-rolled from scratch."""
    from app.history import GameSummary, History
    h = History(path="nowhere.jsonl")
    for n in range(4):
        h.games.append(GameSummary(
            id=f"g{n}", played_at=f"2026-09-2{n}T20:00:00", dataset="real",
            rounds=[{"question_id": f"q{n}"}, {"question_id": "shared"}]))
    seen = h.seen("real", window=3)
    assert seen["shared"] == 3                  # the window, not the whole file
    assert seen.get("q3") is None or "q3" in seen
    assert sum(1 for k in seen if k.startswith("q")) == 3


def test_seen_ignores_other_datasets():
    """A demo rehearsal must not make the real deck think it has been played."""
    from app.history import GameSummary, History
    h = History(path="nowhere.jsonl")
    h.games.append(GameSummary(id="d", played_at="2026-09-24T20:00:00",
                               dataset="demo", rounds=[{"question_id": "q1"}]))
    assert h.seen("real") == {}


def test_a_question_seen_last_game_is_less_likely_next_game():
    import random

    from app.game import DealRules, Game
    from tests.conftest import make_dataset, q as _q
    qs = [_q(f"x{i}", kind=f"k{i % 5}") for i in range(40)]
    data = make_dataset(qs, rounds=10)
    rules = DealRules(max_per_subject=1)

    repeats_cold, repeats_fresh = 0, 0
    for t in range(60):
        first = Game(data, rng=random.Random(t), rules=rules)
        first.deal()
        used = {x.id: 1 for x in first.deck}

        cold = Game(data, rng=random.Random(t + 500), rules=rules)
        cold.deal()
        repeats_cold += len({x.id for x in cold.deck} & set(used))

        warm = Game(data, rng=random.Random(t + 500), rules=rules)
        warm.deal(seen=used)
        repeats_fresh += len({x.id for x in warm.deck} & set(used))

    assert repeats_fresh < repeats_cold, (repeats_fresh, repeats_cold)
