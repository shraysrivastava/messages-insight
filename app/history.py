#!/usr/bin/env python3
"""
history.py — past games, without a database.

A list and a file (docs/DESIGN.md §4). Every finished game becomes one
`GameSummary`; the real ones are appended to `data/history.jsonl` on the Fly
volume and read back at boot. That is twenty lines, no schema migrations, no
ORM, and it survives the deploys that will be happening right up until game
night. A file is not a database.

**Every line is encrypted.** A summary carries its whole round log, and a
round log carries real message text. `seal.py`'s whole argument is that a
compromised host holds ciphertext; a plaintext history log beside the sealed
dataset would quietly undo that. So the lines are Fernet tokens under the key
the passphrase already derived when the real dataset was opened — no second
secret, nothing extra to remember, and the same "nothing readable at rest"
property the dataset has.

The consequence to know: **history is unreadable until someone unlocks the
real dataset.** The lobby shelf is empty on a cold boot and fills the moment
the passphrase is typed. That is the correct trade and it is not a bug.

**Demo games are never written.** They live in memory for the life of the
process and are discarded on restart. Otherwise every test run pollutes the
record of the games that actually happened.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.game import RoundRecord

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The shelf is a shelf, not an archive. Fifty games is more meetaversaries than
# anyone is going to have.
CAP = 50


@dataclass
class GameSummary:
    """One finished game, complete enough to redraw every end screen from."""
    id: str
    played_at: str                       # ISO 8601, UTC
    dataset: str                         # "real" | "demo" — never mixed
    names: dict[str, str] = field(default_factory=dict)
    colors: dict[str, str] = field(default_factory=dict)
    scores: dict[str, int] = field(default_factory=dict)
    winner: str | None = None
    awards: list[dict] = field(default_factory=list)
    curve: dict = field(default_factory=dict)
    rounds: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GameSummary":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def slug(when: datetime) -> str:
    """`sep14-2026`. Short enough to put in a URL, readable enough to say."""
    return when.strftime("%b%d-%Y").lower()


def summarise(log: list[RoundRecord], players: dict, dataset: str,
              awards: list[dict], curve: dict,
              when: datetime | None = None) -> GameSummary:
    """A finished game -> the record of it. `players` is pid -> anything with
    .name/.color/.score, i.e. `Game.players`."""
    when = when or datetime.now(timezone.utc)
    scores = {pid: p.score for pid, p in players.items()}
    top = sorted(scores.items(), key=lambda kv: -kv[1])
    # A tie has no winner. Naming one would make the shelf lie about a game
    # that was, in fact, level.
    winner = top[0][0] if len(top) == 1 or (
        len(top) > 1 and top[0][1] != top[1][1]) else None
    return GameSummary(
        id=f"{slug(when)}-{when.strftime('%H%M%S')}",
        played_at=when.isoformat(),
        dataset=dataset,
        names={pid: p.name for pid, p in players.items()},
        colors={pid: p.color for pid, p in players.items()},
        scores=scores,
        winner=winner,
        awards=list(awards),
        curve=dict(curve),
        rounds=[asdict(r) for r in log],
    )


class History:
    """The shelf. Real games persist, demo games don't, and nothing is
    readable until the passphrase has been typed."""

    def __init__(self, path: str = "data/history.jsonl", root: str = ROOT):
        self.path = path if os.path.isabs(path) else os.path.join(root, path)
        self.games: list[GameSummary] = []          # newest first
        self.key: bytes | None = None
        self.pending: list[GameSummary] = []        # real games, not yet writable

    # ── the key ───────────────────────────────────────────────────────────

    def unlock(self, key: bytes) -> int:
        """Called when the real dataset opens. Reads the file, and flushes any
        real game that finished before the passphrase was typed — which is a
        real sequence: demo first, unlock later, and the demo game is not
        written either way."""
        self.key = key
        n = self._read()
        for g in self.pending:
            self._append(g)
        self.pending.clear()
        return n

    # ── recording ─────────────────────────────────────────────────────────

    def remember(self, game: GameSummary) -> None:
        self.games.insert(0, game)
        del self.games[CAP:]
        if game.dataset != "real":
            return                                   # demo stays in memory
        if self.key is None:
            self.pending.append(game)
            return
        self._append(game)

    def _append(self, game: GameSummary) -> None:
        from cryptography.fernet import Fernet
        line = Fernet(self.key).encrypt(
            json.dumps(game.to_dict(), ensure_ascii=False).encode("utf-8"))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "ab") as f:
            f.write(line + b"\n")

    def _read(self) -> int:
        """Merge what's on disk into the shelf. A line that doesn't open is
        skipped rather than fatal — a history written under an older
        passphrase must not stop tonight's game from starting."""
        from cryptography.fernet import Fernet, InvalidToken
        if not os.path.exists(self.path) or self.key is None:
            return 0
        f = Fernet(self.key)
        have = {g.id for g in self.games}
        found = 0
        with open(self.path, "rb") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    g = GameSummary.from_dict(json.loads(f.decrypt(raw)))
                except (InvalidToken, ValueError, TypeError, KeyError):
                    continue
                if g.id in have:
                    continue
                have.add(g.id)
                self.games.append(g)
                found += 1
        self.games.sort(key=lambda g: g.played_at, reverse=True)
        del self.games[CAP:]
        return found

    # ── reading ───────────────────────────────────────────────────────────

    def shelf(self, dataset: str) -> list[GameSummary]:
        """Never mix the two. A demo run is not a meetaversary."""
        return [g for g in self.games if g.dataset == dataset]

    def find(self, game_id: str) -> GameSummary | None:
        return next((g for g in self.games if g.id == game_id), None)

    def stats(self, dataset: str) -> dict[str, Any]:
        """All-time numbers for the lobby, computed on the fly. No cache: it is
        fifty games and it is read once per lobby render."""
        games = self.shelf(dataset)
        if not games:
            return {"games": 0}

        record: dict[str, int] = {}
        names: dict[str, str] = {}
        draws = 0
        best_game = best_round = None
        seen: set[str] = set()
        awarded: dict[str, dict[str, int]] = {}

        for g in games:
            names.update(g.names)
            if g.winner:
                record[g.winner] = record.get(g.winner, 0) + 1
            else:
                draws += 1
            for pid, sc in g.scores.items():
                if best_game is None or sc > best_game[1]:
                    best_game = (pid, sc, g.id)
            for r in g.rounds:
                seen.add(r.get("question_id", ""))
                for pid, res in (r.get("results") or {}).items():
                    pts = res.get("points", 0)
                    if best_round is None or pts > best_round[1]:
                        best_round = (pid, pts, r.get("kind", ""))
            for a in g.awards:
                for pid in a.get("winners", []):
                    awarded.setdefault(pid, {})
                    awarded[pid][a["title"]] = awarded[pid].get(a["title"], 0) + 1

        # "Nilu has been Fastest Finger 4 times" — only worth saying past once.
        repeats = []
        for pid, counts in awarded.items():
            title, n = max(counts.items(), key=lambda kv: kv[1])
            if n > 1:
                repeats.append({"pid": pid, "name": names.get(pid, pid),
                                "title": title, "times": n})
        repeats.sort(key=lambda r: -r["times"])

        return {
            "games": len(games),
            "record": [{"pid": pid, "name": names.get(pid, pid),
                        "wins": record.get(pid, 0)}
                       for pid in sorted(names, key=lambda p: -record.get(p, 0))],
            "draws": draws,
            "best_game": ({"pid": best_game[0], "name": names.get(best_game[0], ""),
                           "score": best_game[1]} if best_game else None),
            "best_round": ({"pid": best_round[0], "name": names.get(best_round[0], ""),
                            "points": best_round[1], "kind": best_round[2]}
                           if best_round else None),
            "questions_seen": len(seen - {""}),
            "repeats": repeats[:2],
        }

    def cards(self, dataset: str) -> list[dict]:
        """The wire shape for the lobby shelf — enough to draw a card, not the
        whole round log."""
        out = []
        for g in self.shelf(dataset):
            out.append({
                "id": g.id,
                "played_at": g.played_at,
                "names": g.names,
                "colors": g.colors,
                "scores": g.scores,
                "winner": g.winner,
                "rounds": len(g.rounds),
                "awards": [a.get("title") for a in g.awards],
            })
        return out
