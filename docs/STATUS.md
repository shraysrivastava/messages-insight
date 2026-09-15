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

**Stages 1 and 2 are code-complete.** Everything a script can do is done. The
one thing standing between this repo and a played game is a deploy, and that
needs you.

**Two commands, in this order, and the order matters:**

1. **`make seal`** — needs a passphrase, which only you can choose. Writes
   `datasets/real.json.enc` (`S2.7`) and backs up `mine.toml` at the same
   time. Both `.enc` files then want a `git add`; neither has ever been
   committed, so your eight authored questions still have no version control.
2. **`flyctl auth login`**, then `fly apps create read-receipts`,
   `fly deploy`, then **`fly scale count 1`** — not optional: the lobby, the
   deck, the scores and the decrypted dataset all live in one process's
   memory, so two machines means two games and a lobby that never fills.

Seal *before* deploy. `COPY datasets/` picks up the ciphertext and
`.dockerignore` blocks only the plaintext, so an image built before sealing
ships without the real dataset and the Real button never appears.

**Content — yours, and still the critical path.** The bank is 122 shippable
but only **8 are yours** (3 of them curated), and the dealer wants 9 of every
14 rounds from `mine.toml`. It backfills from `auto/` when yours run short, so
the game works either way — it is just less yours.

1. `make curate`. <kbd>J</kbd> reject, <kbd>K</kbd> accept, <kbd>E</kbd> edit,
   <kbd>S</kbd> to search the whole thread and mint from any message in it.
   Half an hour of this is a game.
2. Fill `lex.pet_names` and `lex.inside_jokes` in `questions/lexicons.toml` —
   turns on 3 questions immediately, and every inside-joke phrase after that
   is a free `month` question.
3. Dump raw ideas into `questions/inbox.md` in plain English. They come back
   as finished `mine.toml` blocks.

**Stage 3 is 7/12.** The density histogram (`S3.1`), the read receipt
(`S3.3`), the superlatives (`S3.4`/`S3.5`) and the reveal choreography are in
and driven in a browser. The one thing left is the second half of `S3.2`, the
context thread — it needs the pipeline to carry context, and nothing does
today: `curate.py` captures ±5 messages and throws them away at mint time.

**Before designing new question formats, run `make chats` — sorry,
`./.venv/bin/python tools/extract.py --schema` — in Terminal.app.** It reports
which columns this macOS's `chat.db` actually has. Several formats worth
wanting are not reachable from the current SQL: `date_read`/`date_delivered`
(how long you left each other on read — the game is named after it), tapbacks
(`associated_message_type`, currently filtered out), edited and unsent
messages, replies, send effects, voice notes. Re-extraction is yours to run,
so it is worth knowing what is there before the bank gets written against
what isn't.

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
- The friend-thread test data is in `corpus.json` / `datasets/test.json`. Both
  gitignored. Re-running `make corpus` with her identifier overwrites it.
- `make demo` used to pull `mine.toml` into the committed demo dataset once a
  curate session had run. Fixed with `--no-mine` and two tests, but it is the
  shape of mistake to keep watching for: anything committed that is built from
  `questions/`.

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
```
