# Read Receipts

A Kahoot-style guessing game built from five years of one iMessage thread. Big
screen hosts, phones play. Built for two people in two states, on one deployed
URL, for a 5-year meetaversary.

```
chat.db ──▶ corpus ──▶ candidates ──▶ your judgment ──▶ questions ──▶ a game
```

Your messages never leave your Mac. What reaches the server is ~90 snippets you
personally approved, encrypted, with the passphrase in your head rather than on
the host.

---

## Where things are

```
docs/       PLAN · DESIGN · QUESTIONS · STATUS · HANDOVER
questions/  the content — config, lexicons, mine.toml, auto/
tools/      extract · mine · curate · compile · seal · validate · status
app/        the server (stage 1)
static/     host screen, phone screen, styles
datasets/   demo.json (committed) · real.json.enc (committed, encrypted)
poc/        the original proof of concept, still runnable
```

## Where to start

```bash
python3 tools/status.py
```

That prints what's done and what's left, verified against the repo rather than
against a checklist someone remembered to tick. Then:

| I want to… | Read |
| --- | --- |
| know what to build next | [`docs/PLAN.md`](docs/PLAN.md) |
| know what it should feel like | [`docs/DESIGN.md`](docs/DESIGN.md) |
| write questions | [`docs/QUESTIONS.md`](docs/QUESTIONS.md) → [`questions/inbox.md`](questions/inbox.md) |
| see what's done | [`docs/STATUS.md`](docs/STATUS.md) |
| understand the data contract | [`docs/HANDOVER.md`](docs/HANDOVER.md) §2 |

## Run the POC right now

Nothing above is built yet. The proof of concept is, and it plays a full game on
fake data:

```bash
pip install fastapi "uvicorn[standard]" segno
python3 poc/make_fake_data.py --out poc/game_data.json
python3 poc/server.py --data poc/game_data.json --seconds 25 --rounds 14
```

Open the first printed URL on a laptop, scan the QR with a phone.

## The one rule

**Every stage ends playable.** Stage 2 is the ship line; stages 3 and 4 are
upside. If you stop on any Sunday between now and mid-September, you still have a
real game to play.

## Privacy

The real dataset is a searchable archive of a private relationship.

- `.gitignore` before the first commit, not after. Git history is forever.
- `chat.db`, `corpus.json`, and `questions/mine.toml` never get committed.
- `datasets/real.json.enc` does — it's ciphertext, and the server has no key.
- A deployed instance defaults to demo data. Real data needs a passphrase typed
  on the host screen, which is never stored anywhere.
