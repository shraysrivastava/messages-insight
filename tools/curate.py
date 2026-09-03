#!/usr/bin/env python3
"""
curate.py — 300 fast judgments instead of 90 blank pages.

    python3 tools/curate.py                    # localhost:8900, opens a browser
    python3 tools/curate.py --port 9000 --no-open

`auto/messages.toml` is full of SLOTS: finished questions missing only a real
message. `mine.py` has already proposed 365 messages that could fill them. This
is the page where you say yes or no, one keystroke each, and the yeses land in
`questions/mine.toml` as finished blocks with the message, the options, the
answer and the date baked in.

    J  reject      K  accept      E  edit then accept
    N  skip slot   U  undo        S  search      ?  keys

Three things make it worth building rather than editing TOML by hand:

  · CONTEXT. Five messages either side, always on screen. You cannot write a
    payoff for a message you can't remember the reason for.
  · VALIDATION. Accept runs the block through app/schema.py before it touches
    the file. A slot whose reveal still says TODO refuses to ship, and hands
    you the editor instead of a broken question at round 9.
  · SEARCH. Type `goodnight` and see every hit in five years with its date.
    Mint a question from any of them. This is where the good ones come from.

Resumable: every decision is recorded in `questions/.curate.json`, so closing
the tab loses nothing. Nothing is ever overwritten — accepts append, undo
removes exactly the block it wrote.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tomllib
except ModuleNotFoundError:                     # py < 3.11
    import tomli as tomllib

from app.schema import Question
from tools.lexicon import load_lexicons, normalise
from tools.mine import WORD_RE, candidate as mk_candidate, interestingness, readable
from tools.resolvers import Corpus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLANK = "▁▁▁▁▁"
MARKER = "# ── curated ── "

# Vars that compile.py can still fill in after we're done. Everything else has
# to be baked at mint time, because a curated question carries no resolver.
COMPILE_VARS = {"p1", "p2", "total", "years", "months_n"}

# Which candidate kinds fill which shape of question. The slot's `source.mine`
# names one of these.
TEXT_KINDS = {"who_said_it", "complaint", "apology", "longest"}
BLANK_KINDS = {"fill_blank", "fill_emoji", "redact"}
REPLY_KINDS = {"reply", "reply_inverted"}

G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


# ── slots ─────────────────────────────────────────────────────────────────

@dataclass
class Slot:
    """A question in auto/ that is finished apart from the message itself."""

    id: str
    block: dict          # the TOML block, minus `source` and `status`
    src: dict            # the `source` table: kind + filters
    file: str

    @property
    def kind(self) -> str:
        return self.src.get("mine", "")


def load_slots(qdir: str) -> list[Slot]:
    out = []
    for path in sorted(glob.glob(os.path.join(qdir, "auto", "*.toml"))):
        with open(path, "rb") as f:
            for q in tomllib.load(f).get("q", []):
                src = q.get("source")
                if q.get("status") != "mine" or not isinstance(src, dict):
                    continue
                if "mine" not in src:
                    continue
                out.append(Slot(
                    id=q["id"],
                    block={k: v for k, v in q.items()
                           if k not in ("source", "status")},
                    src=src,
                    file=os.path.relpath(path, ROOT),
                ))
    return out


def existing_ids(mine_path: str) -> set[str]:
    if not os.path.exists(mine_path):
        return set()
    with open(mine_path, "rb") as f:
        return {q.get("id", "") for q in tomllib.load(f).get("q", [])}


# ── candidates ────────────────────────────────────────────────────────────

def _dt(c: dict) -> datetime:
    return datetime.fromisoformat(c["ts"])


def _clock(dt: datetime) -> str:
    return dt.strftime("%-I:%M%p").lower()


def derive(cands: list[dict], seed: int = 11) -> list[dict]:
    """Two slots ask for kinds `mine.py` doesn't generate. Both are one
    transform away from a kind it does, so do it here rather than leave
    `redacted-1` and `reply-roulette` permanently unfillable."""
    rng = random.Random(seed)
    out: list[dict] = []
    replies = [c for c in cands if c["kind"] == "reply"]

    for c in cands:
        if c["kind"] == "fill_blank":
            r = _redact(c, rng)
            if r:
                out.append(r)
        elif c["kind"] == "reply":
            r = _invert(c, replies, rng)
            if r:
                out.append(r)
    return out


def _redact(c: dict, rng: random.Random, blanks: int = 3) -> dict | None:
    """One blank becomes three. The asked-about word stays the original one, so
    the options and the answer carry over untouched."""
    words = c["blanked"].split()
    ix = [i for i, w in enumerate(words)
          if BLANK not in w and len(w) >= 3 and any(ch.isalpha() for ch in w)]
    if len(ix) < blanks - 1:
        return None
    for i in rng.sample(ix, blanks - 1):
        words[i] = BLANK
    out = dict(c)
    out["id"] = "redact-" + str(c["i"])
    out["kind"] = "redact"
    out["blanked"] = " ".join(words)
    return out


def _invert(c: dict, pool: list[dict], rng: random.Random) -> dict | None:
    """Reply roulette: show the reply, guess what prompted it. Distractors are
    other candidates' prompts, which is exactly the right level of plausible."""
    seen = {normalise(c["text"])}
    others = []
    for o in pool:
        n = normalise(o["text"])
        if o["id"] != c["id"] and n and n not in seen:
            seen.add(n)
            others.append(o["text"])
    if len(others) < 3:
        return None
    opts = rng.sample(others, 3) + [c["text"]]
    rng.shuffle(opts)
    out = dict(c)
    out["id"] = "reply_inverted-" + str(c["i"])
    out["kind"] = "reply_inverted"
    out["text"] = c["reply"]
    out["options"] = opts
    out["answer"] = opts.index(c["text"])
    return out


def _spread_months(c: dict, corpus: Corpus) -> int:
    """How far apart the two messages of a compare_dates candidate are."""
    try:
        d = datetime.strptime(c["other_date"], "%B %d, %Y")
    except (KeyError, ValueError):
        return 0
    ix = corpus.month_ix.get(f"{d.year}-{d.month:02d}")
    return abs(ix - c["month"]) if ix is not None else 0


def slot_pool(slot: Slot, cands: list[dict], corpus: Corpus,
              lexicons: dict) -> tuple[list[dict], str]:
    """Candidates that fit this slot, best first, plus a note if a filter had
    to be relaxed. Filters that silently match nothing are how you end up
    staring at an empty queue wondering what you did wrong."""
    src = slot.src
    pool = [c for c in cands if c["kind"] == slot.kind]
    note = ""

    if by := src.get("by"):
        pool = [c for c in pool if c["from"] == by]
    if hours := src.get("hours"):
        lo, hi = hours[0], hours[1]
        pool = [c for c in pool if lo <= _dt(c).hour < hi]
    if lex := src.get("lex"):
        L = lexicons.get(lex)
        if L is not None and L.include is not None:
            pool = [c for c in pool if L.matches(normalise(c["text"]))]
    if spread := src.get("spread_months"):
        pool = [c for c in pool if _spread_months(c, corpus) >= spread]
    if before := src.get("before"):
        older = [c for c in pool if c["ts"][:7] < before]
        if older:
            pool = older
        else:
            # The thread starts after the cutoff. "Year one" is still a real
            # idea — say so out loud and show the front of the timeline.
            cutoff = max(0, len(corpus.months) // 3 - 1)
            pool = [c for c in pool if c["month"] <= cutoff]
            note = (f"nothing before {before} — the thread starts "
                    f"{corpus.months[0]}, so showing its first "
                    f"{cutoff + 1} months instead")

    return sorted(pool, key=lambda c: -c.get("score", 0)), note


# ── mining a slot's own window ────────────────────────────────────────────
#
# `mine.py` proposes 50 candidates per generator across the whole thread. A
# slot that wants a 3am message, or one that says "search for work news",
# usually finds none of them in that narrow window. Rather than leave the slot
# permanently unfillable, go back to the corpus and mine the window itself.

SHAPE_OF_TYPE = {"month": "datable", "binary": "who_said_it"}
MINEABLE = {"who_said_it", "complaint", "apology", "longest", "datable"}


def _predicate(src: dict, lexicons: dict):
    """The cheap per-message filters, applied to corpus messages rather than
    to candidates. Returns None if the slot asks for a lexicon nobody has
    written yet — better to say so than to return the whole thread."""
    by, hours, lexname = src.get("by"), src.get("hours"), src.get("lex")
    L = lexicons.get(lexname) if lexname else None
    if lexname and (L is None or L.include is None):
        return None

    def ok(m):
        if by and m["from"] != by:
            return False
        if hours and not (hours[0] <= m["dt"].hour < hours[1]):
            return False
        if L is not None and not L.matches(m["norm"]):
            return False
        return True
    return ok


def supplement(slot: Slot, corpus: Corpus, freq, lexicons: dict,
               limit: int = 120) -> list[dict]:
    """Candidates mined from the corpus for one slot, in mine.py's own shape."""
    kind = slot.kind
    if kind == "search":
        kind = SHAPE_OF_TYPE.get(slot.block.get("type", ""), "")
    if kind not in MINEABLE:
        return []
    ok = _predicate(slot.src, lexicons)
    if ok is None:
        return []

    out = []
    for m in corpus.messages:
        if not readable(m) or not ok(m):
            continue
        ix = corpus.month_of(m)
        extra = {"answer": ix} if kind == "datable" else {
            "answer": 0 if m["from"] == "p1" else 1}
        out.append(mk_candidate(corpus, m, kind, interestingness(m, freq), **extra))
    out.sort(key=lambda c: -c["score"])
    # Run them back through the same filters, under the kind they actually are.
    src = dict(slot.src)
    src["mine"] = kind
    pool, _ = slot_pool(Slot(slot.id, slot.block, src, slot.file),
                        out[:limit], corpus, lexicons)
    return pool


# ── minting ───────────────────────────────────────────────────────────────

VAR_RE = re.compile(r"\{(\w+)(?::[^{}]*)?\}")


def esc(s: str) -> str:
    """compile.py runs every string through .format(). A brace in a real
    message is not a template var."""
    return str(s).replace("{", "{{").replace("}", "}}")


def bake(template: str, vals: dict) -> str:
    """Fill in the vars that came from this message; leave {p1} and friends
    for the compiler, which still knows how to render those."""
    def sub(m):
        k = m.group(1)
        return esc(vals[k]) if k in vals else m.group(0)
    return VAR_RE.sub(sub, template)


CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}\s*[ap]\.?m\.?", re.I)


def mint(slot: Slot, cand: dict, corpus: Corpus, qid: str,
         topic: str | None) -> tuple[dict, list[str]]:
    """Slot + candidate -> a finished question block, plus anything you should
    know before you accept it."""
    kind = cand["kind"]
    q = dict(slot.block)
    notes: list[str] = []

    sender = corpus.name(cand["from"])
    other = corpus.name("p2" if cand["from"] == "p1" else "p1")
    vals = {
        "winner": sender,
        "loser": other,
        "date": cand["date"],
        "month": corpus.pretty_month(cand["month"]),
        "time": _clock(_dt(cand)),
        "full": cand["text"],
    }

    if kind in TEXT_KINDS:
        q["text"] = esc(cand["text"])
        q["answer"] = cand["answer"]
        vals["answer"] = sender
        words = len(cand["text"].split())
        if words > 40:
            notes.append(f"{words} words — long for the big screen. "
                         "E to trim it.")
    elif kind in BLANK_KINDS:
        q["text"] = esc(cand["blanked"])
        q["options"] = [esc(o) for o in cand["options"]]
        q["answer"] = cand["answer"]
        vals["answer"] = cand["options"][cand["answer"]]
    elif kind in REPLY_KINDS:
        q["text"] = esc(cand["text"])
        q["options"] = [esc(o) for o in cand["options"]]
        q["answer"] = cand["answer"]
        vals["answer"] = cand["options"][cand["answer"]]
    elif kind == "datable":
        q["text"] = esc(cand["text"])
        q["answer"] = cand["month"]
        vals["answer"] = vals["month"]
    elif kind == "compare_dates":
        a, b = cand["pair"]["A"], cand["pair"]["B"]
        q["text"] = esc(f"A: “{a}”\nB: “{b}”")
        q["options"] = ["A", "B"]
        q["answer"] = cand["answer"]
        first = cand["answer"] == 0
        vals["answer"] = "A" if first else "B"
        vals["date"] = cand["date"] if first else cand["other_date"]
        vals["other_date"] = cand["other_date"] if first else cand["date"]
    else:
        raise ValueError(f"no mint template for candidate kind {kind!r}")

    q["id"] = qid
    if topic:
        q["topic"] = topic
    else:
        q.pop("topic", None)
    q["prompt"] = bake(q.get("prompt", ""), vals)
    q["reveal"] = bake(q.get("reveal", ""), vals)
    q["status"] = "ready"

    # A slot that names a clock time is naming the wrong one for every message
    # but the one it was written against.
    clock = _clock(_dt(cand))
    if CLOCK_RE.search(q["prompt"]) and clock not in q["prompt"].lower():
        q["prompt"] = CLOCK_RE.sub(clock, q["prompt"], count=1)
        notes.append(f"prompt said a different time — corrected to {clock}")

    return q, notes


def leftover_vars(q: dict) -> list[str]:
    """Vars nothing will ever fill. They render as empty string at compile
    time, which is how a reveal ends up reading 'Sent by  ·  .'"""
    found = []
    for key in ("prompt", "text", "reveal"):
        for v in VAR_RE.findall(str(q.get(key) or "")):
            if v not in COMPILE_VARS and v not in found:
                found.append(v)
    return found


def preview(q: dict, names: tuple[str, str]) -> dict:
    """What the block will actually say once compile.py renders it."""
    ctx = {"p1": names[0], "p2": names[1], "total": 0, "years": 0, "months_n": 0}

    def render(s):
        try:
            return str(s).format(**{**{v: "" for v in VAR_RE.findall(str(s))},
                                    **ctx})
        except (KeyError, IndexError, ValueError):
            return str(s)

    out = {k: render(v) for k, v in q.items()
           if k in ("prompt", "text", "reveal")}
    out["options"] = [render(o) for o in (q.get("options") or [])]
    return out


def validate(q: dict, names: tuple[str, str]) -> str | None:
    """Run the block past the real schema before it touches the file. Returns
    an error message, or None if it would ship."""
    p = preview(q, names)
    candidate = {k: v for k, v in q.items() if k != "status"}
    candidate.pop("source", None)
    candidate.update({k: v for k, v in p.items() if v or k != "text"})
    if p["options"]:
        candidate["options"] = p["options"]
    candidate["origin"] = "mine"
    try:
        Question.model_validate(candidate)
    except Exception as e:                          # pydantic ValidationError
        errs = getattr(e, "errors", None)
        if callable(errs):
            # The default string form pastes the whole input back at you,
            # message text included. Just the sentence, please.
            out = []
            for d in errs():
                loc = ".".join(str(x) for x in d.get("loc", ()))
                msg = d.get("msg", "").replace("Value error, ", "")
                out.append(f"{loc}: {msg}" if loc else msg)
            return "; ".join(out)
        return str(e).splitlines()[0]
    return None


# ── writing TOML ──────────────────────────────────────────────────────────

FIELD_ORDER = ["id", "topic", "type", "kind", "area", "format",
               "prompt", "text", "options", "answer", "reveal", "status"]

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def toml_str(s: str) -> str:
    out = ["\""]
    for ch in str(s):
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append("\"")
    return "".join(out)


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return toml_str(v)


def block_text(q: dict, cand: dict | None = None, slot: Slot | None = None) -> str:
    """One `[[q]]` block, with a marker line `undo` can find again."""
    prov = []
    if cand:
        prov.append(cand["id"])
    if slot:
        prov.append(slot.file)
    line = f"{MARKER}{q['id']}"
    if prov:
        line += "  ·  " + "  ·  ".join(prov)
    rows = [line, "[[q]]"]
    for k in FIELD_ORDER:
        if k in q and q[k] is not None:
            rows.append(f"{k} = {toml_value(q[k])}")
    for k, v in q.items():                       # anything the editor added
        if k not in FIELD_ORDER and v is not None:
            rows.append(f"{k} = {toml_value(v)}")
    return "\n".join(rows) + "\n"


def append_block(path: str, text: str) -> None:
    head = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
        if existing and not existing.endswith("\n\n"):
            head = "\n" if existing.endswith("\n") else "\n\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(head + text)


def remove_block(path: str, qid: str) -> bool:
    """Delete exactly the block `qid`'s marker introduces, and nothing else."""
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith(MARKER + qid)
                  and ln[len(MARKER) + len(qid):len(MARKER) + len(qid) + 1]
                  in ("", "\n", " ")), None)
    if start is None:
        return False

    end, seen = start + 1, False
    while end < len(lines):
        ln = lines[end]
        if ln.startswith("[[q]]"):
            if seen:
                break
            seen = True
        elif ln.startswith(MARKER):
            break
        end += 1

    while start > 0 and not lines[start - 1].strip():
        start -= 1
    del lines[start:end]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True


# ── the sidecar ───────────────────────────────────────────────────────────

def load_state(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                s = json.load(f)
            s.setdefault("seen", {})
            s.setdefault("minted", [])
            s.setdefault("skipped", [])
            return s
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "seen": {}, "minted": [], "skipped": []}


def save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, path)


# ── the session ───────────────────────────────────────────────────────────

@dataclass
class Session:
    corpus: Corpus
    cands: list[dict]
    slots: list[Slot]
    lexicons: dict
    mine_path: str
    state_path: str
    state: dict = field(default_factory=dict)
    guards: dict = field(default_factory=dict)

    def __post_init__(self):
        from collections import Counter
        self.by_id = {c["id"]: c for c in self.cands}
        self.slot_by_id = {s.id: s for s in self.slots}
        self.freq = Counter(w for m in self.corpus.messages
                            for w in WORD_RE.findall(m["norm"]))
        self.pools: dict[str, tuple[list[dict], str]] = {}
        mined: dict[str, dict] = {}
        for s in self.slots:
            self.pools[s.id] = self._pool_for(s, mined)
        for cid, c in mined.items():
            if cid not in self.by_id:
                self.by_id[cid] = c
                self.cands.append(c)

    def _pool_for(self, slot: Slot, mined: dict) -> tuple[list[dict], str]:
        pool, note = slot_pool(slot, self.cands, self.corpus, self.lexicons)
        if pool:
            return pool, note
        extra = supplement(slot, self.corpus, self.freq, self.lexicons)
        if not extra:
            return pool, note
        for c in extra:
            mined.setdefault(c["id"], c)
        return extra, "mined from the thread directly — nothing pre-mined fit this slot"

    # -- naming

    @property
    def names(self) -> tuple[str, str]:
        return self.corpus.meta["p1"], self.corpus.meta["p2"]

    def taken(self) -> set[str]:
        return existing_ids(self.mine_path) | {
            m["qid"] for m in self.state["minted"]}

    def new_id(self, base: str) -> str:
        taken = self.taken()
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    # -- what to show

    def filled(self) -> set[str]:
        return {m["slot"] for m in self.state["minted"] if m.get("slot")}

    def current_slot(self) -> Slot | None:
        done = self.filled() | set(self.state["skipped"])
        for s in self.slots:
            if s.id in done:
                continue
            if self.queue(s):
                return s
        return None

    def used_messages(self) -> set[int]:
        """A message that is already a question doesn't get to be a second one.
        Two rounds on the same bubble reads as a bug from the sofa."""
        out = set()
        for m in self.state["minted"]:
            if m.get("i") is not None:
                out.add(m["i"])
            elif m.get("cand") in self.by_id:
                out.add(self.by_id[m["cand"]]["i"])
        return out

    def queue(self, slot: Slot) -> list[dict]:
        pool, _ = self.pools[slot.id]
        used = self.used_messages()
        return [c for c in pool
                if c["id"] not in self.state["seen"] and c["i"] not in used]

    def card(self) -> dict | None:
        slot = self.current_slot()
        if slot is None:
            return None
        q = self.queue(slot)
        if not q:
            return None
        cand = q[0]
        qid = self.new_id(slot.id)
        topic = slot.id if qid == slot.id else None
        block, notes = mint(slot, cand, self.corpus, qid, topic)
        err = validate(block, self.names)
        stray = leftover_vars(block)
        if stray:
            notes.append("nothing will fill " +
                         ", ".join("{" + v + "}" for v in stray) +
                         " — they compile to nothing")
        if block.get("type") == "month":
            notes += self._month_warning(block["answer"])
        pool, relaxed = self.pools[slot.id]
        return {
            "slot": {"id": slot.id, "file": slot.file, "kind": slot.kind,
                     "label": slot.block.get("kind", ""),
                     "type": slot.block.get("type", ""),
                     "format": slot.block.get("format", "bubble"),
                     "note": relaxed, "remaining": len(q)},
            "cand": {"id": cand["id"], "i": cand["i"], "date": cand["date"],
                     "time": _clock(_dt(cand)), "from": cand["from"],
                     "score": cand.get("score"),
                     "sender": self.corpus.name(cand["from"]),
                     "context": cand["context"]},
            "block": block,
            "preview": preview(block, self.names),
            "answer_label": self._answer_label(block),
            "notes": notes,
            "error": err,
        }

    def _answer_label(self, q: dict) -> str:
        """`month 0` means nothing to a human judging a question."""
        if q.get("type") == "month" and isinstance(q.get("answer"), int):
            n = len(self.corpus.months)
            if 0 <= q["answer"] < n:
                return self.corpus.pretty_month(q["answer"])
        return str(q.get("answer", ""))

    def _month_warning(self, ix) -> list[str]:
        """compile.py drops month answers in the outer band — they're
        guessable from where the slider ends. Say so now, not at compile."""
        edge = float(self.guards.get("month_edge_pct", 0.10))
        n = len(self.corpus.months)
        if not isinstance(ix, int) or n < 2:
            return []
        if n * edge <= ix <= n * (1 - edge):
            return []
        return [f"{self.corpus.pretty_month(ix)} is in the first or last "
                f"{edge:.0%} of the thread — the compiler drops these as "
                f"guessable from the slider alone"]

    def progress(self) -> dict:
        fillable = [s for s in self.slots if self.pools[s.id][0]]
        empty = [s.id for s in self.slots if not self.pools[s.id][0]]
        return {
            "filled": len(self.filled()),
            "slots": len(fillable),
            "empty": empty,
            "skipped": self.state["skipped"],
            "reviewed": len(self.state["seen"]),
            "accepted": len(self.state["minted"]),
            "candidates": len(self.cands),
            "minted": [m["qid"] for m in self.state["minted"]][-8:],
        }

    def view(self) -> dict:
        return {"card": self.card(), "progress": self.progress(),
                "names": list(self.names), "mine": os.path.relpath(
                    self.mine_path, ROOT)}

    # -- decisions

    def reject(self, cand_id: str) -> None:
        self.state["seen"][cand_id] = "reject"
        save_state(self.state_path, self.state)

    def accept(self, cand_id: str, block: dict, slot_id: str | None) -> str | None:
        err = validate(block, self.names)
        if err:
            return err
        block = dict(block)
        block["id"] = self.new_id(block.get("id") or "question")
        block["status"] = "ready"
        cand = self.by_id.get(cand_id)
        slot = self.slot_by_id.get(slot_id or "")
        append_block(self.mine_path, block_text(block, cand, slot))
        self.state["seen"][cand_id] = "accept"
        self.state["minted"].append({
            "qid": block["id"], "slot": slot_id, "cand": cand_id,
            "i": (cand or {}).get("i"),
            "at": datetime.now().isoformat(timespec="seconds")})
        save_state(self.state_path, self.state)
        return None

    def skip_slot(self, slot_id: str) -> None:
        if slot_id and slot_id not in self.state["skipped"]:
            self.state["skipped"].append(slot_id)
            save_state(self.state_path, self.state)

    def undo(self) -> str | None:
        if not self.state["minted"]:
            return "nothing to undo"
        last = self.state["minted"][-1]
        if not remove_block(self.mine_path, last["qid"]):
            return (f"couldn't find {last['qid']} in mine.toml — "
                    "left the record alone")
        self.state["minted"].pop()
        self.state["seen"].pop(last["cand"], None)
        save_state(self.state_path, self.state)
        return None

    # -- search

    def search(self, phrase: str, by: str | None = None, limit: int = 80) -> list[dict]:
        from tools.lexicon import PhraseLex
        phrase = phrase.strip()
        if not phrase:
            return []
        # expand() makes every letter of the *phrase* repeatable, so the
        # tolerance runs one way: "lol" finds "loool", but "loool" finds
        # nothing. Collapsing runs in what you typed makes it run both ways,
        # and costs nothing — "lol" re-expands to the same regex either way.
        lex = PhraseLex(re.sub(r"(.)\1{2,}", r"\1", phrase))
        if lex.include is None:
            return []
        hits = []
        for m in self.corpus.side(by):
            if lex.matches(m["norm"]):
                hits.append({
                    "i": m["i"], "from": m["from"],
                    "sender": self.corpus.name(m["from"]),
                    "text": m["text"], "date": self.corpus.pretty(m),
                    "time": _clock(m["dt"]),
                    "month": self.corpus.month_of(m),
                })
        return hits[:limit]

    def from_message(self, i: int, shape: str) -> dict:
        """Mint a question out of any message in the thread, not just one
        mine.py happened to propose. This is where the best ones come from."""
        m = next((x for x in self.corpus.messages if x["i"] == i), None)
        if m is None:
            raise ValueError(f"no message {i}")
        base = {
            "id": f"{shape}-{i}", "i": i, "from": m["from"], "text": m["text"],
            "ts": m["ts"], "date": self.corpus.pretty(m),
            "month": self.corpus.month_of(m), "score": 0,
            "context": self._context(i),
        }
        if shape == "who_said_it":
            cand = {**base, "kind": "who_said_it",
                    "answer": 0 if m["from"] == "p1" else 1}
            slot = self._template("who_said_it")
            qid = self.new_id(f"who-said-m{i}")
        elif shape == "datable":
            cand = {**base, "kind": "datable", "answer": base["month"]}
            slot = self._template("datable")
            qid = self.new_id(f"date-this-m{i}")
        else:
            raise ValueError(f"unknown shape {shape!r}")
        if slot is None:
            raise ValueError(f"no slot in auto/ to model a {shape} on")
        block, notes = mint(slot, cand, self.corpus, qid, None)
        self.by_id[cand["id"]] = cand
        if block.get("type") == "month":
            notes += self._month_warning(block["answer"])
        return {"cand": cand, "block": block, "notes": notes,
                "preview": preview(block, self.names),
                "answer_label": self._answer_label(block),
                "error": validate(block, self.names),
                "slot": {"id": None, "label": slot.block.get("kind", ""),
                         "type": slot.block.get("type", ""),
                         "format": slot.block.get("format", "bubble"),
                         "kind": shape, "file": slot.file, "note": "",
                         "remaining": 0}}

    def _template(self, kind: str) -> Slot | None:
        return next((s for s in self.slots if s.kind == kind), None)

    def _context(self, i: int, span: int = 5) -> list[dict]:
        lo, hi = max(0, i - span), min(len(self.corpus.messages), i + span + 1)
        return [{"i": x["i"], "from": x["from"], "text": x["text"],
                 "ts": x["ts"], "self": x["i"] == i}
                for x in self.corpus.messages[lo:hi]]


# ── the web app ───────────────────────────────────────────────────────────

def build_app(sess: Session):
    """One page and six endpoints. `dict` bodies rather than models: this file
    has `from __future__ import annotations`, so anything FastAPI can't resolve
    from module globals silently becomes a query parameter."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(docs_url=None, redoc_url=None)
    page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "curate.html")

    @app.get("/", response_class=HTMLResponse)
    def index():
        with open(page, encoding="utf-8") as f:
            return f.read()

    @app.get("/api/state")
    def state():
        return sess.view()

    @app.post("/api/reject")
    def reject(body: dict):
        sess.reject(body["cand"])
        return sess.view()

    @app.post("/api/accept")
    def accept(body: dict):
        err = sess.accept(body["cand"], body["block"], body.get("slot"))
        return {"error": err, **sess.view()} if err else sess.view()

    @app.post("/api/skip")
    def skip(body: dict):
        sess.skip_slot(body.get("slot") or "")
        return sess.view()

    @app.post("/api/undo")
    def undo(body: dict | None = None):
        return {"error": sess.undo(), **sess.view()}

    @app.post("/api/search")
    def search(body: dict):
        return {"hits": sess.search(body.get("q", ""), body.get("by") or None)}

    @app.post("/api/from-message")
    def from_message(body: dict):
        try:
            return sess.from_message(int(body["i"]),
                                     body.get("shape", "who_said_it"))
        except ValueError as e:
            return {"error": str(e)}

    return app


# ── main ──────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="corpus.json")
    ap.add_argument("--candidates", default="candidates.json")
    ap.add_argument("--questions", default=os.path.join(ROOT, "questions"))
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = ap.parse_args()

    for path, hint in ((args.corpus, "tools/extract.py"),
                       (args.candidates, "tools/mine.py")):
        if not os.path.exists(path):
            raise SystemExit(f"{R}No {path} — run {hint} first.{X}")

    with open(args.corpus, encoding="utf-8") as f:
        corpus = Corpus(json.load(f))
    with open(args.candidates, encoding="utf-8") as f:
        raw = json.load(f)
    with open(os.path.join(args.questions, "config.toml"), "rb") as f:
        cfg = tomllib.load(f)
    with open(os.path.join(args.questions, "lexicons.toml"), "rb") as f:
        lexicons = load_lexicons(tomllib.load(f)["lex"])

    # compile.py takes the names from config.toml, so the reveals baked here
    # have to agree with it or the file will say "Me" on the night.
    meta_cfg = cfg.get("meta", {})
    for key in ("p1", "p2"):
        v = str(meta_cfg.get(key, "")).strip()
        if v and v.upper() != "TODO":
            corpus.meta[key] = v

    cands = raw["candidates"] + derive(raw["candidates"])
    slots = load_slots(args.questions)
    sess = Session(
        corpus=corpus, cands=cands, slots=slots, lexicons=lexicons,
        mine_path=os.path.join(args.questions, "mine.toml"),
        state_path=os.path.join(args.questions, ".curate.json"),
        state=load_state(os.path.join(args.questions, ".curate.json")),
        guards=cfg.get("guards", {}),
    )

    p = sess.progress()
    print(f"\n  {B}READ RECEIPTS · curate{X}")
    print(f"  {len(cands)} candidates · {p['slots']} fillable slots · "
          f"{p['filled']} filled · {p['reviewed']} already judged")
    if p["empty"]:
        print(f"  {Y}no candidates for: {', '.join(p['empty'])}{X}")
    print(f"  writing to {os.path.relpath(sess.mine_path, ROOT)}  "
          f"{D}(gitignored){X}")
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  {G}{url}{X}   {D}J reject · K accept · E edit · S search{X}\n")

    if not args.no_open:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    import uvicorn
    uvicorn.run(build_app(sess), host="127.0.0.1", port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
