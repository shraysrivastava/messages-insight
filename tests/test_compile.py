"""The pipeline: dedup, guards, templating."""
import json
import os
import tomllib

import pytest

from tools.compile import (ROOT, Report, build_context, dedupe, guard,
                           load_questions, render, shows_histogram)
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


# ── the month histogram (S3.1) ────────────────────────────────────────────

def test_a_question_answered_by_the_density_table_hides_the_histogram():
    """"Which month did we text the least?" is free if the picture is drawn."""
    assert not shows_histogram({"type": "month"}, {"quietest_month": True})
    assert not shows_histogram({"type": "month"}, {"busiest_month": True})


def test_an_ordinary_month_question_keeps_its_histogram():
    assert shows_histogram({"type": "month"}, {"first_use": "i_love_you"})


def test_only_month_questions_are_affected():
    assert shows_histogram({"type": "number"}, {"quietest_month": True})


def test_an_author_can_turn_it_off_by_hand():
    assert not shows_histogram({"type": "month", "histogram": False}, None)


def test_a_question_with_no_resolver_keeps_its_histogram():
    """A curated question has a source, not a spec. It is not density-derived."""
    assert shows_histogram({"type": "month"}, None)


def test_a_narrowed_density_question_keeps_its_histogram():
    """The busiest month *for work stress* is not the busiest month. The
    whole-thread picture does not answer it."""
    assert shows_histogram({"type": "month"},
                           {"busiest_month": True, "within": "work"})


# ── the demo dataset is handed to people (CLAUDE.md, Privacy) ─────────────

def test_the_demo_build_leaves_your_own_questions_out(tmp_path):
    """`mine.toml` quotes the real thread verbatim. A demo built from the fake
    corpus still leaks if the question bank carries those blocks through."""
    (tmp_path / "auto").mkdir()
    (tmp_path / "mine.toml").write_text(
        '[[q]]\nid="m1"\ntype="binary"\nkind="k"\nprompt="p"\nreveal="r"\n')
    (tmp_path / "auto" / "a.toml").write_text(
        '[[q]]\nid="a1"\ntype="binary"\nkind="k"\nprompt="p"\nreveal="r"\n')

    both = load_questions(str(tmp_path))
    assert sorted(q["id"] for q in both) == ["a1", "m1"]

    auto_only = load_questions(str(tmp_path), include_mine=False)
    assert [q["id"] for q in auto_only] == ["a1"]


def test_the_committed_demo_dataset_carries_nothing_of_yours():
    """A regression guard on the file itself, not the builder. This is the one
    dataset in git, and `make demo` rewrites it."""
    with open(os.path.join(ROOT, "datasets", "demo.json"), encoding="utf-8") as f:
        demo = json.load(f)
    assert [q["id"] for q in demo["questions"] if q.get("origin") == "mine"] == []

    mine = os.path.join(ROOT, "questions", "mine.toml")
    if not os.path.exists(mine):
        return                              # not checked out here; nothing to compare
    with open(mine, "rb") as f:
        yours = {q.get("text") for q in tomllib.load(f).get("q", []) if q.get("text")}
    shipped = {q.get("text") for q in demo["questions"] if q.get("text")}
    assert not (yours & shipped), "a curated message reached the demo dataset"
