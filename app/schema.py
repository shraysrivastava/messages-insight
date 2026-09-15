"""
schema.py — the data contract, enforced.

Everything the server and both clients ever see is one compiled JSON file. This
module is the only definition of what that file may contain. `compile.py` writes
it, `validate.py` checks it, and `main.py` refuses to boot without it.

Fail here, loudly, at compile time. The alternative is finding out at round 9
that a month answer was out of range.

    from app.schema import Dataset
    Dataset.model_validate_json(open("datasets/demo.json").read())
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Mechanics. Adding one means touching accuracy() in game.py and both clients.
QType = Literal["binary", "choice", "number", "month", "percent", "wager", "mutual"]

# Rendering hints. Unknown values fall back to "bubble" on the client, so a new
# format can never break a game — but we still enumerate the known ones here so
# a typo gets caught at compile time rather than silently rendering plain.
QFormat = Literal["bubble", "blank", "redacted", "compare", "thread", "timestamp"]

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Types whose `answer` is an index into `options`.
INDEXED = {"binary", "choice", "wager"}


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p1: str
    p2: str
    months: list[str] = Field(min_length=2)
    density: list[int] | None = None
    rounds: int = Field(default=14, ge=1, le=50)
    seconds: float = Field(default=25.0, gt=0, le=300)
    total: int | None = None
    first: str | None = None
    last: str | None = None

    @model_validator(mode="after")
    def _months_contiguous(self) -> "Meta":
        """`months` is the slider domain and `month` answers index into it. If it
        has a hole, every answer after the hole points at the wrong month."""
        bad = [m for m in self.months if not MONTH_RE.match(m)]
        if bad:
            raise ValueError(f"months must be YYYY-MM, got {bad[:3]}")
        if self.months != sorted(self.months):
            raise ValueError("months must be ascending")

        def nxt(m: str) -> str:
            y, mo = (int(x) for x in m.split("-"))
            return f"{y + 1}-01" if mo == 12 else f"{y}-{mo + 1:02d}"

        for a, b in zip(self.months, self.months[1:]):
            if nxt(a) != b:
                raise ValueError(f"months not contiguous: {a} -> {b}")

        if self.density is not None and len(self.density) != len(self.months):
            raise ValueError(
                f"density has {len(self.density)} entries "
                f"for {len(self.months)} months"
            )
        if self.p1.strip().upper() == "TODO" or self.p2.strip().upper() == "TODO":
            raise ValueError("player names still say TODO — set them in questions/config.toml")
        return self


class ContextMsg(BaseModel):
    """One message in a reveal's context thread. Deliberately thin: who, what,
    and whether this is the one the question was about."""
    # `self` is the field name the reveal wants and a Python keyword, so it is
    # aliased; populate_by_name lets both spellings in.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    who: Literal["p1", "p2"]
    text: Annotated[str, Field(min_length=1)]
    self_: bool = Field(default=False, alias="self")


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: QType
    kind: Annotated[str, Field(min_length=1)]
    prompt: Annotated[str, Field(min_length=1)]
    reveal: Annotated[str, Field(min_length=1)]
    answer: Any = None
    text: str | None = None
    options: list[str] | None = None
    unit: str | None = None
    area: str | None = None
    format: QFormat = "bubble"

    # The month slider draws `meta.density` behind it. A question whose answer
    # *is* that array ("which month did we text the least?") must not, or the
    # picture answers it. compile.py sets this from the resolver.
    histogram: bool = True

    # The few messages either side of the one this question came from. The
    # reveal draws them as a small thread with the source highlighted, which
    # is the difference between "the answer was pasta" and the actual evening
    # in May 2023 when you said it (DESIGN 2.5).
    context: list["ContextMsg"] | None = None

    # Provenance, carried through so the dealer can prefer authored questions
    # and the history log can say where a round came from.
    origin: Literal["mine", "auto"] = "auto"
    topic: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> "Question":
        t = self.type

        if "TODO" in f"{self.prompt}{self.reveal}{self.text or ''}{self.options or ''}":
            raise ValueError(f"{self.id}: still contains TODO")

        if t in INDEXED or t == "mutual":
            if not self.options or not (2 <= len(self.options) <= 4):
                raise ValueError(f"{self.id}: {t} needs 2-4 options")
            if len({o.strip().lower() for o in self.options}) != len(self.options):
                raise ValueError(f"{self.id}: options collide after normalisation")
            if t == "binary" and len(self.options) != 2:
                raise ValueError(f"{self.id}: binary needs exactly 2 options")
        elif self.options:
            raise ValueError(f"{self.id}: {t} must not carry options")

        # `mutual` is scored by whether the players match each other, so it is
        # the one type with no correct answer.
        if t == "mutual":
            if self.answer is not None:
                raise ValueError(f"{self.id}: mutual has no correct answer")
            return self

        if self.answer is None:
            raise ValueError(f"{self.id}: missing answer")

        if t in INDEXED:
            if not isinstance(self.answer, int) or isinstance(self.answer, bool):
                raise ValueError(f"{self.id}: {t} answer must be an option index")
            if not 0 <= self.answer < len(self.options or []):
                raise ValueError(
                    f"{self.id}: answer {self.answer} out of range "
                    f"for {len(self.options or [])} options"
                )
        elif t == "number":
            if not isinstance(self.answer, (int, float)) or isinstance(self.answer, bool):
                raise ValueError(f"{self.id}: number answer must be numeric")
            if self.answer < 0:
                raise ValueError(f"{self.id}: number answer must be >= 0")
        elif t == "percent":
            if not isinstance(self.answer, (int, float)) or isinstance(self.answer, bool):
                raise ValueError(f"{self.id}: percent answer must be numeric")
            if not 0 <= self.answer <= 100:
                raise ValueError(f"{self.id}: percent answer must be 0-100")
        elif t == "month":
            if not isinstance(self.answer, int) or isinstance(self.answer, bool):
                raise ValueError(f"{self.id}: month answer must be an index into meta.months")

        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: Meta
    questions: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross(self) -> "Dataset":
        n = len(self.meta.months)
        ids: set[str] = set()
        for q in self.questions:
            if q.id in ids:
                raise ValueError(f"duplicate question id: {q.id}")
            ids.add(q.id)
            if q.type == "month" and not 0 <= q.answer < n:
                raise ValueError(
                    f"{q.id}: month answer {q.answer} outside 0..{n - 1}"
                )
        if len(self.questions) < self.meta.rounds:
            raise ValueError(
                f"only {len(self.questions)} questions for {self.meta.rounds} rounds"
            )
        return self

    # Convenience for the dealer and the status dashboard.
    @property
    def by_origin(self) -> dict[str, int]:
        out = {"mine": 0, "auto": 0}
        for q in self.questions:
            out[q.origin] += 1
        return out


def load(path: str) -> Dataset:
    """Read and validate a compiled dataset. Raises on anything malformed."""
    with open(path, encoding="utf-8") as f:
        return Dataset.model_validate_json(f.read())
