import random

import pytest

from app.game import DealRules, Game
from app.schema import Dataset

MONTHS = [f"2021-{m:02d}" for m in range(3, 13)] + \
         [f"{y}-{m:02d}" for y in (2022, 2023) for m in range(1, 13)]


def q(id, type="binary", kind="k", answer=0, origin="auto", **kw):
    base = dict(id=id, type=type, kind=kind, prompt="p?", reveal="r.", answer=answer,
                origin=origin)
    if type in ("binary", "choice", "wager", "mutual"):
        base["options"] = kw.pop("options", ["A", "B"])
    if type == "mutual":
        base["answer"] = None
    base.update(kw)
    return base


def make_dataset(questions=None, rounds=4, months=None):
    questions = questions or [q(f"q{i}", kind=f"k{i%3}") for i in range(12)]
    return Dataset.model_validate({
        "meta": {"p1": "Shray", "p2": "Nilu", "months": months or MONTHS,
                 "rounds": rounds, "seconds": 20.0},
        "questions": questions,
    })


@pytest.fixture
def game():
    g = Game(make_dataset(), rng=random.Random(7))
    g.add_player("a", "Shray")
    g.add_player("b", "Nilu")
    return g
