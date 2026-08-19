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


def test_playable_bank_smaller_than_rounds_shrinks_the_game():
    """The schema won't let a dataset ship with fewer questions than rounds, but
    filtering to PLAYABLE types can still leave the bank short. Deal what we have
    rather than crashing on game night."""
    qs = [q(f"x{i}", kind=f"k{i}") for i in range(5)]
    qs += [q(f"p{i}", type="percent", answer=50, kind=f"pc{i}") for i in range(10)]
    g = Game(make_dataset(qs, rounds=14), rng=random.Random(3))
    g.deal()
    assert len(g.deck) == 5
    assert g.rounds == 5


def test_unplayable_types_never_reach_the_bank():
    """percent/wager/mutual have no client input yet, so they can't be dealt."""
    qs = [q(f"k{i}", kind=f"k{i}") for i in range(6)]
    qs += [q("p1", type="percent", answer=50, kind="pc"),
           q("w1", type="wager", answer=0, kind="wg"),
           q("mu1", type="mutual", kind="mu")]
    g = Game(make_dataset(qs, rounds=6), rng=random.Random(3))
    g.deal()
    assert {"p1", "w1", "mu1"}.isdisjoint({x.id for x in g.deck})
