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
| hand this to Claude | [`CLAUDE.md`](CLAUDE.md) — loaded automatically |
| know what to build next | [`docs/PLAN.md`](docs/PLAN.md) |
| know what it should feel like | [`docs/DESIGN.md`](docs/DESIGN.md) |
| write questions | [`docs/QUESTIONS.md`](docs/QUESTIONS.md) → [`questions/inbox.md`](questions/inbox.md) |
| see what's done | [`docs/STATUS.md`](docs/STATUS.md) |
| understand the data contract | [`docs/HANDOVER.md`](docs/HANDOVER.md) §2 |

## Play it right now

```bash
make setup     # .venv on python 3.14, everything installed
make play      # builds a fake dataset and serves a real game
```

Open the first printed URL on a laptop, scan the QR with a phone. That's the
whole pipeline — synthetic corpus, compiled through the real compiler, played by
the real server. No message of yours is involved.

## Then the real thing

Your terminal needs Full Disk Access (System Settings > Privacy & Security),
and these two commands must run in **Terminal.app** — a terminal inside an
editor usually can't inherit that permission.

```bash
make chats                                        # find her chat identifier
make corpus CHAT="+15551234567,her@gmail.com"     # both, if the thread is split
```

Everything after this reads `corpus.json` and works from anywhere.

```bash
make mine       # corpus -> ~500 ranked candidate questions
make curate     # a browser page. J reject, K accept, E edit, S search.
make compile    # questions/ + corpus -> datasets/real.json
make real       # play it locally
```

`make curate` is where the game actually gets made. It opens on the first of 26
slots — questions that are finished apart from the message itself — with the
best candidates ranked behind each one. Accepts land in `questions/mine.toml`.
Half an hour of it is a game.

Then lock it up and put it somewhere:

```bash
make seal       # -> datasets/real.json.enc and questions/mine.toml.enc
make deploy     # needs flyctl
fly scale count 1
```

`fly scale count 1` is not optional. There is no database — the lobby, the deck,
the scores and the decrypted dataset all live in one process's memory, so two
machines means two games and a lobby that never fills.

`make` on its own prints the status dashboard; `make help` lists every target.

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
- `questions/mine.toml.enc` is committed too, and is the only backup your own
  questions have. Re-run `make seal` after an evening of curating, or the
  backup is of the file as it was before you started.
