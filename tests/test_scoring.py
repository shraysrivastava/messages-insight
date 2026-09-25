"""Scoring. The thing most likely to break silently."""
import random

import pytest

from app.game import Game
from app.schema import Question
from tests.conftest import MONTHS, make_dataset, q


def Q(**kw):
    return Question.model_validate(q("x", **kw))


# ── accuracy, per type ────────────────────────────────────────────────────

def test_binary_all_or_nothing(game):
    x = Q(type="binary", answer=1)
    assert game.accuracy(x, 1) == 1.0
    assert game.accuracy(x, 0) == 0.0
    assert game.accuracy(x, None) == 0.0


def test_choice_all_or_nothing(game):
    x = Q(type="choice", answer=2, options=["a", "b", "c", "d"])
    assert game.accuracy(x, 2) == 1.0
    assert game.accuracy(x, 3) == 0.0


def test_number_proximity(game):
    x = Q(type="number", answer=100)
    assert game.accuracy(x, 100) == 1.0
    assert game.accuracy(x, 90) == pytest.approx(0.9)
    assert game.accuracy(x, 0) == 0.0
    assert game.accuracy(x, 250) == 0.0          # never negative
    assert game.accuracy(x, "cat") == 0.0        # junk from a client


def test_number_answer_of_zero_does_not_divide_by_zero(game):
    x = Q(type="number", answer=0)
    assert game.accuracy(x, 0) == 1.0
    assert game.accuracy(x, 1) == 0.0


def test_percent_band(game):
    x = Q(type="percent", answer=50)
    assert game.accuracy(x, 50) == 1.0
    assert game.accuracy(x, 65) == pytest.approx(0.5)
    assert game.accuracy(x, 20) == 0.0


def test_month_proximity_and_edges(game):
    n = len(MONTHS)
    x = Q(type="month", answer=n // 2)
    assert game.accuracy(x, n // 2) == 1.0
    span = max(n, 6) / 3
    assert game.accuracy(x, n // 2 + 3) == pytest.approx(1 - 3 / span)
    assert game.accuracy(x, 0) == 0.0            # a third of the thread away
    assert game.accuracy(x, n - 1) == 0.0


def test_bool_is_not_a_number(game):
    """True == 1 in Python. A checkbox must not score as a numeric guess."""
    assert game.accuracy(Q(type="number", answer=1), True) == 0.0
    assert game.accuracy(Q(type="month", answer=1), True) == 0.0


# ── speed weighting ───────────────────────────────────────────────────────

def test_instant_answer_is_worth_double_a_buzzer_beater(game):
    game.deck = [Q(type="binary", answer=0)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 0, at=1000.0)          # instant
    game.record_answer("b", 0, at=1020.0)          # at the buzzer
    game.close_question()
    assert game.players["a"].score == 1000
    assert game.players["b"].score == 500


def test_zero_accuracy_scores_zero_however_fast(game):
    game.deck = [Q(type="binary", answer=0)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 1, at=1000.0)
    game.close_question()
    assert game.players["a"].score == 0


def test_no_answer_scores_zero(game):
    game.deck = [Q(type="binary", answer=0)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.close_question()
    assert game.players["a"].score == 0


# ── client-supplied timestamps ────────────────────────────────────────────

def test_client_timestamp_is_clamped_to_the_window(game):
    """A phone claiming it answered before the question opened gets clamped."""
    game.deck = [Q(type="binary", answer=0)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 0, at=0.0)             # absurdly early
    game.record_answer("b", 0, at=9e9)             # absurdly late
    assert game.players["a"].answered_at == 1000.0
    assert game.players["b"].answered_at == 1020.0


def test_first_answer_wins(game):
    game.deck = [Q(type="binary", answer=0)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    assert game.record_answer("a", 1, at=1001.0) is True
    assert game.record_answer("a", 0, at=1002.0) is False
    assert game.players["a"].answer == 1


def test_answers_outside_question_phase_are_ignored(game):
    game.deck = [Q(type="binary", answer=0)]
    game.begin_round(0)                            # phase == countdown
    assert game.record_answer("a", 0) is False


# ── mutual ────────────────────────────────────────────────────────────────

def test_mutual_scores_on_matching_and_pays_the_first_one_in(game):
    game.deck = [Q(type="mutual")]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 1, at=1001.0)
    game.record_answer("b", 1, at=1019.0)
    game.close_question()
    assert game.players["a"].score == 750      # agreed, and got there first
    assert game.players["b"].score == 500      # agreed


def test_the_mutual_bonus_is_relative_not_a_speed_curve(game):
    """Both dawdled; one still got there first, and still earns it."""
    game.deck = [Q(type="mutual")]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 1, at=1018.0)
    game.record_answer("b", 1, at=1019.0)
    game.close_question()
    assert game.players["a"].score == 750
    assert game.players["b"].score == 500


def test_nobody_earns_the_bonus_for_being_first_to_disagree(game):
    game.deck = [Q(type="mutual")]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 0, at=1001.0)
    game.record_answer("b", 1, at=1019.0)
    game.close_question()
    assert game.players["a"].score == 0
    assert game.players["b"].score == 0


def test_an_exact_tie_earns_the_bonus_for_nobody(game):
    game.deck = [Q(type="mutual")]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 1, at=1005.0)
    game.record_answer("b", 1, at=1005.0)
    game.close_question()
    assert game.players["a"].score == 500
    assert game.players["b"].score == 500


def test_mutual_mismatch_scores_nothing(game):
    game.deck = [Q(type="mutual")]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 0)
    game.record_answer("b", 1)
    game.close_question()
    assert game.players["a"].score == 0
    assert game.players["b"].score == 0


# ── wager / the Final Receipt ─────────────────────────────────────────────

def wagered(game, a, b, answer=0):
    """Run one Final Receipt. `a` and `b` are (pick, stake) tuples."""
    game.deck = [Q(type="wager", answer=answer)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", {"pick": a[0], "stake": a[1]}, at=1001.0)
    game.record_answer("b", {"pick": b[0], "stake": b[1]}, at=1019.0)
    return game.close_question()


def test_wager_pays_the_stake_and_ignores_speed(game):
    game.players["a"].score = game.players["b"].score = 2000
    wagered(game, (0, 800), (0, 300))
    # the slow one is not punished: the decision is the round, not the reflex
    assert game.players["a"].score == 2800
    assert game.players["b"].score == 2300


def test_wager_takes_the_stake_back_when_you_are_wrong(game):
    game.players["a"].score = 2000
    game.players["b"].score = 2000
    wagered(game, (1, 800), (0, 300))
    assert game.players["a"].score == 1200
    assert game.players["b"].score == 2300


def test_a_lost_wager_cannot_take_you_below_zero(game):
    """There is no round after this one to win it back, and a negative number
    is a worse last screen of the night than a small one."""
    game.players["a"].score = 100
    wagered(game, (1, 500), (0, 0))
    assert game.players["a"].score == 0


def test_the_stake_is_clamped_to_what_you_could_lose(game):
    game.players["a"].score = 1200
    wagered(game, (0, 99999), (0, 0))
    assert game.players["a"].score == 2400            # capped at 1200


def test_everyone_can_stake_the_floor_at_zero_points(game):
    assert game.stake_cap(game.players["a"]) == 500
    game.players["a"].score = 3000
    assert game.stake_cap(game.players["a"]) == 3000


def test_a_wager_without_a_pick_is_refused(game):
    game.deck = [Q(type="wager", answer=0)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    assert game.record_answer("a", 0) is False           # bare index
    assert game.record_answer("a", {"stake": 500}) is False
    assert game.players["a"].answer is None


def test_the_stake_reaches_the_round_log(game):
    """superlatives.py reads it off PlayerResult for All In and Ice in the
    Veins; nothing else records how much was risked."""
    game.players["a"].score = 2000
    rec = wagered(game, (0, 800), (1, 50))
    assert rec.results["a"].stake == 800
    assert rec.results["b"].stake == 50


# ── the round log ─────────────────────────────────────────────────────────

def test_grade_appends_a_complete_round_record(game):
    game.deck = [Q(type="binary", answer=1, kind="Who said it", origin="mine")]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.record_answer("a", 1, at=1005.0)
    game.record_answer("b", 0, at=1010.0)
    rec = game.close_question()

    assert len(game.log) == 1
    assert rec.question_id == "x"
    assert rec.kind == "Who said it"
    assert rec.origin == "mine"
    assert rec.correct == 1
    assert set(rec.results) == {"a", "b"}
    assert rec.results["a"].accuracy == 1.0
    assert rec.results["b"].points == 0
    assert rec.results["a"].elapsed == 5.0
    assert rec.results["a"].rank_after == 1
    assert rec.results["b"].rank_after == 2


def test_log_survives_a_whole_game(game):
    game.deal()
    for i in range(len(game.deck)):
        game.begin_round(i)
        game.open_question(now=1000.0 + i * 100)
        game.record_answer("a", 0, at=1001.0 + i * 100)
        game.close_question()
    assert len(game.log) == len(game.deck)
    assert [r.index for r in game.log] == list(range(len(game.deck)))


# ── snapshot ──────────────────────────────────────────────────────────────

def test_snapshot_never_leaks_the_answer_before_the_reveal(game):
    game.deck = [Q(type="binary", answer=1)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    snap = game.snapshot(now=1001.0)
    assert "answer" not in snap["question"]
    assert "reveal" not in snap["question"]
    game.close_question()
    snap = game.snapshot(now=1030.0)
    assert snap["question"]["answer"] == 1
    assert snap["question"]["reveal"] == "r."


def test_snapshot_hides_the_question_in_the_lobby(game):
    assert game.snapshot()["question"] is None


def test_the_histogram_flag_only_travels_when_it_is_off(game):
    """The slider draws the density picture unless told not to, so the common
    case costs nothing on the wire and an old client just draws it."""
    game.deck = [Q(type="month", answer=3)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    assert "histogram" not in game.snapshot(now=1001.0)["question"]

    game.deck = [Q(type="month", answer=3, histogram=False)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    assert game.snapshot(now=1001.0)["question"]["histogram"] is False


def test_the_round_log_keeps_the_options_it_was_scored_against(game):
    """Without them the receipts reel replays "Shray said 0"."""
    game.deck = [Q(type="choice", answer=1, options=["pasta", "pizza", "toast"])]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.add_player("a", "Shray").answer = 1
    rec = game.grade()
    assert rec.options == ["pasta", "pizza", "toast"]
    assert rec.options[rec.results["a"].answer] == "pizza"


def test_the_context_thread_is_held_back_until_the_reveal(game):
    """It is the conversation the answer is in. Sent with the question, it is
    the answer."""
    ctx = [{"who": "p2", "text": "you up?", "self": False},
           {"who": "p1", "text": "always", "self": True}]
    game.deck = [Q(type="binary", answer=1, context=ctx)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    assert "context" not in game.snapshot(now=1001.0)["question"]
    game.close_question()
    assert game.snapshot(now=1030.0)["question"]["context"][1]["self"] is True


def test_the_round_log_keeps_the_context_too(game):
    ctx = [{"who": "p2", "text": "you up?", "self": False},
           {"who": "p1", "text": "always", "self": True}]
    game.deck = [Q(type="binary", answer=1, context=ctx)]
    game.begin_round(0)
    game.open_question(now=1000.0)
    game.add_player("a", "Shray").answer = 1
    assert game.grade().context[0]["text"] == "you up?"
