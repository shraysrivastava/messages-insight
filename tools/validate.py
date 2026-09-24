#!/usr/bin/env python3
"""
validate.py — check the authoring source, and any compiled dataset.

    python3 tools/validate.py                  lint questions/
    python3 tools/validate.py datasets/demo.json   also validate a dataset

compile.py already validates its output. This exists to catch mistakes at the
place you made them — a typo'd lexicon name, a duplicate id, an answer index
past the end of options — rather than as a resolver failure three steps later.

Exit code is non-zero if anything is wrong, so it drops straight into CI.
"""

from __future__ import annotations

import glob
import re
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from app.schema import Dataset
from tools.resolvers import RESOLVERS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDIR = os.path.join(ROOT, "questions")
G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"

TYPES = {"binary", "choice", "number", "month", "percent", "wager", "mutual"}
FORMATS = {"bubble", "blank", "redacted", "compare", "thread", "timestamp"}
STATUSES = {"ready", "draft", "mine"}
FIELDS = {"id", "topic", "type", "kind", "area", "format", "prompt", "text",
          "options", "answer", "reveal", "status", "unit", "source",
          "min_margin", "min_answer", "min_hits", "month_edge_pct", "mode",
          # curate.py bakes the surrounding thread into the block, and
          # Question.context carries it through to the reveal. It was missing
          # here, so every curated block with context linted as an error.
          "context"}

# One message inside a `context` array. Mirrors app.schema.ContextMsg — the
# field is `who`, not `from`, and getting that wrong passed this linter twice
# before compile.py rejected it a hundred and twenty times over.
CONTEXT_KEYS = {"who", "text", "self"}

SOURCE_KEYS = {"mine", "search", "first_message", "by", "before", "after",
               "lex", "hours", "blanks", "spread_months"}


def lint(qdir: str = QDIR) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []

    with open(os.path.join(qdir, "lexicons.toml"), "rb") as f:
        lexicons = tomllib.load(f)["lex"]
    lex_names = set(lexicons)

    # A lexicon whose `regex` doesn't compile takes compile.py down with a
    # PatternError three frames deep, and nothing upstream notices. Written
    # after fourteen of them were declared "clean" by this very function:
    # `regex` is a *list*, and a bare string iterates character by character.
    for name, body in lexicons.items():
        pats = body.get("regex")
        if pats is None:
            continue
        if isinstance(pats, str):
            errors.append(f"lexicons.toml:{name}: `regex` must be a list, "
                          f"not a bare string")
            continue
        for pat in pats:
            try:
                re.compile(pat)
            except re.error as e:
                errors.append(f"lexicons.toml:{name}: bad regex {pat!r} ({e})")

    files = [("mine", os.path.join(qdir, "mine.toml"))] + \
            [("auto", f) for f in sorted(glob.glob(os.path.join(qdir, "auto", "*.toml")))]

    seen_ids: dict[str, str] = {}
    kinds, areas, ready = Counter(), Counter(), 0

    for origin, path in files:
        if not os.path.exists(path):
            continue
        rel = os.path.relpath(path, ROOT)
        with open(path, "rb") as f:
            try:
                qs = tomllib.load(f).get("q", [])
            except Exception as e:
                errors.append(f"{rel}: unparseable — {e}")
                continue

        for q in qs:
            qid = q.get("id")
            where = f"{rel}:{qid or '<no id>'}"
            if not qid:
                errors.append(f"{where}: missing id")
                continue
            if qid in seen_ids:
                errors.append(f"{where}: duplicate id (also in {seen_ids[qid]})")
            seen_ids[qid] = rel

            unknown = set(q) - FIELDS - {"origin", "_file"}
            if unknown:
                errors.append(f"{where}: unknown field(s) {sorted(unknown)}")

            if q.get("type") not in TYPES:
                errors.append(f"{where}: bad type {q.get('type')!r}")
            if q.get("status", "ready") not in STATUSES:
                errors.append(f"{where}: bad status {q.get('status')!r}")
            if q.get("format", "bubble") not in FORMATS:
                errors.append(f"{where}: unknown format {q.get('format')!r}")
            for field in ("kind", "prompt", "reveal"):
                if not str(q.get(field, "")).strip():
                    errors.append(f"{where}: missing {field}")

            kinds[q.get("kind")] += 1
            if q.get("area"):
                areas[q["area"]] += 1
            if q.get("status", "ready") == "ready":
                ready += 1

            ans = q.get("answer")
            if isinstance(ans, dict):
                key = next((k for k in ans if k in RESOLVERS), None)
                if key is None:
                    errors.append(f"{where}: no known resolver in {sorted(ans)}")
                else:
                    ref = ans.get(key)
                    if isinstance(ref, str) and key in {
                            "count", "who_says_more", "first_use", "days_until",
                            "first_use_sender"}:
                        if ref not in lex_names:
                            errors.append(f"{where}: unknown lexicon {ref!r}")
                        elif lexicons[ref].get("status") == "draft":
                            warns.append(f"{where}: lexicon {ref!r} is still a draft")
                    # `within` scopes a month resolver to a lexicon;
                    # `within_seconds` is a duration. Distinct keys on purpose.
                    if "within" in ans and ans["within"] not in lex_names:
                        errors.append(f"{where}: unknown lexicon {ans['within']!r} in `within`")
                    if "within_seconds" in ans and not isinstance(
                            ans["within_seconds"], (int, float)):
                        errors.append(f"{where}: within_seconds must be a number")
            elif isinstance(ans, int) and q.get("options"):
                if not 0 <= ans < len(q["options"]):
                    errors.append(
                        f"{where}: answer {ans} out of range for "
                        f"{len(q['options'])} options")

            ctx = q.get("context")
            if ctx is not None:
                if not isinstance(ctx, list) or not ctx:
                    errors.append(f"{where}: `context` must be a non-empty list")
                else:
                    for row in ctx:
                        if not isinstance(row, dict):
                            errors.append(f"{where}: context rows must be tables")
                            break
                        bad = set(row) - CONTEXT_KEYS
                        if bad:
                            errors.append(f"{where}: context row has unknown "
                                          f"field(s) {sorted(bad)}")
                            break
                        if row.get("who") not in ("p1", "p2"):
                            errors.append(f"{where}: context row `who` must be "
                                          f"p1 or p2")
                            break

            src = q.get("source")
            if isinstance(src, dict):
                bad = set(src) - SOURCE_KEYS
                if bad:
                    errors.append(f"{where}: unknown source key(s) {sorted(bad)}")
                if src.get("lex") and src["lex"] not in lex_names:
                    errors.append(f"{where}: unknown lexicon {src['lex']!r} in source")

            opts = q.get("options")
            if opts is not None:
                if not 2 <= len(opts) <= 4:
                    errors.append(f"{where}: {len(opts)} options (needs 2-4)")
                if q.get("type") == "binary" and len(opts) != 2:
                    errors.append(f"{where}: binary needs exactly 2 options")

            if q.get("status") == "ready" and q.get("type") != "mutual" \
                    and ans is None and not src:
                errors.append(f"{where}: ready but has no answer or source")

    # bank-level health
    if kinds and max(kinds.values()) > ready * 0.35:
        top = kinds.most_common(1)[0]
        warns.append(f"kind {top[0]!r} is {top[1]} questions — the deck can't "
                     f"interleave if one label dominates")
    if len(kinds) < 10:
        warns.append(f"only {len(kinds)} distinct kinds; aim for 10+")

    return errors, warns


def main() -> None:
    errors, warns = lint()
    print(f"\n{B}questions/{X}")
    for e in errors:
        print(f"  {R}error{X}  {e}")
    for w in warns:
        print(f"  {Y}warn {X}  {w}")
    if not errors and not warns:
        print(f"  {G}clean{X}")
    elif not errors:
        print(f"  {G}no errors{X}")

    for path in sys.argv[1:]:
        print(f"\n{B}{path}{X}")
        try:
            with open(path, encoding="utf-8") as f:
                data = Dataset.model_validate_json(f.read())
            print(f"  {G}valid{X} — {len(data.questions)} questions, "
                  f"{len(data.meta.months)} months, "
                  f"yours {data.by_origin['mine']} / generated {data.by_origin['auto']}")
        except Exception as e:
            print(f"  {R}invalid{X}\n{e}")
            errors.append(path)

    print()
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
