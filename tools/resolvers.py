"""
resolvers.py — turn `answer = { count = "love_you" }` into a number.

Every resolver takes the corpus and its spec table and returns a Resolution:
a value, plus whatever extras the reveal template might want ({n1}, {winner},
{date}, {month}), plus generated options for the choice-shaped ones.

Adding a resolver is one function and one line in RESOLVERS. That is the
intended way to answer "can we do a question about X" — usually yes, in about
fifteen lines.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from tools.lexicon import EMOJI_RE, Lexicon, PhraseLex, RegexLex, normalise

STOPWORDS = set("""a about after all also am an and any are as at back be because been
before being but by can cant come could did didnt do dont down even for from get go
going good got had has have he her here hers him his how i if im in into is isnt it
its just know like ll me might more most much my no not now of off on one only or
other our out over re she should so some such than that thats the their them then
there these they this those to too up us ve very was way we well were what when
where which while who why will with would yeah yes yet you your youre u ur ok okay
oh lol haha ya na be got will got want need really think thing things time day""".split())

TYPO_HINTS = {"teh", "adn", "jsut", "taht", "waht", "hte", "recieve", "seperate",
              "definately", "alot", "youre", "thier", "wierd", "becuase", "freind"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HOUR_BUCKETS = [(5, 11, "Morning"), (11, 17, "Afternoon"),
                (17, 22, "Evening"), (22, 29, "Late night")]


@dataclass
class Resolution:
    value: Any = None
    extras: dict = field(default_factory=dict)
    options: list[str] | None = None
    text: str | None = None
    hits: int | None = None
    error: str | None = None
    # Index into corpus.messages of the message this answer came from, when
    # there is one. compile.py turns it into the context thread the reveal
    # shows — "the actual conversation from May 2023 where you said it"
    # (DESIGN 2.5). Resolvers that count rather than quote leave it None.
    source: int | None = None


class Corpus:
    """The extracted thread, with everything precomputed once."""

    def __init__(self, raw: dict):
        self.meta = raw["meta"]
        self.messages = raw["messages"]
        self.months: list[str] = self.meta["months"]
        self.density: list[int] = self.meta.get("density") or []
        self.month_ix = {m: i for i, m in enumerate(self.months)}
        for m in self.messages:
            m["norm"] = normalise(m["text"])
            m["dt"] = datetime.fromisoformat(m["ts"])
            m["words"] = len(m["text"].split())
        self.by = {
            "p1": [m for m in self.messages if m["from"] == "p1"],
            "p2": [m for m in self.messages if m["from"] == "p2"],
        }

    # helpers ---------------------------------------------------------------

    def month_of(self, m: dict) -> int:
        return self.month_ix[m["ts"][:7]]

    def side(self, who: str | None) -> list[dict]:
        return self.by[who] if who in ("p1", "p2") else self.messages

    def name(self, who: str) -> str:
        return self.meta["p1"] if who == "p1" else self.meta["p2"]

    def pretty(self, m: dict) -> str:
        return m["dt"].strftime("%B %-d, %Y")

    def pretty_month(self, ix: int) -> str:
        y, mo = self.months[ix].split("-")
        return datetime(int(y), int(mo), 1).strftime("%B %Y")


# ── lexicon plumbing ──────────────────────────────────────────────────────

def _lex(spec: dict, lexicons: dict[str, Lexicon], key: str) -> Lexicon | None:
    """Resolve whichever of the phrase-ish keys this spec used."""
    if key in ("count", "who_says_more", "first_use", "days_until",
               "first_use_sender", "within", "lex"):
        name = spec.get(key)
        return lexicons.get(name) if isinstance(name, str) else None
    if key == "count_phrase":
        return PhraseLex(spec[key])
    if key == "count_regex":
        return RegexLex(spec[key])
    if key == "count_emoji":
        return Lexicon("emoji", {"emoji": [spec[key]]})
    return None


def _matching(c: Corpus, lex: Lexicon, who: str | None = None) -> list[dict]:
    return [m for m in c.side(who) if lex.matches(m["norm"])]


def _count(c: Corpus, lex: Lexicon, who=None, mode="messages") -> int:
    ms = c.side(who)
    if mode == "occurrences":
        return sum(lex.hits(m["norm"]) for m in ms)
    return sum(1 for m in ms if lex.matches(m["norm"]))


# ── counting ──────────────────────────────────────────────────────────────

def r_count(c, spec, lex, key):
    if lex is None:
        return Resolution(error=f"unknown lexicon {spec.get(key)!r}")
    if lex.draft:
        return Resolution(error=f"lexicon {lex.name!r} still says TODO")
    n = _count(c, lex, spec.get("by"), spec.get("mode", "messages"))
    return Resolution(value=n, hits=n)


def r_total_messages(c, spec, *_):
    return Resolution(value=len(c.messages), hits=len(c.messages))


def r_distinct_emoji(c, spec, *_):
    seen = {e for m in c.messages for e in EMOJI_RE.findall(m["norm"])}
    return Resolution(value=len(seen), hits=len(seen))


def r_attachments(c, spec, *_):
    n = sum(1 for m in c.messages if m.get("att"))
    return Resolution(value=n, hits=n)


def r_messages_between(c, spec, *_):
    lo, hi = spec["messages_between"]
    n = sum(1 for m in c.messages if lo <= m["dt"].hour < hi)
    return Resolution(value=n, hits=n)


def r_longest_message_words(c, spec, *_):
    best = max(c.messages, key=lambda m: m["words"])
    return Resolution(value=best["words"], hits=1,
                      extras={"date": c.pretty(best)}, text=best["text"],
                      source=best.get("i"))


def r_longest_gap_hours(c, spec, *_):
    best, when = 0.0, None
    for a, b in zip(c.messages, c.messages[1:]):
        gap = (b["dt"] - a["dt"]).total_seconds() / 3600
        if gap > best:
            best, when = gap, a
    return Resolution(value=round(best), hits=1,
                      extras={"date": c.pretty(when)} if when else {})


def r_max_day_count(c, spec, *_):
    days = Counter(m["ts"][:10] for m in c.messages)
    day, n = days.most_common(1)[0]
    return Resolution(value=n, hits=n,
                      extras={"date": datetime.fromisoformat(day).strftime("%B %-d, %Y")})


def r_longest_streak_days(c, spec, *_):
    days = sorted({m["ts"][:10] for m in c.messages})
    best = run = 1
    for a, b in zip(days, days[1:]):
        da, db = datetime.fromisoformat(a), datetime.fromisoformat(b)
        run = run + 1 if db - da == timedelta(days=1) else 1
        best = max(best, run)
    return Resolution(value=best, hits=best)


def r_avg_per_day(c, spec, *_):
    days = len({m["ts"][:10] for m in c.messages})
    return Resolution(value=round(len(c.messages) / max(days, 1)), hits=len(c.messages))


def r_question_count(c, spec, *_):
    ms = c.side(spec.get("by"))
    n = sum(1 for m in ms if "?" in m["text"])
    return Resolution(value=n, hits=n)


def r_days_until(c, spec, lex, key):
    if lex is None or lex.draft:
        return Resolution(error=f"unusable lexicon {spec.get(key)!r}")
    hits = _matching(c, lex, spec.get("by"))
    if not hits:
        return Resolution(error=f"no messages match {lex.name!r}")
    delta = hits[0]["dt"] - c.messages[0]["dt"]
    return Resolution(value=delta.days, hits=len(hits),
                      extras={"date": c.pretty(hits[0])}, text=hits[0]["text"],
                      source=hits[0].get("i"))


# ── percentages ───────────────────────────────────────────────────────────

def _pct(n, d):
    return round(100 * n / d) if d else 0


def r_share_of_messages(c, spec, *_):
    who = spec["share_of_messages"]
    return Resolution(value=_pct(len(c.by[who]), len(c.messages)), hits=len(c.messages))


def r_share_between(c, spec, *_):
    lo, hi = spec["share_between"]
    n = sum(1 for m in c.messages if lo <= m["dt"].hour < hi)
    return Resolution(value=_pct(n, len(c.messages)), hits=n)


def r_share_with_emoji(c, spec, *_):
    n = sum(1 for m in c.messages if EMOJI_RE.search(m["norm"]))
    return Resolution(value=_pct(n, len(c.messages)), hits=n)


def r_share_one_word(c, spec, *_):
    n = sum(1 for m in c.messages if m["words"] == 1)
    return Resolution(value=_pct(n, len(c.messages)), hits=n)


def r_share_questions(c, spec, *_):
    n = sum(1 for m in c.messages if "?" in m["text"])
    return Resolution(value=_pct(n, len(c.messages)), hits=n)


def r_share_weekend(c, spec, *_):
    n = sum(1 for m in c.messages if m["dt"].weekday() >= 5)
    return Resolution(value=_pct(n, len(c.messages)), hits=n)


def r_share_days_covered(c, spec, *_):
    days = {m["ts"][:10] for m in c.messages}
    span = (c.messages[-1]["dt"].date() - c.messages[0]["dt"].date()).days + 1
    return Resolution(value=_pct(len(days), span), hits=len(days))


def r_share_quick_reply(c, spec, *_):
    who = spec.get("by", "p2")
    within = spec.get("within_seconds", 60)
    other = "p1" if who == "p2" else "p2"
    asked = replied = 0
    for a, b in zip(c.messages, c.messages[1:]):
        if a["from"] == other:
            asked += 1
            if b["from"] == who and (b["dt"] - a["dt"]).total_seconds() <= within:
                replied += 1
    return Resolution(value=_pct(replied, asked), hits=replied)


# ── months ────────────────────────────────────────────────────────────────

def r_first_use(c, spec, lex, key):
    if lex is None or lex.draft:
        return Resolution(error=f"unusable lexicon {spec.get(key)!r}")
    hits = _matching(c, lex, spec.get("by"))
    if not hits:
        return Resolution(error=f"no messages match {lex.name!r}")
    first = hits[0]
    ix = c.month_of(first)
    return Resolution(
        value=ix, hits=len(hits), text=first["text"], source=first.get("i"),
        extras={"date": c.pretty(first), "month": c.pretty_month(ix),
                "winner": c.name(first["from"])},
    )


def r_first_use_sender(c, spec, lex, key):
    res = r_first_use(c, spec, lex, key)
    if res.error:
        return res
    hits = _matching(c, lex, spec.get("by"))
    who = hits[0]["from"]
    res.value = 0 if who == "p1" else 1
    res.extras["winner"] = c.name(who)
    res.extras["loser"] = c.name("p2" if who == "p1" else "p1")
    return res


def _month_counts(c, lexicons, spec):
    within = spec.get("within")
    if within:
        lex = lexicons.get(within)
        if lex is None or lex.draft:
            return None
        counts = [0] * len(c.months)
        for m in _matching(c, lex):
            counts[c.month_of(m)] += 1
        return counts
    return list(c.density) or [0] * len(c.months)


def _edge_safe(c, counts, pick):
    """Ignore months outside the thread's real span when picking a minimum."""
    return pick


def r_busiest_month(c, spec, lexicons):
    counts = _month_counts(c, lexicons, spec)
    if counts is None or not any(counts):
        return Resolution(error=f"no messages match {spec.get('within')!r}")
    ix = counts.index(max(counts))
    return Resolution(value=ix, hits=max(counts),
                      extras={"month": c.pretty_month(ix)})


def r_quietest_month(c, spec, lexicons):
    counts = _month_counts(c, lexicons, spec)
    if counts is None:
        return Resolution(error="no data")
    # Only consider months inside the thread; a month with zero messages at the
    # very start or end is an artefact of the range, not a quiet month.
    inner = list(enumerate(counts))[1:-1] or list(enumerate(counts))
    ix = min(inner, key=lambda kv: kv[1])[0]
    return Resolution(value=ix, hits=counts[ix] or 1,
                      extras={"month": c.pretty_month(ix)})


# ── binary comparisons ────────────────────────────────────────────────────

def _binary(c, n1: int, n2: int) -> Resolution:
    win = "p1" if n1 >= n2 else "p2"
    return Resolution(
        value=0 if win == "p1" else 1,
        hits=n1 + n2,
        extras={"n1": max(n1, n2), "n2": min(n1, n2),
                "winner": c.name(win),
                "loser": c.name("p2" if win == "p1" else "p1"),
                "_margin": (max(n1, n2) / max(min(n1, n2), 1))},
    )


def r_who_says_more(c, spec, lex, key):
    if lex is None:
        return Resolution(error=f"unknown lexicon {spec.get(key)!r}")
    if lex.draft:
        return Resolution(error=f"lexicon {lex.name!r} still says TODO")
    return _binary(c, _count(c, lex, "p1"), _count(c, lex, "p2"))


def _emoji_count(ms):
    return sum(len(EMOJI_RE.findall(m["norm"])) for m in ms)


def _double_texts(ms_all, who):
    n = 0
    for a, b in zip(ms_all, ms_all[1:]):
        if a["from"] == who and b["from"] == who and \
                (b["dt"] - a["dt"]).total_seconds() > 300:
            n += 1
    return n


def _reply_gap_max(ms_all, who):
    best = 0.0
    for a, b in zip(ms_all, ms_all[1:]):
        if a["from"] != who and b["from"] == who:
            best = max(best, (b["dt"] - a["dt"]).total_seconds() / 3600)
    return round(best)


def _day_edges(ms_all, first=True):
    out = Counter()
    seen = {}
    for m in ms_all:
        d = m["ts"][:10]
        if first:
            if d not in seen:
                seen[d] = True
                out[m["from"]] += 1
        else:
            seen[d] = m["from"]
    if not first:
        out = Counter(seen.values())
    return out


def _typos(ms):
    n = 0
    for m in ms:
        words = m["norm"].split()
        if any(w in TYPO_HINTS for w in words) or \
                any(re.search(r"(.)\1{2,}", w) for w in words):
            n += 1
    return n


def r_who_more(c, spec, *_):
    kind = spec["who_more"]
    a, b = c.by["p1"], c.by["p2"]
    if kind == "more_emoji":
        return _binary(c, _emoji_count(a), _emoji_count(b))
    if kind == "all_caps":
        f = lambda ms: sum(1 for m in ms if len(m["text"]) > 3 and m["text"].isupper())
        return _binary(c, f(a), f(b))
    if kind == "exclamations":
        f = lambda ms: sum(m["text"].count("!") for m in ms)
        return _binary(c, f(a), f(b))
    if kind == "one_word_replies":
        f = lambda ms: sum(1 for m in ms if m["words"] == 1)
        return _binary(c, f(a), f(b))
    if kind == "more_questions":
        f = lambda ms: sum(1 for m in ms if "?" in m["text"])
        return _binary(c, f(a), f(b))
    if kind == "longer_messages":
        f = lambda ms: round(sum(m["words"] for m in ms) / max(len(ms), 1))
        return _binary(c, f(a), f(b))
    if kind == "double_texts":
        return _binary(c, _double_texts(c.messages, "p1"), _double_texts(c.messages, "p2"))
    if kind == "left_on_read":
        return _binary(c, _reply_gap_max(c.messages, "p1"), _reply_gap_max(c.messages, "p2"))
    if kind == "first_message_of_day":
        cnt = _day_edges(c.messages, first=True)
        return _binary(c, cnt["p1"], cnt["p2"])
    if kind == "last_message_of_day":
        cnt = _day_edges(c.messages, first=False)
        return _binary(c, cnt["p1"], cnt["p2"])
    if kind == "typos":
        return _binary(c, _typos(a), _typos(b))
    return Resolution(error=f"unknown who_more kind {kind!r}")


# ── choice generators ─────────────────────────────────────────────────────

def r_top_emoji(c, spec, *_):
    n = int(spec["top_emoji"])
    counts = Counter(e for m in c.messages for e in EMOJI_RE.findall(m["norm"]))
    if len(counts) < n:
        return Resolution(error="not enough distinct emoji")
    top = [e for e, _ in counts.most_common(n)]
    return Resolution(value=0, options=top, hits=counts[top[0]],
                      extras={"answer": top[0]})


def r_top_word(c, spec, *_):
    n = int(spec["top_word"])
    counts = Counter(w for m in c.messages for w in m["norm"].split()
                     if w not in STOPWORDS and len(w) > 3 and w.isalpha())
    common = [w for w, _ in counts.most_common(60)]
    if len(common) < n:
        return Resolution(error="not enough vocabulary")
    # Distractors from adjacent frequency bands: plausible, not eliminable.
    picks = [common[0]] + common[6:6 + n - 1]
    return Resolution(value=0, options=picks, hits=counts[common[0]],
                      extras={"answer": common[0]})


def r_busiest_weekday(c, spec, *_):
    counts = Counter(m["dt"].weekday() for m in c.messages)
    best = counts.most_common(1)[0][0]
    others = [d for d, _ in counts.most_common()[1:4]]
    days = [WEEKDAYS[best]] + [WEEKDAYS[d] for d in others]
    return Resolution(value=0, options=days, hits=counts[best],
                      extras={"answer": WEEKDAYS[best]})


def r_peak_hour(c, spec, *_):
    counts = Counter()
    for m in c.messages:
        h = m["dt"].hour
        for lo, hi, label in HOUR_BUCKETS:
            if lo <= (h if h >= 5 else h + 24) < hi:
                counts[label] += 1
                break
    if len(counts) < 2:
        return Resolution(error="not enough spread across the day")
    labels = [l for l, _ in counts.most_common()]
    return Resolution(value=0, options=labels[:4], hits=counts[labels[0]],
                      extras={"answer": labels[0]})


def r_busiest_year(c, spec, *_):
    counts = Counter(m["ts"][:4] for m in c.messages)
    order = [y for y, _ in counts.most_common()]
    if len(order) < 2:
        return Resolution(error="thread spans one year")
    opts = [order[0]] + sorted(y for y in order[1:4])
    return Resolution(value=0, options=opts, hits=counts[order[0]],
                      extras={"answer": order[0]})


RESOLVERS: dict[str, Callable] = {
    "count": r_count, "count_phrase": r_count, "count_regex": r_count,
    "count_emoji": r_count,
    "total_messages": r_total_messages, "distinct_emoji": r_distinct_emoji,
    "attachments": r_attachments, "messages_between": r_messages_between,
    "longest_message_words": r_longest_message_words,
    "longest_gap_hours": r_longest_gap_hours, "max_day_count": r_max_day_count,
    "longest_streak_days": r_longest_streak_days, "avg_per_day": r_avg_per_day,
    "question_count": r_question_count, "days_until": r_days_until,
    "share_of_messages": r_share_of_messages, "share_between": r_share_between,
    "share_with_emoji": r_share_with_emoji, "share_one_word": r_share_one_word,
    "share_questions": r_share_questions, "share_weekend": r_share_weekend,
    "share_days_covered": r_share_days_covered,
    "share_quick_reply": r_share_quick_reply,
    "first_use": r_first_use, "first_use_sender": r_first_use_sender,
    "busiest_month": r_busiest_month, "quietest_month": r_quietest_month,
    "who_says_more": r_who_says_more, "who_more": r_who_more,
    "top_emoji": r_top_emoji, "top_word": r_top_word,
    "busiest_weekday": r_busiest_weekday, "peak_hour": r_peak_hour,
    "busiest_year": r_busiest_year,
}

# Resolvers that want the whole lexicon table rather than one lexicon.
WANTS_TABLE = {"busiest_month", "quietest_month"}

# Resolvers whose answer is read straight off `meta.density` — the same array
# the month slider draws as a histogram (PLAN S3.1). Drawing the picture next
# to the question would be handing over the answer, so compile.py turns the
# histogram off for exactly these. It happens to be the same set as
# WANTS_TABLE today; it is written out separately because it is a different
# fact about them, and the two will drift.
FROM_DENSITY = {"busiest_month", "quietest_month"}

# Resolvers whose spec key names a lexicon or phrase.
WANTS_LEX = {"count", "count_phrase", "count_regex", "count_emoji",
             "who_says_more", "first_use", "first_use_sender", "days_until"}


def resolve(corpus: Corpus, spec: dict, lexicons: dict[str, Lexicon]) -> Resolution:
    """Dispatch on whichever key in the spec names a resolver."""
    key = next((k for k in spec if k in RESOLVERS), None)
    if key is None:
        return Resolution(error=f"no resolver in {sorted(spec)}")
    fn = RESOLVERS[key]
    try:
        if key in WANTS_TABLE:
            return fn(corpus, spec, lexicons)
        if key in WANTS_LEX:
            return fn(corpus, spec, _lex(spec, lexicons, key), key)
        return fn(corpus, spec)
    except Exception as e:            # a bad resolver must not kill the build
        return Resolution(error=f"{type(e).__name__}: {e}")
