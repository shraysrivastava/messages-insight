"""superlatives.py — every award, against a log written by hand.

The awards are the last screen of the night and nobody gets to re-run them.
Each test here builds the smallest log that should fire one award, plus the
smallest log that should *not* — because the thresholds are the whole design
(docs/DESIGN.md §3) and a threshold nobody tested is a decoration.
"""

import pytest

from app.game import PlayerResult, RoundRecord
from app.superlatives import Award, Tally, award, as_dict
import app.superlatives as S

NAMES = {"a": "Shray", "b": "Nilu"}


def res(answer=0, points=500, accuracy=1.0, elapsed=5.0, rank=1, stake=None):
    return PlayerResult(answer=answer, points=points, accuracy=accuracy,
                        elapsed=elapsed, rank_after=rank, stake=stake)


def rec(i=0, type="binary", kind="Receipts", qid=None, correct=0, **results):
    return RoundRecord(
        index=i, question_id=qid or f"q{i}", kind=kind, type=type,
        prompt="p?", reveal="r.", correct=correct, results=dict(results))


def only(log, key, seconds=25.0):
    """The named award, or None. `award()` caps at 5, so ask for everything."""
    for a in award(log, NAMES, seconds=seconds, limit=99):
        if a.key == key:
            return a
    return None


# ── speed ─────────────────────────────────────────────────────────────────

def test_fastest_finger_fires_on_a_clear_gap():
    log = [rec(i, a=res(elapsed=2.0), b=res(elapsed=6.0)) for i in range(4)]
    a = only(log, "fastest_finger")
    assert a and a.winner == "a"
    assert "Shray" in a.evidence and "4.0s faster" in a.evidence


def test_fastest_finger_does_not_fire_on_a_rounding_error():
    log = [rec(i, a=res(elapsed=5.0), b=res(elapsed=6.0)) for i in range(4)]
    assert only(log, "fastest_finger") is None


def test_a_dead_tie_goes_unawarded():
    log = [rec(i, a=res(elapsed=3.0), b=res(elapsed=3.0)) for i in range(4)]
    assert only(log, "fastest_finger") is None


def test_speed_awards_ignore_rounds_you_never_answered():
    """A missing answer is recorded with the full clock. That is not slowness."""
    log = [rec(i, a=res(elapsed=2.0), b=res(answer=None, points=0, accuracy=0.0,
                                             elapsed=25.0)) for i in range(4)]
    assert only(log, "fastest_finger") is None      # b has no answered rounds


def test_overthinker_wants_three_right_answers():
    slow = [rec(i, a=res(elapsed=18.0), b=res(elapsed=2.0)) for i in range(2)]
    assert only(slow, "overthinker") is None
    slow.append(rec(2, a=res(elapsed=18.0), b=res(elapsed=2.0)))
    a = only(slow, "overthinker")
    assert a and a.winner == "a" and "3 they got right" in a.evidence


def test_overthinker_only_counts_rounds_they_got_right():
    log = [rec(i, a=res(elapsed=20.0, points=0, accuracy=0.0), b=res(elapsed=2.0))
           for i in range(4)]
    assert only(log, "overthinker") is None


def test_buzzer_beater_needs_three_late_answers():
    late = [rec(i, a=res(elapsed=23.0), b=res(elapsed=4.0)) for i in range(2)]
    assert only(late, "buzzer_beater") is None
    late.append(rec(2, a=res(elapsed=23.5), b=res(elapsed=4.0)))
    a = only(late, "buzzer_beater")
    assert a and a.winner == "a" and "3 rounds" in a.evidence


def test_buzzer_beater_is_measured_against_this_games_clock():
    log = [rec(i, a=res(elapsed=9.0), b=res(elapsed=1.0)) for i in range(3)]
    assert only(log, "buzzer_beater", seconds=25.0) is None
    assert only(log, "buzzer_beater", seconds=10.0) is not None


def test_panic_button_wants_a_fast_answer_that_scored_nothing():
    log = [rec(0, a=res(elapsed=1.2, points=0, accuracy=0.0), b=res(elapsed=8.0))]
    a = only(log, "panic_button")
    assert a and a.winner == "a" and "1.2s" in a.evidence


def test_panic_button_ignores_a_fast_answer_that_worked():
    log = [rec(0, a=res(elapsed=1.2, points=900), b=res(elapsed=8.0))]
    assert only(log, "panic_button") is None


# ── accuracy ──────────────────────────────────────────────────────────────

def test_clairvoyant_is_an_exact_month():
    log = [rec(0, type="month", a=res(accuracy=1.0), b=res(accuracy=0.6)),
           rec(1, type="month", a=res(accuracy=0.9), b=res(accuracy=0.5))]
    a = only(log, "clairvoyant")
    assert a and a.winner == "a" and "exact month 1×" in a.evidence


def test_historian_needs_three_month_rounds_and_a_real_gap():
    two = [rec(i, type="month", a=res(accuracy=0.9), b=res(accuracy=0.2))
           for i in range(2)]
    assert only(two, "historian") is None
    two.append(rec(2, type="month", a=res(accuracy=0.9), b=res(accuracy=0.2)))
    a = only(two, "historian")
    assert a and a.winner == "a" and "90%" in a.evidence


def test_historian_does_not_fire_on_a_hair():
    log = [rec(i, type="month", a=res(accuracy=0.60), b=res(accuracy=0.55))
           for i in range(4)]
    assert only(log, "historian") is None


def test_accountant_is_the_same_award_over_numbers():
    log = [rec(i, type="number", correct=100, a=res(answer=100, accuracy=1.0),
               b=res(answer=40, accuracy=0.4)) for i in range(3)]
    a = only(log, "accountant")
    assert a and a.winner == "a" and "the numbers" in a.evidence


def test_mind_reader_reads_the_who_convention_and_wants_eighty_percent():
    log = [rec(i, qid=f"who-said-{i}", a=res(accuracy=1.0), b=res(accuracy=0.0))
           for i in range(4)]
    a = only(log, "mind_reader")
    assert a and a.winner == "a" and "4 of 4" in a.evidence

    weak = [rec(i, qid=f"who-said-{i}",
                a=res(accuracy=1.0 if i < 3 else 0.0), b=res(accuracy=0.0))
            for i in range(5)]
    assert only(weak, "mind_reader") is None        # 3/5 is below the bar


def test_mind_reader_ignores_rounds_that_are_not_who_questions():
    log = [rec(i, qid=f"count-{i}", a=res(accuracy=1.0), b=res(accuracy=0.0))
           for i in range(6)]
    assert only(log, "mind_reader") is None


# ── streaks ───────────────────────────────────────────────────────────────

def test_ice_cold_is_three_consecutive_blanks():
    log = [rec(i, a=res(points=0, accuracy=0.0), b=res(points=700))
           for i in range(3)]
    a = only(log, "ice_cold")
    assert a and a.winner == "a" and "3 rounds" in a.evidence


def test_ice_cold_breaks_on_a_single_point():
    log = [rec(0, a=res(points=0, accuracy=0.0), b=res(points=700)),
           rec(1, a=res(points=10), b=res(points=700)),
           rec(2, a=res(points=0, accuracy=0.0), b=res(points=700))]
    assert only(log, "ice_cold") is None


def test_on_fire_is_four_in_a_row():
    three = [rec(i, a=res(accuracy=1.0), b=res(accuracy=0.0, points=0))
             for i in range(3)]
    assert only(three, "on_fire") is None
    three.append(rec(3, a=res(accuracy=1.0), b=res(accuracy=0.0, points=0)))
    a = only(three, "on_fire")
    assert a and a.winner == "a" and "4 in a row" in a.evidence


def test_a_graded_near_miss_is_not_a_correct_answer():
    """A month two out still scores. It is not a streak."""
    log = [rec(i, type="month", a=res(accuracy=0.5, points=400),
               b=res(accuracy=0.0, points=0)) for i in range(5)]
    assert only(log, "on_fire") is None


# ── the shape of the game ─────────────────────────────────────────────────

def test_comeback_kid_needs_a_real_hole_to_climb_out_of():
    log = [rec(0, a=res(points=0, accuracy=0.0), b=res(points=2000)),
           rec(1, a=res(points=0, accuracy=0.0), b=res(points=0, accuracy=0.0)),
           rec(2, a=res(points=1500), b=res(points=0, accuracy=0.0)),
           rec(3, a=res(points=1500), b=res(points=0, accuracy=0.0))]
    a = only(log, "comeback_kid")
    assert a and a.winner == "a" and "2,000 behind" in a.evidence


def test_comeback_kid_does_not_fire_on_a_close_game():
    log = [rec(i, a=res(points=500), b=res(points=400)) for i in range(4)]
    assert only(log, "comeback_kid") is None


def test_wire_to_wire_wants_every_single_round():
    log = [rec(i, a=res(points=900), b=res(points=100)) for i in range(4)]
    a = only(log, "wire_to_wire")
    assert a and a.winner == "a" and "all 4 rounds" in a.evidence


def test_wire_to_wire_is_broken_by_one_level_round():
    log = [rec(0, a=res(points=500), b=res(points=500))] + \
          [rec(i, a=res(points=900), b=res(points=100)) for i in range(1, 4)]
    assert only(log, "wire_to_wire") is None


def test_quietly_devastating_is_a_win_from_nowhere():
    log = [rec(i, a=res(points=100), b=res(points=900)) for i in range(3)] + \
          [rec(3, a=res(points=5000), b=res(points=0, accuracy=0.0))]
    a = only(log, "quietly_devastating")
    assert a and a.winner == "a"
    assert only(log, "wire_to_wire") is None        # they are mutually exclusive


def test_split_brain_is_shared_by_both_of_you():
    log = [rec(i, a=res(answer=1, points=0, accuracy=0.0),
               b=res(answer=1, points=0, accuracy=0.0)) for i in range(2)]
    a = only(log, "split_brain")
    assert a and set(a.winners) == {"a", "b"}
    assert "same wrong answer" in a.evidence


def test_split_brain_needs_the_same_wrong_answer_not_just_two_wrong_ones():
    log = [rec(i, a=res(answer=1, points=0, accuracy=0.0),
               b=res(answer=2, points=0, accuracy=0.0)) for i in range(3)]
    assert only(log, "split_brain") is None


# ── numbers ───────────────────────────────────────────────────────────────

def test_sniper_is_within_five_percent():
    log = [rec(0, type="number", correct=1000,
               a=res(answer=1020, accuracy=0.98), b=res(answer=400, accuracy=0.4))]
    a = only(log, "sniper")
    assert a and a.winner == "a" and "1,020" in a.evidence


def test_sniper_does_not_fire_on_a_near_miss():
    log = [rec(0, type="number", correct=1000,
               a=res(answer=1200, accuracy=0.8), b=res(answer=400, accuracy=0.4))]
    assert only(log, "sniper") is None


def test_wildly_optimistic_wants_four_times_the_answer():
    log = [rec(0, type="number", correct=50,
               a=res(answer=300, accuracy=0.0, points=0), b=res(answer=52))]
    a = only(log, "wildly_optimistic")
    assert a and a.winner == "a" and "6×" in a.evidence


def test_wildly_optimistic_ignores_a_mere_overshoot():
    log = [rec(0, type="number", correct=50,
               a=res(answer=120, accuracy=0.0, points=0), b=res(answer=52))]
    assert only(log, "wildly_optimistic") is None


# ── kinds ─────────────────────────────────────────────────────────────────

def test_sentimental_reads_the_soft_kinds():
    soft = sorted(S.SOFT_KINDS)[:3]
    log = [rec(i, kind=k, a=res(accuracy=0.95), b=res(accuracy=0.2))
           for i, k in enumerate(soft)]
    a = only(log, "sentimental")
    assert a and a.winner == "a" and "soft rounds" in a.evidence


def test_an_unknown_kind_simply_never_fires_sentimental():
    log = [rec(i, kind="Brand new label", a=res(accuracy=0.95), b=res(accuracy=0.2))
           for i in range(4)]
    assert only(log, "sentimental") is None


def test_the_realist_is_petty_grievances():
    log = [rec(i, kind=S.PETTY, a=res(accuracy=0.2), b=res(accuracy=0.95))
           for i in range(3)]
    a = only(log, "realist")
    assert a and a.winner == "b" and S.PETTY in a.evidence


def test_the_constant_wants_eight_scoring_rounds():
    seven = [rec(i, a=res(points=500), b=res(points=100 * (i % 7 + 1)))
             for i in range(7)]
    assert only(seven, "the_constant") is None
    eight = [rec(i, a=res(points=500), b=res(points=100 * (i % 7 + 1)))
             for i in range(8)]
    a = only(eight, "the_constant")
    assert a and a.winner == "a"


# ── dealing them ──────────────────────────────────────────────────────────

def test_award_deals_at_most_five_most_decisive_first():
    log = [rec(i, type="month", qid=f"who-{i}", kind=S.PETTY,
               a=res(accuracy=1.0, elapsed=1.0, points=900),
               b=res(accuracy=0.0, elapsed=24.0, points=0, answer=None))
           for i in range(10)]
    got = award(log, NAMES)
    assert len(got) == 5
    assert [a.decisiveness for a in got] == sorted(
        (a.decisiveness for a in got), reverse=True)


def test_an_evaluator_that_explodes_does_not_take_the_podium_with_it(monkeypatch):
    def boom(t):
        raise ZeroDivisionError("not on the night")
    monkeypatch.setattr(S, "CATALOG", [boom, S.fastest_finger])
    log = [rec(i, a=res(elapsed=2.0), b=res(elapsed=8.0)) for i in range(4)]
    assert [a.key for a in award(log, NAMES)] == ["fastest_finger"]


def test_an_empty_log_awards_nothing():
    assert award([], NAMES) == []


def test_awards_never_mutate_the_log():
    log = [rec(i, a=res(elapsed=2.0), b=res(elapsed=8.0)) for i in range(4)]
    before = [(r.index, dict(r.results)) for r in log]
    award(log, NAMES)
    assert [(r.index, dict(r.results)) for r in log] == before


def test_a_player_who_joined_late_is_absent_not_wrong():
    """No result for a round is not a zero. Otherwise every latecomer wins
    Ice Cold for the rounds they were not in the room for."""
    log = [rec(0, a=res(points=900)), rec(1, a=res(points=900)),
           rec(2, a=res(points=900)),
           rec(3, a=res(points=900), b=res(points=800))]
    t = Tally(log=log, names=NAMES, seconds=25.0)
    assert t.pids == ["a", "b"]
    assert only(log, "ice_cold") is None


def test_the_wire_shape_is_json_ready():
    log = [rec(i, a=res(elapsed=2.0), b=res(elapsed=8.0)) for i in range(4)]
    d = as_dict(award(log, NAMES)[0])
    assert set(d) == {"key", "title", "winners", "evidence"}
    assert isinstance(d["winners"], list)


# ── the score graph (S4.1) ────────────────────────────────────────────────

def test_the_curve_is_the_running_score_per_player():
    log = [rec(0, a=res(points=900), b=res(points=100)),
           rec(1, a=res(points=200), b=res(points=800))]
    c = S.curve(log, NAMES)
    assert {l.name: l.points for l in c.lines} == {"Shray": (900, 1100),
                                                   "Nilu": (100, 900)}
    assert c.rounds == 2 and c.high == 1100


def test_a_lead_change_is_recorded_where_it_happens():
    log = [rec(0, a=res(points=900), b=res(points=100)),     # Shray ahead
           rec(1, a=res(points=0, accuracy=0.0), b=res(points=1000))]  # Nilu takes it
    assert S.curve(log, NAMES).leads == (1,)


def test_level_is_nobody_leading_not_a_lead_change():
    """Drawing level and then retaking the lead is one change, not two, or a
    close game comes out as a dotted line."""
    log = [rec(0, a=res(points=900), b=res(points=100)),
           rec(1, a=res(points=100), b=res(points=900)),      # level at 1000
           rec(2, a=res(points=900), b=res(points=100))]      # Shray again
    assert S.curve(log, NAMES).leads == ()


def test_the_biggest_round_of_the_game_is_annotated():
    log = [rec(0, a=res(points=400), b=res(points=100)),
           rec(1, a=res(points=120), b=res(points=980)),
           rec(2, a=res(points=300), b=res(points=100))]
    c = S.curve(log, NAMES)
    assert (c.best_round, c.best_pid, c.best_points) == (1, "b", 980)


def test_an_empty_log_makes_an_empty_curve():
    c = S.curve([], NAMES)
    assert c.rounds == 0 and c.leads == () and c.best_pid is None and c.high == 0


def test_the_curve_wire_shape_is_json_ready():
    log = [rec(0, a=res(points=900), b=res(points=100))]
    d = S.curve_dict(S.curve(log, NAMES))
    assert set(d) == {"rounds", "lines", "leads", "best", "high"}
    assert d["lines"][0]["points"] == [900]
    import json; json.dumps(d)


# ── the Final Receipt ─────────────────────────────────────────────────────
#
# All In and Ice in the Veins are the only two awards about what someone
# risked rather than what they knew, and the only two that read `stake`.


def game_to_a_wager(before_a, before_b, a_stake, b_stake, a_right, b_right):
    """Enough ordinary rounds to put both players on a known score, then the
    Final Receipt. `stake_cap` is the score going in, floored at 500, so the
    body of the game is what decides whether a stake counts as all in."""
    log = [rec(i, a=res(points=before_a // 2, rank=1),
               b=res(points=before_b // 2, rank=2)) for i in range(2)]
    log.append(rec(2, type="wager", kind="Final receipt",
                   a=res(answer=0 if a_right else 1,
                         points=a_stake if a_right else -a_stake,
                         accuracy=1.0 if a_right else 0.0, stake=a_stake),
                   b=res(answer=0 if b_right else 1,
                         points=b_stake if b_right else -b_stake,
                         accuracy=1.0 if b_right else 0.0, stake=b_stake)))
    return log


def test_ice_in_the_veins_fires_on_a_winning_shove():
    log = game_to_a_wager(2000, 2000, 2000, 100, a_right=True, b_right=True)
    a = only(log, "ice_in_the_veins")
    assert a and a.winners == ("a",)
    assert "2,000" in a.evidence and "Shray" in a.evidence


def test_all_in_fires_on_a_losing_shove():
    log = game_to_a_wager(2000, 2000, 2000, 100, a_right=False, b_right=True)
    a = only(log, "all_in")
    assert a and a.winners == ("a",)
    assert "It was wrong." in a.evidence


def test_the_two_stake_awards_cannot_both_land_on_one_player():
    """Exclusive by construction, not by suppression: one takes the winners,
    the other takes the losers."""
    for right in (True, False):
        log = game_to_a_wager(2000, 2000, 2000, 100, a_right=right, b_right=True)
        got = {a.key for a in award(log, NAMES, limit=99)
               if "a" in a.winners and a.key in ("all_in", "ice_in_the_veins")}
        assert len(got) == 1, got


def test_a_careful_stake_wins_nothing_for_being_big():
    """1,000 of a possible 2,000 is half, not everything."""
    log = game_to_a_wager(2000, 2000, 1000, 100, a_right=True, b_right=False)
    assert only(log, "ice_in_the_veins") is None
    assert only(log, "all_in") is None


def test_both_going_all_in_shares_the_award():
    log = game_to_a_wager(2000, 2000, 2000, 2000, a_right=False, b_right=False)
    a = only(log, "all_in")
    assert a and set(a.winners) == {"a", "b"}
    assert "both put" in a.evidence


def test_the_floor_counts_as_everything():
    """Game.stake_cap lets anyone stake WAGER_FLOOR however little they have,
    so shoving it is going all in — measuring against their score would call
    500 of 300 points a 166% wager and never fire."""
    log = game_to_a_wager(300, 4000, 500, 100, a_right=True, b_right=True)
    a = only(log, "ice_in_the_veins")
    assert a and a.winners == ("a",)


def test_a_game_with_no_wager_fires_neither():
    log = [rec(i, a=res(), b=res(points=0, accuracy=0.0)) for i in range(4)]
    assert only(log, "all_in") is None
    assert only(log, "ice_in_the_veins") is None


def test_a_player_who_never_answered_the_receipt_is_not_all_in():
    log = game_to_a_wager(2000, 2000, 2000, 100, a_right=True, b_right=True)
    log[-1].results["b"] = PlayerResult(answer=None, points=0, accuracy=0.0,
                                        elapsed=25.0, rank_after=2, stake=None)
    a = only(log, "ice_in_the_veins")
    assert a and a.winners == ("a",)


def test_ice_in_the_veins_outranks_the_ordinary_awards():
    """It is the last thing that happens on the last round of the night. If it
    fires, it belongs on the podium rather than sixth in a list of five."""
    log = game_to_a_wager(2000, 2000, 2000, 100, a_right=True, b_right=True)
    top = award(log, NAMES, limit=5)
    assert "ice_in_the_veins" in [a.key for a in top]
