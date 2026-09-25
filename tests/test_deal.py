"""Dealing. Authored questions beat generated ones — that's a product rule."""
import random
from collections import Counter

from app.game import DealRules, Game
from tests.conftest import make_dataset, q


def build(n_mine, n_auto, rounds=14, seed=1, rules=None, seen=None):
    qs = [q(f"m{i}", kind=f"mine{i % 4}", origin="mine") for i in range(n_mine)]
    qs += [q(f"a{i}", kind=f"auto{i % 5}", origin="auto") for i in range(n_auto)]
    g = Game(make_dataset(qs, rounds=rounds), rng=random.Random(seed), rules=rules)
    g.deal(seen=seen)
    return g


def test_deals_the_right_number_of_rounds():
    assert len(build(20, 60).deck) == 14


def test_authored_share_is_a_floor_not_a_cap():
    """65% is filled first; the top-up pass still favours yours at 4x weight,
    so writing more questions monotonically increases your share of the game."""
    g = build(20, 60)
    mine = sum(1 for x in g.deck if x.origin == "mine")
    assert mine >= round(14 * 0.65)          # at least 9 of 14


def test_writing_more_questions_gets_you_more_of_the_game():
    few = sum(1 for x in build(4, 60, seed=5).deck if x.origin == "mine")
    many = sum(1 for x in build(40, 60, seed=5).deck if x.origin == "mine")
    assert many > few


def test_backfills_from_auto_when_you_have_not_written_enough():
    g = build(3, 60)
    assert len(g.deck) == 14
    assert sum(1 for x in g.deck if x.origin == "mine") == 3


def test_authored_only_bank_deals_only_authored():
    g = build(30, 0)
    assert all(x.origin == "mine" for x in g.deck)


def test_no_kind_dominates_a_game():
    g = build(20, 60)
    worst = Counter(x.kind for x in g.deck).most_common(1)[0][1]
    assert worst <= DealRules().max_per_kind


def test_same_kind_never_lands_twice_in_a_row():
    for seed in range(20):
        deck = build(20, 60, seed=seed).deck
        assert all(a.kind != b.kind for a, b in zip(deck, deck[1:])), seed


def test_no_duplicates_in_a_deck():
    ids = [x.id for x in build(20, 60).deck]
    assert len(ids) == len(set(ids))


def test_replays_differ():
    a = [x.id for x in build(20, 60, seed=1).deck]
    b = [x.id for x in build(20, 60, seed=2).deck]
    assert a != b


def test_freshness_avoids_recently_seen_questions():
    """Down-weight, not exclude — a small bank must still be able to fill."""
    seen = {f"a{i}": 5 for i in range(30)}
    fresh = build(0, 60, seen=seen).deck
    stale = sum(1 for x in fresh if seen.get(x.id))
    assert stale < 7          # would be ~7 if freshness did nothing


def test_freshness_can_be_turned_off():
    rules = DealRules(freshness=False)
    g = build(20, 60, rules=rules)
    assert len(g.deck) == 14


def test_small_bank_still_deals_a_full_game():
    """Kind caps must not deadlock a bank with few categories."""
    qs = [q(f"x{i}", kind="only") for i in range(20)]
    g = Game(make_dataset(qs, rounds=14), rng=random.Random(3))
    g.deal()
    assert len(g.deck) == 14


def test_the_wager_is_always_the_last_round_and_never_one_of_the_others():
    """Round 15 of 14. A wager is held out of the body of the game entirely, so
    it can't land at round 3, and one is always appended when the bank has one."""
    qs = [q(f"k{i}", kind=f"k{i}") for i in range(6)]
    qs += [q(f"w{i}", type="wager", answer=0, kind="Final receipt")
           for i in range(3)]
    g = Game(make_dataset(qs, rounds=6), rng=random.Random(3))
    g.deal()
    assert len(g.deck) == 7                      # six rounds, then the closer
    assert g.deck[-1].type == "wager"
    assert [x.type for x in g.deck[:-1]] == ["binary"] * 6


def test_wagers_do_not_count_towards_the_round_target():
    """A bank of five ordinary questions plays five rounds plus the receipt —
    the wagers must not pad `rounds` up to the dataset's number.

    This is also the "bank smaller than rounds" case: the schema won't let a
    dataset ship with fewer questions than rounds, but holding the wagers back
    can still leave the body of the game short. Deal what we have rather than
    crashing on game night.
    """
    qs = [q(f"x{i}", kind=f"k{i}") for i in range(5)]
    qs += [q(f"w{i}", type="wager", answer=0, kind="Final receipt")
           for i in range(10)]
    g = Game(make_dataset(qs, rounds=14), rng=random.Random(3))
    g.deal()
    assert g.rounds == 5
    assert len(g.deck) == 6
    assert g.deck[-1].type == "wager"


def test_no_wager_in_the_bank_means_no_extra_round():
    qs = [q(f"k{i}", kind=f"k{i}") for i in range(6)]
    g = Game(make_dataset(qs, rounds=6), rng=random.Random(3))
    g.deal()
    assert len(g.deck) == 6


def test_final_receipt_off_drops_the_closer():
    qs = [q(f"k{i}", kind=f"k{i}") for i in range(6)]
    qs += [q("w1", type="wager", answer=0, kind="Final receipt")]
    g = Game(make_dataset(qs, rounds=6), rng=random.Random(3),
             rules=DealRules(final_receipt=False))
    g.deal()
    assert len(g.deck) == 6
    assert "w1" not in {x.id for x in g.deck}


def test_percent_and_mutual_are_dealt():
    """Both have phone inputs now — a 0-100 slider and the same option grid the
    choice questions use. This is the assertion that fails if PLAYABLE is
    narrowed again without the UI going with it."""
    qs = [q(f"k{i}", kind=f"k{i}") for i in range(4)]
    qs += [q("p1", type="percent", answer=50, kind="pc"),
           q("mu1", type="mutual", kind="mu")]
    g = Game(make_dataset(qs, rounds=6), rng=random.Random(3))
    g.deal()
    assert {"p1", "mu1"} <= {x.id for x in g.deck}


# ── the subject cap ───────────────────────────────────────────────────────

def test_the_same_subject_never_lands_twice_in_one_game():
    """`kind` is only the eyebrow. Three questions about what gets sent after
    midnight, filed under three different kinds, are the same question in three
    costumes — and a bank of 160 has no need to ask twice."""
    qs = [q(f"a{i}", kind=f"k{i}", subject="late_night") for i in range(5)]
    qs += [q(f"b{i}", kind=f"j{i}", subject=f"other{i}") for i in range(10)]
    g = Game(make_dataset(qs, rounds=10), rng=random.Random(5))
    g.deal()
    subs = [x.subject for x in g.deck if x.subject]
    assert len(subs) == len(set(subs)), subs


def test_a_question_with_no_subject_is_never_blocked():
    """One baked from a real message is about that message and can only ever
    collide with itself — if these were capped, the message rounds, which are
    most of the bank, would deal one per game."""
    qs = [q(f"m{i}", kind=f"k{i % 3}") for i in range(12)]
    g = Game(make_dataset(qs, rounds=9), rng=random.Random(5))
    g.deal()
    assert len(g.deck) == 9


def test_the_closer_is_not_pre_answered_by_the_body_of_the_game():
    """A wager on who said it first is worth nothing at round 15 if round 4
    already showed the message. The Final Receipt is chosen before the draw and
    owns its subject."""
    qs = [q(f"x{i}", kind=f"k{i}", subject="love_you") for i in range(6)]
    qs += [q(f"y{i}", kind=f"j{i}", subject=f"free{i}") for i in range(10)]
    qs += [q("fin", type="wager", answer=0, kind="Final receipt", subject="love_you")]
    for seed in range(20):
        g = Game(make_dataset(qs, rounds=8), rng=random.Random(seed))
        g.deal()
        assert g.deck[-1].id == "fin"
        assert not any(x.subject == "love_you" for x in g.deck[:-1])


def test_raising_the_subject_cap_lets_a_pair_through():
    qs = [q(f"a{i}", kind=f"k{i}", subject="same") for i in range(4)]
    qs += [q(f"b{i}", kind=f"j{i}", subject=f"o{i}") for i in range(8)]
    g = Game(make_dataset(qs, rounds=8), rng=random.Random(3),
             rules=DealRules(max_per_subject=2))
    g.deal()
    assert max(Counter(x.subject for x in g.deck if x.subject).values()) <= 2


def test_the_subject_cap_never_shortens_the_deck_when_there_is_material():
    """The cap must narrow *which* questions, not how many rounds you get."""
    qs = [q(f"a{i}", kind=f"k{i % 4}", subject=f"s{i % 6}") for i in range(40)]
    g = Game(make_dataset(qs, rounds=6), rng=random.Random(9))
    g.deal()
    assert len(g.deck) == 6
