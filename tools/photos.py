#!/usr/bin/env python3
"""
photos.py — the pictures in the thread, made small enough to ship.

    make photos                     # downscale everything extract.py found
    make photos LIMIT=200           # just the first 200, to see it work

`extract.py` records where each photograph lives — an absolute path into
`~/Library/Messages/Attachments`, which is on this Mac and nowhere else. This
turns each one into a downscaled JPEG in `photos/` (gitignored) and writes the
copy's path and size back into `corpus.json`. `compile.py` embeds the ones a
question actually asks for, so the only pictures that ever leave this machine
are the handful inside the sealed dataset.

Resizing is `sips`, which ships with macOS. Not Pillow: this file can only ever
run on the Mac that has the Messages database, so a dependency to install would
buy nothing, and `sips` reads HEIC — which is what half a modern camera roll
is — without being asked twice.

It is safe to re-run. Anything already downscaled is skipped, which matters
because five years of photographs is slow and iCloud will interrupt you.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def sips(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sips", *args], capture_output=True, text=True)


def dimensions(path: str) -> tuple[int, int] | None:
    r = sips("-g", "pixelWidth", "-g", "pixelHeight", path)
    if r.returncode != 0:
        return None
    dims = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, _, v = line.strip().partition(":")
            if k in ("pixelWidth", "pixelHeight") and v.strip().isdigit():
                dims[k] = int(v.strip())
    if "pixelWidth" not in dims or "pixelHeight" not in dims:
        return None
    return dims["pixelWidth"], dims["pixelHeight"]


def downscale(src: str, dst: str, longest: int, quality: int) -> bool:
    """One picture, resampled to fit a `longest`-pixel box, as JPEG."""
    r = sips("-s", "format", "jpeg",
             "-s", "formatOptions", str(quality),
             "-Z", str(longest),
             src, "--out", dst)
    return r.returncode == 0 and os.path.exists(dst)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="corpus.json")
    ap.add_argument("--out", default="photos", help="gitignored directory")
    ap.add_argument("--longest", type=int, default=900,
                    help="longest edge in pixels (default 900)")
    ap.add_argument("--quality", type=int, default=60)
    ap.add_argument("--limit", type=int, help="stop after this many, for a look")
    ap.add_argument("--force", action="store_true", help="redo ones already done")
    args = ap.parse_args()

    if sys.platform != "darwin":
        sys.exit("photos.py needs `sips`, which is macOS only — and so is chat.db.")

    with open(args.corpus, encoding="utf-8") as f:
        corpus = json.load(f)

    photos = corpus.get("photos")
    if not photos:
        sys.exit(
            f"No photos in {args.corpus}.\n"
            "Re-extract in Terminal.app — a corpus built before attachments "
            "were queried has no `photos` list:\n"
            '  make corpus CHAT="+1555…,her@gmail.com" P1=Shray P2=Nilu')

    out_dir = os.path.join(ROOT, args.out) if not os.path.isabs(args.out) else args.out
    os.makedirs(out_dir, exist_ok=True)

    todo = photos if args.limit is None else photos[:args.limit]
    done = skipped = missing = failed = 0
    total_bytes = 0

    print(f"\n{B}{len(todo):,} photos{X} -> {args.out}/  "
          f"{D}(longest edge {args.longest}px, quality {args.quality}){X}\n")

    for n, p in enumerate(todo, 1):
        dst = os.path.join(out_dir, f"{p['k']}.jpg")
        rel = os.path.join(args.out, f"{p['k']}.jpg")

        if not args.force and os.path.exists(dst) and p.get("thumb") == rel:
            skipped += 1
            total_bytes += p.get("bytes", 0)
            continue

        src = p["src"]
        if not os.path.exists(src):
            # Overwhelmingly this is iCloud: the row is in the database and the
            # file has been offloaded. Nothing to do about it from here, but it
            # has to be counted or the totals lie.
            p.pop("thumb", None)
            missing += 1
            continue

        if not downscale(src, dst, args.longest, args.quality):
            p.pop("thumb", None)
            failed += 1
            continue

        size = os.path.getsize(dst)
        dims = dimensions(dst)
        p["thumb"] = rel
        p["bytes"] = size
        if dims:
            p["w"], p["h"] = dims
        done += 1
        total_bytes += size

        if n % 100 == 0 or n == len(todo):
            print(f"  {n:>6,}/{len(todo):,}   {done:,} done  {skipped:,} already  "
                  f"{missing:,} offloaded  {failed:,} failed", end="\r", flush=True)

    with open(args.corpus, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False)

    have = done + skipped
    print(" " * 78, end="\r")
    print(f"  {G}{have:,} ready{X}   {D}{done:,} new, {skipped:,} already there{X}")
    if missing:
        print(f"  {Y}{missing:,} offloaded to iCloud{X} {D}— open Messages, scroll "
              f"the thread, and re-run{X}")
    if failed:
        print(f"  {R}{failed:,} failed to convert{X}")
    if have:
        print(f"  {D}{total_bytes / 1e6:.1f} MB on disk, "
              f"{total_bytes / have / 1024:.0f} KB each{X}")
        print(f"\n  A question asks for one by name:  "
              f"{D}photo = \"{todo[0]['name']}\"{X}")
        print(f"  {D}compile.py embeds only the ones a question asks for.{X}")
    print()


if __name__ == "__main__":
    main()
