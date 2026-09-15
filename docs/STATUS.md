# Status

**Run `python3 tools/status.py` — don't trust this file alone.**

Most of what matters is verified automatically against the repo: does the file
exist, does the bank compile, do the tests pass, is scale-to-zero actually off in
`fly.toml`. Those checks (`S*`) live in `tools/status.py` and cannot go stale.

This file holds only what a script can't see — the checks that need a human to
say "yes, that happened." Tick them yourself. `tools/status.py` reads them and
folds them into the same dashboard.

```
python3 tools/status.py             everything
python3 tools/status.py --stage 2   just the MVP
python3 tools/status.py --bank      just the question bank
```

---

## ▶ Resume here

**Every build task in the plan is done except one, and that one is yours.**
`tools/status.py` reads 44/45. The missing check is `S2.7`,
`datasets/real.json.enc`, which needs a passphrase only you can choose.

**Two commands, in this order, and the order matters:**

1. **`make seal`** — writes `datasets/real.json.enc` and backs up `mine.toml`
   at the same time. Both `.enc` files then want a `git add`; neither has ever
   been committed, so your authored questions still have no version control.
2. **`flyctl auth login`**, then `fly apps create read-receipts`,
   `fly deploy`, then **`fly scale count 1`** — not optional: the lobby, the
   deck, the scores and the decrypted dataset all live in one process's
   memory, so two machines means two games and a lobby that never fills.

Seal *before* deploy. `COPY datasets/` picks up the ciphertext and
`.dockerignore` blocks only the plaintext, so an image built before sealing
ships without the real dataset and the Real button never appears.

### What the game does now

Stages 3 and 4 are code-complete. Everything below was built against the demo
corpus and driven in a real browser; none of it needs a single real question
to work, and all of it lights up the moment real ones arrive.

- **Lobby** — "Previously on Read Receipts": head-to-head record, a card per
  past game, an all-time line (biggest round, repeated awards, questions seen
  so you can tell when the bank is going stale). Cards open that game's reel.
- **Question** — options stagger in; the month slider has the density
  histogram behind it, which is suppressed on the questions it would answer.
- **Locked** — your answer as a sent bubble, `Delivered`, then
  `Read 9:42 PM` when she locks in. The host sees `locked in 3.2s`, never
  whether it was right.
- **Reveal** — 450ms of silence, the answer resolves, the real conversation
  around the message slides in as a thread with the source lit, the truth
  types out behind an indicator, the rope moves and the points land.
- **Podium** — confetti, a crown, the score graph with lead-change pips and
  the biggest round annotated, four to six awards dealt as cards, and
  **[ Replay the receipts ]**.
- **Sound** — synthesised, host only, mute in the top bar.

### Content is now the only critical path

The bank is 122 shippable but only **8 are yours** (3 curated), and the dealer
wants 9 of every 14 rounds from `mine.toml`. It backfills from `auto/`, so the
game works either way — it is just less yours.

**Before writing formats, run this in Terminal.app:**

```
./.venv/bin/python tools/extract.py --schema
```

It reports which columns this macOS's `chat.db` actually has. Several formats
worth wanting are not reachable from the current SQL: `date_read` and
`date_delivered` (how long you left each other on read — the game is named
after it), tapbacks, edited and unsent messages, replies, send effects, voice
notes. Re-extraction is yours to run, so it is worth knowing what is there
before the bank is written against what isn't.

**Spoilers.** You are a player. `make real` and any server pointed at
`datasets/real.json` put the whole deck on screen; `make status`,
`make compile`, `make lint` and `make seal` print only counts and reasons and
are safe to watch. For `M5.1`, rehearse the mechanics on demo and verify the
real deck at the lobby only — unlock it, confirm the toggle flips, and do not
press Start. No question text appears before round one.

**Known open threads**
- `questions/mine.toml` is gitignored and unbacked-up until `make seal` runs
  *and* the resulting `.enc` is committed. The passphrase exists nowhere but
  your head — `M5.2` is the checkbox for that.
- **History is unreadable until the passphrase is typed.** Every line of
  `data/history.jsonl` is ciphertext under the key the dataset unlock derives
  (DESIGN §4). The lobby shelf is therefore empty on a cold boot and fills
  when you unlock Real. That is the trade, and it is deliberate.
- **Fly needs a volume for history to survive a deploy.** `data/` is on the
  machine's disk. Without `fly volumes create`, every deploy forgets the past
  games. Not urgent before the first game; urgent before the second.
- The friend-thread test data is in `corpus.json` / `datasets/test.json`. Both
  gitignored. Re-running `make corpus` with her identifier overwrites it.

---

## The five stages

| Stage | Name | Gate — you are done when… |
| --- | --- | --- |
| 0 | POC | *(done)* The game loop works on fake data. |
| 1 | Foundations | You can play a rough game on your laptop, on real data. |
| 2 | **MVP** | **A full 14-round game has been played on the deployed URL.** |
| 3 | Feel | The game feels designed rather than assembled. |
| 4 | The Arc | Past games, awards, receipts reel. |

**Stage 2 is the ship line.** Everything after it is upside. Every stage ends
with something playable — if you stop on any Sunday you still have a game.

---

## Manual checks

Only tick a box when the thing has actually happened. A green dashboard you
lied to is worse than a red one.

### Stage 1 — Foundations

- [x] `M1.1` Full Disk Access granted; `extract.py` read the real thread
- [x] `M1.2` Skimmed `corpus.json` by eye — text decoded, no tapback junk
- [x] `M1.3` Played one full game locally on real data

### Stage 2 — MVP

- [ ] `M2.1` Curated a first pass — 60+ questions you'd actually show her
- [ ] `M2.2` Filled `lex.pet_names` and `lex.inside_jokes`
- [ ] `M2.3` Wrote 10+ of your own questions in `mine.toml`
- [ ] `M2.4` Deployed; opened the URL on a phone that isn't on your WiFi
- [ ] `M2.5` Left a lobby idle 10 minutes — socket survived, machine stayed up
- [ ] `M2.6` Passphrase gate tested: right one loads, wrong one fails closed
- [x] `M2.7` Confirmed no plaintext real data in git — no message text in any blob
      Every `text` field in `mine.toml` and `real.json` checked against the
      whole `git log --all -p`. Two hits, both authored slot templates that
      live in `questions/auto/` and were always committed.
- [ ] `M2.8` **Played a full 14-round game on the deployed URL, laptop + phone**

### Stage 3 — Feel

- [ ] `M3.1` Watched a reveal land and it felt good, not perfunctory
- [ ] `M3.2` Read all reveals in one sitting; rewrote the weak ones
- [ ] `M3.3` Bank at 90+ with 20+ of your own
- [ ] `M3.4` Checked the month slider on a real phone, not just desktop

### Stage 4 — The Arc

- [ ] `M4.1` Played three games; history shelf shows all three
- [ ] `M4.2` Superlatives fired sensibly — no award off a rounding error
- [ ] `M4.3` Read the receipts reel end to end

### Game day

- [ ] `M5.1` Dress rehearsal on real data, alone, on the deployed URL
- [ ] `M5.2` Passphrase saved somewhere you'll have it that night
- [ ] `M5.3` Demo dataset one click away as a fallback
- [ ] `M5.4` Sound checked on the actual laptop you'll host from
- [ ] `M5.5` Sent her the link and the join code

---

## Drift from the plan

Where the build diverged from `PLAN.md` / `DESIGN.md`, and why. Nothing here
was a silent change; each one is in a commit message too.

| Drift | Why |
| --- | --- |
| `static/sound.js` is a new file; `static/sounds/` never existed | Every cue is synthesised from oscillators. No assets to vendor, nothing to 404 on the night. `status.py`'s `S4.5` check looked for audio files and could never have fired |
| `S4.7` is a protocol-level smoke test, not Playwright | Playwright isn't installed and a headless Chrome in the unit suite is minutes plus a standing flake budget. `tests/test_smoke.py` plays a whole game through `Room` in 0.4s; the rendering is verified with the CDP harness by hand. The check is renamed to match |
| `curve()` lives in `superlatives.py`, not its own module | `Tally.running()` already computed the cumulative score. A second file working it out separately is how the graph and the awards start disagreeing about who won |
| The data contract grew five fields | `Question.histogram` and `Question.context` (+ `ContextMsg`); `RoundRecord.options` and `.context`; `players[].took` on the wire. HANDOVER §2 is still the shape, these are additions to it, each with a comment saying what breaks without it |
| `READ_BEAT` — a new 1.2s pause between the last answer and the reveal | Without it the round closed on the same tick the second person answered, and the `Delivered` → `Read` flip happened on a screen already being replaced. The screen the game is named after was unreachable |
| `{t:"reel", id}` added to the protocol | The reel needs a past game's whole round log, which is far too big to put in every state broadcast |
| `compile.py --no-mine`, and `make demo` passes it | `make demo` was pulling curated real messages into the committed demo dataset once a curate session had run. It never reached git; two tests now hold the line |
| `extract.py --schema` is new | Designing a question format that needs a column this macOS lacks is a format that can't ship. Finding that out after writing twenty questions is the expensive order |
| `status.py` S3.1 check moved from `host.html` to `player.html` | The month slider is a phone input. The check could never have fired |
| History is encrypted per line | DESIGN §4 offered the choice and recommended it. A summary carries its round log and a round log carries real message text; a plaintext history beside a sealed dataset would undo what `seal.py` is for |

---

## Blocked / decisions outstanding

Keep this honest. An empty list is the goal.

- [x] ~~Full Disk Access~~ — granted to Terminal.app
- [x] ~~`chat.db` not yet extracted~~ — 7,640 messages pulled in Terminal.app;
      the whole pipeline runs on the real thread now.
- [x] ~~Python 3.11+~~ — 3.14 installed, `.venv` created, full stack verified

---

## Log

Append a line whenever a stage gate clears. Useful in week 4 when you can't
remember whether something got done.

```
2026-08-18  Stage 0 closed. Plan, design, and a 156-question bank written.
2026-08-18  Stage 1 build complete (12/16). schema, game+round log, lexicon,
            resolvers, compile, extract, mine, validate, status. 54 tests green.
            Compiled dataset verified playable in the POC server end to end.
            Remaining: S1.4/M1.1-M1.3 all need chat.db.
2026-08-18  STAGE 1 GATE CLEARED. Extracted a real thread (7,640 messages, 48
            months, 1 bad char). Compiled 43 questions. Played a full game in
            the browser. Real data caught 4 bugs the synthetic corpus could not:
            {winner} rendering "Me", a compliment lexicon matching "if you look
            at gym data", reveals that assumed their own answer, and prompts
            hardcoding "five years" on a 4-year thread.
2026-09-02  Stage 2 build complete. curate.py, seal.py, app/main.py, the
            demo/real passphrase toggle, Dockerfile, fly.toml, self-hosted
            fonts. Everything a script can do; S2.7 and M2.4-M2.8 all wait on
            a passphrase and a deploy.
2026-09-13  First curate session. 3 questions minted from real messages;
            mine.toml at 8 blocks.
2026-09-14  Verified the container for the first time — python:3.14-slim,
            295MB, /healthz and both pages 200, dealt 51 from demo. The big
            untested assumption in the deploy is gone.
2026-09-14  Drove the passphrase gate end to end in a real browser over a real
            socket: toggle renders, wrong passphrase says "That didn't open
            it." and stays on demo, right one swaps the deck and the hero
            stats follow. The decrypted deck is cached for the life of the
            process — asked once a night, by design.
2026-09-14  Stage 3: S3.1 density histogram, S3.4/S3.5 superlatives (20
            awards, 41 tests, 5 fired in a real game), and the first half of
            S3.2 — reveal choreography. 225 tests green.
2026-09-14  Caught `make demo` baking three curated real messages into the
            committed demo dataset. Never reached git; the committed build
            predated the curate session. compile.py --no-mine and two tests
            now hold it.
2026-09-14  M2.7 verified properly: every `text` field in mine.toml and
            real.json checked against the whole `git log --all -p`. No
            message text has ever been committed.
2026-09-15  S3.3 the read receipt, and the READ_BEAT that makes it reachable.
            extract.py --schema written so the question formats can be
            designed against what chat.db actually has.
2026-09-15  STAGE 4 BUILD COMPLETE. Score graph (S4.1), history.py with
            encrypted lines (S4.2), the lobby shelf (S4.3), the receipts reel
            (S4.4), a synthesised soundtrack plus confetti and a crown
            (S4.5), and a whole-game smoke test (S4.7). 262 tests green.
2026-09-15  S3.2 finished: the context thread. curate.py had been capturing
            the conversation around each message and throwing it away at mint
            time; it now bakes it, and compile.py attaches it to generated
            questions from the resolver's source index. The reveal and the
            reel both show it.
2026-09-15  Standings redrawn as the tug of war DESIGN 2.6 asked for, and the
            phone's verdicts now know what type of question you got wrong.
            44/45 — the only open check is S2.7, which needs the passphrase.
```
