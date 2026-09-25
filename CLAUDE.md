# Read Receipts — working notes for Claude

A Kahoot-style guessing game built from one private iMessage thread. Big screen
hosts, phones play. Two players, in different states, on one deployed URL, for a
5-year meetaversary in **mid-September 2026**.

**Start every session with `python3 tools/status.py`.** It verifies against the
filesystem — files, tests, bank health — so it cannot go stale the way a
checklist does. Don't ask the user what's done; run it.

---

## Read these before proposing anything

| Doc | What it settles |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | Build order, stage IDs, locked decisions |
| [docs/DESIGN.md](docs/DESIGN.md) | Screens, motion, superlatives, the deck |
| [docs/QUESTIONS.md](docs/QUESTIONS.md) | Question archetypes and writing rules |
| [docs/STATUS.md](docs/STATUS.md) | Manual checkboxes + **Resume here** |
| [docs/HANDOVER.md](docs/HANDOVER.md) | The original POC. §2 data contract is still authoritative |

Task IDs (`S2.4`, `M1.3`) are shared between PLAN.md, STATUS.md and
`tools/status.py`. One vocabulary. If you add work, give it an ID in all three.

---

## Non-negotiables

**Privacy.** This repo will contain the entire text history of a relationship if
someone is careless.

- Never commit `corpus.json`, `candidates.json`, `questions/mine.toml`,
  `questions/inbox.md`, `datasets/real.json`, or anything from `~/Library/Messages`.
  They're gitignored — keep it that way, and check `git status` before committing.
- `datasets/real.json.enc` **is** committed on purpose. It's ciphertext and the
  server holds no key (docs/PLAN.md §4).
- Don't print message content into chat beyond what's needed to answer the
  question at hand. Aggregates over dumps.
- **`make demo` must pass `--no-mine`.** `datasets/demo.json` is committed and
  handed to people; building it from the whole `questions/` tree pulls curated
  real messages straight into it. It happened once, caught before the commit.
  Two tests hold the line — one on the builder, one on the committed file.
- **`data/history.jsonl` is encrypted line by line** under the key the dataset
  unlock derives. A summary carries its round log and a round log carries real
  message text.

**He is a player, so don't spoil him.** `make real`, `make curate` and any
server pointed at `datasets/real.json` put the deck on screen. `make status`,
`make compile`, `make lint` and `make seal` print counts and reasons only.
When he asks to see something working, reach for `datasets/demo.json`.

**The game must be playable at the end of every stage.** Stage 2 is the ship
line; stages 3 and 4 are upside. Never leave the repo in a state where
`make play` doesn't work.

**The user's questions beat generated ones.** He has said he won't audit
`auto/`. Provenance is the directory — `questions/mine.toml` is his,
`questions/auto/*.toml` is generated — and the dealer fills 65% of each game
from his first. Don't add a field for this; the filesystem is the mechanism.

---

## Environment

- **Python 3.14 in `.venv`.** System `python3` is 3.9 and has no `tomllib` or
  `pytest`. Use `./.venv/bin/python` or a `make` target, never bare `python3`
  for anything in `app/` or `tools/`.
- **`chat.db` is unreadable from Claude's shell.** Full Disk Access was granted
  to Terminal.app; Claude's process is a child of a translocated VS Code and
  can't inherit it. Anything touching `~/Library/Messages` — i.e. `make chats`
  and `make corpus` — the **user runs in Terminal.app**. Everything downstream
  reads `corpus.json` from the repo and works fine from here.
- **Her thread is split across a phone number and a Gmail address.** Always pass
  both, comma separated: `make corpus CHAT="+1555...,her@gmail.com"`. Extraction
  dedups by message ROWID and prints a per-identifier breakdown.
- `make setup` rebuilds the venv from `requirements.txt`.

---

## The pipeline

```
chat.db ──extract──▶ corpus.json ──mine──▶ candidates.json
                          │                      │
                          │                 curate.py  ◀── him, judging
                          │                      ▼
                          └────────────▶ questions/mine.toml ◀── him, writing
                                                 │  + questions/auto/
                                            compile.py
                                                 ▼
                                        datasets/real.json ──seal──▶ .enc ──▶ deploy
```

```bash
make              # status dashboard
make play         # fake corpus → real compiler → real server. Always works.
make test         # 262 tests
make lint         # validate questions/ and compiled datasets
make serve DATA=datasets/test.json
```

---

## Architecture, and why

**`app/game.py` has no framework imports.** The clock and the sockets live in
`main.py` (not written yet); `Game` exposes pure transitions. That's what makes
scoring testable, and scoring is the thing that breaks silently.

**`grade()` appends a `RoundRecord` to `game.log`.** It does nothing yet.
Superlatives, the score graph, the history shelf and the receipts reel are all
pure functions over that log. Keep it complete even where it looks redundant.

**`subject` is what stops a game repeating itself.** `kind` is the eyebrow and
`topic` is the compile-time dedup key; neither can see that "who says goodnight
more", "how many goodnights" and "when was the first goodnight" are one subject
in three costumes. `compile.py` derives `subject` from the resolver, the dealer
allows one per game, and the Final Receipt is chosen first so nothing in the
body can pre-answer it. A question baked from a real message has no subject on
purpose — it can only collide with itself.

**`PLAYABLE` in `game.py` gates which types get dealt.** `percent`, `wager` and
`mutual` are scored but not in `PLAYABLE`, because no client input exists yet.
`compile.py` filters on it and reports what it skipped, which is what lets the
bank carry questions for mechanics that may never ship. Widening that set is how
a new mechanic launches.

**`curate.py` bakes, it doesn't resolve.** A question minted from a real
message has no resolver behind it, so `{winner}`, `{date}`, `{month}` and
`{answer}` are substituted when the block is written and only `{p1}`/`{p2}`
survive for `compile.py`. Braces inside message text are doubled on the way in.
Decisions live in `questions/.curate.json` (gitignored) and every accepted block
carries a `# ── curated ──` marker, which is how undo finds exactly its own
block and nothing a human typed.

**`superlatives.py` and `history.py` are pure functions over `game.log`.** The
awards, the score graph (`curve()`, which shares `Tally` so it cannot disagree
with them about who won), the shelf and the reel all read the same list of
`RoundRecord`s. That is why the log has to stay complete — `options` and
`context` are on it because the reel replays rounds long after the `Question`
they came from is gone.

**Context is baked for curated questions, resolved for generated ones.**
`curate.py` writes the ±2 messages into the block at mint time because `i`
shifts on re-extraction, and a question pointing at the wrong evening is worse
than one with no context. `compile.py` derives it for generated questions from
`Resolution.source`. Both land in the same `Question.context`, and it is
copied verbatim, never templated — real messages contain braces.

**The soundtrack is synthesised** (`static/sound.js`). Oscillators and
envelopes, no asset files, host screen only. There is no `static/sounds/`.

**Matching is three layers** (`tools/lexicon.py`): normalise → expand every
literal phrase into a repeat-and-space-tolerant regex → lexicons for real
synonyms. `"i love you"` catches `ily`, `iloveyou`, `i loveeee youuu`, and
refuses `i love your hair`. Counting counts *messages*, so overlapping variants
never double-count. If you add a phrase, add it to `questions/lexicons.toml`,
not to a regex in code.

**Fairness guards in `compile.py` drop questions that aren't answerable** — a
`who_*` closer than 1.25× is a coin flip in costume, a `number` under 20 scores
degenerately, a `month` answer in the outer 10% is guessable from the slider
range. Every drop is reported with a reason. Tune in `questions/config.toml`.

---

## Authoring conventions

- TOML, `[[q]]` blocks. `id` unique across all files. `topic` defaults to `id`;
  a `mine.toml` question sharing a `topic` silently replaces the generated one.
- **A reveal must never assume its own answer.** "Sunday scaries are real"
  shipped on a thread whose busiest day was Wednesday. If a reveal states a
  fact, that fact must come from a template var.
- Template vars: `{p1} {p2} {total} {years} {months_n} {answer} {answer:,}
  {n1} {n2} {winner} {loser} {date} {month}`.
- `status`: `ready` compiles · `draft` is skipped · `mine` waits for `curate.py`.
- Vary `kind` — the deck interleaves by it. 10+ labels minimum.
- When he pastes raw question ideas, convert them to `mine.toml` blocks and
  write any new lexicon or resolver the idea needs. That's the intended
  workflow; see `questions/inbox.md`.

---

## Habits that have paid off here

- Run the pipeline on real data early. Four bugs surfaced that the synthetic
  corpus structurally could not show.
- When a test fails, ask whether the test or the code is wrong. Twice the test
  was: `authored_share` is a floor not a target, and the schema rightly refuses
  a dataset with fewer questions than rounds.
- Filter at the point of use, not at extraction. Dropping short messages in
  `extract.py` starved half the resolvers.
