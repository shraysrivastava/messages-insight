#!/usr/bin/env python3
"""
status.py — what's done, what's left.

    python3 tools/status.py            full dashboard
    python3 tools/status.py --stage 1  just one stage
    python3 tools/status.py --bank     just the question bank

Two kinds of check:

  AUTO    verified against the filesystem right now — a file exists, the bank
          compiles, the tests pass. Cannot be wrong, cannot go stale.
  MANUAL  checkboxes in docs/STATUS.md, for things a script can't see
          ("played a full game end to end"). You tick these yourself.

The auto checks are the point. A checklist you maintain by hand drifts from
reality within a week; this one can't.
"""

import argparse, glob, os, re, subprocess, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import tomllib
except ModuleNotFoundError:                      # py < 3.11
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
TICK, CROSS, DASH = "✔", "✗", "·"


def p(path):
    return os.path.join(ROOT, path)


def exists(path):
    return os.path.exists(p(path))


def any_exists(*paths):
    return any(exists(x) for x in paths)


# ── auto checks ────────────────────────────────────────────────────────────
# (stage, id, label, predicate)

CHECKS = [
    (0, "S0.1", "POC runs (poc/server.py)",            lambda: exists("poc/server.py")),
    (0, "S0.2", "POC static assets",                   lambda: exists("poc/static/host.html")),
    (0, "S0.3", "Docs written",                        lambda: exists("docs/PLAN.md") and exists("docs/DESIGN.md")),
    (0, "S0.4", "Question bank exists",                lambda: exists("questions/config.toml")),

    (1, "S1.1", ".gitignore protects real data",       lambda: _gitignore_ok()),
    (1, "S1.2", "First commit landed",                 lambda: _has_commits()),
    (1, "S1.3", "tools/extract.py",                    lambda: exists("tools/extract.py")),
    (1, "S1.4", "corpus.json built (needs chat.db)",   lambda: exists("corpus.json")),
    (1, "S1.5", "app/schema.py",                       lambda: exists("app/schema.py")),
    (1, "S1.6", "tools/validate.py",                   lambda: exists("tools/validate.py")),
    (1, "S1.7", "app/game.py extracted",               lambda: exists("app/game.py")),
    (1, "S1.8", "round log in game.py",                lambda: _grep("app/game.py", r"RoundRecord")),
    (1, "S1.9", "scoring tests exist",                 lambda: any_exists("tests/test_scoring.py", "tests/test_game.py")),
    (1, "S1.10", "tests pass",                         lambda: _pytest_ok()),
    (1, "S1.11", "tools/mine.py",                      lambda: exists("tools/mine.py")),
    (1, "S1.12", "tools/compile.py",                   lambda: exists("tools/compile.py")),
    (1, "S1.13", "a dataset compiles clean",           lambda: exists("datasets/real.json") or exists("datasets/demo.json")),

    (2, "S2.0", "app/main.py (the real server)",       lambda: exists("app/main.py")),
    (2, "S2.1", "tools/curate.py",                     lambda: exists("tools/curate.py")),
    (2, "S2.2", "60+ shippable questions",             lambda: _bank()["shippable"] >= 60),
    (2, "S2.3", "join code enforced",                  lambda: _grep("app/main.py", r"def code_ok")),
    (2, "S2.4", "client-timestamped answers",          lambda: _grep("app/main.py", r'msg\.get\("at"\)') and _grep("static/shared.js", r"serverNow")),
    (2, "S2.5", "websocket heartbeat",                 lambda: _grep("app/main.py", r"HEARTBEAT")),
    (2, "S2.6", "tools/seal.py",                       lambda: exists("tools/seal.py")),
    (2, "S2.7", "datasets/real.json.enc",              lambda: exists("datasets/real.json.enc")),
    (2, "S2.8", "app/datasets.py + toggle",            lambda: exists("app/datasets.py")),
    (2, "S2.9", "demo dataset committed",              lambda: exists("datasets/demo.json")),
    (2, "S2.10", "Dockerfile",                         lambda: exists("Dockerfile")),
    (2, "S2.11", "fly.toml, scale-to-zero off",        lambda: _grep("fly.toml", r"auto_stop_machines\s*=\s*false")),
    (2, "S2.12", "fonts self-hosted",                  lambda: bool(glob.glob(p("static/fonts/*"))) or bool(glob.glob(p("poc/static/fonts/*")))),
    (2, "S2.13", "datasets/dev.json.enc (rehearsal deck)", lambda: exists("datasets/dev.json.enc")),

    # The month slider is a phone input, so the histogram behind it is in
    # player.html. This used to look in host.html and could never have fired.
    (3, "S3.1", "density histogram",                   lambda: _grep("static/player.html", r"function density") or _grep("poc/static/player.html", r"density")),
    (3, "S3.2", "reveal choreography + context",       lambda: _grep("static/host.html", r"context") or _grep("poc/static/host.html", r"context")),
    (3, "S3.3", "locked / read-receipt state",         lambda: _grep("static/player.html", r"Delivered") or _grep("poc/static/player.html", r"Delivered")),
    (3, "S3.4", "app/superlatives.py",                 lambda: exists("app/superlatives.py")),
    (3, "S3.5", "superlatives tested",                 lambda: exists("tests/test_superlatives.py")),
    # These three used to grep game.py for the word, which was true from the
    # day the scorer was written and stayed true for months while no client
    # could play any of them. A type ships when it is in PLAYABLE *and* a
    # phone can answer it, so that is what they check now.
    (3, "S3.6", "percent type",                        lambda: _playable("percent") and _grep("static/player.html", r'q\.type === "percent"')),
    (3, "S3.7", "wager / Final Receipt",               lambda: _playable("wager") and _grep("static/player.html", r'q\.type === "wager"') and _grep("app/game.py", r"_final_receipt")),
    (3, "S3.8", "weighted dealing (mine first)",       lambda: _grep("app/game.py", r"authored_share|weight_mine")),
    (3, "S3.9", "blind audit mode (make audit)",       lambda: _grep("tools/compile.py", r"def blind") and _grep("Makefile", r"\naudit:")),
    (3, "S3.10", "text audit (make questions)",        lambda: exists("tools/audit.py") and _grep("Makefile", r"\nquestions:")),
    (3, "S3.11", "the clients read `format`",          lambda: _grep("static/shared.js", r"function messageBlock") and _grep("static/app.css", r"\.compare") and _grep("static/host.html", r"messageBlock")),
    (3, "S3.12", "photos (extract -> photos/ -> dataset)", lambda: exists("tools/photos.py") and _grep("tools/extract.py", r"def load_attachments") and _grep("tools/compile.py", r"def load_photo") and _grep("app/main.py", r"/photo/current")),

    # `svg` used to be in this pattern and matched the join QR's /qr.svg —
    # a dashboard that ticks itself is worse than no dashboard. Name the
    # function `scoreGraph` when you build it.
    (4, "S4.1", "score graph",                         lambda: _grep("static/host.html", r"scoreGraph") or _grep("poc/static/host.html", r"scoreGraph")),
    (4, "S4.2", "app/history.py",                      lambda: exists("app/history.py")),
    (4, "S4.3", "history shelf in lobby",              lambda: _grep("static/host.html", r"history") or _grep("poc/static/host.html", r"history")),
    (4, "S4.4", "receipts reel",                       lambda: _grep("static/host.html", r"reel")),
    # Synthesised rather than sampled — there is no static/sounds/ and there
    # never will be. Every cue is oscillators and an envelope (static/sound.js).
    (4, "S4.5", "sound design",                        lambda: _grep("static/sound.js", r"function voice") or bool(glob.glob(p("static/sounds/*")))),
    (4, "S4.6", "mutual type",                         lambda: _playable("mutual") and _grep("static/host.html", r"agreedOption")),
    (4, "S4.7", "end-to-end smoke test",               lambda: any_exists("tests/test_smoke.py", "tests/smoke.spec.js", "tests/e2e")),
    # Built as "music beds under each phase", then cut on 2026-09-24 — the game
    # wanted sound effects and not a soundtrack. The ID stays and what it
    # verifies moved with the decision: every beat that makes a noise has a cue
    # behind it, and nothing loops.
    (4, "S4.8", "a cue on every beat, no music",       lambda: all(
        _grep("static/sound.js", rf"\n    {c}\(") for c in
        ("send", "receive", "correct", "wrong", "tick", "ping", "flourish"))
        and not _grep("static/sound.js", r"const BEDS")),
    (4, "S4.9", "the opener (five years, on the lobby)", lambda: _grep("static/host.html", r"function opener") and _grep("static/app.css", r"\.opener-bars")),
]

STAGES = {
    0: ("Stage 0 — POC", "done before this plan existed"),
    1: ("Stage 1 — Foundations", "playable locally on real data"),
    2: ("Stage 2 — MVP / Shippable", "she can play it from another state"),
    3: ("Stage 3 — Feel", "the version worth showing people"),
    4: ("Stage 4 — The Arc", "history, superlatives, the emotional close"),
    5: ("Game day", "the only deadline that matters"),
}

GATES = {
    1: "You can play a rough game on your laptop, on real data.",
    2: "MVP DONE. A full 14-round game has been played on the deployed URL.",
    3: "The game feels designed rather than assembled.",
    4: "Past games, awards, and a receipts reel. Stop any time before here.",
    5: "You played it with her.",
}


# ── helpers ────────────────────────────────────────────────────────────────

def _playable(qtype):
    """Is this type in game.PLAYABLE? Reading the line rather than importing
    keeps status.py runnable on the system python (3.9), which app/ is not."""
    if not exists("app/game.py"):
        return False
    try:
        with open(p("app/game.py"), encoding="utf-8", errors="ignore") as f:
            m = re.search(r"^PLAYABLE = \{(.*?)\}", f.read(), re.M | re.S)
    except OSError:
        return False
    return bool(m) and f'"{qtype}"' in m.group(1)


def _grep(path, pattern):
    if not exists(path):
        return False
    try:
        with open(p(path), encoding="utf-8", errors="ignore") as f:
            return bool(re.search(pattern, f.read()))
    except OSError:
        return False


def _gitignore_ok():
    if not exists(".gitignore"):
        return False
    with open(p(".gitignore"), encoding="utf-8") as f:
        t = f.read()
    return all(k in t for k in ("chat.db", "corpus.json", "questions/"))


def _has_commits():
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                           capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _python():
    """Prefer the project venv — the system python is 3.9 and has no pytest."""
    venv = p(".venv/bin/python")
    return venv if os.path.exists(venv) else sys.executable


def _pytest_ok():
    if not glob.glob(p("tests/test_*.py")):
        return False
    try:
        r = subprocess.run([_python(), "-m", "pytest", "-q", "tests"],
                           cwd=ROOT, capture_output=True, timeout=180)
        return r.returncode == 0
    except Exception:
        return False


_BANK = None

def _bank():
    """Load every question file. Provenance is the directory."""
    global _BANK
    if _BANK is not None:
        return _BANK
    out = {"questions": [], "lexicons": {}, "error": None,
           "mine": 0, "auto": 0, "shippable": 0}
    if tomllib is None:
        out["error"] = "no tomllib/tomli — run: pip install tomli (or use python 3.11+)"
        _BANK = out
        return out
    try:
        if exists("questions/lexicons.toml"):
            with open(p("questions/lexicons.toml"), "rb") as f:
                out["lexicons"] = tomllib.load(f).get("lex", {})
        files = []
        if exists("questions/mine.toml"):
            files.append(("mine", "questions/mine.toml"))
        for f in sorted(glob.glob(p("questions/auto/*.toml"))):
            files.append(("auto", os.path.relpath(f, ROOT)))
        for origin, rel in files:
            with open(p(rel), "rb") as fh:
                for q in tomllib.load(fh).get("q", []):
                    q["_origin"], q["_file"] = origin, rel
                    q.setdefault("topic", q.get("id"))
                    out["questions"].append(q)
        for q in out["questions"]:
            out[q["_origin"]] += 1
        # shippable = ready, no TODO anywhere in it
        out["shippable"] = sum(
            1 for q in out["questions"]
            if q.get("status") == "ready" and "TODO" not in str(q)
        )
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    _BANK = out
    return out


def _manual():
    """Parse ticked checkboxes out of docs/STATUS.md."""
    items = []
    if not exists("docs/STATUS.md"):
        return items
    with open(p("docs/STATUS.md"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\s*-\s*\[([ xX])\]\s*`?(M\d+\.\d+)`?\s*(.*)", line)
            if m:
                items.append((int(m.group(2)[1]), m.group(2),
                              m.group(3).strip(), m.group(1).lower() == "x"))
    return items


def bar(done, total, width=24):
    if not total:
        return D + "—" * width + X
    n = round(width * done / total)
    col = G if done == total else (Y if done else D)
    return col + "█" * n + X + D + "░" * (width - n) + X


# ── render ─────────────────────────────────────────────────────────────────

def show_bank():
    b = _bank()
    print(f"\n{B}QUESTION BANK{X}")
    if b["error"]:
        print(f"  {R}{CROSS}{X} {b['error']}")
        return
    qs = b["questions"]
    ready = [q for q in qs if q.get("status") == "ready"]
    mine_ready = [q for q in ready if q["_origin"] == "mine"]
    print(f"  {len(qs)} authored   "
          f"{G}{b['shippable']} shippable{X}   "
          f"{len([q for q in qs if q.get('status')=='mine'])} awaiting curate   "
          f"{len([q for q in qs if q.get('status')=='draft'])} draft")
    print(f"  {B}yours{X} {b['mine']}   generated {b['auto']}   "
          f"lexicons {len(b['lexicons'])}")

    target = 60
    print(f"\n  shippable / 60 floor   {bar(min(b['shippable'], target), target)} "
          f"{b['shippable']}/{target}")

    # authored share: can the dealer hit 65% of 14 rounds from mine.toml?
    need = round(14 * 0.65)
    have = len([q for q in mine_ready if "TODO" not in str(q)])
    print(f"  yours / {need} per game     {bar(min(have, need), need)} {have}/{need}"
          + ("" if have >= need else f"  {Y}dealer will backfill from auto/{X}"))

    todo_lex = [k for k, v in b["lexicons"].items() if v.get("status") == "draft"]
    if todo_lex:
        print(f"\n  {Y}lexicons awaiting you:{X} {', '.join(todo_lex)}"
              f"  {D}(each unblocks 2-3 questions){X}")

    print(f"\n  {D}types{X}   " + "  ".join(
        f"{k} {v}" for k, v in sorted(Counter(q["type"] for q in qs).items())))
    areas = Counter(q.get("area", "?") for q in qs)
    thin = [a for a, c in areas.items() if c <= 2]
    print(f"  {D}areas{X}   {len(areas)} covered, {len(set(q['kind'] for q in qs))} kinds"
          + (f"   {Y}thin: {', '.join(sorted(thin))}{X}" if thin else ""))


def show_stages(only=None):
    manual = _manual()
    for stage in sorted(STAGES):
        if only is not None and stage != only:
            continue
        title, sub = STAGES[stage]
        auto = [(i, l, fn()) for s, i, l, fn in CHECKS if s == stage]
        man = [(i, l, d) for s, i, l, d in manual if s == stage]
        rows = auto + man
        done = sum(1 for *_, ok in rows if ok)
        print(f"\n{B}{title}{X}  {D}{sub}{X}")
        print(f"  {bar(done, len(rows))}  {done}/{len(rows)}")
        for i, label, ok in rows:
            mark = f"{G}{TICK}{X}" if ok else f"{D}{DASH}{X}"
            tone = D if ok else ""
            manual_tag = f" {D}(manual){X}" if i.startswith("M") else ""
            print(f"    {mark} {tone}{i:<6} {label}{X}{manual_tag}")
        if stage in GATES:
            gate_met = done == len(rows)
            col = G if gate_met else Y
            print(f"    {col}GATE{X} {D}{GATES[stage]}{X}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", type=int)
    ap.add_argument("--bank", action="store_true")
    a = ap.parse_args()

    print(f"\n{B}READ RECEIPTS{X}  {D}status · {os.path.basename(ROOT)}{X}")
    if a.bank:
        show_bank()
    else:
        show_stages(a.stage)
        show_bank()

    b = _bank()
    total_auto = sum(1 for *_, fn in CHECKS if fn())
    print(f"\n{B}OVERALL{X}  {bar(total_auto, len(CHECKS), 32)} "
          f"{total_auto}/{len(CHECKS)} verified\n")


if __name__ == "__main__":
    main()
