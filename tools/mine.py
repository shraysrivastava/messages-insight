#!/usr/bin/env python3
"""
mine.py — corpus.json -> candidates.json

    python3 tools/mine.py --corpus corpus.json --out candidates.json

Produces *candidates*, not questions. The difference matters: it over-generates
wildly and ranks by rough interestingness, on the assumption that you'll reject
most of them in curate.py and that rejecting is fast.

Every candidate carries provenance — source index, date, and the surrounding
messages — because you cannot write a decent reveal without seeing what came
before and after.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.lexicon import EMOJI_RE, Lexicon, normalise
from tools.resolvers import STOPWORDS, Corpus

CONTEXT = 5
WORD_RE = re.compile(r"[a-z']{2,}")
PROPER_RE = re.compile(r"\b[A-Z][a-z]{2,}")
COMPLAINT = Lexicon("complaint", {"any": [
    "annoying", "annoyed", "so mad", "furious", "cant believe", "seriously",
    "ridiculous", "the worst", "hate that", "why would", "unbelievable",
    "im so done", "fed up", "typical"]})
APOLOGY = Lexicon("apology", {"any": [
    "sorry", "my bad", "my fault", "i was wrong", "forgive me", "didnt mean to",
    "that was on me"]})


def readable(m: dict, lo: int = 6, hi: int = 28) -> bool:
    """Long enough to be interesting, short enough for the big screen."""
    if "\n" in m["text"] or len(m["text"]) > 220:
        return False
    return lo <= m["words"] <= hi


def interestingness(m: dict, freq: Counter) -> float:
    """Rough. Its only job is to float the good ones into the first hundred."""
    words = WORD_RE.findall(m["norm"])
    if not words:
        return 0.0
    rare = sum(1 for w in words if freq[w] <= 3) / len(words)
    score = 1.0
    score += 1.5 * rare                                    # unusual vocabulary
    score += 0.8 * bool(PROPER_RE.search(m["text"]))       # a name, a place
    score += 0.6 * bool(EMOJI_RE.search(m["norm"]))
    score += 0.5 if 9 <= m["words"] <= 20 else 0.0         # the sweet spot
    score -= 1.2 * bool(re.search(r"\b(ok|okay|yeah|sure|lol)\b$", m["norm"]))
    return score


def context_of(c: Corpus, m: dict) -> list[dict]:
    lo = max(0, m["i"] - CONTEXT)
    hi = min(len(c.messages), m["i"] + CONTEXT + 1)
    return [{"i": x["i"], "from": x["from"], "text": x["text"],
             "ts": x["ts"], "self": x["i"] == m["i"]}
            for x in c.messages[lo:hi]]


def candidate(c: Corpus, m: dict, kind: str, score: float, **extra) -> dict:
    return {
        "id": f"{kind}-{m['i']}",
        "kind": kind,
        "i": m["i"],
        "from": m["from"],
        "text": m["text"],
        "ts": m["ts"],
        "date": c.pretty(m),
        "month": c.month_of(m),
        "score": round(score, 3),
        "context": context_of(c, m),
        **extra,
    }


# ── generators ────────────────────────────────────────────────────────────

def g_who_said_it(c, pool, freq, rng, n):
    """Rank up messages whose vocabulary appears in *both* senders' history —
    those are the genuinely ambiguous ones, and the fun of the round is the
    ambiguity."""
    vocab = {w: Counter() for w in ("p1", "p2")}
    for m in c.messages:
        for w in WORD_RE.findall(m["norm"]):
            vocab[m["from"]][w] += 1
    out = []
    for m in pool:
        words = [w for w in WORD_RE.findall(m["norm"]) if w not in STOPWORDS]
        if not words:
            continue
        shared = sum(1 for w in words if vocab["p1"][w] and vocab["p2"][w])
        ambiguity = shared / len(words)
        out.append(candidate(c, m, "who_said_it",
                             interestingness(m, freq) + 1.5 * ambiguity,
                             answer=0 if m["from"] == "p1" else 1))
    return top(out, n)


def g_fill_blank(c, pool, freq, rng, n):
    """Blank a mid-frequency content word; distractors from the same band."""
    band = [w for w, k in freq.items()
            if 12 <= k <= 400 and w not in STOPWORDS and len(w) > 3 and w.isalpha()]
    if len(band) < 8:
        return []
    bandset = set(band)
    out = []
    for m in pool:
        words = m["text"].split()
        picks = [i for i, w in enumerate(words)
                 if normalise(w) in bandset and len(normalise(w)) > 3]
        if not picks:
            continue
        i = rng.choice(picks)
        answer = re.sub(r"[^\w']", "", words[i])
        blanked = list(words)
        blanked[i] = "▁▁▁▁▁"
        # Distractors must not already be visible in the message — an option
        # you can see in the bubble is instantly eliminable, which makes the
        # round free points.
        visible = {normalise(w) for w in words}
        pool_d = [w for w in band
                  if w not in visible and abs(len(w) - len(answer)) <= 3]
        if len(pool_d) < 3:
            continue
        distractors = rng.sample(pool_d, 3)
        options = [answer] + distractors
        rng.shuffle(options)
        out.append(candidate(c, m, "fill_blank",
                             interestingness(m, freq) + 0.5,
                             blanked=" ".join(blanked), options=options,
                             answer=options.index(answer)))
    return top(out, n)


def g_fill_emoji(c, pool, freq, rng, n):
    counts = Counter(e for m in c.messages for e in EMOJI_RE.findall(m["norm"]))
    common = [e for e, _ in counts.most_common(8)]
    if len(common) < 4:
        return []
    out = []
    for m in c.messages:
        found = EMOJI_RE.findall(m["norm"])
        if len(found) != 1 or not readable(m, 4, 24) or found[0] not in common:
            continue
        answer = found[0]
        options = [answer] + rng.sample([e for e in common if e != answer], 3)
        rng.shuffle(options)
        out.append(candidate(c, m, "fill_emoji", interestingness(m, freq),
                             blanked=re.sub(EMOJI_RE, "▁", m["text"], count=1),
                             options=options, answer=options.index(answer)))
    return top(out, n)


def g_reply(c, pool, freq, rng, n):
    """A message whose reply is short and surprising."""
    out = []
    by_i = {m["i"]: m for m in c.messages}
    replies = [m for m in c.messages if 1 <= m["words"] <= 8]
    for r in replies:
        prev = by_i.get(r["i"] - 1)
        if not prev or prev["from"] == r["from"] or not readable(prev):
            continue
        pool_others = [x["text"] for x in rng.sample(replies, min(40, len(replies)))
                       if x["i"] != r["i"]]
        if len(pool_others) < 3:
            continue
        options = [r["text"]] + rng.sample(pool_others, 3)
        rng.shuffle(options)
        out.append(candidate(c, prev, "reply", interestingness(prev, freq) + 0.4,
                             options=options, answer=options.index(r["text"]),
                             reply=r["text"]))
    return top(out, n)


def g_datable(c, pool, freq, rng, n):
    out = [candidate(c, m, "datable", interestingness(m, freq), answer=c.month_of(m))
           for m in pool]
    # avoid the extremes: guessable from the slider range alone
    lo, hi = len(c.months) * 0.1, len(c.months) * 0.9
    out = [x for x in out if lo <= x["answer"] <= hi]
    return top(out, n)


def g_lexical(c, pool, freq, rng, n, lex, kind):
    out = [candidate(c, m, kind, interestingness(m, freq) + 0.8,
                     answer=0 if m["from"] == "p1" else 1)
           for m in pool if lex.matches(m["norm"])]
    return top(out, n)


def g_longest(c, pool, freq, rng, n):
    ranked = sorted(c.messages, key=lambda m: -m["words"])[:n]
    return [candidate(c, m, "longest", float(m["words"]),
                      answer=0 if m["from"] == "p1" else 1) for m in ranked]


def g_compare_dates(c, pool, freq, rng, n):
    """Two messages far apart in time — 'which came first'."""
    out = []
    span = len(c.months)
    for _ in range(n * 3):
        a, b = rng.sample(pool, 2)
        if abs(c.month_of(a) - c.month_of(b)) < max(12, span // 4):
            continue
        first, second = (a, b) if a["i"] < b["i"] else (b, a)
        out.append(candidate(c, first, "compare_dates",
                             interestingness(first, freq) + interestingness(second, freq),
                             pair={"A": first["text"], "B": second["text"]},
                             answer=0, other_date=c.pretty(second)))
        if len(out) >= n:
            break
    return out


def _stem(w: str) -> str:
    """Collapse runs of repeated letters, so `much`, `muchhhh` and `muchhhhhh`
    are recognised as one answer rather than three options."""
    return re.sub(r"(.)\1+", r"\1", w)


def g_finish_sentence(c, pool, freq, rng, n):
    """Finish the sentence: a phrase one of them says constantly, cut off.

    Different from `g_fill_blank` in the two ways that matter. The blank always
    lands at the *end*, so the round is "what does she say next" rather than
    "which word is missing"; and the distractors are other completions **the
    same person actually used after the same prefix**, so every option is
    something they really typed and none can be eliminated on grammar alone.

    A prefix qualifies on three counts: used often enough to be a habit
    (`MIN_USES`), one completion clearly dominant (`MIN_SHARE`), and enough
    real alternatives to fill the other tiles. Roughly 140 prefixes clear it on
    a five-year thread; on the demo corpus, none do, which is correct — a
    synthetic corpus has no habits.
    """
    MIN_USES, MIN_SHARE, PREFIXES = 18, 0.55, (3, 4)
    nxt = defaultdict(Counter)
    where = {}
    for m in c.messages:
        toks = WORD_RE.findall(m["norm"])
        for plen in PREFIXES:
            for i in range(len(toks) - plen):
                key = (m["from"], " ".join(toks[i:i + plen]))
                nxt[key][toks[i + plen]] += 1
                where.setdefault((key, toks[i + plen]), m)

    out, used_prefix = [], set()
    for (who, prefix), comp in sorted(
            nxt.items(),
            key=lambda kv: (-len(kv[0][1].split()), -sum(kv[1].values()))):
        total = sum(comp.values())
        if total < MIN_USES or prefix in used_prefix:
            continue
        # A 3-word prefix that is the tail of a 4-word one already kept asks
        # the same question with less of the sentence showing.
        if any(kept.endswith(prefix) or prefix.endswith(kept)
               for kept in used_prefix):
            continue
        (best, hits), *rest = comp.most_common()
        if hits / total < MIN_SHARE or len(rest) < 3:
            continue
        # A function word isn't a habit, it's grammar. "what ya up ___" has
        # exactly one legal completion and asking it tests nothing.
        if best in STOPWORDS or len(best) < 3:
            continue
        src = where.get(((who, prefix), best))
        if src is None:
            continue
        # "much" / "muchhhh" / "muchhhhhh" are the same answer three times, and
        # the plain spelling gives it away. Keep one option per collapsed stem.
        seen_stems = {_stem(best)}
        distractors = []
        for w, _ in rest:
            if _stem(w) in seen_stems or len(w) < 3:
                continue
            seen_stems.add(_stem(w))
            distractors.append(w)
            if len(distractors) >= 8:
                break
        if len(distractors) < 3:
            continue
        used_prefix.add(prefix)
        options = [best] + rng.sample(distractors, 3)
        rng.shuffle(options)
        # Score on how lopsided the habit is, not on rare vocabulary: the
        # point is that they say this *the same way* every time.
        out.append(candidate(c, src, "finish_sentence",
                             (hits / total) * 2 + min(total, 200) / 100,
                             prefix=prefix, blanked=f"{prefix} \u2581\u2581\u2581\u2581\u2581",
                             uses=total, share=round(hits / total, 3),
                             options=options, answer=options.index(best)))
    return top(out, n)


def g_unanswered(c, pool, freq, rng, n):
    """A message that sat there. The round is "how long did this go
    unanswered", which is the only shape in the deck where the funny part is
    the silence rather than anything either of them typed.

    Wants a question, ideally — an unanswered `wyd?` is funnier than an
    unanswered statement — and wants the gap to be the *reply*, not the end
    of a conversation that had already finished, so the next message has to
    come from the other person.
    """
    MIN_HOURS = 6
    out = []
    for a, b in zip(c.messages, c.messages[1:]):
        if a["from"] == b["from"] or not readable(a, 3, 22):
            continue
        hours = (b["dt"] - a["dt"]).total_seconds() / 3600
        if hours < MIN_HOURS:
            continue
        asked = a["text"].strip().endswith("?")
        out.append(candidate(c, a, "unanswered",
                             min(hours, 72) / 12 + (1.5 if asked else 0)
                             + interestingness(a, freq) * 0.3,
                             hours=round(hours), asked=asked,
                             answer=0 if a["from"] == "p1" else 1))
    return top(out, n)


# Words and emoji that belong almost entirely to one of them. A round that
# asks who spoke is over the moment one of these appears — and the deck asks
# about these tells directly elsewhere, so quoting one here gives the same
# answer away twice.
TELL_RE = re.compile(
    r"\b(cus|bc|yea|yeah|imma|ima|tryna|trynna|abt|wym|wdym|lmfao|jus|kms|"
    r"shru|nu|momma|munchkin)\b|😹|🥲", re.I)


JUNK_RE = re.compile(
    r"https?://|www\.|ask alexa|check this out|give this playlist|"
    r"soundcloud|#\w+|\bhttps\b", re.I)


def clean(*ms) -> bool:
    """Reject forwarded promos and runs where the same text repeats — both
    produce questions with no answer worth guessing."""
    texts = [m["text"] if isinstance(m, dict) else m for m in ms]
    if any(JUNK_RE.search(t) for t in texts):
        return False
    return len({t.strip().lower() for t in texts}) == len(texts)


def g_callback(c, pool, freq, rng, n):
    """The same distinctive phrase, said twice, years apart.

    Two messages that echo each other across the whole thread — show both,
    ask which came first. The point is not the date, it is the recognition:
    they said the same odd thing in 2022 and again in 2026 and neither of them
    noticed. A thread rather than a pile.

    Finds 4-word phrases that appear in exactly two messages, far enough apart
    that the question is not guessable from context, and content-bearing
    enough that the echo means something — four stopwords in a row recur
    constantly and say nothing.
    """
    GRAM, MIN_MONTHS = 4, 24
    seen = defaultdict(list)
    for m in c.messages:
        if not readable(m, 5, 26):
            continue
        toks = WORD_RE.findall(m["norm"])
        for i in range(len(toks) - GRAM + 1):
            gram = toks[i:i + GRAM]
            if sum(1 for w in gram if w in STOPWORDS) > 1:
                continue
            seen[" ".join(gram)].append(m)

    out, used = [], set()
    for phrase, ms in seen.items():
        if len(ms) != 2:                      # twice is an echo; ten is a habit
            continue
        a, b = sorted(ms, key=lambda m: m["i"])
        if a["i"] in used or b["i"] in used:
            continue
        if c.month_of(b) - c.month_of(a) < MIN_MONTHS:
            continue
        if not clean(a, b):
            continue
        used.add(a["i"]); used.add(b["i"])
        out.append(candidate(c, a, "callback",
                             (c.month_of(b) - c.month_of(a)) / 12
                             + interestingness(a, freq),
                             phrase=phrase,
                             pair={"A": a["text"], "B": b["text"]},
                             other_i=b["i"], other_date=c.pretty(b),
                             answer=0))
    return top(out, n)


def g_whose_turn(c, pool, freq, rng, n):
    """A short exchange with both sides showing and neither name on it.

    Harder than a single message and better, because the contrast is the clue:
    you are not recognising a voice in isolation, you are working out which of
    two voices starts. Wants an exchange that alternates cleanly and where
    both messages could plausibly belong to either of them.
    """
    out = []
    for i in range(len(c.messages) - 3):
        a, b, d = c.messages[i], c.messages[i + 1], c.messages[i + 2]
        if a["from"] == b["from"] or b["from"] == d["from"]:
            continue
        if not all(readable(m, 4, 18) for m in (a, b, d)):
            continue
        # a real back-and-forth, not three messages hours apart
        if (d["dt"] - a["dt"]).total_seconds() > 900 or not clean(a, b, d):
            continue
        # The opener is the thing being guessed, so it is the one that must
        # not carry a tell. The replies may — by then the round is decided.
        if TELL_RE.search(a["norm"]):
            continue
        out.append(candidate(c, a, "whose_turn",
                             interestingness(a, freq) + interestingness(b, freq),
                             exchange=[a["text"], b["text"], d["text"]],
                             answer=0 if a["from"] == "p1" else 1))
    return top(out, n)


def g_escalation(c, pool, freq, rng, n):
    """Three messages from one person, mid-flight, shuffled.

    A thought arriving in pieces — put it back in order. It is the only shape
    that tests tone rather than content: you work out which came first from
    how wound up it sounds, not from what it says.

    Wants an unbroken run from one sender, close together, with nothing from
    the other person in between to give the order away.
    """
    out = []
    for i in range(len(c.messages) - 3):
        run = c.messages[i:i + 3]
        if len({m["from"] for m in run}) != 1:
            continue
        if i and c.messages[i - 1]["from"] == run[0]["from"]:
            continue                          # start of the run, not the middle
        if not all(readable(m, 4, 20) for m in run):
            continue
        if (run[-1]["dt"] - run[0]["dt"]).total_seconds() > 240 or not clean(*run):
            continue

        def heat(m):
            t = m["text"]
            return (t.count("!") + t.count("?") + 3 * t.isupper()
                    + sum(1 for ch in t if ch.isupper()) / max(len(t), 1) * 4)

        h = [heat(m) for m in run]
        # Three consecutive messages are not an escalation unless they build.
        # Without this the generator returns any three texts in a row and the
        # order is unguessable, which is a worse round than no round.
        if h[-1] <= h[0]:
            continue
        out.append(candidate(c, run[0], "escalation",
                             (h[-1] - h[0]) + interestingness(run[0], freq),
                             run=[m["text"] for m in run], answer=0))
    return top(out, n)


def top(items, n):
    return sorted(items, key=lambda x: -x["score"])[:n]


# ── main ──────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="corpus.json")
    ap.add_argument("--out", default="candidates.json")
    ap.add_argument("--per", type=int, default=50, help="candidates per generator")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    if not os.path.exists(args.corpus):
        raise SystemExit(f"No corpus at {args.corpus} — run tools/extract.py first.")

    rng = random.Random(args.seed)
    with open(args.corpus, encoding="utf-8") as f:
        c = Corpus(json.load(f))
    pool = [m for m in c.messages if readable(m)]
    if len(pool) < 50:
        raise SystemExit(f"Only {len(pool)} usable messages — not enough to mine.")
    freq = Counter(w for m in c.messages for w in WORD_RE.findall(m["norm"]))

    gens = [
        ("who_said_it", g_who_said_it),
        ("fill_blank", g_fill_blank),
        ("finish_sentence", g_finish_sentence),
        ("unanswered", g_unanswered),
        ("callback", g_callback),
        ("whose_turn", g_whose_turn),
        ("escalation", g_escalation),
        ("fill_emoji", g_fill_emoji),
        ("reply", g_reply),
        ("datable", g_datable),
        ("longest", g_longest),
        ("compare_dates", g_compare_dates),
        ("complaint", lambda *a: g_lexical(*a, COMPLAINT, "complaint")),
        ("apology", lambda *a: g_lexical(*a, APOLOGY, "apology")),
    ]

    out: list[dict] = []
    print()
    for name, fn in gens:
        got = fn(c, pool, freq, rng, args.per)
        out.extend(got)
        print(f"  {len(got):>4}  {name}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"corpus": os.path.basename(args.corpus), "candidates": out},
                  f, ensure_ascii=False)
    print(f"\n  {len(out)} candidates -> {args.out}  (gitignored)")
    print(f"  {len(pool):,} of {len(c.messages):,} messages were usable\n")


if __name__ == "__main__":
    main()
