#!/usr/bin/env python3
"""
build_game.py — turn an iMessage thread into a two-player guessing game.

Usage:
    python3 build_game.py --list
    python3 build_game.py --chat "+15551234567" --p1 "You" --p2 "Her"

Produces a single self-contained chat_game.html you can open on any device.
Nothing leaves your machine.
"""

import argparse
import collections
import html
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

APPLE_EPOCH = 978307200  # 2001-01-01 in Unix seconds

# ---------------------------------------------------------------- db plumbing


def open_db(path):
    """Copy the DB (and its WAL) somewhere safe, then open read-only."""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        sys.exit(
            f"Can't find {path}\n"
            "If it exists but you get a permissions error, grant your terminal "
            "Full Disk Access in System Settings > Privacy & Security."
        )
    tmp = tempfile.mkdtemp(prefix="chatgame_")
    dest = os.path.join(tmp, "chat.db")
    for suffix in ("", "-wal", "-shm"):
        src = path + suffix
        if os.path.exists(src):
            try:
                shutil.copy2(src, dest + suffix)
            except PermissionError:
                sys.exit(
                    "Permission denied reading Messages.\n"
                    "Grant your terminal Full Disk Access in "
                    "System Settings > Privacy & Security, then reopen it."
                )
    conn = sqlite3.connect(dest)
    conn.row_factory = sqlite3.Row
    return conn


def apple_time_to_dt(value):
    """Messages stores nanoseconds since 2001 on modern macOS, seconds on old."""
    if value is None:
        return None
    seconds = value / 1_000_000_000 if value > 1e11 else value
    try:
        return datetime.fromtimestamp(seconds + APPLE_EPOCH, tz=timezone.utc).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def decode_attributed_body(blob):
    """
    Message text often lives only in attributedBody, a serialized
    NSAttributedString. Try the proper decoder, fall back to byte-walking.
    """
    if not blob:
        return None
    try:
        import typedstream  # pip install typedstream

        for item in typedstream.unarchive_from_data(blob).contents:
            for value in getattr(item, "values", []):
                if isinstance(getattr(value, "archived_value", None), str):
                    return value.archived_value
    except Exception:
        pass
    try:
        chunk = blob.split(b"NSString")[1][5:]
        if chunk[0] == 0x81:
            length = int.from_bytes(chunk[1:3], "little")
            chunk = chunk[3 : 3 + length]
        else:
            length = chunk[0]
            chunk = chunk[1 : 1 + length]
        text = chunk.decode("utf-8", errors="ignore").strip()
        return text or None
    except Exception:
        return None


def list_chats(conn):
    rows = conn.execute(
        """
        SELECT c.chat_identifier AS ident,
               COALESCE(NULLIF(c.display_name,''), c.chat_identifier) AS label,
               COUNT(cmj.message_id) AS n,
               MIN(m.date) AS first, MAX(m.date) AS last
        FROM chat c
        JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
        JOIN message m ON m.ROWID = cmj.message_id
        GROUP BY c.chat_identifier
        ORDER BY n DESC
        LIMIT 40
        """
    ).fetchall()
    print(f"\n{'messages':>9}  {'span':<25}  chat")
    print("-" * 72)
    for r in rows:
        first, last = apple_time_to_dt(r["first"]), apple_time_to_dt(r["last"])
        span = (
            f"{first:%b %Y} – {last:%b %Y}" if first and last else "?"
        )
        print(f"{r['n']:>9}  {span:<25}  {r['label']}")
    print("\nRerun with --chat \"<identifier>\" to build the game.\n")


def load_messages(conn, identifiers):
    placeholders = ",".join("?" for _ in identifiers)
    rows = conn.execute(
        f"""
        SELECT DISTINCT m.ROWID AS rid, m.text, m.attributedBody,
               m.is_from_me, m.date
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        JOIN chat c ON c.ROWID = cmj.chat_id
        WHERE c.chat_identifier IN ({placeholders})
          AND COALESCE(m.associated_message_type, 0) = 0
          AND COALESCE(m.item_type, 0) = 0
        ORDER BY m.date
        """,
        identifiers,
    ).fetchall()

    out = []
    for r in rows:
        text = (r["text"] or "").strip() or decode_attributed_body(r["attributedBody"])
        when = apple_time_to_dt(r["date"])
        if not text or not when:
            continue
        text = text.replace("\ufffc", "").strip()  # attachment placeholder char
        if not text:
            continue
        out.append({"text": text, "mine": bool(r["is_from_me"]), "dt": when})
    return out


# ------------------------------------------------------------ question making

STOPWORDS = set(
    """a about after all also am an and any are as at back be because been before
    being but by can cant come could did didnt do dont down even for from get go
    going good got had has have he her here hers him his how i if im in into is
    isnt it its just know like ll me might more most much my no not now of off on
    one only or other our out over re she should so some such than that thats the
    their them then there these they this those to too up us ve very was way we
    well were what when where which while who why will with would yeah yes yet you
    your youre u ur ok okay oh lol haha ya na""".split()
)

EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff]"
    "[\U0001f3fb-\U0001f3ff]?\ufe0f?"
)
WORD_RE = re.compile(r"[a-z']{2,}")
URL_RE = re.compile(r"https?://|www\.")


def words_of(text):
    return WORD_RE.findall(text.lower())


def clean_pool(messages, lo=6, hi=28):
    """Messages long enough to be interesting, short enough to read on a phone."""
    pool = []
    for m in messages:
        if URL_RE.search(m["text"]) or "\n" in m["text"]:
            continue
        n = len(m["text"].split())
        if lo <= n <= hi and len(m["text"]) < 220:
            pool.append(m)
    return pool


def label(m, p1, p2):
    return p1 if m["mine"] else p2


def q_who_said_it(pool, p1, p2, rng, count):
    picks = rng.sample(pool, min(count, len(pool)))
    return [
        {
            "type": "binary",
            "kind": "Who said it",
            "prompt": "Who sent this?",
            "text": m["text"],
            "options": [p1, p2],
            "answer": 0 if m["mine"] else 1,
            "reveal": f"{label(m, p1, p2)} · {m['dt']:%B %-d, %Y}",
        }
        for m in picks
    ]


def q_fill_blank(pool, freq, p1, p2, rng, count):
    ranked = [w for w, c in freq.most_common() if w not in STOPWORDS and len(w) >= 4]
    band = ranked[10:400] or ranked
    out = []
    tries = 0
    seen = set()
    while len(out) < count and tries < count * 40:
        tries += 1
        m = rng.choice(pool)
        candidates = [
            w
            for w in words_of(m["text"])
            if len(w) >= 4 and w not in STOPWORDS and m["text"].lower().count(w) == 1
        ]
        key = " ".join(words_of(m["text"]))
        if not candidates or key in seen:
            continue
        seen.add(key)
        target = rng.choice(candidates)
        distractors = rng.sample([w for w in band if w != target], 3)
        options = distractors + [target]
        rng.shuffle(options)
        masked = re.sub(
            r"\b" + re.escape(target) + r"\b",
            "▁▁▁▁▁",
            m["text"],
            count=1,
            flags=re.IGNORECASE,
        )
        if "▁" not in masked:
            continue
        out.append(
            {
                "type": "choice",
                "kind": "Fill in the blank",
                "prompt": f"{label(m, p1, p2)} sent this. What's the missing word?",
                "text": masked,
                "options": options,
                "answer": options.index(target),
                "reveal": f"“{m['text']}” · {m['dt']:%B %Y}",
            }
        )
    return out


def q_numbers(messages, freq, p1, p2, rng):
    mine = sum(1 for m in messages if m["mine"])
    theirs = len(messages) - mine
    by_day = collections.Counter(m["dt"].date() for m in messages)
    busiest_day, busiest_n = by_day.most_common(1)[0]
    late = sum(1 for m in messages if m["dt"].hour in (0, 1, 2, 3, 4))
    days = len(by_day)

    def phrase_count(needle):
        return sum(1 for m in messages if needle in m["text"].lower())

    out = [
        {
            "type": "number",
            "kind": "Guess the number",
            "prompt": "How many messages have we sent each other, total?",
            "answer": len(messages),
            "reveal": f"{len(messages):,} messages across {days:,} days — "
            f"{mine:,} from {p1}, {theirs:,} from {p2}.",
        },
        {
            "type": "number",
            "kind": "Guess the number",
            "prompt": "What's the most messages we've ever sent in a single day?",
            "answer": busiest_n,
            "reveal": f"{busiest_n:,} on {busiest_day:%B %-d, %Y}.",
        },
        {
            "type": "number",
            "kind": "Guess the number",
            "prompt": "How many messages have we sent between midnight and 5am?",
            "answer": late,
            "reveal": f"{late:,}. Nothing good happens after 2am.",
        },
    ]
    for needle, blurb in [
        ("i love you", "times we've typed “I love you”"),
        ("miss you", "times one of us said “miss you”"),
        ("sorry", "apologies, give or take"),
    ]:
        n = phrase_count(needle)
        if n >= 5:
            out.append(
                {
                    "type": "number",
                    "kind": "Guess the number",
                    "prompt": "How many times have we said "
                    f"“{needle[0].upper() + needle[1:]}”?",
                    "answer": n,
                    "reveal": f"{n:,} {blurb}.",
                }
            )
    rng.shuffle(out)
    return out


def q_first_time(messages, p1, p2, months, count):
    phrases = [
        "i love you",
        "miss you",
        "good morning",
        "goodnight",
        "marry",
        "always",
        "promise",
        "obsessed",
        "forever",
    ]
    out = []
    for phrase in phrases:
        hit = next((m for m in messages if phrase in m["text"].lower()), None)
        if not hit:
            continue
        key = f"{hit['dt']:%Y-%m}"
        if key not in months:
            continue
        out.append(
            {
                "type": "month",
                "kind": "First time we said it",
                "prompt": "When did one of us first say "
                f"“{phrase[0].upper() + phrase[1:]}”?",
                "text": hit["text"],
                "answer": months.index(key),
                "reveal": f"{label(hit, p1, p2)}, {hit['dt']:%B %-d, %Y}",
            }
        )
        if len(out) >= count:
            break
    return out


def q_guess_date(pool, p1, p2, months, rng, count):
    picks = rng.sample(pool, min(count * 3, len(pool)))
    out = []
    for m in picks:
        key = f"{m['dt']:%Y-%m}"
        if key not in months:
            continue
        out.append(
            {
                "type": "month",
                "kind": "Guess the date",
                "prompt": f"{label(m, p1, p2)} sent this. When?",
                "text": m["text"],
                "answer": months.index(key),
                "reveal": f"{m['dt']:%B %-d, %Y}",
            }
        )
        if len(out) >= count:
            break
    return out


def q_top_emoji(messages, rng):
    counts = collections.Counter()
    for m in messages:
        counts.update(EMOJI_RE.findall(m["text"]))
    top = [e for e, _ in counts.most_common(6)]
    if len(top) < 4:
        return []
    winner = top[0]
    options = top[:4]
    rng.shuffle(options)
    return [
        {
            "type": "choice",
            "kind": "Top of the charts",
            "prompt": "Which emoji have we used the most?",
            "options": options,
            "answer": options.index(winner),
            "reveal": f"{winner} — {counts[winner]:,} times. "
            f"Runner-up: {top[1]} at {counts[top[1]]:,}.",
        }
    ]


def build_questions(messages, p1, p2, rounds, seed):
    rng = random.Random(seed)
    pool = clean_pool(messages)
    if len(pool) < 20:
        sys.exit("Not enough usable messages in that thread to build a game.")

    freq = collections.Counter()
    for m in messages:
        freq.update(w for w in words_of(m["text"]))

    months = sorted({f"{m['dt']:%Y-%m}" for m in messages})

    per = max(3, (rounds * 5) // 6)   # deep bank -> different game every replay
    bank = (
        q_who_said_it(pool, p1, p2, rng, per + 1)
        + q_fill_blank(pool, freq, p1, p2, rng, per + 1)
        + q_numbers(messages, freq, p1, p2, rng)[: per + 1]
        + q_first_time(messages, p1, p2, months, per)
        + q_guess_date(pool, p1, p2, months, rng, per)
        + q_top_emoji(messages, rng)
    )
    rng.shuffle(bank)

    # Interleave so the same round type never lands three times in a row.
    return bank, months


# ------------------------------------------------------------------- assembly


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="~/Library/Messages/chat.db")
    ap.add_argument("--list", action="store_true", help="show your chats and exit")
    ap.add_argument("--chat", help="chat identifier, comma-separated if she has several")
    ap.add_argument("--p1", default="Me", help="your name")
    ap.add_argument("--p2", default="You", help="her name")
    ap.add_argument("--rounds", type=int, default=14)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="game_data.json")
    args = ap.parse_args()

    conn = open_db(args.db)

    if args.list or not args.chat:
        list_chats(conn)
        return

    identifiers = [s.strip() for s in args.chat.split(",") if s.strip()]
    messages = load_messages(conn, identifiers)
    if not messages:
        sys.exit("No messages found for that identifier. Try --list to see options.")

    print(f"Loaded {len(messages):,} messages.")
    questions, months = build_questions(
        messages, args.p1, args.p2, args.rounds, args.seed
    )
    rounds = min(args.rounds, len(questions))
    print(f"Built a bank of {len(questions)} questions; {rounds} rounds per game.")

    data = {
        "meta": {
            "p1": args.p1,
            "p2": args.p2,
            "months": months,
            "rounds": rounds,
            "total": len(messages),
            "first": f"{messages[0]['dt']:%B %Y}",
            "last": f"{messages[-1]['dt']:%B %Y}",
        },
        "questions": questions,
    }

    out_path = os.path.abspath(os.path.expanduser(args.out))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print(f"\nDone → {out_path}\n  python3 server.py --data {args.out}\n")


if __name__ == "__main__":
    main()
