#!/usr/bin/env python3
"""
rethread.py — give every question that quotes a message the conversation it
came from.

    make rethread            # report what is missing and what it can find
    make rethread WRITE=1    # bake the threads into questions/*.toml

`curate.py` bakes the surrounding messages into a block at mint time. The
question families written by script rather than by curate — escalation, whose
turn, what happened next, finish the sentence — never did, so half the deck
put a bubble on screen at the reveal with no conversation around it. This finds
the source message again and bakes it, in the same shape and for the same
reason curate does: baked, not an index, because `i` moves every time the
thread is re-extracted.

WHY IT MATCHES ON TEXT. Several of these ids end in the corpus index they were
minted from, and after the September re-extraction *every one of those indices
was wrong* — they now point at a different evening. Text is the only anchor
that survives, and it has to be fuzzy: the quoted lines differ from the corpus
by the odd apostrophe or emoji, enough to break an exact compare and not enough
to be a different message.

WHAT IT SKIPS, on purpose:
  · questions with no message at all — counts, shares, Same Page. Nothing to
    surround.
  · `compare` (Callback). Two messages years apart; one thread belongs to one
    of them, and showing it would say which came first.
  · anything already carrying a thread.
  · anything it cannot pin down to a single message, which it reports rather
    than guessing. A question pointing at the wrong evening is worse than one
    with no context at all.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.curate import toml_value                       # noqa: E402
from tools.lexicon import normalise                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLANK = "\u2581"
G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"

# Below this a "match" is a different message that happens to share words.
FLOOR = 0.90
SPAN = 10                      # messages either side, same as curate.context_for


def probe(text: str, fmt: str) -> str:
    """The part of a question's bubble that is really a message.

    A blanked question shows a message with holes in it, so only the run before
    the first hole is quotable. A `compare` carries two messages under A:/B:
    labels — the caller skips those, but the parsing lives here anyway so the
    reason is in one place.
    """
    if fmt == "compare":
        line = text.split("\n")[0]
        m = re.match(r"^[A-Z]\s*:\s*(.*)$", line)
        return (m.group(1) if m else line).strip("\u201c\u201d\"' ")
    line = text.split("\n")[0].strip()
    if BLANK in line:
        # The LONGEST run between holes, not just the prefix. A redacted
        # message often starts with two words and hides the third, and
        # "honestly the" identifies nothing.
        runs = [r.strip() for r in re.split(BLANK + "+", line)]
        return max(runs, key=len) if runs else ""
    return line


class Finder:
    def __init__(self, messages: list[dict]):
        self.messages = messages
        self.norms = [normalise(m["text"]) for m in messages]
        self.exact: dict[str, list[int]] = collections.defaultdict(list)
        self.word: dict[str, set[int]] = collections.defaultdict(set)
        self.short: dict[str, set[int]] = collections.defaultdict(set)
        for i, n in enumerate(self.norms):
            if not n:
                continue
            self.exact[n].append(i)
            for w in set(n.split()):
                (self.word if len(w) > 4 else self.short)[w].add(i)

    def find(self, text: str) -> tuple[int | None, float, str]:
        """(index, confidence, why). None when it is not sure enough to say."""
        n = normalise(text)
        if len(n) < 12:
            return None, 0.0, "too short to identify"

        hits = self.exact.get(n, [])
        if len(hits) == 1:
            return hits[0], 1.0, "exact"
        if len(hits) > 1:
            return None, 1.0, f"{len(hits)} messages say exactly this"

        # Blanked questions quote a prefix, so a message that starts with it is
        # the one — as long as only one does.
        starts = [i for i, m in enumerate(self.norms) if m.startswith(n)]
        if len(starts) == 1:
            return starts[0], 0.99, "prefix"
        if len(starts) > 1:
            return None, 0.99, f"{len(starts)} messages start with this"

        # Otherwise: near-miss. Narrow by rare words, then score properly.
        cand: set[int] = set()
        for w in sorted((w for w in n.split() if len(w) > 4), key=len, reverse=True)[:4]:
            cand |= self.word.get(w, set())
        if not cand:
            # Nothing long enough to index on — a line of short words is still
            # a real message, so fall back to the rarest short word there is.
            short = sorted(set(n.split()), key=lambda w: len(self.short.get(w, ())))
            for w in short[:2]:
                cand |= self.short.get(w, set())
        if not cand:
            return None, 0.0, "no candidates"
        scored = []
        for i in cand:
            r = difflib.SequenceMatcher(None, n, self.norms[i]).ratio()
            if r >= FLOOR:
                scored.append((r, i))
        if not scored:
            return None, 0.0, "nothing close enough"
        scored.sort(reverse=True)
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.02:
            return None, scored[0][0], "two messages equally close"
        return scored[0][1], scored[0][0], f"fuzzy {scored[0][0]:.2f}"

    def thread(self, i: int) -> list[dict]:
        lo, hi = max(0, i - SPAN), min(len(self.messages), i + SPAN + 1)
        out = []
        for m in self.messages[lo:hi]:
            t = (m.get("text") or "").strip()
            if t:
                out.append({"who": m["from"], "text": t, "self": m["i"] == i})
        return out if len(out) > 1 else []


def blocks_needing_context(qdir: str, respan: bool = False):
    """Every `[[q]]` worth (re)threading, as (path, id, probe_text, format).

    Normally that means blocks showing a message with no thread. With `respan`
    it also means blocks whose thread is the wrong width — and for those the
    anchor is better than a probe, because the thread already names the exact
    message it was built around (`self = true`).
    """
    import tomllib
    for path in sorted(glob.glob(os.path.join(qdir, "*.toml"))
                       + glob.glob(os.path.join(qdir, "auto", "*.toml"))):
        if os.path.basename(path) in ("config.toml", "lexicons.toml"):
            continue
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for q in data.get("q", []):
            if not q.get("text") or q.get("format") == "compare":
                continue
            ctx = q.get("context")
            if not ctx:
                yield path, q.get("id", "?"), q["text"], q.get("format", "bubble")
            elif respan and len(ctx) < SPAN + 1:
                anchor = next((c["text"] for c in ctx if c.get("self")), None)
                if anchor:
                    yield path, q.get("id", "?"), anchor, "bubble"


# A whole `context = [...]`, in both spellings that exist: curate writes it on
# one line, this tool writes one message per line. Anchored on a `]` that ends
# a line, which a `]` inside a message never does — an entry always closes with
# `}` or `},` first.
# NOTE the missing `\s*` before `$`. It was there once, and being greedy it ate
# the newline after the closing bracket — which only showed on blocks where
# `context` was the last field, because then the next `[[q]]` got pulled onto
# the same line. The trailing newline is not ours to consume.
CONTEXT_RE = re.compile(r"(?ms)^context\s*=\s*\[.*?\]$")


def write_context(path: str, qid: str, ctx: list[dict], replace: bool = False) -> bool:
    """Put a `context = [...]` into one block, after `text`.

    Re-parses the file afterwards and rolls back if it no longer loads. This
    edits questions the user wrote by hand; corrupting that file to save a
    thread would be a bad trade.
    """
    import tomllib
    with open(path, encoding="utf-8") as f:
        src = f.read()
    parts = re.split(r"(?m)^\[\[q\]\]\s*$", src)
    for i, blk in enumerate(parts):
        if not re.search(rf'(?m)^id\s*=\s*"{re.escape(qid)}"', blk):
            continue
        line = "context = [\n" + "".join(
            f"  {toml_value(c)},\n" for c in ctx) + "]"
        if CONTEXT_RE.search(blk):
            if not replace:
                return False
            parts[i] = CONTEXT_RE.sub(lambda _: line, blk, count=1)
        else:
            m = re.search(r"(?m)^text\s*=.*$", blk)
            parts[i] = (blk.replace(m.group(0), m.group(0) + "\n" + line, 1)
                        if m else blk.rstrip("\n") + "\n" + line + "\n")
        out = "[[q]]".join(parts)
        try:
            tomllib.loads(out)
        except Exception as e:
            print(f"  {R}refused to write {qid}: {e}{X}")
            return False
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="corpus.json")
    ap.add_argument("--questions", default=os.path.join(ROOT, "questions"))
    ap.add_argument("--write", action="store_true", help="bake them in")
    ap.add_argument("--respan", action="store_true",
                    help="also rebuild threads that were baked narrower")
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        finder = Finder(json.load(f)["messages"])

    todo = list(blocks_needing_context(args.questions, args.respan))
    what = ("need a thread, or a wider one" if args.respan
            else "show a message with no thread around it")
    print(f"\n{B}{len(todo)} questions{X} {what}  {D}(span {SPAN}){X}\n")

    done = 0
    unsure: list[tuple[str, str]] = []
    for path, qid, text, fmt in todo:
        i, conf, why = finder.find(probe(text, fmt))
        if i is None:
            unsure.append((qid, why))
            continue
        ctx = finder.thread(i)
        if not ctx:
            unsure.append((qid, "nothing either side of it"))
            continue
        if args.write and write_context(path, qid, ctx, replace=args.respan):
            done += 1
        elif not args.write:
            done += 1

    verb = "baked" if args.write else "can be found"
    print(f"  {G}{done} {verb}{X}")
    if unsure:
        print(f"  {Y}{len(unsure)} left alone{X} "
              f"{D}— a thread on the wrong evening is worse than none{X}")
        for qid, why in unsure:
            print(f"      {qid:<26} {D}{why}{X}")
    if done and not args.write:
        print(f"\n  {D}re-run with WRITE=1 to bake them in{X}")
    print()


if __name__ == "__main__":
    main()
