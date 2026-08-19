"""The pipeline: dedup, guards, templating."""
import pytest

from tools.compile import Report, build_context, dedupe, guard, render
from tools.resolvers import Resolution


def q(id, origin="auto", topic=None, **kw):
    return {"id": id, "origin": origin, "topic": topic or id,
            "type": "binary", "prompt": "who?", "reveal": "them", **kw}


# ── dedup ─────────────────────────────────────────────────────────────────

def test_your_question_kills_the_generated_one_on_the_same_topic():
    rep = Report()
    out = dedupe([q("auto-love", topic="love-count"),
                  q("my-love", origin="mine", topic="love-count")], {}, rep)
    assert [x["id"] for x in out] == ["my-love"]


def test_a_generated_question_on_an_untouched_topic_survives():
    rep = Report()
    out = dedupe([q("a1", topic="t1"), q("m1", origin="mine", topic="t2")], {}, rep)
    assert len(out) == 2


def test_two_of_your_own_colliding_is_an_error_not_a_silent_drop():
    with pytest.raises(SystemExit):
        dedupe([q("m1", origin="mine", topic="same"),
                q("m2", origin="mine", topic="same")], {}, Report())


def test_near_duplicate_prompts_are_reported_never_auto_dropped():
    rep = Report()
    a = q("m1", origin="mine"); a["prompt"] = "How many times have we said I love you?"
    b = q("a1"); b["prompt"] = "How many times have we said I love you today?"
    out = dedupe([a, b], {}, rep)
    assert len(out) == 2                 # nothing lost
    assert rep.warnings                   # but you get told


# ── guards ────────────────────────────────────────────────────────────────

CFG = {"guards": {"min_margin": 1.25, "min_answer": 20, "min_hits": 3,
                  "month_edge_pct": 0.10, "require_reveal": True}}


def test_a_coin_flip_is_not_a_question():
    rep = Report()
    close = Resolution(value=0, hits=100, extras={"n1": 51, "n2": 50, "_margin": 1.02})
    assert guard(q("x"), close, CFG, 60, rep) is False
    clear = Resolution(value=0, hits=100, extras={"n1": 90, "n2": 10, "_margin": 9.0})
    assert guard(q("y"), clear, CFG, 60, rep) is True


def test_tiny_numbers_score_degenerately_so_they_are_dropped():
    rep = Report()
    small = dict(q("x"), type="number", answer=4)
    assert guard(small, Resolution(value=4, hits=4), CFG, 60, rep) is False


def test_month_answers_at_the_extremes_are_guessable():
    rep = Report()
    for ix, ok in ((2, False), (30, True), (58, False)):
        item = dict(q("x"), type="month", answer=ix)
        assert guard(item, Resolution(value=ix, hits=9), CFG, 60, rep) is ok


def test_too_few_matches_is_a_drop():
    rep = Report()
    assert guard(q("x"), Resolution(value=1, hits=2), CFG, 60, rep) is False


def test_a_todo_never_reaches_the_big_screen():
    rep = Report()
    item = dict(q("x"), reveal="TODO — write this")
    assert guard(item, Resolution(value=1, hits=9), CFG, 60, rep) is False


# ── templating ────────────────────────────────────────────────────────────

def test_template_vars_render():
    ctx = {"p1": "Shray", "p2": "Nilu", "answer": 1877, "winner": "Nilu"}
    assert render("{p1} & {p2}", ctx, "x") == "Shray & Nilu"
    assert render("{answer:,} times", ctx, "x") == "1,877 times"


def test_unknown_template_var_names_the_question():
    with pytest.raises(ValueError, match="my-q"):
        render("{nonsense}", {"p1": "a"}, "my-q")


def test_context_resolves_an_index_answer_to_its_option_text():
    res = Resolution(value=1)
    ctx = build_context({"p1": "Shray", "p2": "Nilu", "total": 10},
                        res, {"type": "binary"}, ["Shray", "Nilu"])
    assert ctx["answer"] == "Nilu"
