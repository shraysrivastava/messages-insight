#!/usr/bin/env python3
"""
datasets.py — which game this server can play, and how the real one is opened.

Three datasets ship in the image:

    datasets/demo.json       fake, committed, safe to hand to anyone
    datasets/dev.json.enc    the real deck with every answer blinded
    datasets/real.json.enc   ciphertext, committed, useless without the words

`dev` exists so a dress rehearsal can happen on the deployed URL without
spoiling the person who wrote the questions: same deck, same ids, same
bubbles, answers replaced by a uniform random draw (compile.py `blind`). It
is sealed rather than shipped in the clear because it still quotes five years
of real messages — only the answers are gone, not the thread.

The host screen shows `[ Demo ] [ Real 🔒 ]`. Clicking Real asks for the
passphrase, which is typed on the night and never stored — not in an env var,
not in a Fly secret, not on disk. The key is derived from it in memory, the
plaintext is cached for the life of the process, and nothing is ever written
back down. A compromised host holds ciphertext (docs/PLAN.md §4).

Two consequences worth being deliberate about:

**Wrong passphrase and missing file give the same answer.** There is nothing to
learn from the difference, and something to lose.

**Attempts are rate limited.** scrypt already makes guessing expensive — about
150ms each — but a limit means a wrong-passphrase loop can't quietly become a
job that runs all night against a URL somebody found.
"""

from __future__ import annotations

import os
import time
from collections import deque

from app.schema import Dataset

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_TRIES = 5
WINDOW = 60.0


class Locked(Exception):
    """The real dataset didn't open. Deliberately says no more than that."""


class Library:
    """The datasets this server can play. One of them is behind a passphrase."""

    #: id -> (label, ciphertext path). Both open with the same passphrase;
    #: one secret, one unlock, and `dev` is only useful to someone who could
    #: have opened `real` anyway.
    SEALED = {"dev": ("Dev", "datasets/dev.json.enc"),
              "real": ("Real", "datasets/real.json.enc")}

    def __init__(self, demo: str = "datasets/demo.json",
                 sealed: str = "datasets/real.json.enc",
                 root: str = ROOT):
        self.demo_path = os.path.join(root, demo)
        # `sealed` stays in the signature for callers that pass a single path;
        # it overrides where `real` is looked for.
        self.sealed_paths = {k: os.path.join(root, v)
                             for k, (_, v) in self.SEALED.items()}
        self.sealed_paths["real"] = os.path.join(root, sealed)
        self.sealed_path = self.sealed_paths["real"]
        self.cache: dict[str, Dataset] = {}
        # The key the passphrase derived, kept for the life of the process
        # alongside the plaintext that is already here. history.py writes its
        # lines with it rather than asking for the words a second time.
        self.key: bytes | None = None
        self.tries: deque[float] = deque()
        self.current = "demo"

    # ── what the host screen may offer ────────────────────────────────────

    def options(self) -> list[dict]:
        out = []
        if os.path.exists(self.demo_path):
            out.append({"id": "demo", "label": "Demo", "locked": False,
                        "ready": True})
        for key, (label, _) in self.SEALED.items():
            if os.path.exists(self.sealed_paths[key]):
                out.append({"id": key, "label": label, "locked": True,
                            "ready": key in self.cache})
        return out

    def state(self) -> dict:
        return {"current": self.current, "options": self.options()}

    # ── opening one ───────────────────────────────────────────────────────

    def load(self, which: str, passphrase: str | None = None) -> Dataset:
        """Return a dataset, decrypting if it has to. Raises Locked on anything
        that didn't work, without saying which thing."""
        if which == "demo":
            if "demo" not in self.cache:
                if not os.path.exists(self.demo_path):
                    raise Locked("no demo dataset")
                with open(self.demo_path, encoding="utf-8") as f:
                    self.cache["demo"] = Dataset.model_validate_json(f.read())
            return self.cache["demo"]

        if which not in self.SEALED:
            raise Locked("no such dataset")
        path = self.sealed_paths[which]

        # Already open. The passphrase is asked for once per process, which is
        # once per game night.
        if which in self.cache:
            return self.cache[which]

        if not self._allow():
            raise Locked("too many attempts")
        if not passphrase or not os.path.exists(path):
            raise Locked("could not open")

        from tools.seal import BadPassphrase, open_with_key
        try:
            with open(path, "rb") as f:
                plain, key = open_with_key(f.read(), passphrase)
            ds = Dataset.model_validate_json(plain)
        except (BadPassphrase, ValueError) as e:
            raise Locked("could not open") from e

        self.cache[which] = ds
        self.key = key
        self.tries.clear()          # it worked; stop counting
        return ds

    def _allow(self) -> bool:
        now = time.time()
        while self.tries and now - self.tries[0] > WINDOW:
            self.tries.popleft()
        if len(self.tries) >= MAX_TRIES:
            return False
        self.tries.append(now)
        return True

    def forget(self) -> None:
        """Drop the decrypted copy. Nothing calls this during a game; it exists
        so a test can prove the plaintext isn't kept anywhere else."""
        self.key = None
        self.cache.pop("real", None)
        if self.current == "real":
            self.current = "demo"
