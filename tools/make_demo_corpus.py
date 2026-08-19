#!/usr/bin/env python3
"""
make_demo_corpus.py — a fake corpus.json with the same shape as the real one.

    python3 tools/make_demo_corpus.py --out demo_corpus.json

Exists so the entire pipeline — compile, mine, curate, the game itself — can be
built and tested before anyone touches chat.db. It deliberately plants the
phrases the lexicons look for, with plausible first-use dates and lopsided
per-sender habits, so every resolver has something real to chew on.

The output feeds `compile.py` to produce datasets/demo.json, which is the safe
dataset that ships publicly.
"""

from __future__ import annotations

import argparse
import json
import random

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from tools.extract import build_corpus

CHATTER = [
    "ok but you have to admit the second one was better than the first",
    "i cannot stop thinking about those dumplings we had on tuesday",
    "im on the train now should be home in like forty minutes",
    "you left your charger here again this is the third time this month",
    "watching that documentary you told me about and youre completely right",
    "can we please go back to that place with the tiny chairs",
    "i told my mom about the thing and she is unreasonably excited",
    "the cat next door was on our windowsill again staring at me judgmentally",
    "reading your text from this morning again because it made my whole day",
    "sorry i fell asleep mid sentence apparently that was very rude of me",
    "we are never letting me pick the restaurant again after that",
    "i keep laughing about what you said in the car yesterday",
    "genuinely obsessed with the playlist you made me last weekend",
    "come outside i have something ridiculous to show you right now",
    "you were right about the shoes and i hate admitting it",
    "why did nobody tell me the season finale was going to do that",
    "im making the pasta tonight the one with too much lemon",
    "just got out of the meeting and it went so much better than expected",
    "found an old picture of us from that first summer and im emotional",
    "please remind me to actually book the tickets this time",
    "the flight got delayed two hours so im just sitting at the gate",
    "my boss scheduled another meeting that couldve been an email",
    "its raining so hard here i can barely see across the street",
    "i think im getting sick my throat has been weird all day",
    "venmo'd you for the tickets let me know if thats wrong",
    "traffic was insane i am going to be like fifteen minutes late",
    "one more episode and then i swear im going to bed",
    "the dog would not stop barking at absolutely nothing for an hour",
    "i found the exact lamp we were looking at but its expensive",
    "everyone at dinner asked about you and i talked for too long",
]

# phrase -> (month offset of first use, how often after that)
PLANTED = {
    "goodnight": (1, 0.10),
    "good morning": (1, 0.09),
    "i love you": (7, 0.06),
    "miss you": (4, 0.05),
    "sorry": (2, 0.04),
    "thank you": (1, 0.05),
    "cant wait to see you": (5, 0.03),
    "when do you land": (9, 0.015),
    "our place": (26, 0.02),
    "move in": (24, 0.01),
    "marry": (33, 0.006),
    "one day": (14, 0.012),
    "obsessed": (11, 0.02),
    "forever": (20, 0.008),
    "youre the best": (6, 0.02),
    "my parents": (8, 0.012),
}
EMOJI = ["😭", "🥺", "😂", "❤️", "🙃", "🫠", "💀", "🥰"]

# Real threads are mostly short. Without these the corpus has no one-word
# replies, which starves half the stats and all of the "what did she say next".
SHORT = ["ok", "yeah", "haha", "no", "wait", "same", "stop", "please", "why",
         "on my way", "five minutes", "i know", "me too", "so good", "not true",
         "absolutely not", "you're kidding", "obviously", "fine", "deal"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="demo_corpus.json")
    ap.add_argument("--p1", default="Alex")
    ap.add_argument("--p2", default="Sam")
    ap.add_argument("--months", type=int, default=66)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    start = datetime(2021, 3, 1, 9, 0, tzinfo=timezone.utc).astimezone()
    messages: list[dict] = []

    for month in range(args.months):
        # volume swells and dips over the years so the density histogram has shape
        base = 55 + int(40 * (month / args.months)) + rng.randint(-18, 25)
        for _ in range(max(12, base)):
            day = rng.randint(0, 27)
            hour = rng.choices(range(24), weights=(
                [2, 1, 1, 1, 1, 1] + [4, 8, 9, 7, 6, 7] +
                [8, 7, 6, 6, 7, 9] + [12, 14, 13, 10, 6, 3]))[0]
            when = start + timedelta(days=month * 30 + day,
                                     hours=hour - 9, minutes=rng.randint(0, 59))
            # p2 texts a bit more, and at greater length — gives who_more a margin
            who = "p2" if rng.random() < 0.54 else "p1"
            text = rng.choice(SHORT) if rng.random() < 0.38 else rng.choice(CHATTER)

            for phrase, (first_m, rate) in PLANTED.items():
                if month >= first_m and rng.random() < rate:
                    text = f"{phrase} {text}" if rng.random() < 0.5 else f"{text} {phrase}"
                    break

            if who == "p2" and rng.random() < 0.30:
                text += " " + rng.choice(EMOJI)
            elif rng.random() < 0.10:
                text += " " + rng.choice(EMOJI[:3])
            if who == "p1" and rng.random() < 0.18:
                text += " lol"
            if who == "p2" and rng.random() < 0.12:
                text += " haha"

            messages.append({"i": 0, "ts": when.isoformat(), "from": who, "text": text,
                             **({"att": 1} if rng.random() < 0.05 else {})})

    messages.sort(key=lambda m: m["ts"])
    for i, m in enumerate(messages):
        m["i"] = i

    corpus = build_corpus(messages, args.p1, args.p2)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False)

    meta = corpus["meta"]
    print(f"  {meta['total']:,} fake messages · {meta['first']} – {meta['last']} "
          f"· {len(meta['months'])} months")
    print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
