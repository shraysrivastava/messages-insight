"""Extraction, especially merging a thread split across two identifiers."""
import sqlite3

import pytest

from tools.extract import (apple_time_to_dt, count_per_identifier,
                           load_attachments, load_messages, month_range)


def msgs(conn, idents):
    """load_messages returns (messages, photos); most tests want the first."""
    return load_messages(conn, idents, load_attachments(conn, idents))[0]

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
        CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, filename TEXT,
                                 mime_type TEXT, uti TEXT, transfer_name TEXT);
        CREATE TABLE message_attachment_join (message_id INT, attachment_id INT);
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

    def att(aid, rid, name, mime, uti):
        c.execute("INSERT INTO attachment VALUES (?,?,?,?,?)",
                  (aid, f"~/Library/Messages/Attachments/ab/{name}", mime, uti, name))
        c.execute("INSERT INTO message_attachment_join VALUES (?,?)", (rid, aid))

    msg(8, "", 0, 500, [1])                      # photo, no caption
    att(1, 8, "IMG_0001.HEIC", "image/heic", "public.heic")
    msg(9, "look at his face", 0, 501, [1])      # photo with a caption
    att(2, 9, "IMG_0002.JPG", "image/jpeg", "public.jpeg")
    msg(10, "", 1, 502, [1])                     # a video: still dropped
    att(3, 10, "IMG_0003.MOV", "video/quicktime", "com.apple.quicktime-movie")
    msg(11, "", 0, 503, [1])                     # three at once, one kept
    att(4, 11, "a.png", "image/png", "public.png")
    att(5, 11, "b.png", "image/png", "public.png")
    att(6, 11, "c.png", "image/png", "public.png")
    msg(12, "", 0, 504, [1])                     # NULL mime, image UTI
    att(7, 12, "old.gif", None, "com.compuserve.gif")
    return c


def test_merging_two_identifiers_gets_everything():
    c = fixture_db()
    only_phone = msgs(c, ["+15551234567"])
    both = msgs(c, ["+15551234567", "her@gmail.com"])
    assert len(both) > len(only_phone)
    assert "later one from her gmail thread" in [m["text"] for m in both]


def test_a_message_in_both_chats_is_counted_once():
    c = fixture_db()
    texts = [m["text"] for m in msgs(c, ["+15551234567", "her@gmail.com"])]
    assert texts.count("this one lives in both chats") == 1


def test_merged_messages_come_back_in_date_order():
    c = fixture_db()
    ms = msgs(c, ["+15551234567", "her@gmail.com"])
    assert [m["ts"] for m in ms] == sorted(m["ts"] for m in ms)
    assert [m["i"] for m in ms] == list(range(len(ms)))


def test_both_identifiers_map_to_the_same_person():
    """is_from_me decides the side, so her email and her number are both p2."""
    c = fixture_db()
    ms = msgs(c, ["+15551234567", "her@gmail.com"])
    hers = [m for m in ms if m["from"] == "p2"]
    assert "first one from the phone number" in [m["text"] for m in hers]
    assert "later one from her gmail thread" in [m["text"] for m in hers]


def test_tapbacks_and_reactions_are_dropped():
    c = fixture_db()
    texts = [m["text"] for m in msgs(c, ["+15551234567"])]
    assert not any(t.startswith("Liked ") for t in texts)
    assert "reaction row" not in texts


def test_short_replies_are_kept():
    """One-word replies are the raw material for half the stats."""
    c = fixture_db()
    assert "ok" in [m["text"] for m in msgs(c, ["+15551234567"])]


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


# ── photographs ───────────────────────────────────────────────────────────

def test_a_message_that_is_only_a_photo_is_kept():
    """It used to be dropped as "attachment only / undecodable", which made
    every picture in five years invisible to the game."""
    c = fixture_db()
    ms, photos = load_messages(c, ["+15551234567"],
                               load_attachments(c, ["+15551234567"]))
    captionless = [m for m in ms if m["text"] == "" and "photo" in m]
    assert captionless, "photo-only messages are still being dropped"
    assert len(photos) == 4              # heic, jpeg, the burst, the gif


def test_a_photo_points_back_at_its_message():
    c = fixture_db()
    ms, photos = load_messages(c, ["+15551234567"],
                               load_attachments(c, ["+15551234567"]))
    for p in photos:
        m = ms[p["i"]]
        assert m["photo"] == p["k"]
        assert m["ts"] == p["ts"] and m["from"] == p["from"]


def test_a_caption_is_kept_with_its_photo():
    c = fixture_db()
    ms, _ = load_messages(c, ["+15551234567"],
                          load_attachments(c, ["+15551234567"]))
    capt = [m for m in ms if m["text"] == "look at his face"]
    assert capt and "photo" in capt[0]


def test_only_pictures_come_through():
    """A video is an attachment too, and a round is a picture on a big screen."""
    c = fixture_db()
    atts = load_attachments(c, ["+15551234567"])
    names = [a["name"] for group in atts.values() for a in group]
    assert "IMG_0003.MOV" not in names
    assert "IMG_0002.JPG" in names


def test_a_null_mime_type_still_reads_as_an_image():
    """mime_type is NULL on a lot of old rows; the UTI is the fallback."""
    c = fixture_db()
    names = [a["name"] for g in load_attachments(c, ["+15551234567"]).values()
             for a in g]
    assert "old.gif" in names


def test_a_burst_of_photos_becomes_one_round():
    c = fixture_db()
    _, photos = load_messages(c, ["+15551234567"],
                              load_attachments(c, ["+15551234567"]))
    burst = [p for p in photos if p["name"] == "a.png"]
    assert len(burst) == 1
    assert burst[0]["of"] == 3
    assert "b.png" not in [p["name"] for p in photos]


def test_the_source_path_is_expanded():
    """chat.db stores a literal ~; nothing downstream expands it."""
    c = fixture_db()
    _, photos = load_messages(c, ["+15551234567"],
                              load_attachments(c, ["+15551234567"]))
    assert photos and not photos[0]["src"].startswith("~")


def test_photos_survive_into_the_corpus():
    from tools.extract import build_corpus
    c = fixture_db()
    ms, photos = load_messages(c, ["+15551234567"],
                               load_attachments(c, ["+15551234567"]))
    corpus = build_corpus(ms, "Shray", "Nilu", photos)
    assert len(corpus["photos"]) == len(photos)
    assert corpus["messages"][corpus["photos"][0]["i"]]["photo"] == 0


def test_a_corpus_with_no_photos_carries_no_photo_key():
    """Every corpus extracted before today has none, and they must still load."""
    from tools.extract import build_corpus
    ms = [{"i": 0, "ts": "2024-01-01T10:00:00+00:00", "from": "p1", "text": "hi"},
          {"i": 1, "ts": "2024-02-01T10:00:00+00:00", "from": "p2", "text": "hello"}]
    assert "photos" not in build_corpus(ms, "A", "B", [])
