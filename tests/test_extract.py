"""Extraction, especially merging a thread split across two identifiers."""
import sqlite3

import pytest

from tools.extract import (apple_time_to_dt, count_per_identifier,
                           load_messages, month_range)

APPLE_EPOCH_NS = 1_000_000_000


def fixture_db():
    """A chat.db-shaped database with her thread split across a number and an
    email, including one message reachable from both chats."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT,
                           display_name TEXT);
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT,
                              attributedBody BLOB, is_from_me INT, date INT,
                              cache_has_attachments INT,
                              associated_message_type INT, item_type INT);
        CREATE TABLE chat_message_join (chat_id INT, message_id INT);
        INSERT INTO chat VALUES (1, '+15551234567', ''), (2, 'her@gmail.com', '');
    """)

    def msg(rid, text, mine, day, chats, assoc=0):
        ts = (day * 86400) * APPLE_EPOCH_NS
        c.execute("INSERT INTO message VALUES (?,?,?,?,?,0,?,0)",
                  (rid, text, None, mine, ts, assoc))
        for ch in chats:
            c.execute("INSERT INTO chat_message_join VALUES (?,?)", (ch, rid))

    msg(1, "first one from the phone number", 0, 100, [1])
    msg(2, "reply from me on the number", 1, 101, [1])
    msg(3, "later one from her gmail thread", 0, 300, [2])
    msg(4, "this one lives in both chats", 0, 400, [1, 2])   # the dedup case
    msg(5, 'Liked "this one lives in both chats"', 1, 401, [1])   # tapback
    msg(6, "reaction row", 1, 402, [1], assoc=2000)              # associated
    msg(7, "ok", 1, 403, [1])                                    # short: kept
    return c


def test_merging_two_identifiers_gets_everything():
    c = fixture_db()
    only_phone = load_messages(c, ["+15551234567"])
    both = load_messages(c, ["+15551234567", "her@gmail.com"])
    assert len(both) > len(only_phone)
    assert "later one from her gmail thread" in [m["text"] for m in both]


def test_a_message_in_both_chats_is_counted_once():
    c = fixture_db()
    texts = [m["text"] for m in load_messages(c, ["+15551234567", "her@gmail.com"])]
    assert texts.count("this one lives in both chats") == 1


def test_merged_messages_come_back_in_date_order():
    c = fixture_db()
    ms = load_messages(c, ["+15551234567", "her@gmail.com"])
    assert [m["ts"] for m in ms] == sorted(m["ts"] for m in ms)
    assert [m["i"] for m in ms] == list(range(len(ms)))


def test_both_identifiers_map_to_the_same_person():
    """is_from_me decides the side, so her email and her number are both p2."""
    c = fixture_db()
    ms = load_messages(c, ["+15551234567", "her@gmail.com"])
    hers = [m for m in ms if m["from"] == "p2"]
    assert "first one from the phone number" in [m["text"] for m in hers]
    assert "later one from her gmail thread" in [m["text"] for m in hers]


def test_tapbacks_and_reactions_are_dropped():
    c = fixture_db()
    texts = [m["text"] for m in load_messages(c, ["+15551234567"])]
    assert not any(t.startswith("Liked ") for t in texts)
    assert "reaction row" not in texts


def test_short_replies_are_kept():
    """One-word replies are the raw material for half the stats."""
    c = fixture_db()
    assert "ok" in [m["text"] for m in load_messages(c, ["+15551234567"])]


def test_per_identifier_counts_expose_a_typo():
    c = fixture_db()
    per = count_per_identifier(c, ["+15551234567", "her@gmial.com"])
    assert per["+15551234567"] > 0
    assert per["her@gmial.com"] == 0


def test_month_range_is_contiguous_across_a_gap():
    ms = [{"ts": "2021-03-04T10:00:00+00:00"}, {"ts": "2022-02-01T10:00:00+00:00"}]
    months = month_range(ms)
    assert months[0] == "2021-03" and months[-1] == "2022-02"
    assert len(months) == 12
