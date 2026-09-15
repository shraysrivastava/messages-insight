#!/usr/bin/env python3
"""
superlatives.py — the end-of-game awards, computed from the round log.

`Game.grade()` appends a `RoundRecord` for every round and nothing reads it
during play. This is the first thing that does — the awards, and `curve()`,
which is the same log read as a shape instead of a verdict (`S4.1`). They
share `Tally`, which already had to compute a running score to know who was
ever ahead. Everything here is a pure function over `list[RoundRecord]`: no
clock, no sockets, no `Game`. That is
deliberate — an award that misfires on the night is worse than no award, and
the only way to know it doesn't is to run it against a log you wrote by hand.

Three rules, from docs/DESIGN.md §3:

**Every award needs a threshold.** "Fastest Finger" off a 0.1s difference is
not a joke, it's a rounding error. Each evaluator returns `None` unless the
margin clears a stated bar.

**Ties go unawarded.** Silence beats a limp award.

**Deal 4-6, not all of them.** Every award reports how decisively it fired;
`award()` takes the top few. Different games surface different awards, which
is what makes them feel earned rather than issued.

Two awards in the design catalog are not here: **All In** and **Ice in the
Veins**, both of which need the size of a Final Receipt wager. `PlayerResult`
records the answer, not the stake, so they cannot be computed yet — they
arrive with the field, when `wager` joins `PLAYABLE` in game.py.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

from app.game import RoundRecord

# A hit. Exact types are 1.0 or 0.0, so this only bites on the graded ones,
# where it is a judgement call: a month guess two months out scores points and
# should not also be called "correct" in a streak award.
HIT = 0.7

# Types whose accuracy is graded on a curve rather than being right or wrong.
GRADED = {"number", "month", "percent"}

# Kinds that earn the Sentimental award. Unknown labels simply never fire it,
# so a new kind in the bank costs nothing here.
SOFT_KINDS = frozenset({
    "First time we said it", "Soft launch", "The distance", "In sickness",
    "Character witness", "Deep cut", "Five minutes away",
})

PETTY = "Petty grievances"

# The last few seconds of the clock, for Buzzer Beater.
BUZZER = 3.0


@dataclass(frozen=True)
class Award:
    """One fired award. `winners` is a tuple because two of them are shared."""
    key: str
    title: str
    winners: tuple[str, ...]
    evidence: str
    decisiveness: float

    @property
    def winner(self) -> str:
        return self.winners[0]


@dataclass
class Tally:
    """Everything the evaluators need, computed once.

    `log` is the whole game; `pids` is every player who was present for any
    round. A player who joined late simply has no result in the rounds before
    they arrived, and every accessor below treats that as "did not answer"
    rather than as a zero — being absent is not the same as being wrong.
    """
    log: list[RoundRecord]
    names: dict[str, str]
    seconds: float
    pids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        seen: list[str] = []
        for r in self.log:
            for pid in r.results:
                if pid not in seen:
                    seen.append(pid)
        # Anyone the caller named but who never played is still a player; the
        # lobby knew about them. Order is stable so evidence strings are too.
        for pid in self.names:
            if pid not in seen:
                seen.append(pid)
        self.pids = seen

    # ── the primitives ────────────────────────────────────────────────────

    def name(self, pid: str) -> str:
        return self.names.get(pid, pid)

    def rounds(self, pred: Callable[[RoundRecord], bool] | None = None) -> list[RoundRecord]:
        return [r for r in self.log if pred is None or pred(r)]

    def result(self, r: RoundRecord, pid: str):
        return r.results.get(pid)

    def answered(self, r: RoundRecord, pid: str) -> bool:
        res = self.result(r, pid)
        return res is not None and res.answer is not None

    def hit(self, r: RoundRecord, pid: str) -> bool:
        res = self.result(r, pid)
        if res is None or res.answer is None:
            return False
        return res.accuracy >= (HIT if r.type in GRADED else 0.999)

    def points(self, r: RoundRecord, pid: str) -> int:
        res = self.result(r, pid)
        return res.points if res else 0

    def running(self) -> dict[str, list[int]]:
        """Cumulative score after each round, per player.

        Used instead of `rank_after` wherever an award turns on who was ahead.
        `rank_after` has to break ties somehow, and every award that cares
        about a lead should treat a tie as nobody leading."""
        out = {pid: [] for pid in self.pids}
        total = {pid: 0 for pid in self.pids}
        for r in self.log:
            for pid in self.pids:
                total[pid] += self.points(r, pid)
                out[pid].append(total[pid])
        return out

    def final(self) -> dict[str, int]:
        run = self.running()
        return {pid: (v[-1] if v else 0) for pid, v in run.items()}

    def leader_after(self, i: int) -> str | None:
        """Who led after round `i`, or None if it was level."""
        run = self.running()
        standing = sorted(((v[i], pid) for pid, v in run.items() if i < len(v)),
                          reverse=True)
        if len(standing) < 2:
            return standing[0][1] if standing else None
        if standing[0][0] == standing[1][0]:
            return None
        return standing[0][1]

    def champion(self) -> str | None:
        return self.leader_after(len(self.log) - 1) if self.log else None

    # ── the shape most awards take: best mean of something ────────────────

    def best_mean(self, value: Callable[[RoundRecord, str], float | None],
                  pred: Callable[[RoundRecord], bool] | None = None,
                  least: bool = False, minimum: int = 1,
                  ) -> tuple[str, float, float, int] | None:
        """Return (pid, their mean, the gap to the runner-up, sample size).

        `None` when fewer than two players qualify or the top two are exactly
        level — which is the tie rule, enforced in one place rather than
        twenty."""
        means: list[tuple[float, str, int]] = []
        for pid in self.pids:
            vals = [v for r in self.rounds(pred)
                    if (v := value(r, pid)) is not None]
            if len(vals) >= minimum:
                means.append((statistics.fmean(vals), pid, len(vals)))
        if len(means) < 2:
            return None
        means.sort(reverse=not least)
        (top, pid, n), (second, _, _) = means[0], means[1]
        gap = abs(top - second)
        if gap == 0:
            return None
        return pid, top, gap, n

    def best_count(self, value: Callable[[RoundRecord, str], bool],
                   pred: Callable[[RoundRecord], bool] | None = None,
                   ) -> tuple[str, int, int] | None:
        """Return (pid, their count, the gap to the runner-up). Ties unawarded."""
        counts = sorted(((sum(1 for r in self.rounds(pred) if value(r, pid)), pid)
                         for pid in self.pids), reverse=True)
        if len(counts) < 2 or counts[0][0] == counts[1][0] or counts[0][0] == 0:
            return None
        return counts[0][1], counts[0][0], counts[0][0] - counts[1][0]


def _secs(x: float) -> str:
    return f"{x:.1f}s"


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


# ── the catalog ───────────────────────────────────────────────────────────
#
# Each evaluator takes a Tally and returns an Award or None. They are listed in
# no particular order; `award()` ranks what fired by decisiveness.

def fastest_finger(t: Tally) -> Award | None:
    got = t.best_mean(lambda r, p: t.result(r, p).elapsed if t.answered(r, p) else None,
                      least=True, minimum=3)
    if not got:
        return None
    pid, mean, gap, n = got
    if gap < 1.5:
        return None
    return Award("fastest_finger", "Fastest Finger", (pid,),
                 f"{t.name(pid)}, {_secs(mean)} average — {_secs(gap)} faster than you",
                 gap / 1.5)


def overthinker(t: Tally) -> Award | None:
    got = t.best_mean(lambda r, p: t.result(r, p).elapsed if t.hit(r, p) else None,
                      minimum=3)
    if not got:
        return None
    pid, mean, gap, n = got
    if gap < 2.0:
        return None
    return Award("overthinker", "The Overthinker", (pid,),
                 f"{t.name(pid)} took {_secs(mean)} on the {n} they got right",
                 gap / 2.0)


def buzzer_beater(t: Tally) -> Award | None:
    late = lambda r, p: (t.answered(r, p)
                         and t.result(r, p).elapsed >= t.seconds - BUZZER)
    got = t.best_count(late)
    if not got:
        return None
    pid, n, gap = got
    if n < 3:
        return None
    return Award("buzzer_beater", "Buzzer Beater", (pid,),
                 f"{t.name(pid)} answered {n} rounds in the last {BUZZER:.0f} seconds",
                 n / 3)


def panic_button(t: Tally) -> Award | None:
    worst: tuple[float, str, RoundRecord] | None = None
    for r in t.log:
        for pid in t.pids:
            res = t.result(r, pid)
            if res is None or res.answer is None or res.points > 0:
                continue
            if worst is None or res.elapsed < worst[0]:
                worst = (res.elapsed, pid, r)
    if worst is None or worst[0] > 2.0:
        return None
    elapsed, pid, r = worst
    return Award("panic_button", "Panic Button", (pid,),
                 f"{t.name(pid)} locked in after {_secs(elapsed)} on “{r.kind}” "
                 f"and scored nothing",
                 (2.0 - elapsed) / 2.0 + 0.5)


def clairvoyant(t: Tally) -> Award | None:
    exact = lambda r, p: (t.result(r, p) is not None
                          and t.result(r, p).accuracy >= 0.999)
    got = t.best_count(exact, lambda r: r.type == "month")
    if not got:
        return None
    pid, n, gap = got
    return Award("clairvoyant", "Clairvoyant", (pid,),
                 f"{t.name(pid)} named the exact month {n}×",
                 1.0 + n * 0.5)


def historian(t: Tally) -> Award | None:
    return _accuracy_award(t, "month", "historian", "The Historian",
                           "month rounds")


def accountant(t: Tally) -> Award | None:
    return _accuracy_award(t, "number", "accountant", "The Accountant",
                           "the numbers")


def _accuracy_award(t: Tally, qtype: str, key: str, title: str,
                    label: str) -> Award | None:
    got = t.best_mean(lambda r, p: t.result(r, p).accuracy if t.result(r, p) else None,
                      lambda r: r.type == qtype, minimum=3)
    if not got:
        return None
    pid, mean, gap, n = got
    if gap < 0.15:
        return None
    return Award(key, title, (pid,),
                 f"{t.name(pid)} averaged {_pct(mean)} across {n} {label}",
                 gap / 0.15)


def mind_reader(t: Tally) -> Award | None:
    """"Who said it" rounds. The bank names them `who-*` by convention — the
    same convention the fairness guards in compile.py key off."""
    who = lambda r: r.question_id.startswith("who")
    n_rounds = len(t.rounds(who))
    if n_rounds < 4:
        return None
    got = t.best_mean(lambda r, p: (1.0 if t.hit(r, p) else 0.0) if t.result(r, p) else None,
                      who, minimum=4)
    if not got:
        return None
    pid, mean, gap, n = got
    if mean < 0.8:
        return None
    return Award("mind_reader", "Mind Reader", (pid,),
                 f"{t.name(pid)} got {round(mean * n)} of {n} right on who said it",
                 mean + gap)


def _longest_run(t: Tally, pid: str, pred: Callable[[RoundRecord, str], bool]) -> int:
    """Rounds the player was not in the room for are skipped, not counted.

    `points()` reads an absent result as zero, which is right for a scoreboard
    and wrong for a streak: it would hand Ice Cold to whoever joined late, for
    the rounds they missed. Absence neither extends a run nor breaks one."""
    best = run = 0
    for r in t.log:
        if t.result(r, pid) is None:
            continue
        run = run + 1 if pred(r, pid) else 0
        best = max(best, run)
    return best


def ice_cold(t: Tally) -> Award | None:
    runs = sorted(((_longest_run(t, pid, lambda r, p: t.points(r, p) == 0), pid)
                   for pid in t.pids), reverse=True)
    if len(runs) < 2 or runs[0][0] < 3 or runs[0][0] == runs[1][0]:
        return None
    n, pid = runs[0]
    return Award("ice_cold", "Ice Cold", (pid,),
                 f"{t.name(pid)} went {n} rounds without a single point",
                 n / 3)


def on_fire(t: Tally) -> Award | None:
    runs = sorted(((_longest_run(t, pid, t.hit), pid) for pid in t.pids),
                  reverse=True)
    if len(runs) < 2 or runs[0][0] < 4 or runs[0][0] == runs[1][0]:
        return None
    n, pid = runs[0]
    return Award("on_fire", "On Fire", (pid,),
                 f"{t.name(pid)} got {n} in a row",
                 n / 4)


def comeback_kid(t: Tally) -> Award | None:
    champ = t.champion()
    if champ is None or len(t.log) < 4:
        return None
    run = t.running()
    worst = 0
    for i in range(len(t.log) - 1):
        best_other = max((v[i] for pid, v in run.items() if pid != champ), default=0)
        worst = max(worst, best_other - run[champ][i])
    if worst < 1500:
        return None
    return Award("comeback_kid", "Comeback Kid", (champ,),
                 f"{t.name(champ)} was {worst:,} behind and still won",
                 worst / 1500)


def wire_to_wire(t: Tally) -> Award | None:
    champ = t.champion()
    if champ is None or len(t.log) < 4:
        return None
    if any(t.leader_after(i) != champ for i in range(len(t.log))):
        return None
    run = t.running()
    margin = run[champ][-1] - max((v[-1] for pid, v in run.items() if pid != champ),
                                  default=0)
    return Award("wire_to_wire", "Wire to Wire", (champ,),
                 f"{t.name(champ)} led after all {len(t.log)} rounds",
                 1.5 + margin / 5000)


def quietly_devastating(t: Tally) -> Award | None:
    champ = t.champion()
    if champ is None or len(t.log) < 4:
        return None
    if any(t.leader_after(i) == champ for i in range(len(t.log) - 1)):
        return None
    return Award("quietly_devastating", "Quietly Devastating", (champ,),
                 f"{t.name(champ)} never led once until the final round",
                 1.8)


def same_page(t: Tally) -> Award | None:
    mutual = t.rounds(lambda r: r.type == "mutual")
    if not mutual:
        return None
    got = t.best_mean(lambda r, p: (1.0 if t.points(r, p) > 0 else 0.0)
                      if t.result(r, p) else None,
                      lambda r: r.type == "mutual", minimum=1)
    if not got:
        return None
    pid, mean, gap, n = got
    if mean < 0.6:
        return None
    return Award("same_page", "Same Page", (pid,),
                 f"{t.name(pid)} matched on {round(mean * n)} of {n} Same Page rounds",
                 mean + gap)


def split_brain(t: Tally) -> Award | None:
    """Both of you, wrong, in exactly the same way. Shared by definition."""
    if len(t.pids) < 2:
        return None
    hits = []
    for r in t.log:
        answers = [t.result(r, p) for p in t.pids]
        if any(a is None or a.answer is None or a.points > 0 for a in answers):
            continue
        first = answers[0].answer
        if all(a.answer == first for a in answers):
            hits.append(r)
    if len(hits) < 2:
        return None
    return Award("split_brain", "Split Brain", tuple(t.pids),
                 f"{len(hits)} rounds where you both gave the same wrong answer",
                 len(hits) / 2)


def sniper(t: Tally) -> Award | None:
    best: tuple[float, str, RoundRecord] | None = None
    for r in t.rounds(lambda r: r.type == "number"):
        if not isinstance(r.correct, (int, float)):
            continue
        for pid in t.pids:
            res = t.result(r, pid)
            if res is None or not isinstance(res.answer, (int, float)):
                continue
            off = abs(res.answer - r.correct) / max(abs(r.correct), 1)
            if best is None or off < best[0]:
                best = (off, pid, r)
    if best is None or best[0] > 0.05:
        return None
    off, pid, r = best
    return Award("sniper", "The Sniper", (pid,),
                 f"{t.name(pid)} guessed {t.result(r, pid).answer:,} — "
                 f"the answer was {r.correct:,}",
                 1.0 + (0.05 - off) * 10)


def wildly_optimistic(t: Tally) -> Award | None:
    worst: tuple[float, str, RoundRecord] | None = None
    for r in t.rounds(lambda r: r.type == "number"):
        if not isinstance(r.correct, (int, float)) or r.correct <= 0:
            continue
        for pid in t.pids:
            res = t.result(r, pid)
            if res is None or not isinstance(res.answer, (int, float)):
                continue
            ratio = res.answer / r.correct
            if ratio >= 4 and (worst is None or ratio > worst[0]):
                worst = (ratio, pid, r)
    if worst is None:
        return None
    ratio, pid, r = worst
    return Award("wildly_optimistic", "Wildly Optimistic", (pid,),
                 f"{t.name(pid)} guessed {t.result(r, pid).answer:,} — "
                 f"{ratio:.0f}× the real {r.correct:,}",
                 ratio / 4)


def sentimental(t: Tally) -> Award | None:
    return _kind_award(t, lambda r: r.kind in SOFT_KINDS, "sentimental",
                       "Sentimental", "the soft rounds")


def realist(t: Tally) -> Award | None:
    return _kind_award(t, lambda r: r.kind == PETTY, "realist",
                       "The Realist", f"“{PETTY}”")


def _kind_award(t: Tally, pred: Callable[[RoundRecord], bool], key: str,
                title: str, label: str) -> Award | None:
    if len(t.rounds(pred)) < 3:
        return None
    got = t.best_mean(lambda r, p: t.result(r, p).accuracy if t.result(r, p) else None,
                      pred, minimum=3)
    if not got:
        return None
    pid, mean, gap, n = got
    if gap < 0.15:
        return None
    return Award(key, title, (pid,),
                 f"{t.name(pid)} averaged {_pct(mean)} on {label}",
                 gap / 0.15)


def the_constant(t: Tally) -> Award | None:
    spread: list[tuple[float, str]] = []
    for pid in t.pids:
        pts = [t.points(r, pid) for r in t.log if t.points(r, pid) > 0]
        if len(pts) >= 8:
            spread.append((statistics.pstdev(pts), pid))
    if len(spread) < 2:
        return None
    spread.sort()
    if spread[0][0] == spread[1][0]:
        return None
    sd, pid = spread[0]
    return Award("the_constant", "The Constant", (pid,),
                 f"{t.name(pid)} scored within ±{sd:.0f} of the same number all game",
                 (spread[1][0] - sd) / max(sd, 1))


CATALOG: list[Callable[[Tally], Award | None]] = [
    fastest_finger, overthinker, buzzer_beater, panic_button, clairvoyant,
    historian, accountant, mind_reader, ice_cold, on_fire, comeback_kid,
    wire_to_wire, quietly_devastating, same_page, split_brain, sniper,
    wildly_optimistic, sentimental, realist, the_constant,
]


def award(log: list[RoundRecord], names: dict[str, str], seconds: float = 25.0,
          limit: int = 5) -> list[Award]:
    """Every award that fired, most decisive first, capped at `limit`.

    An evaluator that raises is skipped rather than allowed to take the podium
    down with it. The awards are the last screen of the night; a `None` where a
    number was expected is not worth losing it over."""
    fired: list[Award] = []
    t = Tally(log=list(log), names=dict(names), seconds=seconds)
    for fn in CATALOG:
        try:
            a = fn(t)
        except Exception:
            continue
        if a is not None:
            fired.append(a)
    fired.sort(key=lambda a: -a.decisiveness)
    return fired[:limit]


def as_dict(a: Award) -> dict[str, Any]:
    """The wire shape. The host screen deals these as cards."""
    return {"key": a.key, "title": a.title, "winners": list(a.winners),
            "evidence": a.evidence}


# ── the score graph (S4.1) ────────────────────────────────────────────────
#
# Lives here rather than in a module of its own because `Tally.running()` is
# exactly the series it needs, and a second file computing the same cumulative
# scores is how the graph and the awards start disagreeing about who won.


@dataclass(frozen=True)
class Line:
    pid: str
    name: str
    points: tuple[int, ...]          # cumulative, one per round played


@dataclass(frozen=True)
class Curve:
    """Everything the SVG needs, already decided. The client draws; it does not
    work out who was leading."""
    rounds: int
    lines: tuple[Line, ...]
    leads: tuple[int, ...]           # rounds where the lead changed hands
    best_round: int | None           # the biggest single round of the game
    best_pid: str | None
    best_points: int
    high: int                        # the y axis, i.e. the winning score


def curve(log: list[RoundRecord], names: dict[str, str]) -> Curve:
    t = Tally(log=list(log), names=dict(names), seconds=0.0)
    run = t.running()
    lines = tuple(Line(pid=pid, name=t.name(pid), points=tuple(run[pid]))
                  for pid in t.pids)

    # A lead change is a change in *who* is ahead, and level is nobody. Coming
    # back to level and then retaking it is one change, not two, or a close
    # game turns into a dotted line.
    leads: list[int] = []
    prev: str | None = None
    for i in range(len(log)):
        who = t.leader_after(i)
        if who is not None and prev is not None and who != prev:
            leads.append(i)
        if who is not None:
            prev = who

    best_round = best_pid = None
    best_points = 0
    for r in log:
        for pid in t.pids:
            pts = t.points(r, pid)
            if pts > best_points:
                best_points, best_round, best_pid = pts, r.index, pid

    high = max((l.points[-1] for l in lines if l.points), default=0)
    return Curve(rounds=len(log), lines=lines, leads=tuple(leads),
                 best_round=best_round, best_pid=best_pid,
                 best_points=best_points, high=high)


def curve_dict(c: Curve) -> dict[str, Any]:
    return {
        "rounds": c.rounds,
        "lines": [{"pid": l.pid, "name": l.name, "points": list(l.points)}
                  for l in c.lines],
        "leads": list(c.leads),
        "best": ({"round": c.best_round, "pid": c.best_pid,
                  "points": c.best_points} if c.best_pid else None),
        "high": c.high,
    }
