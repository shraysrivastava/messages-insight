"""rethread.py — finding the conversation a quoted message came from.

The whole tool rests on one claim: the corpus index baked into a question id
stops being true the moment the thread is re-extracted, so the text is the only
anchor. Every test here is about not guessing wrong — a thread on the wrong
evening is worse than no thread at all.
"""
import os

import pytest

from tools.rethread import Finder, probe, write_context

BLANK = "▁"


def corpus(*texts):
    return [{"i": i, "from": "p1" if i % 2 else "p2", "text": t,
             "ts": f"2024-01-{1 + i % 28:02d}T10:00:00+00:00"}
            for i, t in enumerate(texts)]


# ── what part of a bubble is really a message ────────────────────────────

def test_probe_reads_a_plain_bubble():
    assert probe("i am never eating there again", "bubble") \
        == "i am never eating there again"


def test_probe_takes_the_longest_run_of_a_redacted_message():
    """Only the prefix used to count, and "honestly the" identifies nothing."""
    t = f"honestly the {BLANK*5} was completely unbelievable but the {BLANK*5} was worse"
    assert probe(t, "redacted") == "was completely unbelievable but the"


def test_probe_strips_the_label_off_a_compare():
    assert probe('A: “u ever just not wanna sleep”\nB: “later”',
                 "compare") == "u ever just not wanna sleep"


def test_probe_takes_the_first_line_of_a_thread():
    assert probe("are you awake\nunfortunately\nsame", "thread") == "are you awake"


# ── finding it again ──────────────────────────────────────────────────────

def test_an_exact_message_is_found():
    f = Finder(corpus("morning", "are you awake", "unfortunately", "same"))
    i, conf, why = f.find("are you awake")
    assert i == 1 and conf == 1.0 and why == "exact"


def test_a_near_miss_is_still_found():
    """The quoted line differs from the corpus by an apostrophe or an emoji —
    enough to break an exact compare, not enough to be a different message."""
    f = Finder(corpus("nothing", "i dont like facetime at all", "bye"))
    i, conf, why = f.find("i don't like facetime at all \U0001f622")
    assert i == 1 and conf >= 0.9


def test_a_phrase_many_messages_share_is_refused():
    """Finish the sentence quotes a habit, not a message. There is no single
    conversation behind it and the tool must say so rather than pick one."""
    f = Finder(corpus("thats what im saying", "thats what im talking about",
                      "thats what im on about", "unrelated"))
    i, conf, why = f.find("thats what im")
    assert i is None
    assert "start with this" in why


def test_two_messages_equally_close_are_refused():
    f = Finder(corpus("the meal was awful honestly", "the meal was awful honestlyy"))
    i, _, why = f.find("the meal was awful honestlx")
    assert i is None and "equally close" in why


def test_something_that_is_not_in_the_thread_is_refused():
    f = Finder(corpus("morning", "afternoon", "evening"))
    assert f.find("a sentence that was never sent by anybody")[0] is None


def test_a_very_short_line_is_refused():
    f = Finder(corpus("ok", "sure", "yeah"))
    assert f.find("ok")[0] is None


# ── the thread it builds ──────────────────────────────────────────────────

def test_the_thread_is_the_messages_either_side_with_the_source_marked():
    f = Finder(corpus(*[str(n) for n in range(40)]))
    ctx = f.thread(20)
    assert len(ctx) == 21                       # ten either side
    assert [c["text"] for c in ctx] == [str(n) for n in range(10, 31)]
    assert [c["self"] for c in ctx].count(True) == 1
    assert ctx[10]["self"] is True
    assert all(c["who"] in ("p1", "p2") for c in ctx)


def test_a_thread_near_the_start_is_just_shorter():
    f = Finder(corpus(*[str(n) for n in range(40)]))
    ctx = f.thread(2)
    assert [c["text"] for c in ctx] == [str(n) for n in range(0, 13)]
    assert ctx[2]["self"] is True
    assert all(c["who"] in ("p1", "p2") for c in ctx)


def test_a_message_with_nothing_around_it_gets_no_thread():
    f = Finder(corpus("alone"))
    assert f.thread(0) == []


# ── writing it back ───────────────────────────────────────────────────────

def test_context_is_written_after_text_and_only_once(tmp_path):
    p = tmp_path / "q.toml"
    p.write_text('[[q]]\nid = "x1"\ntext = "hello there"\nstatus = "ready"\n',
                 encoding="utf-8")
    ctx = [{"who": "p1", "text": 'she said "hi"', "self": False},
           {"who": "p2", "text": "hello there", "self": True}]
    assert write_context(str(p), "x1", ctx) is True
    assert write_context(str(p), "x1", ctx) is False      # idempotent

    import tomllib
    q = tomllib.loads(p.read_text(encoding="utf-8"))["q"][0]
    assert q["text"] == "hello there"                     # untouched
    assert [c["self"] for c in q["context"]] == [False, True]
    assert q["context"][0]["text"] == 'she said "hi"'     # quotes escaped


def test_writing_to_an_unknown_id_changes_nothing(tmp_path):
    p = tmp_path / "q.toml"
    before = '[[q]]\nid = "x1"\ntext = "hello"\n'
    p.write_text(before, encoding="utf-8")
    assert write_context(str(p), "nope", [{"who": "p1", "text": "a", "self": True}]) is False
    assert p.read_text(encoding="utf-8") == before
