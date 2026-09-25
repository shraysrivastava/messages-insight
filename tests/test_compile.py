"""The pipeline: dedup, guards, templating."""
import json
import os
import sys
import tomllib

import pytest

from tools.compile import (REVEAL_MASK, ROOT, Report, blind, build_context,
                           dedupe, guard, load_questions, render,
                           shows_histogram, shuffle_options)
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


# ── the dev dataset is the audit surface (CLAUDE.md, Privacy) ─────────────
# He designs the game and also plays it. `--dev` is how he reviews every
# question without learning a single answer, so these tests guard the one
# property that makes that true.

def _real():
    return [
        {"id": "b", "type": "binary", "kind": "k", "prompt": "who?",
         "reveal": "Shray. 412 to 208.", "options": ["Shray", "Nilu"],
         "answer": 0, "context": [{"from": "p1", "text": "a real message"}]},
        {"id": "n", "type": "number", "kind": "k", "prompt": "how many?",
         "reveal": "4,182 of them.", "answer": 4182, "histogram": True},
        {"id": "m", "type": "month", "kind": "k", "prompt": "when?",
         "reveal": "March 2024.", "answer": 19},
    ]


def test_the_dev_dataset_keeps_every_question_and_its_order():
    """He cuts questions by number, so the numbering has to match real.json."""
    out = blind(_real(), months=48)
    assert [x["id"] for x in out] == ["b", "n", "m"]
    assert [x["prompt"] for x in out] == ["who?", "how many?", "when?"]


def test_the_dev_dataset_states_no_answer_anywhere():
    for x in blind(_real(), months=48):
        assert x["reveal"] == REVEAL_MASK
        assert "context" not in x       # the thread shows who was talking
        assert x["histogram"] is False  # the density curve narrows the month


def test_a_blinded_answer_is_independent_of_the_real_one():
    """The guarantee. Answers are drawn uniformly, *ignoring* the truth — so
    they carry zero information about it. Flip every real answer and the
    distribution of blinded ones must not move."""
    flipped = []
    for x in _real():
        y = dict(x)
        y["answer"] = {"b": 1, "n": 7, "m": 2}[x["id"]]   # note: 7, not 4182
        flipped.append(y)
    for seed in range(25):
        assert ([x["answer"] for x in blind(_real(), 48, seed)]
                == [x["answer"] for x in blind(flipped, 48, seed)])


def test_blinded_answers_stay_inside_the_schema():
    from app.schema import Question
    for seed in range(25):
        for x in blind(_real(), months=48, seed=seed):
            Question.model_validate(x)      # raises if out of range


# ── resolver options used to always answer to A ──────────────────────────

def test_resolver_options_do_not_all_answer_to_a():
    """`top_emoji` and friends return most_common(n) with value=0. Shipped
    unshuffled, every choice round in the game answered to option A."""
    seen = set()
    for qid in [f"q{i}" for i in range(40)]:
        out = {"options": ["a", "b", "c", "d"], "answer": 0}
        shuffle_options(out, qid)
        seen.add(out["answer"])
    assert len(seen) > 1, "every question still answers to the same index"


def test_shuffling_keeps_the_answer_pointing_at_the_same_option():
    for qid in [f"q{i}" for i in range(40)]:
        out = {"options": ["w", "x", "y", "z"], "answer": 0}
        shuffle_options(out, qid)
        assert out["options"][out["answer"]] == "w"


def test_shuffling_is_stable_across_recompiles():
    """A question must not change shape between the audit pass and the game."""
    a = {"options": ["w", "x", "y", "z"], "answer": 0}
    b = {"options": ["w", "x", "y", "z"], "answer": 0}
    shuffle_options(a, "same-id"); shuffle_options(b, "same-id")
    assert a == b


def test_the_committed_dataset_does_not_answer_to_a_every_time():
    with open(os.path.join(ROOT, "datasets", "demo.json"), encoding="utf-8") as f:
        qs = json.load(f)["questions"]
    idx = {q["answer"] for q in qs if q["type"] == "choice"}
    assert len(idx) > 1, f"every choice question answers to {idx}"


# ── the min_hits guard vs. extremum resolvers ────────────────────────────

@pytest.mark.parametrize("res_name", ["longest_message_words",
                                      "longest_gap_hours", "quietest_month"])
def test_an_extremum_question_is_not_dropped_for_having_one_match(res_name):
    """These report a single result by definition. Reporting `hits=1` made
    `min_hits` drop them on every build — `quietest-month`, `longest-gap` and
    `longest-message` were all silently missing from the shipped dataset."""
    import json as _json
    from tools.resolvers import Corpus, resolve
    corpus = Corpus(_json.loads(_json.dumps({
        "meta": {"p1": "A", "p2": "B",
                 "months": ["2024-01", "2024-02", "2024-03"]},
        "messages": [{"i": i, "ts": f"2024-0{1 + i % 3}-0{1 + i % 9}T12:00:00",
                      "from": "p1" if i % 2 else "p2", "text": "hello there " * (i + 1)}
                     for i in range(30)],
    })))
    r = resolve(corpus, {res_name: True}, {})
    assert r.error is None, r.error
    assert r.hits is None, f"{res_name} still reports a match count"
    rep = Report()
    assert guard({"id": "x", "type": "number", "answer": 99}, r, {}, 3, rep)


def test_a_source_picked_message_is_not_dropped_for_having_one_match():
    """`source = {first_message = true}` and `source = {search = ...}` select
    ONE message. Reporting `hits=1` put them under the default min_hits of 3,
    which silently dropped the Final Receipt from every build — invisible for
    as long as wagers were also being dropped as unplayable."""
    import json as _json
    from tools.compile import resolve_source
    from tools.resolvers import Corpus
    corpus = Corpus(_json.loads(_json.dumps({
        "meta": {"p1": "A", "p2": "B", "months": ["2024-01", "2024-02"]},
        "messages": [{"i": i, "ts": f"2024-0{1 + i % 2}-0{1 + i % 9}T12:00:00",
                      "from": "p1" if i % 2 else "p2", "text": "hello there"}
                     for i in range(10)],
    })))
    for src in ({"first_message": True}, {"search": "hello"}):
        r = resolve_source(corpus, src, {})
        assert r.error is None, r.error
        assert r.hits is None, f"{src} still reports a match count"
        rep = Report()
        assert guard({"id": "x", "type": "wager", "answer": 0}, r, CFG, 2, rep)


# ── the text audit must not be able to print an answer ───────────────────

def test_the_text_audit_refuses_a_dataset_that_still_has_reveals(tmp_path):
    """Its safety property is structural: it reads only a --dev build, which
    has no answers in it. Pointed at real.json it must refuse, not print."""
    import subprocess
    bad = tmp_path / "real.json"
    bad.write_text(json.dumps({
        "meta": {"p1": "A", "p2": "B", "months": ["2024-01"], "density": [1],
                 "total": 1, "first": "January 2024", "last": "January 2024",
                 "rounds": 1, "seconds": 25},
        "questions": [{"id": "q1", "type": "binary", "kind": "k",
                       "prompt": "who?", "reveal": "A. 400 to 200.",
                       "options": ["A", "B"], "answer": 0}],
    }))
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "audit.py"),
         "--data", str(bad)], capture_output=True, text=True)
    assert r.returncode != 0
    assert "refusing to print" in r.stdout + r.stderr
    assert "400 to 200" not in r.stdout


def test_a_days_until_question_does_not_print_the_message_itself():
    """It asks how many days. Showing the message answers a different
    question — who said it first, and when — on the same screen."""
    import json as _json
    from tools.lexicon import Lexicon
    from tools.resolvers import Corpus, resolve
    corpus = Corpus(_json.loads(_json.dumps({
        "meta": {"p1": "A", "p2": "B", "months": ["2024-01", "2024-02"]},
        "messages": [{"i": i, "ts": f"2024-01-{i + 1:02d}T12:00:00",
                      "from": "p1" if i % 2 else "p2",
                      "text": "i love you" if i == 5 else "hello there friend"}
                     for i in range(12)],
    })))
    lex = {"love_you": Lexicon("love_you", {"any": ["i love you"]})}
    r = resolve(corpus, {"days_until": "love_you"}, lex)
    assert r.error is None and r.value == 5
    assert r.text is None, "the message reached the question screen"
    assert r.source is not None, "the reveal still needs the thread"


# ── photographs ───────────────────────────────────────────────────────────

def _photo_corpus(tmp_path, name="IMG_0001.HEIC"):
    """A corpus with one downscaled photo on disk, as `make photos` leaves it."""
    import base64 as _b64
    from tools.resolvers import Corpus
    # A one-pixel JPEG. The bytes don't matter; the path through does.
    jpg = _b64.b64decode(
        "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
        "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
        "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
    thumb = tmp_path / "0.jpg"
    thumb.write_bytes(jpg)
    return Corpus({
        "meta": {"p1": "A", "p2": "B", "months": ["2024-01", "2024-02"]},
        "messages": [{"i": 0, "ts": "2024-01-05T10:00:00+00:00",
                      "from": "p2", "text": "", "photo": 0}],
        "photos": [{"k": 0, "i": 0, "ts": "2024-01-05T10:00:00+00:00", "from": "p2",
                    "src": "/nowhere/x.heic", "mime": "image/heic", "name": name,
                    "thumb": str(thumb)}],
    }), _b64.b64encode(jpg).decode()


def test_a_photo_is_embedded_by_name(tmp_path):
    """Named, not indexed: `k` renumbers on every re-extraction and a question
    pointing at the wrong photograph is worse than one with none."""
    from tools.compile import load_photo
    corpus, expect = _photo_corpus(tmp_path)
    assert load_photo(corpus, "IMG_0001.HEIC", "q1") == expect


def test_a_photo_that_was_never_downscaled_is_a_reason_not_a_crash(tmp_path):
    from tools.compile import load_photo
    corpus, _ = _photo_corpus(tmp_path)
    corpus.photos[0].pop("thumb")
    with pytest.raises(ValueError, match="make photos"):
        load_photo(corpus, "IMG_0001.HEIC", "q1")


def test_an_unknown_photo_name_says_so(tmp_path):
    from tools.compile import load_photo
    corpus, _ = _photo_corpus(tmp_path)
    with pytest.raises(ValueError, match="no photo named"):
        load_photo(corpus, "IMG_9999.HEIC", "q1")


def test_two_photos_with_the_same_name_refuse_to_be_guessed_between(tmp_path):
    from tools.compile import load_photo
    corpus, _ = _photo_corpus(tmp_path)
    corpus.photos.append(dict(corpus.photos[0], k=1))
    with pytest.raises(ValueError, match="2 photos named"):
        load_photo(corpus, "IMG_0001.HEIC", "q1")


def test_a_corpus_with_no_photos_says_to_re_extract(tmp_path):
    from tools.compile import load_photo
    corpus, _ = _photo_corpus(tmp_path)
    corpus.photos = []
    with pytest.raises(ValueError, match="re-extract"):
        load_photo(corpus, "IMG_0001.HEIC", "q1")


def test_the_photo_never_rides_in_the_state_snapshot(tmp_path):
    """It is 120 KB and the snapshot goes out on every heartbeat. The client
    gets a flag and fetches /photo/current once."""
    import random as _random

    from app.game import Game
    from tests.conftest import make_dataset, q as _q
    _, b64 = _photo_corpus(tmp_path)
    qs = [_q(f"k{i}", kind=f"k{i}") for i in range(4)]
    qs.append(_q("pic", kind="Photo", format="photo", photo=b64))
    g = Game(make_dataset(qs, rounds=5), rng=_random.Random(1))
    g.deal()
    g.add_player("a", "A")
    ix = next(i for i, x in enumerate(g.deck) if x.id == "pic")
    g.begin_round(ix)
    g.open_question(now=1000.0)
    pub = g.snapshot()["question"]
    assert pub["photo"] is True
    assert b64 not in json.dumps(pub)


# ── subject derivation ────────────────────────────────────────────────────

@pytest.mark.parametrize("spec,want", [
    ({"count": "love_you"}, "love_you"),
    ({"count": "love_you", "by": "p1"}, "love_you"),          # a slice, not a subject
    ({"count": "love_you", "year": 2022}, "love_you"),
    ({"who_says_more": "sorry"}, "sorry"),
    ({"first_use_sender": "love_you"}, "love_you"),
    ({"busiest_month": True, "within": "travel"}, "travel"),  # within is the subject
    ({"busiest_month": True}, "busiest_month"),
    ({"share_between": [0, 5]}, "share_between:[0, 5]"),
    ({"share_between": [9, 17]}, "share_between:[9, 17]"),    # a different subject
    ({"share_of_messages": "p1"}, "share_of_messages:p1"),
    ({"top_emoji": 4}, "top_emoji:4"),
    (None, None),
    ({}, None),
])
def test_subject_is_the_fact_not_the_slice(spec, want):
    from tools.compile import subject_of
    assert subject_of(spec) == want


def test_a_question_baked_from_one_message_has_no_subject():
    """It is about that message. Giving it a subject would make the dealer
    treat every Who Said It round as interchangeable and deal one per game."""
    from tools.compile import subject_of
    assert subject_of({"mine": "who_said_it"}) == "mine:who_said_it"
    assert subject_of(None) is None


def test_the_shipped_bank_asks_nothing_twice_in_one_game():
    """The regression guard for the whole audit: deal the real deck a hundred
    times and no game may contain two questions about the same fact."""
    import collections
    import random as _random

    from app.game import DealRules, Game
    from app.schema import load
    path = os.path.join(ROOT, "datasets", "real.json")
    if not os.path.exists(path):
        pytest.skip("no compiled real.json on this machine")
    data = load(path)
    rules = DealRules(**data.meta.deal.model_dump())
    for seed in range(100):
        g = Game(data, rng=_random.Random(seed), rules=rules)
        g.deal()
        subs = [q.subject for q in g.deck if q.subject]
        dupes = [s for s, n in collections.Counter(subs).items() if n > 1]
        assert not dupes, f"seed {seed} asks about {dupes} twice"
