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

- [ ] `M1.1` Full Disk Access granted; `extract.py` read the real thread
- [ ] `M1.2` Skimmed `corpus.json` by eye — text decoded, no tapback junk
- [ ] `M1.3` Played one full game locally on real data

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
```
