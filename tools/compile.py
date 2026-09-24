#!/usr/bin/env python3
"""
compile.py — questions/ + corpus.json -> a validated dataset.

    python3 tools/compile.py --corpus corpus.json --out datasets/real.json
    python3 tools/compile.py --corpus demo_corpus.json --out datasets/demo.json

What it does, in order:

  merge      mine.toml then auto/*.toml. Provenance is the directory.
  resolve    computed answers against the corpus, through the lexicons.
  render     {p1}, {answer:,}, {winner}, {date} and friends.
  dedup      a question of yours kills any generated one on the same topic.
  guard      drop anything that isn't actually answerable — see [guards].
  filter     drop types the clients can't render yet.
  validate   against app/schema.py, and fail loudly.

Nothing is dropped silently except an auto/ question losing to one of yours.
Everything else is reported with a reason.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tomllib
except ModuleNotFoundError:                     # py < 3.11
    import tomli as tomllib

from app.game import PLAYABLE
from app.schema import Dataset
from tools.lexicon import load_lexicons
from tools.resolvers import FROM_DENSITY, RESOLVERS, Corpus, resolve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEXED = {"binary", "choice", "wager", "mutual"}

G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


class Report:
    def __init__(self):
        self.dropped: dict[str, list[str]] = defaultdict(list)
        self.warnings: list[str] = []

    def drop(self, reason: str, qid: str, detail: str = ""):
        self.dropped[reason].append(f"{qid}{(' — ' + detail) if detail else ''}")

    def warn(self, msg: str):
        self.warnings.append(msg)


# ── loading ───────────────────────────────────────────────────────────────

def load_questions(qdir: str, include_mine: bool = True) -> list[dict]:
    """Every question block under `qdir`. Provenance is the directory.

    `include_mine=False` builds from `auto/` alone. That is what the demo
    dataset needs: `mine.toml` holds messages `curate.py` lifted verbatim out
    of the real thread, and `datasets/demo.json` is committed and handed to
    anyone. A demo built from the fake corpus is still not safe if it carries
    three real messages through the question bank (CLAUDE.md, Privacy).
    """
    out = []
    mine = os.path.join(qdir, "mine.toml")
    files = ([("mine", mine)] if include_mine and os.path.exists(mine) else []) + \
            [("auto", f) for f in sorted(glob.glob(os.path.join(qdir, "auto", "*.toml")))]
    for origin, path in files:
        with open(path, "rb") as f:
            for q in tomllib.load(f).get("q", []):
                q["origin"] = origin
                q["_file"] = os.path.relpath(path, ROOT)
                q.setdefault("topic", q.get("id"))
                out.append(q)
    return out


# ── templating ────────────────────────────────────────────────────────────

def render(text: str, ctx: dict, qid: str) -> str:
    """Format with a clear error rather than a KeyError three frames deep."""
    try:
        return text.format(**ctx)
    except KeyError as e:
        raise ValueError(f"{qid}: unknown template var {e}") from None
    except (ValueError, TypeError) as e:
        raise ValueError(f"{qid}: bad template ({e})") from None


def thread_around(corpus, i: int | None, span: int = 2) -> list[dict] | None:
    """The messages either side of the one a question came from.

    Only for questions the corpus can point at — a count has no source message
    and gets nothing, which is right: there is no conversation to show. The
    text is copied verbatim and never rendered as a template, because real
    messages contain braces and `{` is not a template var just because someone
    typed it at 2am.
    """
    if i is None:
        return None
    msgs = getattr(corpus, "messages", None)
    if not msgs or not (0 <= i < len(msgs)):
        return None
    lo, hi = max(0, i - span), min(len(msgs), i + span + 1)
    out = []
    for m in msgs[lo:hi]:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        out.append({"who": m["from"], "text": text, "self": m.get("i") == i})
    # One message on its own is not a thread, it is the bubble that is already
    # on screen.
    return out if len(out) > 1 else None


def shows_histogram(q: dict, spec: dict | None) -> bool:
    """Whether the month slider may draw `meta.density` behind this question.

    It may not when the answer *is* the density array — "which month did we
    text the least?" is free if the picture is on screen. The resolver is the
    signal, not the wording: `resolvers.FROM_DENSITY` names the ones that read
    the table. An author can also just say `histogram = false`.
    """
    if q.get("histogram") is False:
        return False
    if q.get("type") != "month" or not spec:
        return True
    key = next((k for k in spec if k in RESOLVERS), None)
    if key not in FROM_DENSITY:
        return True
    # `within` narrows the count to one lexicon — the busiest month *for work
    # stress* is not the busiest month, and the whole-thread picture does not
    # answer it. Only the unfiltered form reads `meta.density` itself.
    return bool(spec.get("within"))


def build_context(meta: dict, res, q: dict, options: list[str] | None) -> dict:
    """Template vars available to every prompt, text and reveal."""
    ctx = {
        "p1": meta["p1"],
        "p2": meta["p2"],
        "total": meta.get("total", 0),
        "years": max(1, round(len(meta.get("months", [])) / 12)),
        "months_n": len(meta.get("months", [])),
        "answer": "",
        "n1": "", "n2": "", "winner": "", "loser": "",
        "date": "", "month": "",
    }
    if res is not None:
        ctx.update({k: v for k, v in res.extras.items() if not k.startswith("_")})
        if "answer" not in res.extras:
            if q["type"] in INDEXED and options and isinstance(res.value, int):
                ctx["answer"] = options[res.value] if res.value < len(options) else ""
            elif res.value is not None:
                ctx["answer"] = res.value
    return ctx


# ── guards ────────────────────────────────────────────────────────────────

def guard(q: dict, res, cfg: dict, months: int, rep: Report) -> bool:
    g = cfg.get("guards", {})
    qid = q["id"]
    t = q["type"]

    if g.get("require_reveal", True) and "TODO" in (
            q.get("reveal", "") + q.get("prompt", "") + (q.get("text") or "")):
        rep.drop("still has a TODO in it", qid)
        return False

    min_hits = q.get("min_hits", g.get("min_hits", 3))
    if res is not None and res.hits is not None and res.hits < min_hits:
        rep.drop("too few matches in the thread", qid, f"{res.hits} hits")
        return False

    if res is not None and "_margin" in res.extras:
        need = q.get("min_margin", g.get("min_margin", 1.25))
        if res.extras["_margin"] < need:
            rep.drop("too close to call (coin flip)", qid,
                     f"{res.extras['n1']} vs {res.extras['n2']}")
            return False

    if t == "number":
        need = q.get("min_answer", g.get("min_answer", 20))
        if isinstance(q.get("answer"), (int, float)) and q["answer"] < need:
            rep.drop("number too small to score fairly", qid, f"answer={q['answer']}")
            return False

    if t == "month":
        edge = q.get("month_edge_pct", g.get("month_edge_pct", 0.10))
        lo, hi = months * edge, months * (1 - edge)
        if not lo <= q["answer"] <= hi:
            rep.drop("month answer is guessable from the slider range", qid,
                     f"index {q['answer']} of {months}")
            return False

    return True


# ── the pipeline ──────────────────────────────────────────────────────────

def compile_dataset(corpus_path: str, qdir: str, playable: set[str], rep: Report,
                    names: tuple[str | None, str | None] = (None, None),
                    include_mine: bool = True):
    with open(os.path.join(qdir, "config.toml"), "rb") as f:
        cfg = tomllib.load(f)
    with open(os.path.join(qdir, "lexicons.toml"), "rb") as f:
        lexicons = load_lexicons(tomllib.load(f)["lex"])
    with open(corpus_path, encoding="utf-8") as f:
        corpus = Corpus(json.load(f))

    meta_cfg = cfg.get("meta", {})
    meta = dict(corpus.meta)

    def _name(key: str, override: str | None, fallback: str) -> str:
        """Precedence: --p1/--p2 flag, then config.toml, then whatever the
        corpus recorded at extraction. A config value of TODO counts as unset,
        so a throwaway test thread compiles without editing config."""
        if override:
            return override
        v = str(meta_cfg.get(key, "")).strip()
        return fallback if not v or v.upper() == "TODO" else v

    meta["p1"] = _name("p1", names[0], meta["p1"])
    meta["p2"] = _name("p2", names[1], meta["p2"])
    # Resolvers render {winner}/{loser} from the corpus object, so the override
    # has to reach it too — otherwise reveals say "Me" instead of your name.
    corpus.meta["p1"], corpus.meta["p2"] = meta["p1"], meta["p2"]
    meta["rounds"] = meta_cfg.get("rounds", 14)
    meta["seconds"] = float(meta_cfg.get("seconds", 25))
    meta.pop("first_ts", None)
    meta.pop("last_ts", None)

    raw = load_questions(qdir, include_mine=include_mine)
    built: list[dict] = []

    for q in raw:
        qid = q.get("id", "?")
        status = q.get("status", "ready")

        if status == "mine":
            rep.drop("waiting on curate.py to fill in a message", qid)
            continue
        if status != "ready":
            rep.drop("still a draft", qid)
            continue
        if q["type"] not in playable:
            rep.drop(f"type not built yet ({q['type']})", qid)
            continue

        res = None
        spec = q.get("answer") if isinstance(q.get("answer"), dict) else None
        src = q.get("source") if isinstance(q.get("source"), dict) else None

        if src and "mine" in src:
            rep.drop("waiting on curate.py to fill in a message", qid)
            continue

        if spec:
            res = resolve(corpus, spec, lexicons)
        elif src:
            res = resolve_source(corpus, src, lexicons)
        if res is not None and res.error:
            rep.drop("could not resolve", qid, res.error)
            continue

        options = q.get("options")
        resolver_options = False
        ctx = build_context(meta, res, q, options)
        try:
            out = {
                "id": qid,
                "type": q["type"],
                "kind": q["kind"],
                "prompt": render(q["prompt"], ctx, qid),
                "reveal": render(q["reveal"], ctx, qid),
                "origin": q["origin"],
                "topic": q.get("topic", qid),
                "area": q.get("area"),
                "format": q.get("format", "bubble"),
            }
            if options:
                out["options"] = [render(o, ctx, qid) for o in options]
            elif res is not None and res.options:
                out["options"] = list(res.options)
                resolver_options = True
            if q.get("text"):
                out["text"] = render(q["text"], ctx, qid)
            elif res is not None and res.text:
                out["text"] = res.text
            if q.get("unit"):
                out["unit"] = q["unit"]
            if not shows_histogram(q, spec):
                out["histogram"] = False
            ctx = q.get("context") or (
                thread_around(corpus, res.source) if res is not None else None)
            if ctx:
                out["context"] = ctx
            out["answer"] = None if q["type"] == "mutual" else (
                res.value if res is not None else q.get("answer"))
            if resolver_options:
                shuffle_options(out, qid)
        except ValueError as e:
            rep.drop("template error", qid, str(e))
            continue

        if not guard(out, res, cfg, len(meta["months"]), rep):
            continue
        built.append(out)

    built = dedupe(built, cfg, rep)
    return meta, built


def resolve_source(corpus: Corpus, src: dict, lexicons):
    """`source` picks a real message into `text` rather than computing a number."""
    from tools.resolvers import Resolution

    if src.get("first_message"):
        m = corpus.messages[0]
    elif "search" in src:
        from tools.lexicon import PhraseLex
        lex = PhraseLex(src["search"])
        pool = corpus.side(src.get("by"))
        hit = next((x for x in pool if lex.matches(x["norm"])), None)
        if hit is None:
            return Resolution(error=f"no message matching {src['search']!r}")
        m = hit
    else:
        return Resolution(error=f"unsupported source {sorted(src)}")

    ix = corpus.month_of(m)
    return Resolution(
        value=0 if m["from"] == "p1" else 1,
        hits=1, text=m["text"],
        extras={"date": corpus.pretty(m), "month": corpus.pretty_month(ix),
                "winner": corpus.name(m["from"]),
                "loser": corpus.name("p2" if m["from"] == "p1" else "p1")},
    )


def shuffle_options(out: dict, qid: str) -> None:
    """Resolver-built options arrive in rank order with the answer at index 0.

    `top_emoji`, `top_word`, `busiest_weekday` and `peak_hour` all return
    `most_common(n)` and `value=0`, so before this existed *every* `choice`
    question in the compiled dataset answered to option A. One player noticing
    that wins every one of those rounds for the rest of the night.

    Seeded by question id, so the order is stable across recompiles — a
    question doesn't silently change shape between the audit pass and the
    game. Authored options are never touched: a binary's `["{p1}", "{p2}"]`
    means option 0 *is* p1, and the resolvers encode the winner that way.
    """
    opts = out.get("options")
    if not opts or not isinstance(out.get("answer"), int):
        return
    order = list(range(len(opts)))
    random.Random(qid).shuffle(order)
    out["options"] = [opts[i] for i in order]
    out["answer"] = order.index(out["answer"])


def dedupe(qs: list[dict], cfg: dict, rep: Report) -> list[dict]:
    """Yours beat generated ones on the same topic. Silently, by design — the
    whole point is that you never have to go audit auto/."""
    policy = cfg.get("dedup", {})
    mine_topics = {q["topic"] for q in qs if q["origin"] == "mine"}

    seen_mine: dict[str, str] = {}
    for q in qs:
        if q["origin"] != "mine":
            continue
        if q["topic"] in seen_mine and policy.get("mine_collision", "error") == "error":
            raise SystemExit(
                f"{R}Two of your own questions share topic {q['topic']!r}: "
                f"{seen_mine[q['topic']]} and {q['id']}{X}"
            )
        seen_mine[q["topic"]] = q["id"]

    kept = []
    for q in qs:
        if q["origin"] == "auto" and q["topic"] in mine_topics:
            continue                       # yours wins; not reported as a problem
        kept.append(q)

    # Fuzzy overlap is reported, never auto-dropped — too easy to lose something.
    # Compare the prompt *and* the bubble: curate.py mints a dozen questions
    # that all ask "Who sent this?" about a different message, and they are not
    # duplicates of each other in any sense worth a warning.
    def sig(q: dict) -> str:
        return q["prompt"] + "\n" + (q.get("text") or "")

    thresh = float(policy.get("fuzzy_threshold", 0.82))
    for i, a in enumerate(kept):
        for b in kept[i + 1:]:
            if a["origin"] == b["origin"] == "auto":
                continue
            ratio = difflib.SequenceMatcher(None, sig(a), sig(b)).ratio()
            if ratio >= thresh:
                rep.warn(f"{a['id']} and {b['id']} look alike ({ratio:.0%}) — "
                         f"set the same `topic` on yours to replace it")
    return kept


# ── dev mode ──────────────────────────────────────────────────────────────

REVEAL_MASK = "— answer hidden · dev mode —"


def blind(questions: list[dict], months: int, seed: int = 0) -> list[dict]:
    """Strip every answer out of a compiled dataset, keeping the questions.

    This is the audit surface. The question set is *identical* to the real
    one — same ids, same order, same prompts, same bubbles — so a question can
    be discussed by its number and cut by its id. What changes is that nothing
    downstream of the guess survives.

    The replacement answer is drawn uniformly at random from the valid range,
    **ignoring the real one entirely**. That is deliberate and it is the whole
    guarantee: a uniform draw carries zero information about the value it
    replaced, so no amount of staring at `dev.json` — or at this function —
    tells you anything about the real thread. Sometimes it will coincide with
    the truth. You cannot know when, which is the point.

    Also dropped: `reveal` (it states the answer in words), `context` (the
    surrounding thread shows who was talking), and `histogram` (the density
    curve behind the month slider narrows the answer on sight).
    """
    rng = random.Random(seed)
    out = []
    for q in questions:
        d = dict(q)
        t = d["type"]
        if t == "mutual":
            pass                                   # no answer to hide
        elif t in ("binary", "choice", "wager"):
            d["answer"] = rng.randrange(len(d.get("options") or [0, 1]))
        elif t == "percent":
            d["answer"] = rng.randrange(0, 101)
        elif t == "month":
            d["answer"] = rng.randrange(months)
        elif t == "number":
            # A flat range, not one scaled off the real value. The player types
            # a free number — nothing in the UI is sized from the answer — so
            # there is no reason to preserve its magnitude, and preserving it
            # would hand over the single most useful hint a count has.
            d["answer"] = rng.randrange(20, 10000)
        d["reveal"] = REVEAL_MASK
        d.pop("context", None)
        d["histogram"] = False
        out.append(d)
    return out


# ── output ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="corpus.json")
    ap.add_argument("--questions", default=os.path.join(ROOT, "questions"))
    ap.add_argument("--out", default="datasets/real.json")
    ap.add_argument("--types", help="override the playable set, comma separated")
    ap.add_argument("--p1", help="override the player names (else config.toml, else corpus)")
    ap.add_argument("--p2")
    ap.add_argument("--verbose", action="store_true", help="list every dropped question")
    ap.add_argument("--dev", action="store_true",
                    help="blind the answers — same questions, no reveals. This is the dataset you audit; see blind().")
    ap.add_argument("--no-mine", action="store_true",
                    help="build from auto/ only — what the committed demo "
                         "dataset uses, so no curated message can reach it")
    args = ap.parse_args()

    if not os.path.exists(args.corpus):
        raise SystemExit(
            f"No corpus at {args.corpus}\n"
            "Run tools/extract.py for the real thing, or "
            "tools/make_demo_corpus.py for a safe fake one."
        )

    playable = set(args.types.split(",")) if args.types else set(PLAYABLE)
    rep = Report()
    meta, questions = compile_dataset(args.corpus, args.questions, playable, rep,
                                      names=(args.p1, args.p2),
                                      include_mine=not args.no_mine)

    if args.dev:
        questions = blind(questions, len(meta["months"]))

    try:
        data = Dataset.model_validate({"meta": meta, "questions": questions})
    except Exception as e:
        print(f"\n{R}Validation failed.{X}\n{e}\n")
        raise SystemExit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    # by_alias so ContextMsg's `self` is spelled the way the reveal reads it;
    # it is the only aliased field in the schema.
    payload = data.model_dump(exclude_none=True, by_alias=True)
    for q in payload["questions"]:
        # Only the exception travels. `histogram` is true for all but a couple
        # of month questions, and writing it 120 times makes every recompile a
        # hundred-line diff on a file that is in git.
        if q.get("histogram") is True:
            q.pop("histogram")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    # ── report ──
    qs = data.questions
    print(f"\n{B}{len(qs)} questions{X} -> {args.out}")
    origin = Counter(q.origin for q in qs)
    print(f"  {B}yours {origin['mine']}{X}   generated {origin['auto']}   "
          f"{len(set(q.kind for q in qs))} kinds   "
          f"{len(set(q.area for q in qs if q.area))} areas")
    print("  types  " + "  ".join(f"{k} {v}" for k, v in
                                  sorted(Counter(q.type for q in qs).items())))

    if rep.dropped:
        total = sum(len(v) for v in rep.dropped.values())
        print(f"\n{D}dropped {total}:{X}")
        for reason, ids in sorted(rep.dropped.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(ids):>3}  {reason}")
            if args.verbose:
                for i in ids:
                    print(f"       {D}{i}{X}")
    # month questions only: `--dev` clears the histogram on everything, and
    # reporting "hidden on 148 month questions" out of 148 total was nonsense.
    hidden = [q.id for q in qs if q.type == "month" and not q.histogram]
    if hidden:
        print(f"  {D}histogram hidden on {len(hidden)} month question"
              f"{'s' if len(hidden) > 1 else ''} the slider would answer{X}")

    if rep.warnings:
        print(f"\n{Y}warnings:{X}")
        for w in rep.warnings[:10]:
            print(f"  {w}")

    need = meta["rounds"]
    if len(qs) < need * 3:
        print(f"\n{Y}  {len(qs)} questions for {need}-round games — "
              f"replays will repeat. Aim for {need * 3}+.{X}")
    print()


if __name__ == "__main__":
    main()
