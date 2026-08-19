#!/usr/bin/env python3
"""
make_fake_data.py — a plausible game_data.json with invented messages.

Same shape as the real thing, so you can build and play the whole game
without ever opening chat.db.

    python3 make_fake_data.py --out game_data.json
"""

import argparse
import json
import random
from datetime import date

LINES = [
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
]

PHRASES = ["i love you", "miss you", "good morning", "goodnight", "promise"]
EMOJI = ["😭", "🥺", "😂", "❤️", "🙃", "🫠"]


def months_between(a, b):
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="game_data.json")
    ap.add_argument("--p1", default="Alex")
    ap.add_argument("--p2", default="Sam")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    months = months_between(date(2021, 3, 1), date(2026, 8, 1))
    qs = []

    for _ in range(8):
        line = rng.choice(LINES)
        who = rng.choice([args.p1, args.p2])
        qs.append({
            "type": "binary", "kind": "Who said it", "prompt": "Who sent this?",
            "text": line, "options": [args.p1, args.p2],
            "answer": 0 if who == args.p1 else 1,
            "reveal": f"{who} · {rng.choice(['March','July','October'])} "
                      f"{rng.randint(2021, 2026)}",
        })

    for _ in range(8):
        line = rng.choice(LINES)
        words = [w for w in line.split() if len(w) >= 5]
        if not words:
            continue
        target = rng.choice(words)
        pool = [w for ln in LINES for w in ln.split() if len(w) >= 5 and w != target]
        opts = rng.sample(sorted(set(pool)), 3) + [target]
        rng.shuffle(opts)
        qs.append({
            "type": "choice", "kind": "Fill in the blank",
            "prompt": f"{rng.choice([args.p1, args.p2])} sent this. "
                      "What's the missing word?",
            "text": line.replace(target, "▁▁▁▁▁", 1),
            "options": opts, "answer": opts.index(target),
            "reveal": f"“{line}”",
        })

    for prompt, ans, blurb in [
        ("How many messages have we sent each other, total?", 48213,
         "48,213 messages across 1,982 days."),
        ("What's the most messages we've sent in a single day?", 412,
         "412, on a Tuesday for no clear reason."),
        ("How many messages have we sent between midnight and 5am?", 3104,
         "3,104. Nothing good happens after 2am."),
        ("How many times have we said “I love you”?", 1877,
         "1,877 times, and counting."),
        ("How many times have we said “Sorry”?", 964,
         "964 apologies, give or take."),
    ]:
        qs.append({"type": "number", "kind": "Guess the number",
                   "prompt": prompt, "answer": ans, "reveal": blurb})

    for phrase in PHRASES:
        idx = rng.randrange(0, min(14, len(months)))
        qs.append({
            "type": "month", "kind": "First time we said it",
            "prompt": f"When did one of us first say “{phrase.capitalize()}”?",
            "text": rng.choice(LINES),
            "answer": idx,
            "reveal": f"{rng.choice([args.p1, args.p2])}, {months[idx]}",
        })

    for _ in range(6):
        idx = rng.randrange(len(months))
        qs.append({
            "type": "month", "kind": "Guess the date",
            "prompt": f"{rng.choice([args.p1, args.p2])} sent this. When?",
            "text": rng.choice(LINES), "answer": idx,
            "reveal": f"{months[idx]}",
        })

    opts = rng.sample(EMOJI, 4)
    qs.append({
        "type": "choice", "kind": "Top of the charts",
        "prompt": "Which emoji have we used the most?",
        "options": opts, "answer": 0,
        "reveal": f"{opts[0]} — 2,411 times. Runner-up: {opts[1]} at 1,802.",
    })

    data = {
        "meta": {"p1": args.p1, "p2": args.p2, "months": months,
                 "rounds": args.rounds, "total": 48213,
                 "first": "March 2021", "last": "August 2026"},
        "questions": qs,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"Wrote {args.out} — {len(qs)} fake questions, {args.rounds} per game.")


if __name__ == "__main__":
    main()
