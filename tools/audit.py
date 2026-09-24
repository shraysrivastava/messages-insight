#!/usr/bin/env python3
"""
audit.py — read the whole deck as text, with no answers in it.

    make questions                 every question, grouped by kind
    make questions ARGS="--kind 'Finish the sentence'"
    make questions ARGS="--mine"   only the ones you wrote

He designs this game and also plays it, so the bank has to be reviewable by
someone who must not learn a single answer (docs/STATUS.md, "Resume here").
`make audit` does that in the browser; this does it in the terminal, without
the lobby, the sockets or the reveal choreography.

It reads `datasets/dev.json`, which `compile.py --dev` builds by replacing
every answer with a uniform random draw and masking every reveal. That is the
safety property and it is structural: this tool cannot leak an answer because
the file it reads does not contain one. Pointed at a dataset that still has
reveals in it, it refuses rather than print them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.compile import REVEAL_MASK

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B, D, G, Y, R, X = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"
LETTERS = "ABCD"


def load(path: str) -> dict:
    if not os.path.exists(path):
        raise SystemExit(
            f"{R}No dataset at {path}{X}\n"
            f"  make dev       builds it from {os.environ.get('CORPUS', 'corpus.json')}"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    leaks = [q["id"] for q in data["questions"] if q.get("reveal") != REVEAL_MASK]
    if leaks:
        raise SystemExit(
            f"{R}{path} still has real reveals in it — refusing to print.{X}\n"
            f"  {len(leaks)} of {len(data['questions'])} questions, e.g. {leaks[0]}\n"
            f"  This tool only reads a --dev build. Run:  make dev"
        )
    return data


def wrap(text: str, width: int, indent: str) -> list[str]:
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(indent + line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(indent + line)
    return out


def render(q: dict, n: int, width: int) -> list[str]:
    tag = f"{G}yours{X}" if q.get("origin") == "mine" else f"{D}auto {X}"
    rows = [f"{B}{n:>4}{X}  {q['id']:<28} {D}{q['type']:<7}{X} {tag} "
            f"{D}{q.get('area') or '—'}{X}"]
    rows += wrap(q["prompt"], width, " " * 6)
    if q.get("text"):
        first = True
        for line in q["text"].split("\n"):
            for row in wrap(line, width - 8, ""):
                rows.append(f"      {D}{'▸' if first else ' '}{X} {row}")
                first = False
    if q.get("options"):
        cells = [f"{D}{LETTERS[i]}{X} {o}" for i, o in enumerate(q["options"])]
        joined = "   ".join(cells)
        rows.append("      " + joined if len(joined) < width else
                    "\n".join("      " + c for c in cells))
    if q.get("unit"):
        rows.append(f"      {D}answer in {q['unit']}{X}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default="datasets/dev.json")
    ap.add_argument("--kind", help="only this kind")
    ap.add_argument("--area", help="only this area")
    ap.add_argument("--type", dest="qtype", help="only this type")
    ap.add_argument("--mine", action="store_true", help="only what you wrote")
    ap.add_argument("--width", type=int, default=76)
    ap.add_argument("--ids", action="store_true", help="just the ids, one per line")
    args = ap.parse_args()

    path = args.data if os.path.isabs(args.data) else os.path.join(ROOT, args.data)
    data = load(path)
    qs = data["questions"]
    if args.mine:
        qs = [q for q in qs if q.get("origin") == "mine"]
    for attr, val in (("kind", args.kind), ("area", args.area), ("type", args.qtype)):
        if val:
            qs = [q for q in qs if str(q.get(attr, "")).lower() == val.lower()]

    if args.ids:
        print("\n".join(q["id"] for q in qs))
        return

    if not qs:
        raise SystemExit("Nothing matched those filters.")

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for q in qs:
        by_kind[q["kind"]].append(q)

    meta = data["meta"]
    print(f"\n{B}READ RECEIPTS · the bank{X}   {D}{len(qs)} questions · "
          f"{meta['p1']} & {meta['p2']} · answers hidden{X}\n")

    n = 0
    for kind in sorted(by_kind):
        group = by_kind[kind]
        rule = "─" * max(3, args.width - len(kind) - 8)
        print(f"{B}── {kind} {rule} {len(group)}{X}")
        for q in group:
            n += 1
            print("\n".join(render(q, n, args.width)))
            print()

    mine = sum(1 for q in qs if q.get("origin") == "mine")
    print(f"{B}{len(qs)}{X} questions   {G}yours {mine}{X}   "
          f"{D}generated {len(qs) - mine}{X}   {len(by_kind)} kinds")
    print("   " + "  ".join(f"{D}{t}{X} {c}" for t, c in
                            sorted(Counter(q["type"] for q in qs).items())))
    print(f"\n{D}Cut anything by id — ids are stable, the numbering is not.{X}\n")


if __name__ == "__main__":
    main()
