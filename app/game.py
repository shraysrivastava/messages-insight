"""
game.py — the state machine. No FastAPI, no asyncio, no I/O.

Everything here is a pure function of the dataset plus what the players did, so
scoring can be tested directly. `main.py` owns the clock and the sockets and
calls into this; nothing in this file knows a websocket exists.

Two things worth knowing before you edit:

  · `grade()` appends a RoundRecord to `self.log`. That log is the only source
    for superlatives, the score graph, the history shelf and the receipts reel.
    Keep it complete even when it looks redundant.

  · `deal()` prefers authored questions over generated ones. That's a product
    decision, not an implementation detail — see docs/PLAN.md §5.
"""

from __future__ import annotations

import random
import string
import time
from dataclasses import dataclass, field
from typing import Any

from app.schema import Dataset, Question

COLORS = ["#F2A65A", "#8B8CE8", "#7BD389", "#E8709A", "#5FC9D6", "#D9C05A"]

# The subset the *clients* can currently render. compile.py filters on this, so
# a question type is never dealt before there's an input for it. Widening this
# set is how a new mechanic ships: add the input, add the name here.
#
# `wager` is in it, but it never lands in the body of the game: `deal()` holds
# the wagers back and appends one as the last round (the Final Receipt).
PLAYABLE = {"binary", "choice", "number", "month", "percent", "mutual", "wager"}

# Types whose answer is an index into `options`.
INDEXED = {"binary", "choice", "wager", "mutual"}

MUTUAL_POINTS = 500      # flat — a co-op round shouldn't reward buzzing in

# The Final Receipt. You stake before you answer, you win or lose the stake,
# and speed is worth nothing — the whole round is the decision, not the reflex.
WAGER_STEP = 50          # the slider's granularity, so the number reads round
WAGER_FLOOR = 500        # you can always stake this much, even at zero


@dataclass
class PlayerResult:
    answer: Any
    points: int
    accuracy: float
    elapsed: float
    rank_after: int
    # Only the Final Receipt sets this. superlatives.py needs it for All In and
    # Ice in the Veins, which are about how much you risked, not what you knew.
    stake: int | None = None


@dataclass
class RoundRecord:
    """One round, everything about it. The substrate for every end-of-game view."""
    index: int
    question_id: str
    kind: str
    type: str
    prompt: str
    reveal: str
    correct: Any
    text: str | None = None
    options: list[str] | None = None     # or the reel replays "said 0"
    context: list[dict] | None = None    # the thread around the source message
    format: str = "bubble"
    origin: str = "auto"
    area: str | None = None
    results: dict[str, PlayerResult] = field(default_factory=dict)


@dataclass
class Player:
    id: str
    name: str
    color: str
    score: int = 0
    answer: Any = None
    answered_at: float | None = None
    last: dict | None = None
    online: bool = True
    stake: int | None = None         # the Final Receipt only


@dataclass
class DealRules:
    """Mirrors questions/config.toml [deal].

    It gets there through the dataset, not through the file: `compile.py`
    copies the block into `meta.deal` and `main.build_room` unpacks it here.
    The deployed image has no `questions/` directory (see schema.Deal), so the
    fields and defaults below have to stay in step with that model.
    """
    authored_share: float = 0.65
    weight_mine: int = 4
    weight_auto: int = 1
    max_per_kind: int = 3
    max_per_subject: int = 1
    freshness: bool = True
    final_receipt: bool = True


class Game:
    def __init__(
        self,
        data: Dataset,
        rounds: int | None = None,
        seconds: float | None = None,
        rules: DealRules | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.data = data
        self.meta = data.meta
        # Wagers are playable but never dealt into the body of the game — one
        # of them is appended as the last round instead, so `rounds` counts
        # the ordinary rounds and the deck comes out one longer.
        self.bank = [q for q in data.questions
                     if q.type in PLAYABLE and q.type != "wager"]
        self.finals = [q for q in data.questions if q.type == "wager"]
        self.rules = rules or DealRules()
        self.rng = rng or random.Random()
        self.seconds = seconds if seconds is not None else data.meta.seconds
        self.rounds = min(rounds or data.meta.rounds, len(self.bank))
        self.code = "".join(self.rng.choices(string.ascii_uppercase, k=4))
        self.reset()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def reset(self) -> None:
        self.phase = "lobby"
        self.round = -1
        self.deck: list[Question] = []
        self.players: dict[str, Player] = {}
        self.log: list[RoundRecord] = []
        self.ends_at: float | None = None
        self.started_at: float | None = None

    # ── dealing ───────────────────────────────────────────────────────────

    def deal(self, seen: dict[str, int] | None = None) -> None:
        """Build this game's deck.

        Authored questions come first and are sampled at higher weight; a single
        `kind` and a single `subject` are both capped; recently-seen questions
        are down-weighted so replays differ. Deterministic given the rng, which
        is what makes it testable.

        The subject cap is the one that stops a game feeling repetitive.
        `kind` is only the eyebrow, so three questions about what gets sent
        after midnight — filed under Deep cut, The archive and Chronically
        online — used to be free to land in the same fourteen rounds. They are
        the same question in three costumes, and a bank of 160 has no need to
        ask twice.
        """
        seen = seen or {}
        r = self.rules
        mine = [q for q in self.bank if q.origin == "mine"]
        auto = [q for q in self.bank if q.origin != "mine"]

        picked: list[Question] = []
        per_kind: dict[str, int] = {}
        per_subject: dict[str, int] = {}

        # Choose the closer first so the body of the game can be dealt around
        # it. A wager on who said "I love you" first is worth nothing at round
        # 15 if round 4 already showed the message and named the date.
        final = (self._final_receipt(seen)
                 if r.final_receipt and self.finals else None)
        if final is not None and final.subject:
            per_subject[final.subject] = r.max_per_subject

        def can_take(q: Question) -> bool:
            if per_kind.get(q.kind, 0) >= r.max_per_kind:
                return False
            # A question with no subject is about one specific message and can
            # only ever collide with itself.
            return (q.subject is None
                    or per_subject.get(q.subject, 0) < r.max_per_subject)

        def take(q: Question) -> None:
            picked.append(q)
            per_kind[q.kind] = per_kind.get(q.kind, 0) + 1
            if q.subject:
                per_subject[q.subject] = per_subject.get(q.subject, 0) + 1

        def weight(q: Question) -> float:
            w = float(r.weight_mine if q.origin == "mine" else r.weight_auto)
            if r.freshness:
                w /= 1.0 + seen.get(q.id, 0)
            return w

        def draw(pool: list[Question], upto: int) -> None:
            """Weighted sample without replacement, respecting both caps."""
            avail = [q for q in pool if q not in picked]
            while avail and len(picked) < upto:
                eligible = [q for q in avail if can_take(q)]
                if not eligible:                    # cap blocks everything left
                    eligible = avail
                weights = [weight(q) for q in eligible]
                total = sum(weights)
                if total <= 0:
                    chosen = self.rng.choice(eligible)
                else:
                    chosen = self.rng.choices(eligible, weights=weights, k=1)[0]
                take(chosen)
                avail.remove(chosen)

        # 1. authored questions first, up to the target share
        target = min(len(mine), round(self.rounds * r.authored_share))
        draw(mine, target)
        # 2. top up from everything, still favouring authored
        draw(mine + auto, self.rounds)

        self.deck = self._interleave(picked)

        # The Final Receipt is round 15 of 14: a permanent closer, outside the
        # interleave and outside the caps, because it is the only round whose
        # position is the point. It was chosen before the draw, above.
        if final is not None:
            self.deck.append(final)

    def _interleave(self, questions: list[Question]) -> list[Question]:
        """Round-robin by `kind` so the same category never lands twice running.

        The POC did this by bucketing and popping; same idea, but it keeps the
        weighted order within each bucket instead of reversing it.
        """
        buckets: dict[str, list[Question]] = {}
        for q in questions:
            buckets.setdefault(q.kind, []).append(q)
        lists = sorted(buckets.values(), key=len, reverse=True)
        out: list[Question] = []
        while any(lists):
            for lst in lists:
                if lst:
                    out.append(lst.pop(0))
        return out

    def _final_receipt(self, seen: dict[str, int]) -> Question:
        """Pick the wager to close on, favouring yours and the unseen."""
        r = self.rules
        weights = []
        for q in self.finals:
            w = float(r.weight_mine if q.origin == "mine" else r.weight_auto)
            if r.freshness:
                w /= 1 + seen.get(q.id, 0)
            weights.append(w)
        if sum(weights) <= 0:
            return self.rng.choice(self.finals)
        return self.rng.choices(self.finals, weights=weights, k=1)[0]

    # ── players ───────────────────────────────────────────────────────────

    def add_player(self, pid: str, name: str) -> Player:
        if pid in self.players:
            self.players[pid].online = True
            return self.players[pid]
        used = {p.color for p in self.players.values()}
        color = next((c for c in COLORS if c not in used), COLORS[0])
        p = Player(id=pid, name=(name or "").strip()[:18] or "Player", color=color)
        self.players[pid] = p
        return p

    @property
    def question(self) -> Question | None:
        if 0 <= self.round < len(self.deck):
            return self.deck[self.round]
        return None

    def live(self) -> list[Player]:
        return [p for p in self.players.values() if p.online]

    def everyone_answered(self) -> bool:
        live = self.live()
        return bool(live) and all(p.answer is not None for p in live)

    def record_answer(self, pid: str, value: Any, at: float | None = None) -> bool:
        """First answer wins; later ones are ignored. Returns True if recorded."""
        p = self.players.get(pid)
        if not p or self.phase != "question" or p.answer is not None:
            return False
        q = self.question
        if q is not None and q.type == "wager":
            # The phone sends the pick and the stake together, because they are
            # one decision. Splitting them into two messages would let a client
            # stake, see the board move, and pick afterwards.
            if not isinstance(value, dict):
                return False
            pick = value.get("pick")
            if not isinstance(pick, int) or isinstance(pick, bool):
                return False
            p.stake = self.stake_cap(p, value.get("stake"))
            value = pick
        p.answer = value
        p.answered_at = self._clamp_time(at)
        return True

    def stake_cap(self, p: Player, want: Any = None) -> int:
        """What this player may stake, and what they actually staked.

        Called with no `want` it is the ceiling the phone draws its slider to;
        called with one it clamps. The floor matters: at zero points there is
        nothing to risk and the last round would be a formality, so everyone
        gets something to put on the table.
        """
        cap = max(p.score, WAGER_FLOOR)
        if want is None:
            return cap
        if not isinstance(want, (int, float)) or isinstance(want, bool):
            return 0
        return max(0, min(int(want), cap))

    def _clamp_time(self, at: float | None) -> float:
        """Clamp a client-supplied timestamp into the question window.

        Players are in different states; timing an answer by when it *arrives*
        hands the higher-latency player a permanent handicap on a scoring model
        where speed is worth 2x. Clients send their own clock-corrected time and
        we clamp it — which is the whole anti-cheat story, and plenty for a
        two-player game.
        """
        now = time.time()
        if at is None:
            return now
        lo = self.question_started_at or now
        hi = self.ends_at or now
        return max(lo, min(float(at), hi))

    @property
    def question_started_at(self) -> float | None:
        if self.ends_at is None:
            return None
        return self.ends_at - self.seconds

    # ── scoring ───────────────────────────────────────────────────────────

    def accuracy(self, q: Question, guess: Any) -> float:
        if guess is None:
            return 0.0
        t = q.type
        if t in ("binary", "choice", "wager"):
            return 1.0 if guess == q.answer else 0.0
        if t == "number":
            if not isinstance(guess, (int, float)) or isinstance(guess, bool):
                return 0.0
            off = abs(guess - q.answer) / max(q.answer, 1)
            return max(0.0, 1.0 - off)
        if t == "percent":
            if not isinstance(guess, (int, float)) or isinstance(guess, bool):
                return 0.0
            return max(0.0, 1.0 - abs(guess - q.answer) / 30.0)
        if t == "month":
            if not isinstance(guess, int) or isinstance(guess, bool):
                return 0.0
            span = max(len(self.meta.months), 6) / 3
            return max(0.0, 1.0 - abs(guess - q.answer) / span)
        return 0.0

    def _speed(self, answered_at: float | None) -> float:
        """1.0 for instant, 0.5 at the buzzer. Doubles the value of jumping in."""
        started = self.question_started_at or 0.0
        elapsed = max(0.0, (answered_at if answered_at is not None else self.ends_at or 0.0) - started)
        return 1 - 0.5 * min(1.0, elapsed / self.seconds)

    def grade(self) -> RoundRecord:
        """Score the round, mutate scores, and append the round log entry."""
        q = self.question
        assert q is not None, "grade() with no active question"
        started = self.question_started_at or 0.0

        if q.type == "mutual":
            scores = self._grade_mutual()
        elif q.type == "wager":
            scores = self._grade_wager()
        else:
            scores = {}
            for p in self.players.values():
                acc = self.accuracy(q, p.answer)
                pts = 0 if acc <= 0 else round(1000 * acc * self._speed(p.answered_at))
                scores[p.id] = (acc, pts)

        for p in self.players.values():
            acc, pts = scores.get(p.id, (0.0, 0))
            p.last = {"points": pts, "accuracy": round(acc, 3), "answer": p.answer}
            if q.type == "wager":
                p.last["stake"] = p.stake or 0
            p.score += pts

        order = sorted(self.players.values(), key=lambda p: -p.score)
        ranks = {p.id: i + 1 for i, p in enumerate(order)}

        rec = RoundRecord(
            index=self.round,
            question_id=q.id,
            kind=q.kind,
            type=q.type,
            prompt=q.prompt,
            reveal=q.reveal,
            correct=q.answer,
            text=q.text,
            options=list(q.options) if q.options else None,
            context=([c.model_dump(by_alias=True) for c in q.context]
                     if q.context else None),
            format=q.format,
            origin=q.origin,
            area=q.area,
            results={
                p.id: PlayerResult(
                    answer=p.answer,
                    points=scores.get(p.id, (0.0, 0))[1],
                    accuracy=round(scores.get(p.id, (0.0, 0))[0], 3),
                    elapsed=round(max(0.0, (p.answered_at or self.ends_at or started) - started), 2),
                    rank_after=ranks[p.id],
                    stake=p.stake if q.type == "wager" else None,
                )
                for p in self.players.values()
            },
        )
        self.log.append(rec)
        return rec

    def _grade_mutual(self) -> dict[str, tuple[float, int]]:
        """No correct answer — you score by matching the other players."""
        live = [p for p in self.live() if p.answer is not None]
        out: dict[str, tuple[float, int]] = {}
        for p in self.players.values():
            others = [o for o in live if o.id != p.id]
            if p.answer is None or not others:
                out[p.id] = (0.0, 0)
                continue
            matched = sum(1 for o in others if o.answer == p.answer)
            acc = matched / len(others)
            out[p.id] = (acc, round(MUTUAL_POINTS * acc))
        return out

    def _grade_wager(self) -> dict[str, tuple[float, int]]:
        """Win the stake or lose it. No speed bonus — the decision is the round.

        A loss cannot take anyone below zero. There is no round after this one
        to win it back, and a negative number on the last screen of the night
        is a worse ending than a small one.
        """
        q = self.question
        assert q is not None
        out: dict[str, tuple[float, int]] = {}
        for p in self.players.values():
            stake = p.stake or 0
            if p.answer is None:
                out[p.id] = (0.0, 0)
                continue
            right = p.answer == q.answer
            out[p.id] = (1.0 if right else 0.0,
                         stake if right else -min(stake, p.score))
        return out

    # ── snapshot ──────────────────────────────────────────────────────────

    def snapshot(self, now: float | None = None) -> dict:
        """What both clients see. Never leaks an answer before the reveal."""
        q = self.question
        revealed = self.phase in ("reveal", "final")
        pub = None
        if q and self.phase in ("countdown", "question", "reveal"):
            pub = {
                "type": q.type,
                "kind": q.kind,
                "prompt": q.prompt,
                "format": q.format,
            }
            if q.text is not None:
                pub["text"] = q.text
            if q.options is not None:
                pub["options"] = q.options
            if q.unit is not None:
                pub["unit"] = q.unit
            # A flag, not the bytes. The picture is 120 KB and this dict goes
            # out on every heartbeat; the client fetches /photo/current once.
            if q.photo is not None:
                pub["photo"] = True
            # Only sent when it's off — the slider draws the histogram unless
            # told not to, and a question whose answer is the density array
            # would be giving itself away (schema.Question.histogram).
            if not q.histogram:
                pub["histogram"] = False
            if revealed:
                pub["answer"] = q.answer
                pub["reveal"] = q.reveal
                # Only at the reveal. The thread around the source message
                # would hand the answer over if it arrived with the question.
                if q.context:
                    pub["context"] = [c.model_dump(by_alias=True)
                                      for c in q.context]

        board = sorted(self.players.values(), key=lambda p: -p.score)
        started = self.question_started_at
        return {
            "t": "state",
            "phase": self.phase,
            "code": self.code,
            "round": self.round,
            "rounds": len(self.deck) or self.rounds,
            "seconds": self.seconds,
            "endsAt": self.ends_at,
            "now": now if now is not None else time.time(),
            "question": pub,
            "answered": [p.id for p in self.players.values() if p.answer is not None],
            "players": [
                {
                    "id": p.id, "name": p.name, "color": p.color,
                    "score": p.score, "online": p.online,
                    # How long they took, for the read-receipt state (S3.3).
                    # Speed is public — the host screen says "locked in 3.2s"
                    # on purpose. *Whether it was right* is not, and isn't
                    # here: the tension between "she answered fast" and "was
                    # she right" is the whole hook (DESIGN 2.4).
                    **({"took": round(p.answered_at - started, 2)}
                       if p.answered_at is not None and started else {}),
                    **({"last": p.last} if revealed else {}),
                }
                for p in board
            ],
            "meta": {
                "p1": self.meta.p1,
                "p2": self.meta.p2,
                "months": self.meta.months,
                "density": self.meta.density,
                "total": self.meta.total,
                "first": self.meta.first,
                "last": self.meta.last,
            },
        }

    # ── transitions (the clock lives in main.py) ───────────────────────────

    def begin_round(self, index: int) -> None:
        self.round = index
        self.phase = "countdown"
        self.ends_at = None
        for p in self.players.values():
            p.answer = None
            p.answered_at = None
            p.last = None
            p.stake = None

    def open_question(self, now: float | None = None) -> None:
        self.phase = "question"
        self.ends_at = (now if now is not None else time.time()) + self.seconds

    def close_question(self) -> RoundRecord:
        rec = self.grade()
        self.phase = "reveal"
        self.ends_at = None
        return rec

    def has_next(self) -> bool:
        return self.round + 1 < len(self.deck)

    def finish(self) -> None:
        self.phase = "final"
        self.ends_at = None
