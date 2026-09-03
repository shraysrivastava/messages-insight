#!/usr/bin/env python3
"""
seal.py — encrypt the real data so it can live in a public repo.

    python3 tools/seal.py --all                    # dataset + mine.toml
    python3 tools/seal.py datasets/real.json       # one file
    python3 tools/seal.py --open datasets/real.json.enc --out /tmp/x.json
    python3 tools/seal.py --check datasets/real.json.enc

The whole security model in one line: **the server never holds the key.** Not
an env var, not a Fly secret, not on disk. The passphrase is typed on the host
screen on game night, the key is derived in memory, and the plaintext is cached
for the life of the process and never written down (docs/PLAN.md §4).

What that buys: a compromised host holds ciphertext. An accidental `git add .`
at 1am is a non-event. The passphrase is both the gate and the key, so there is
no way for one to pass while the other holds.

Two files get sealed:

    datasets/real.json      the compiled game        -> datasets/real.json.enc
    questions/mine.toml     your own questions       -> questions/mine.toml.enc

The second one matters more than it looks. `mine.toml` is gitignored because it
quotes real messages, which means your best work — the questions only you can
write — has no version control and no backup. Sealing it fixes that without
putting a word of it in the clear.

Both `.enc` files are committed on purpose. They are ciphertext.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# scrypt, not PBKDF2: memory-hard, so a GPU farm doesn't get the usual 1000x
# discount on guessing a passphrase you have to remember under pressure.
# n=2^15 with r=8 is ~32MB and ~0.15s here — imperceptible once per game night,
# and it multiplies the cost of an offline attack by about five orders of
# magnitude over a plain hash.
KDF = {"n": 1 << 15, "r": 8, "p": 1}
SALT_BYTES = 16
VERSION = 1

MIN_LENGTH = 8          # below this, refuse
SHORT_LENGTH = 12       # below this, say something

DEFAULTS = [("datasets/real.json", "datasets/real.json.enc"),
            ("questions/mine.toml", "questions/mine.toml.enc")]

G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


class BadPassphrase(Exception):
    """Wrong passphrase, or the ciphertext has been tampered with. Deliberately
    one exception for both: the caller has no business telling them apart."""


# ── the primitives ────────────────────────────────────────────────────────

def derive(passphrase: str, salt: bytes, params: dict | None = None) -> bytes:
    p = {**KDF, **(params or {})}
    kdf = Scrypt(salt=salt, length=32, n=p["n"], r=p["r"], p=p["p"])
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def seal(plaintext: bytes, passphrase: str) -> bytes:
    """Plaintext -> a self-describing envelope. The salt and the KDF cost
    travel with the ciphertext, so an old `.enc` still opens after these
    parameters are raised."""
    salt = os.urandom(SALT_BYTES)
    token = Fernet(derive(passphrase, salt)).encrypt(plaintext)
    envelope = {
        "v": VERSION,
        "kdf": "scrypt",
        **KDF,
        "salt": base64.b64encode(salt).decode(),
        "ct": token.decode(),
    }
    return json.dumps(envelope, indent=1).encode("utf-8") + b"\n"


def unseal(envelope: bytes, passphrase: str) -> bytes:
    """Envelope -> plaintext. Raises BadPassphrase on a wrong key, a corrupted
    file, or a truncated one — Fernet authenticates, so there is no path where
    this returns garbage instead of raising."""
    try:
        env = json.loads(envelope)
        salt = base64.b64decode(env["salt"])
        params = {k: int(env[k]) for k in ("n", "r", "p") if k in env}
        key = derive(passphrase, salt, params)
        return Fernet(key).decrypt(env["ct"].encode())
    except (InvalidToken, KeyError, ValueError, TypeError,
            json.JSONDecodeError) as e:
        raise BadPassphrase("could not open") from e


# ── checking what we're about to seal ──────────────────────────────────────

def inspect(path: str, data: bytes) -> str:
    """Refuse to seal something malformed. Sealing garbage means finding out on
    game night, with the passphrase in your hands and no way to tell whether
    the file or your memory is the problem."""
    if path.endswith(".json"):
        from app.schema import Dataset
        ds = Dataset.model_validate_json(data)
        by = ds.by_origin
        return (f"{len(ds.questions)} questions "
                f"({by['mine']} yours, {by['auto']} generated), "
                f"{len(ds.meta.months)} months")
    if path.endswith(".toml"):
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        qs = tomllib.loads(data.decode("utf-8")).get("q", [])
        ready = sum(1 for q in qs if q.get("status", "ready") == "ready")
        return f"{len(qs)} questions, {ready} ready"
    return f"{len(data):,} bytes"


def is_ignored(path: str) -> bool | None:
    """True if git would ignore this path. None if we can't tell."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", path],
                           cwd=ROOT, capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode == 0 if r.returncode in (0, 1) else None


# ── passphrases ───────────────────────────────────────────────────────────

def ask(confirm: bool) -> str:
    """Never echoed, never stored, never defaulted from the environment. If it
    could come from an env var it would end up in one."""
    while True:
        p = getpass.getpass("passphrase: ")
        if len(p) < MIN_LENGTH:
            print(f"  {R}too short — {MIN_LENGTH} characters minimum. "
                  f"This is the only thing between a public repo and five "
                  f"years of your messages.{X}")
            continue
        if confirm and getpass.getpass("again: ") != p:
            print(f"  {R}they didn't match.{X}")
            continue
        if len(p) < SHORT_LENGTH:
            print(f"  {Y}that's short. You type it once a year — "
                  f"make it a sentence.{X}")
        return p


# ── commands ──────────────────────────────────────────────────────────────

def do_seal(pairs: list[tuple[str, str]], passphrase: str | None = None) -> int:
    jobs = []
    for src, dst in pairs:
        if not os.path.exists(src):
            print(f"  {D}skipping {src} — not there{X}")
            continue
        with open(src, "rb") as f:
            data = f.read()
        try:
            summary = inspect(src, data)
        except Exception as e:
            print(f"  {R}{src} won't parse — not sealing it.{X}\n  {D}{e}{X}")
            return 1
        if is_ignored(src) is False:
            print(f"  {Y}heads up: {src} is NOT gitignored{X}")
        jobs.append((src, dst, data, summary))

    if not jobs:
        print(f"\n  {R}nothing to seal.{X}\n")
        return 1

    print()
    for src, _, _, summary in jobs:
        print(f"  {src:28} {D}{summary}{X}")
    print()

    # One passphrase for both files. Two would be two things to remember, and
    # the failure mode of forgetting either one is identical.
    p = passphrase or ask(confirm=True)

    print()
    for src, dst, data, _ in jobs:
        blob = seal(data, p)
        if unseal(blob, p) != data:                 # cheap, and catches a lot
            print(f"  {R}{dst} did not survive a round trip — not writing it.{X}")
            return 1
        with open(dst, "wb") as f:
            f.write(blob)
        print(f"  {G}✔{X} {dst}  {D}{len(blob):,} bytes of ciphertext{X}")

    print(f"\n  {D}commit the .enc files. The plaintext stays gitignored.{X}")
    print(f"  {D}there is no copy of that passphrase anywhere. "
          f"Put it where you'll have it in September.{X}\n")
    return 0


def do_open(path: str, out: str | None, passphrase: str | None = None,
            force: bool = False) -> int:
    with open(path, "rb") as f:
        blob = f.read()
    try:
        data = unseal(blob, passphrase or ask(confirm=False))
    except BadPassphrase:
        print(f"\n  {R}could not open {path}.{X}\n")
        return 1

    if out is None:
        sys.stdout.buffer.write(data)
        return 0

    ignored = is_ignored(out)
    if ignored is False:
        print(f"\n  {R}{out} is not gitignored — that would put the plaintext "
              f"in the repo. Not writing it.{X}\n")
        return 1
    if ignored is None:
        print(f"  {Y}can't tell whether {out} is gitignored.{X}")

    # Restoring a backup over newer work is the one way this tool can destroy
    # something. `mine.toml` is the file you'd least like to lose twice.
    if os.path.exists(out) and not force:
        with open(out, "rb") as f:
            current = f.read()
        if current != data:
            print(f"\n  {R}{out} already exists and differs from the sealed "
                  f"copy.{X}\n  {D}It may be newer. Move it aside, or pass "
                  f"--force to overwrite it.{X}\n")
            return 1
    with open(out, "wb") as f:
        f.write(data)
    print(f"\n  {G}✔{X} {out}  {D}{inspect(out, data)}{X}\n")
    return 0


def do_check(paths: list[str], passphrase: str | None = None) -> int:
    p = passphrase or ask(confirm=False)
    bad = 0
    print()
    for path in paths:
        if not os.path.exists(path):
            print(f"  {D}{path} — not there{X}")
            continue
        with open(path, "rb") as f:
            blob = f.read()
        try:
            data = unseal(blob, p)
        except BadPassphrase:
            print(f"  {R}✘{X} {path}  {D}did not open{X}")
            bad += 1
            continue
        try:
            print(f"  {G}✔{X} {path}  {D}{inspect(path[:-4], data)}{X}")
        except Exception as e:
            print(f"  {Y}✔{X} {path}  {Y}opens, but won't parse: {e}{X}")
            bad += 1
    print()
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="files to seal")
    ap.add_argument("--all", action="store_true",
                    help="seal the dataset and questions/mine.toml")
    ap.add_argument("--open", dest="open_", metavar="FILE.enc",
                    help="decrypt to --out, or to stdout")
    ap.add_argument("--out", help="where --open writes (must be gitignored)")
    ap.add_argument("--force", action="store_true",
                    help="let --open overwrite an existing, different file")
    ap.add_argument("--check", action="store_true",
                    help="verify a passphrase opens the .enc files")
    args = ap.parse_args()

    def abs_(p):
        return p if os.path.isabs(p) else os.path.join(ROOT, p)

    if args.open_:
        raise SystemExit(do_open(abs_(args.open_),
                                 abs_(args.out) if args.out else None,
                                 force=args.force))

    if args.check:
        paths = [abs_(f) for f in args.files] or \
                [abs_(d) for _, d in DEFAULTS if os.path.exists(abs_(d))]
        if not paths:
            raise SystemExit(f"{R}nothing sealed yet — run seal.py --all{X}")
        raise SystemExit(do_check(paths))

    if args.all or not args.files:
        pairs = [(abs_(s), abs_(d)) for s, d in DEFAULTS]
    else:
        pairs = [(abs_(f), abs_(f) + ".enc") for f in args.files]
    raise SystemExit(do_seal(pairs))


if __name__ == "__main__":
    main()
