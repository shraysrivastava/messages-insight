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

**Stage 1 is closed.** The whole pipeline is proven on a real thread: 7,640
messages extracted, 43 questions compiled, a full game played in the browser.

**`curate.py` is built** (`S2.1`), which unblocks the content track. Stage 2 is
now two tracks that run in parallel:

**Content — yours, and the critical path.** The bank is 119 shippable but
**0 from `mine.toml`**, and the dealer wants 9 of every 14 rounds to be yours.

1. `make curate`. A browser opens on the first of 26 slots, each one a finished
   question missing only a real message, with ~500 proposals ranked behind it.
   <kbd>J</kbd> reject, <kbd>K</kbd> accept, <kbd>E</kbd> edit. Accepts land in
   `questions/mine.toml` as finished blocks. Half an hour of this is a game.
   Four slots (`who-said-longest`, `which-came-first-auto`,
   `what-happened-next-1`, `work-first-big-news`) ship with `TODO` reveals on
   purpose — they refuse to save until you write the payoff, and they're the
   four best rounds in the deck.
2. <kbd>S</kbd> in that same page searches the whole thread and mints a question
   from any message in it. This is where the good ones come from.
3. Fill `lex.pet_names` and `lex.inside_jokes` in `questions/lexicons.toml` —
   turns on 3 questions immediately, and every inside-joke phrase after that is
   a free `month` question.
4. Dump raw ideas into `questions/inbox.md` in plain English. They come back as
   finished `mine.toml` blocks.

**Build — everything a script can do is done.** `app/main.py` is the real
server (`S2.0`) with the join code, client-timestamped answers and the
heartbeat (`S2.3`–`S2.5`); `seal.py` and the passphrase gate are in
(`S2.6`, `S2.8`); the Dockerfile, `fly.toml` and self-hosted fonts are
written (`S2.10`–`S2.12`). `make play` runs it, `make poc` runs the old
proof of concept if you ever need the fallback.

**Two things left in stage 2, and both need you:**

1. **`make seal`** — needs a passphrase, which only you can choose. Produces
   `datasets/real.json.enc` (`S2.7`) and backs up `mine.toml` at the same time.
2. **`make deploy`** — needs `flyctl` and a Fly account. Then
   **`fly scale count 1`**, which is not optional: the lobby, the deck, the
   scores and the decrypted dataset all live in one process's memory, so two
   machines means two games and a lobby that never fills.

The Dockerfile has never been built — Docker's daemon wasn't running here. What
*was* verified is the thing a Dockerfile usually gets wrong: the app runs from a
tree containing only the files it copies, with only the runtime dependencies
installed, and the passphrase gate still opens a sealed dataset from it. Check
`primary_region = "ord"` in `fly.toml` — it's a guess at the middle of your two
states.

**One thing only you can do:** `make seal`, once you've curated anything worth
keeping. It asks for a passphrase, writes `datasets/real.json.enc` and
`questions/mine.toml.enc`, and those get committed (`S2.7`). Until you run it,
every question you write in `curate.py` exists in exactly one place, on one
laptop, ungitignored and unbacked-up.

**Known open threads**
- The friend-thread test data is in `corpus.json` / `datasets/test.json`. Both
  gitignored. Re-running `make corpus` with her identifier overwrites it.
- `questions/mine.toml` is gitignored and therefore unbacked-up until you run
  `make seal`, which encrypts it alongside the dataset. The passphrase exists
  nowhere but your head — `M5.2` is the checkbox for that.

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
- [ ] `M2.7` Confirmed no plaintext real data in git (`git log -p | grep`)
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
- [ ] `chat.db` not yet extracted. Everything downstream
      of `corpus.json` is verified against a synthetic corpus until then.
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
```
