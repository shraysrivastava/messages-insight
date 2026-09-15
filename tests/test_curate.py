"""curate.py — the judgments have to survive the file they're written to."""
import json
import tomllib

import pytest

from tools.curate import (
    Session, Slot, append_block, bake, block_text, derive, esc, leftover_vars,
    load_state, mint, remove_block, slot_pool, toml_str, validate,
)
from tools.resolvers import Corpus

MONTHS = [f"2022-{m:02d}" for m in range(1, 13)] + \
         [f"2023-{m:02d}" for m in range(1, 13)]
NAMES = ("Shray", "Nilu")


def corpus():
    """Two years of alternating small talk, one message a week."""
    msgs = []
    for i in range(96):
        y, mo = (2022, i // 4 + 1) if i < 48 else (2023, (i - 48) // 4 + 1)
        day = (i % 4) * 7 + 1
        hour = 3 if i % 17 == 0 else 14           # a few 3am messages
        msgs.append({
            "i": i, "from": "p1" if i % 2 else "p2",
            "ts": f"{y}-{mo:02d}-{day:02d}T{hour:02d}:05:00-06:00",
            "text": f"message number {i} about the dog and the weather today",
        })
    return Corpus({"meta": {"p1": "Shray", "p2": "Nilu", "months": MONTHS,
                            "total": len(msgs)}, "messages": msgs})


def cand(kind="who_said_it", i=40, **kw):
    c = corpus()
    m = c.messages[i]
    base = {"id": f"{kind}-{i}", "kind": kind, "i": i, "from": m["from"],
            "text": m["text"], "ts": m["ts"], "date": c.pretty(m),
            "month": c.month_of(m), "score": 3.0,
            "context": [{"i": m["i"], "from": m["from"], "text": m["text"],
                         "ts": m["ts"], "self": True}],
            "answer": 0 if m["from"] == "p1" else 1}
    base.update(kw)
    return base


def slot(id="who-said-1", mine="who_said_it", **block):
    b = {"id": id, "type": "binary", "kind": "Who said it", "area": "language",
         "format": "bubble", "prompt": "Who sent this?",
         "options": ["{p1}", "{p2}"], "reveal": "{winner} · {date}"}
    b.update(block)
    return Slot(id=id, block=b, src={"mine": mine}, file="questions/auto/x.toml")


# ── writing TOML ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    'she said "no" and meant it',
    "a\nb\tc",
    "emoji 🫠 and an accent é",
    "a { brace } walks in",
    "back\\slash",
])
def test_a_message_survives_the_trip_through_toml(text, tmp_path):
    path = tmp_path / "mine.toml"
    q = {"id": "x", "type": "binary", "kind": "k", "prompt": "p",
         "text": text, "options": ["A", "B"], "answer": 0, "reveal": "r",
         "status": "ready"}
    append_block(str(path), block_text(q))
    assert tomllib.loads(path.read_text())["q"][0]["text"] == text


def test_control_characters_are_escaped_not_emitted_raw():
    assert toml_str("a\x07b") == '"a\\u0007b"'


def test_undo_leaves_the_file_byte_identical(tmp_path):
    path = tmp_path / "mine.toml"
    original = '# his own work\n\n[[q]]\nid = "his"\nprompt = "?"\n'
    path.write_text(original)
    append_block(str(path), block_text({"id": "mine-1", "prompt": "p"}))
    assert len(tomllib.loads(path.read_text())["q"]) == 2

    assert remove_block(str(path), "mine-1")
    assert path.read_text() == original


def test_undo_removes_only_its_own_block(tmp_path):
    path = tmp_path / "mine.toml"
    path.write_text("")
    append_block(str(path), block_text({"id": "a", "prompt": "p"}))
    append_block(str(path), block_text({"id": "b", "prompt": "p"}))
    append_block(str(path), block_text({"id": "c", "prompt": "p"}))

    remove_block(str(path), "b")
    assert [q["id"] for q in tomllib.loads(path.read_text())["q"]] == ["a", "c"]


def test_undoing_something_that_was_hand_edited_away_reports_rather_than_guesses(tmp_path):
    path = tmp_path / "mine.toml"
    path.write_text('[[q]]\nid = "x"\n')
    assert remove_block(str(path), "x") is False        # no marker, no cut


# ── baking ────────────────────────────────────────────────────────────────

def test_message_braces_are_escaped_so_the_compiler_leaves_them_alone():
    assert esc("a {b} c").format() == "a {b} c"


def test_baking_fills_the_message_vars_and_leaves_the_compiler_its_own():
    out = bake("{winner} told {p2} on {date}", {"winner": "Nilu", "date": "May 1"})
    assert out == "Nilu told {p2} on May 1"


def test_a_name_with_a_brace_in_it_cannot_become_a_template_var():
    assert bake("{winner}", {"winner": "{p1}"}) == "{{p1}}"


def test_leftover_vars_flags_what_nothing_will_fill():
    q = {"prompt": "hi {p1}", "reveal": "{winner} on {date}", "text": None}
    assert leftover_vars(q) == ["winner", "date"]


# ── minting ───────────────────────────────────────────────────────────────

def test_who_said_it_mints_a_shippable_question():
    c = corpus()
    q, _ = mint(slot(), cand(), c, "who-said-1", "who-said-1")
    assert validate(q, NAMES) is None
    assert q["answer"] in (0, 1)
    assert q["options"] == ["{p1}", "{p2}"]          # compile still fills these
    assert "{winner}" not in q["reveal"]             # but not this one


def test_the_reveal_names_the_person_who_actually_sent_it():
    c = corpus()
    m = c.messages[40]
    q, _ = mint(slot(), cand(i=40), c, "q", None)
    assert c.name(m["from"]) in q["reveal"]


def test_a_slot_whose_reveal_still_says_todo_refuses_to_ship():
    s = slot(reveal="TODO — write this one properly.")
    q, _ = mint(s, cand(), corpus(), "q", None)
    assert "TODO" in (validate(q, NAMES) or "")


def test_fill_in_the_blank_carries_its_options_and_answer():
    s = slot("blank-1", "fill_blank", type="choice", format="blank",
             prompt="What's missing?", reveal="{month}.", options=None)
    s.block.pop("options")
    c = cand("fill_blank", blanked="message ▁▁▁▁▁ about the dog",
             options=["number", "words", "things", "sounds"], answer=1)
    q, _ = mint(s, c, corpus(), "blank-1", None)
    assert validate(q, NAMES) is None
    assert q["options"] == ["number", "words", "things", "sounds"]
    assert q["answer"] == 1


def test_a_month_question_answers_with_an_index_into_the_slider():
    s = slot("date-this-1", "datable", type="month", prompt="When?",
             reveal="{month}.", options=None)
    s.block.pop("options")
    q, _ = mint(s, cand("datable"), corpus(), "date-this-1", None)
    assert validate(q, NAMES) is None
    assert q["answer"] == cand("datable")["month"]


def test_compare_dates_reveals_the_earlier_ones_date_not_the_bubbles():
    s = slot("which-came-first", "compare_dates", format="compare",
             prompt="Which came first?", options=["A", "B"],
             reveal="{answer}, {date} — {other_date} came later.")
    c = cand("compare_dates", pair={"A": "one", "B": "two"}, answer=1,
             other_date="March 3, 2022")
    q, _ = mint(s, c, corpus(), "q", None)
    assert q["reveal"].startswith("B, March 3, 2022")


def test_a_slot_naming_a_clock_time_gets_corrected_to_this_message():
    s = slot("who-said-3am", prompt="Sent at 3:41am. Who was awake?")
    q, notes = mint(s, cand(i=34), corpus(), "q", None)      # i%17==0 -> 3am
    assert "3:41am" not in q["prompt"]
    assert "3:05am" in q["prompt"]
    assert notes


def test_an_unknown_candidate_kind_is_an_error_not_a_broken_question():
    with pytest.raises(ValueError):
        mint(slot(mine="jokes"), cand("jokes"), corpus(), "q", None)


# ── the two derived kinds ─────────────────────────────────────────────────

def test_redact_blanks_three_words_and_keeps_the_asked_one():
    src = [cand("fill_blank", i=i, blanked=f"one two three four five six {i}",
                options=["a", "b", "c", "d"], answer=0) for i in range(4)]
    out = [c for c in derive(src) if c["kind"] == "redact"]
    assert out and all(c["blanked"].count("▁▁▁▁▁") == 2 for c in out)
    assert out[0]["options"] == ["a", "b", "c", "d"]


def test_reply_roulette_shows_the_reply_and_hides_the_prompt():
    src = [cand("reply", i=i, text=f"prompt {i}", reply=f"reply {i}",
                options=[f"reply {i}", "x", "y", "z"], answer=0)
           for i in range(6)]
    out = [c for c in derive(src) if c["kind"] == "reply_inverted"]
    assert out
    c = out[0]
    assert c["text"].startswith("reply")                 # the reply is shown
    assert c["options"][c["answer"]] == "prompt 0"       # the prompt is guessed


# ── slot filters ──────────────────────────────────────────────────────────

def test_a_by_filter_only_offers_that_persons_messages():
    c = corpus()
    cands = [cand(i=i) for i in range(40, 60)]
    s = slot(); s.src["by"] = "p1"
    pool, _ = slot_pool(s, cands, c, {})
    assert pool and all(x["from"] == "p1" for x in pool)


def test_an_hours_filter_only_offers_messages_from_that_window():
    c = corpus()
    cands = [cand(i=i) for i in range(96)]
    s = slot(); s.src["hours"] = [2, 5]
    pool, _ = slot_pool(s, cands, c, {})
    assert pool and all(x["i"] % 17 == 0 for x in pool)


def test_a_cutoff_the_thread_starts_after_relaxes_out_loud():
    c = corpus()
    cands = [cand(i=i) for i in range(96)]
    s = slot(); s.src["before"] = "2019-01"
    pool, note = slot_pool(s, cands, c, {})
    assert pool                                   # not left empty and silent
    assert "2019-01" in note and "instead" in note


# ── the session ───────────────────────────────────────────────────────────

def session(tmp_path, cands, slots):
    return Session(corpus=corpus(), cands=cands, slots=slots, lexicons={},
                   mine_path=str(tmp_path / "mine.toml"),
                   state_path=str(tmp_path / ".curate.json"),
                   state=load_state(str(tmp_path / ".curate.json")))


def test_rejecting_moves_on_and_never_offers_it_again(tmp_path):
    s = session(tmp_path, [cand(i=i) for i in (40, 42)], [slot()])
    first = s.card()["cand"]["id"]
    s.reject(first)
    assert s.card()["cand"]["id"] != first


def test_a_closed_tab_loses_nothing(tmp_path):
    cands, slots = [cand(i=i) for i in (40, 42)], [slot()]
    s = session(tmp_path, cands, slots)
    s.reject(s.card()["cand"]["id"])
    again = session(tmp_path, cands, slots)          # reopened
    assert again.progress()["reviewed"] == 1
    assert again.card()["cand"]["id"] == "who_said_it-42"


def test_one_message_never_becomes_two_questions(tmp_path):
    s = session(tmp_path, [cand(i=40), cand("datable", i=40)],
                [slot(), slot("date-this-1", "datable", type="month",
                              prompt="When?", reveal="{month}.")])
    card = s.card()
    assert s.accept(card["cand"]["id"], card["block"], "who-said-1") is None
    assert s.card() is None                # the datable one is the same message


def test_accept_writes_a_block_the_compiler_can_read(tmp_path):
    s = session(tmp_path, [cand()], [slot()])
    card = s.card()
    assert s.accept(card["cand"]["id"], card["block"], "who-said-1") is None
    written = tomllib.loads((tmp_path / "mine.toml").read_text())["q"][0]
    assert written["id"] == "who-said-1" and written["status"] == "ready"
    assert written["topic"] == "who-said-1"          # replaces the slot


def test_a_second_question_for_a_filled_slot_gets_its_own_id_and_topic(tmp_path):
    s = session(tmp_path, [cand(i=40), cand(i=42)], [slot()])
    c1 = s.card()
    s.accept(c1["cand"]["id"], c1["block"], "who-said-1")
    q, _ = mint(slot(), cand(i=42), corpus(), s.new_id("who-said-1"), None)
    assert q["id"] == "who-said-1-2"
    assert "topic" not in q                          # so it can't collide


def test_accept_refuses_a_block_the_schema_would_reject(tmp_path):
    s = session(tmp_path, [cand()], [slot()])
    card = s.card()
    bad = {**card["block"], "answer": 9}
    assert s.accept(card["cand"]["id"], bad, "who-said-1") is not None
    assert not (tmp_path / "mine.toml").exists()     # and writes nothing


def test_undo_puts_the_candidate_back_in_the_queue(tmp_path):
    s = session(tmp_path, [cand()], [slot()])
    card = s.card()
    s.accept(card["cand"]["id"], card["block"], "who-said-1")
    assert s.undo() is None
    assert s.card()["cand"]["id"] == card["cand"]["id"]
    assert json.loads((tmp_path / ".curate.json").read_text())["minted"] == []


def test_skipping_a_slot_moves_to_the_next_one(tmp_path):
    s = session(tmp_path, [cand(), cand("datable", i=42)],
                [slot(), slot("date-this-1", "datable", type="month",
                              prompt="When?", reveal="{month}.")])
    s.skip_slot("who-said-1")
    assert s.card()["slot"]["id"] == "date-this-1"


def test_search_is_tolerant_of_how_it_was_typed(tmp_path):
    s = session(tmp_path, [], [])
    assert s.search("weather") and s.search("WEATHERRR")
    assert s.search("nothing in this thread at all") == []


def test_any_message_can_become_a_question_not_just_a_mined_one(tmp_path):
    s = session(tmp_path, [], [slot()])
    out = s.from_message(41, "who_said_it")
    assert out["error"] is None
    assert out["block"]["id"] == "who-said-m41"
    assert s.accept(out["cand"]["id"], out["block"], None) is None


def test_a_month_answer_the_compiler_will_drop_is_flagged_before_you_judge_it(tmp_path):
    s = session(tmp_path, [cand("datable", i=1)],
                [slot("date-this-1", "datable", type="month", prompt="When?",
                      reveal="{month}.")])
    s.guards = {"month_edge_pct": 0.10}
    card = s.card()
    assert card["answer_label"] == "January 2022"     # not "month 0"
    assert any("guessable from the slider" in n for n in card["notes"])


def test_a_month_in_the_middle_of_the_thread_passes_without_a_warning(tmp_path):
    s = session(tmp_path, [cand("datable", i=48)],
                [slot("date-this-1", "datable", type="month", prompt="When?",
                      reveal="{month}.")])
    s.guards = {"month_edge_pct": 0.10}
    assert s.card()["notes"] == []


# ── the context thread (S3.2) ─────────────────────────────────────────────

class _Corpus:
    def __init__(self, texts):
        self.messages = [{"i": i, "from": "p1" if i % 2 else "p2", "text": t}
                         for i, t in enumerate(texts)]


def test_context_is_the_messages_either_side_with_the_source_marked():
    from tools.curate import context_for
    c = _Corpus(["a", "b", "c", "d", "e", "f", "g"])
    ctx = context_for(c, 3)
    assert [m["text"] for m in ctx] == ["b", "c", "d", "e", "f"]
    assert [m["self"] for m in ctx] == [False, False, True, False, False]


def test_context_at_the_very_start_of_the_thread_is_just_shorter():
    from tools.curate import context_for
    ctx = context_for(_Corpus(["a", "b", "c", "d"]), 0)
    assert [m["text"] for m in ctx] == ["a", "b", "c"]


def test_a_message_with_no_neighbours_is_not_a_thread():
    """One bubble is the bubble already on screen, not context for it."""
    from tools.curate import context_for
    assert context_for(_Corpus(["only"]), 0) is None
    assert context_for(_Corpus(["a"]), None) is None


def test_context_survives_a_toml_round_trip():
    """Real messages contain quotes, newlines and braces. All three have to
    come back out the way they went in."""
    import tomllib
    from tools.curate import block_text
    q = {"id": "x", "type": "binary", "kind": "k", "prompt": "p?",
         "reveal": "r.", "answer": 0, "options": ["A", "B"],
         "context": [{"who": "p2", "text": 'he said "no" {seriously}',
                      "self": False},
                     {"who": "p1", "text": "line\nbreak", "self": True}]}
    parsed = tomllib.loads(block_text(q))["q"][0]
    assert parsed["context"][0]["text"] == 'he said "no" {seriously}'
    assert parsed["context"][1]["text"] == "line\nbreak"
    assert parsed["context"][1]["self"] is True
