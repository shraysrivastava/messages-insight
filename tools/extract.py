#!/usr/bin/env python3
"""
extract.py — chat.db -> corpus.json. Runs on your Mac, never anywhere else.

    python3 tools/extract.py --list
    python3 tools/extract.py --chat "+15551234567" --p1 Shray --p2 Nilu

Your terminal needs Full Disk Access (System Settings > Privacy & Security) to
read Messages. If her thread is split across an iMessage address and a phone
number, pass both, comma separated.

Output is a flat, ordered corpus and nothing else — no question generation. The
`i` index and the ordering are load-bearing: curation and reveals both need to
look up message i±5 for context.

    {"meta": {...}, "messages": [{"i":0,"ts":"...","from":"p1","text":"..."}]}

corpus.json is gitignored and stays on this machine.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone

APPLE_EPOCH = 978307200  # 2001-01-01 in unix seconds
OBJ_REPLACEMENT = "￼"  # attachment placeholder
URL_RE = re.compile(r"https?://|www\.")
TAPBACK_RE = re.compile(
    r'^(Liked|Loved|Disliked|Laughed at|Emphasized|Questioned|Removed a[a-z ]*from)\s+[“"]',
    re.I,
)


# ── db plumbing (lifted from the POC's build_game.py — it works) ───────────

def open_db(path: str):
    """Copy the DB and its WAL somewhere safe, then open read-only.

    The POC leaked this temp directory; here the caller gets a context manager
    so the copy of your entire message history doesn't outlive the process.
    """
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        sys.exit(
            f"Can't find {path}\n"
            "If it exists but you get a permissions error, grant your terminal "
            "Full Disk Access in System Settings > Privacy & Security."
        )
    tmp = tempfile.TemporaryDirectory(prefix="readreceipts_")
    dest = os.path.join(tmp.name, "chat.db")
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
    conn = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn, tmp


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
    """Message text often lives only in attributedBody, a serialised
    NSAttributedString. Try the real decoder, fall back to byte-walking."""
    if not blob:
        return None
    try:
        import typedstream

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
            chunk = chunk[3:3 + length]
        else:
            length = chunk[0]
            chunk = chunk[1:1 + length]
        return chunk.decode("utf-8", errors="ignore").strip() or None
    except Exception:
        return None


# ── listing ───────────────────────────────────────────────────────────────

def list_chats(conn) -> None:
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
        ORDER BY n DESC LIMIT 40
        """
    ).fetchall()
    print(f"\n{'messages':>9}  {'span':<25}  chat")
    print("-" * 72)
    for r in rows:
        first, last = apple_time_to_dt(r["first"]), apple_time_to_dt(r["last"])
        span = f"{first:%b %Y} - {last:%b %Y}" if first and last else "?"
        print(f"{r['n']:>9}  {span:<25}  {r['label']}")
    print('\nRerun with --chat "<identifier>" to extract.\n')


# ── extraction ────────────────────────────────────────────────────────────

def count_per_identifier(conn, identifiers: list[str]) -> dict[str, int]:
    """How many messages each identifier contributes, before merging.

    A five-year thread is usually split across a phone number and an Apple ID.
    Merging them is the right call, but a typo in one silently halves the corpus
    and nothing downstream would ever notice — so count them separately first.
    """
    out = {}
    for ident in identifiers:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT m.ROWID)
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE c.chat_identifier = ?
            """, (ident,)).fetchone()
        out[ident] = row[0] if row else 0
    return out


def load_messages(conn, identifiers: list[str]) -> list[dict]:
    ph = ",".join("?" for _ in identifiers)
    rows = conn.execute(
        f"""
        SELECT DISTINCT m.ROWID AS rid, m.text, m.attributedBody,
               m.is_from_me, m.date, m.cache_has_attachments
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        JOIN chat c ON c.ROWID = cmj.chat_id
        WHERE c.chat_identifier IN ({ph})
          AND COALESCE(m.associated_message_type, 0) = 0
          AND COALESCE(m.item_type, 0) = 0
        ORDER BY m.date
        """,
        identifiers,
    ).fetchall()

    out, dropped = [], Counter()
    for r in rows:
        when = apple_time_to_dt(r["date"])
        if not when:
            dropped["no timestamp"] += 1
            continue
        text = (r["text"] or "").strip() or decode_attributed_body(r["attributedBody"]) or ""
        text = text.replace(OBJ_REPLACEMENT, "").strip()
        if not text:
            dropped["attachment only / undecodable"] += 1
            continue
        if TAPBACK_RE.match(text):
            dropped["tapback"] += 1
            continue
        if URL_RE.search(text) and len(text.split()) < 6:
            dropped["link only"] += 1
            continue
        # Deliberately NOT filtering short messages. "ok" and "haha" are the
        # raw material for one-word-reply stats and for "what did she reply".
        # The display pool gets filtered downstream in mine.py's readable().
        out.append({
            "i": len(out),
            "ts": when.isoformat(),
            "from": "p1" if r["is_from_me"] else "p2",
            "text": text,
            **({"att": 1} if r["cache_has_attachments"] else {}),
        })

    if dropped:
        print("  dropped:", ", ".join(f"{v:,} {k}" for k, v in dropped.most_common()))
    return out


def month_range(messages: list[dict]) -> list[str]:
    """Contiguous ascending YYYY-MM. Holes here would silently misindex every
    `month` answer after the hole, so build it by walking, not by set()."""
    stamps = [m["ts"][:7] for m in messages]
    lo, hi = min(stamps), max(stamps)
    out, cur = [], lo
    while cur <= hi:
        out.append(cur)
        y, mo = (int(x) for x in cur.split("-"))
        cur = f"{y + 1}-01" if mo == 12 else f"{y}-{mo + 1:02d}"
    return out


def build_corpus(messages: list[dict], p1: str, p2: str) -> dict:
    months = month_range(messages)
    idx = {m: i for i, m in enumerate(months)}
    density = [0] * len(months)
    for m in messages:
        density[idx[m["ts"][:7]]] += 1
    first, last = messages[0]["ts"], messages[-1]["ts"]

    def pretty(ts: str) -> str:
        return datetime.fromisoformat(ts).strftime("%B %Y")

    return {
        "meta": {
            "p1": p1,
            "p2": p2,
            "months": months,
            "density": density,
            "total": len(messages),
            "first": pretty(first),
            "last": pretty(last),
            "first_ts": first,
            "last_ts": last,
        },
        "messages": messages,
    }


# Columns worth knowing about before you commit to a question format. Apple
# adds these over the years, so what exists depends on the macOS that wrote
# the database — which is why this is a probe and not a constant.
WANTED = {
    "date_read":            "how long a message sat unread — the game's own name",
    "date_delivered":       "delivered-to-read gap, the other half of a read receipt",
    "is_read":              "whether it was ever read at all",
    "associated_message_type": "tapbacks — loved / laughed / emphasized",
    "associated_message_guid": "which message a tapback was aimed at",
    "thread_originator_guid": "replies, so a question can show what it answered",
    "reply_to_guid":        "same, older form",
    "date_edited":          "edited messages — what it said before",
    "message_summary_info": "the edit history blob itself",
    "date_retracted":       "unsent messages — who takes it back more",
    "expressive_send_style_id": "invisible ink, slam, confetti",
    "is_audio_message":     "voice notes",
    "service":              "iMessage vs SMS, i.e. the green bubble",
    "balloon_bundle_id":    "games, polls, Apple Cash",
}


def report_schema(conn) -> None:
    """What this chat.db can answer, beyond what extract.py currently asks it.

    Run this before designing a question format that needs something new. A
    format that wants a column your macOS does not have is a format that
    cannot ship, and finding that out after writing twenty questions is the
    expensive order to find it out in.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(message)").fetchall()}
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    used = {"ROWID", "text", "attributedBody", "is_from_me", "date",
            "cache_has_attachments", "associated_message_type", "item_type"}
    print(f"\n  message table: {len(have)} columns, {len(used & have)} of them used today\n")

    print("  available but unused — each one is a question format:")
    for col, why in WANTED.items():
        if col in have and col not in used:
            print(f"    +  {col:<26} {why}")
    missing = [c for c in WANTED if c not in have]
    if missing:
        print("\n  not in this database (too old a macOS, or renamed):")
        for col in missing:
            print(f"    -  {col}")

    print("\n  related tables:")
    for t in ("attachment", "message_attachment_join", "handle", "chat"):
        print(f"    {'+' if t in tables else '-'}  {t}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="~/Library/Messages/chat.db")
    ap.add_argument("--list", action="store_true", help="show your chats and exit")
    ap.add_argument("--schema", action="store_true",
                    help="report which message columns this macOS has, and exit")
    ap.add_argument("--chat", help="chat identifier(s), comma separated")
    ap.add_argument("--p1", default="Me", help="your name")
    ap.add_argument("--p2", default="Her", help="her name")
    ap.add_argument("--out", default="corpus.json")
    args = ap.parse_args()

    conn, tmp = open_db(args.db)
    try:
        if args.schema:
            report_schema(conn)
            return
        if args.list or not args.chat:
            list_chats(conn)
            return
        idents = [s.strip() for s in args.chat.split(",") if s.strip()]
        print(f"Reading {', '.join(idents)} ...")

        per = count_per_identifier(conn, idents)
        if len(idents) > 1:
            print("  merging:")
            for ident, n in per.items():
                mark = "" if n else "   <- nothing found, check for a typo"
                print(f"    {n:>8,}  {ident}{mark}")
        empty = [i for i, n in per.items() if n == 0]
        if empty and len(empty) == len(idents):
            sys.exit(f"None of {', '.join(empty)} matched a chat. Try --list.")
        if empty:
            print(f"\n  WARNING: {', '.join(empty)} matched nothing. Continuing "
                  f"with the rest — rerun if that was a typo.\n")

        messages = load_messages(conn, idents)
    finally:
        conn.close()
        tmp.cleanup()          # the POC left this copy of your history on disk

    if len(messages) < 200:
        sys.exit(f"Only {len(messages)} usable messages — check the identifier with --list.")

    corpus = build_corpus(messages, args.p1, args.p2)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False)

    m = corpus["meta"]
    sent = Counter(x["from"] for x in messages)
    print(f"\n  {m['total']:,} messages · {m['first']} – {m['last']} · "
          f"{len(m['months'])} months")
    print(f"  {args.p1} {sent['p1']:,}  ·  {args.p2} {sent['p2']:,}")
    print(f"  busiest month: {m['months'][m['density'].index(max(m['density']))]} "
          f"({max(m['density']):,})")
    print(f"\n  wrote {args.out}  ({os.path.getsize(args.out) / 1e6:.1f} MB, gitignored)\n")


if __name__ == "__main__":
    main()
