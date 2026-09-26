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

**All 52 build tasks are done.** Her thread is extracted, the deck compiles,
the game is deployed, and as of 2026-09-24 every question type in the bank is
playable — percent, mutual and the Final Receipt all have inputs, the clients
read `format`, and photographs have a path from `chat.db` to the sealed
dataset. The bank went 145 -> 173 without a question being written.

**The one thing that needs your machine is the photos.** Everything else is a
re-seal, a redeploy, and the manual checks.

### Next, in order

1. **Re-extract, in Terminal.app.** The corpus has no `photos` list in it,
   because nothing had ever queried the attachment tables. This is the only
   step this shell cannot run.

   ```bash
   make corpus CHAT="+1555…,her@gmail.com" P1=Shray P2=Nilu
   make photos                     # or LIMIT=200 for a look first
   ```

   `make corpus` will report how many photographs it found and how many have
   no caption; `make photos` will report how many iCloud has offloaded. Both
   are safe to watch — counts only, no message text, no answers.

2. **Re-seal and redeploy.** `real.json` and `dev.json` both changed — 28 more
   questions and a new `meta.deal` block. The deployed image is carrying the
   old ciphertext.

   ```bash
   make compile && make dev && make seal
   git add datasets/*.enc && git commit -m "Reseal: percent, mutual, the receipt"
   fly deploy && fly status        # must show exactly ONE machine
   ```

3. **Play a 15-round game on the deployed URL, on `Dev`** — `M2.4`, `M2.5`,
   `M2.6`, `M2.8`, and `M3.4` (the sliders on a real phone, not a desktop
   window: there are two of them now).

4. **`make audit`** over the 28 newly-playable questions. They have never been
   looked at, because until now they could not be dealt.

5. **`M4.1`–`M4.3`**, then game day.

### Photo questions, once `make photos` has run

None exist yet — the pipeline shipped, the questions did not. A block names a
file and everything else is an ordinary question:

```toml
[[q]]
id = "photo-rooftop"
type = "binary"
kind = "Deep cut"
photo = "IMG_4417.HEIC"          # compile.py sets format = "photo"
prompt = "Who took this one?"
options = ["{p1}", "{p2}"]
answer = 0
reveal = "You did. Neither of you has admitted it since."
status = "ready"
```

`make lint` catches a name the corpus does not have, and `make compile`
reports a photo that has not been downscaled yet rather than shipping a gap.

### Known, and not urgent yet

- `data/history.jsonl` sits on the machine's ephemeral disk, so the shelf
  empties on every redeploy. A Fly volume fixes it. Harmless before the first
  game, and the thing that loses the first game before the second.
- Two wager questions exist, so the closer repeats on the second night. A
  third would fix it; `final-longest-day` is a draft away.

### The ship line, for reference

Three datasets ship. `demo` is fake and open; `dev` is the real deck with
every answer blinded; `real` is the real thing. All three appear on the host
screen as `[ Demo ] [ Dev 🔒 ] [ Real 🔒 ]`, and dev and real open with the
same passphrase.

```bash
make compile          # questions/ + corpus.json -> datasets/real.json
make dev              # the same deck, answers blinded -> datasets/dev.json
make seal             # seals real.json, dev.json and mine.toml
git add datasets/real.json.enc datasets/dev.json.enc questions/mine.toml.enc
git commit -m "Seal the decks"
```

`make seal` asks for the passphrase once and uses it for all three. Seal
*before* deploy: `COPY datasets/` picks up the ciphertext, `.dockerignore`
blocks the plaintext, and an image built before sealing ships without them.

```bash
flyctl auth login
fly apps create read-receipts
fly deploy
fly scale count 1     # not optional — see fly.toml
fly status            # must show exactly ONE machine
```

Then rehearse on the deployed URL, on `Dev`:

- `M2.4` open it on a phone that isn't on your WiFi
- `M2.5` leave the lobby idle ten minutes — socket survives, machine stays up
- `M2.6` wrong passphrase fails closed, right one loads
- `M2.8` play a full 14 rounds

Play those on **Dev**, not Real. Same deck, same ids, same bubbles, same
number of rounds — the only difference is that the answers are a uniform
random draw and the reveals are masked, so nothing is spoiled. A dev game is
never written to `data/history.jsonl` either (`History.remember` persists
`real` only), so game night's shelf starts clean however many rehearsals you
run.

When it all works on Dev, switching to Real is one click and one passphrase.
Nothing else about the process changes.

### Phase 2 — the questions (mine)

Blocked on phase 0. Roughly in value order:

- `lex.pet_names`, `lex.inside_jokes` from what is already in `inbox.md`
  (`shru`/`nu`/`bubba`, and the `-u` gag: choppu, clingu, independentu) → `M2.2`
- The countable ideas in `inbox.md` as resolvers — `kys`, the emoji
  leaderboard, who said "i love you" first, TMI, LMAOOO-length as a proxy for
  funniest
- Collocation questions ("which of these four phrases does she actually say")
  — the reviewable half of the grid idea, with no new mechanic
- A full read of her corpus for hand-picked message questions
- Target: bank at 90+ compiled, 20+ of yours → `M3.3`

### Phase 3 — the audit loop (your eyes, my hands)

```bash
make audit
```

Every question, one sitting, answers blinded (`S3.9`). Call cuts by round
number; I cut, rewrite and recompile. Repeat until you would show all of it
to her.

### Phase 4 — game day

`M5.1`–`M5.5`. Note `M5.1`: rehearse on **`datasets/dev.json`**, not real data.
It is the same deck with the answers blinded, so it proves the deploy, the
sockets and the sound without spoiling you.

### Checks that changed owner

You decided (2026-09-21) to design the game without ever seeing an answer.
Four manual checks were written assuming the opposite, and now belong to me or
to the demo dataset:

| Check | Was | Now |
| --- | --- | --- |
| `M2.1` Curate a first pass | you, in `curate.py` | me — `curate.py` shows answers |
| `M3.2` Read all reveals, rewrite the weak ones | you | me — a reveal *is* the answer |
| `M4.2` Superlatives fired sensibly | you, on real data | demo data |
| `M4.3` Read the receipts reel end to end | you, on real data | demo data |

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

### Content

The bank is 173 shipping with 140 of them yours, against a dealer that wants 9
of every 14 rounds from `mine.toml`. Content stopped being the critical path
somewhere around the second audit pass.

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
- `corpus.json` is her thread (248,345 messages, Oct 2021 → Sept 2026). The
  earlier friend-thread corpus and `datasets/test.json` are both gone.
  `make try CHAT=...` still builds a throwaway pair for testing on someone
  else; both outputs are gitignored.

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
- [x] `M2.2` Filled `lex.pet_names` and `lex.inside_jokes`
      Built from the corpus, not from memory — plus `pet_names_his`,
      `pet_names_hers`, `the_u_bit` and thirteen spelling-tell lexicons.
- [x] `M2.3` Wrote 10+ of your own questions in `mine.toml`
      58 authored, 48 of them compiling.
- [ ] `M2.4` Deployed; opened the URL on a phone that isn't on your WiFi
- [ ] `M2.5` Left a lobby idle 10 minutes — socket survived, machine stayed up
- [ ] `M2.6` Passphrase gate tested: right one loads, wrong one fails closed
- [x] `M2.7` Confirmed no plaintext real data in git — no message text in any blob
      Every `text` field in `mine.toml` and `real.json` checked against the
      whole `git log --all -p`. Two hits, both authored slot templates that
      live in `questions/auto/` and were always committed.
- [ ] `M2.8` **Played a full 14-round game on the deployed URL, laptop + phone**

### Stage 3 — Feel

- [x] `S3.9` Blind audit mode — `make audit`
- [x] `S3.10` Text audit — `make questions`
- [ ] `M3.1` Watched a reveal land and it felt good, not perfunctory
- [ ] `M3.2` Read all reveals in one sitting; rewrote the weak ones
- [x] `M3.3` Bank at 90+ with 20+ of your own
      133 compile against her thread, 48 yours.
- [ ] `M3.4` Checked the month slider on a real phone, not just desktop

### Stage 4 — The Arc

- [x] `S4.8` Music beds under each phase
- [x] `S4.9` The opener — five years on the lobby screen
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
2026-09-21  S3.9 blind audit mode. `compile.py --dev` mirrors real.json
            question-for-question with answers drawn uniformly at random,
            reveals masked, context and histogram stripped — so the whole deck
            can be reviewed by someone who is also going to play it. `make
            audit` serves all of it under a fixed seed, so round numbers are
            stable and a question can be cut by number. 266 tests green.
            Also: corpus.json turned out to be the roommate thread, not hers —
            zero hits on kys, pet names, "i love you". Needs re-extracting.
2026-09-21  Her thread landed: 248,345 messages, Oct 2021 → Sept 2026, against
            7,640 in the roommate corpus it replaced. Deep pass written up in
            questions/mine.toml — 48 authored questions compiling, bank at
            133. The find was the spelling tells: they use the same words and
            spell them differently, almost without crossover, which is a whole
            round of binaries that are not coin flips.
            Three bugs surfaced on the way, all of them shipping before today:
            · every `choice` question in the dataset answered to option A.
              `top_emoji`/`top_word`/`peak_hour` return most_common(n) with
              value=0 and nothing shuffled. compile.shuffle_options fixes it,
              seeded by question id so the audit and the game agree.
            · `quietest-month`, `longest-gap` and `longest-message` had been
              silently dropped from every build — they report hits=1 and the
              min_hits guard treats that as "too few matches". Extremum
              resolvers now report hits=None.
            · validate.py called lexicons.toml clean with fourteen
              uncompilable regexes in it, and rejected `context` on curated
              blocks although curate.py writes it. Both checked now.
            Also dropped the three blocks curated from the roommate thread.
            273 tests green.
2026-09-23  Finish-the-sentence round: g_finish_sentence in mine.py, 15
            questions in mine.toml, bank at 148 with 63 yours. The generator
            rejects function-word answers (grammar, not habit) and collapses
            elongation variants so "much"/"muchhhh" aren't three options.
            S3.10 `make questions` — the bank as text, grouped by kind, no
            browser. Reads datasets/dev.json only and refuses real.json, so
            it cannot print an answer. Also: `format` turns out to be dead
            metadata — no client code reads it, so `blank`/`redacted`/
            `compare`/`thread` render identically to `bubble` today.
            274 tests green.
2026-09-23  Audit pass 1. Cut 8 on his call. Two notes from him: more
            questions that put a real message on screen, and less
            repetition — 55% of the bank was "Who ___?" or "How many ___?"
            and only a third showed a message. Both addressed: text-showing
            questions 47->69, varied prompts 40->71, bank 169 with 89 his.
            New: THE ARC — questions whose reveal teaches something rather
            than scoring a point. Median reply time is six times slower in
            2026 than 2022; messages are nearly twice as long; the
            vocabulary of two people in college has been replaced by pet
            names and flight times. Four resolvers back it: median_reply,
            words_per_message, reciprocated, era_word.
            Two more bugs: `days_until` printed the matched message on the
            question screen, which buried the prompt AND gave away who sent
            the first "i love you"; and validate.py accepted `from` in a
            context row where the schema wants `who` (120 compile errors,
            linted clean). Both now caught by tests.
            275 tests green.
2026-09-23  Audit pass 2. Cut `longest-message` (112) plus 11 generic
            topic-counts — "how many messages about food / pets / weather"
            — which were the definition of fluff: arbitrary number, no
            payoff, ten of them the same shape. Also killed every duplicated
            prompt; four different messages were all asking "Who sent this?".
            Three round shapes added, all of which existed as empty slots:
            · REDACT — three words knocked out instead of one.
            · REPLY ROULETTE — shows the reply, guess what caused it. The
              only round in the deck that runs backwards.
            · UNANSWERED — a question that sat for 6+ hours. New generator
              g_unanswered; the funny part is the silence, not the message.
            `derive()` in curate.py already had the redact and invert
            transforms; only mine.py couldn't feed them.
            Bank 169, 101 his, 79 showing a real message (was 47), zero
            duplicate prompts, varied prompts 40 -> 88. 275 tests green.
2026-09-23  Dead code swept. Removed: SCORABLE (app/game.py, a constant
            documenting the scorer that nothing enforced, so it could only
            ever drift into a lie), curate.existing_ids (superseded by
            all_ids), resolvers._edge_safe (a no-op whose docstring claimed
            it filtered), poc LOBBY_WAIT_HINT, five unused imports, a dead
            `.tile` CSS selector, and 12 orphaned lexicons — six were the
            unused half of a spelling pair (who_says_more on spell_yea
            already counts both sides, so spell_yeah measured nothing) and
            the rest lost their questions in the fluff cut.
            Kept deliberately: count_phrase / count_regex / count_emoji are
            the escape hatch for writing a question without a lexicon, and
            `format` is carried through the schema for a client that does
            not read it yet. Neither is dead; both are unused.
            The three autouse pytest fixtures read as unreferenced to any
            static scan and must stay. 275 tests green, demo 51 -> 41
            questions (the fluff cut reached auto/).
2026-09-23  Deleted the stale datasets/test.json (Aug 18, roommate corpus).
            S2.13: the deployed instance can now play a THIRD dataset, `dev`
            — the real deck with answers blinded — so a dress rehearsal can
            happen on the real URL without spoiling him. Library grew a
            SEALED table instead of hardcoding demo/real; seal.py --all
            covers dev.json; .dockerignore blocks the plaintext and ships the
            ciphertext. Dev and real open with the same passphrase and a dev
            game is never written to history.jsonl, so the shelf stays clean
            however many rehearsals run. Verified end to end in a temp dir:
            169 questions in both, identical ids and order, every dev reveal
            masked, every real reveal intact, wrong passphrase refused.
            280 tests green.
2026-09-23  S4.8 music, S4.9 the opener — both verified in a real browser
            over CDP, not just syntax-checked.
            sound.js had five one-shot cues and no music. It now has beds:
            a lookahead scheduler queues notes on the *audio* clock (setInterval
            drifts and stalls while a reveal renders) through a bus that can be
            ramped down as a group. lobby / question / outro; `reveal` gets
            silence on purpose, because the 450ms before the answer is the
            joke and a pad through it steps on the punchline. Driven through a
            real round: countdown+question -> question bed, reveal -> none.
            Two bugs found while wiring it: `cue()` returned early when S was
            null, so no bed ever started on first load; and a bed started
            against a *suspended* context schedules every note in the past, so
            they all fire as one chord on resume. Both fixed — the queue holds
            while suspended, and the first gesture of any kind unlocks it.
            The opener draws meta.density on the lobby: 60 bars filling left
            to right over 14s with the month and a running total. Costs no new
            data. On her thread the shape is the story — a near-empty first
            year, then it goes vertical. Cached, so a phone joining re-renders
            the lobby without replaying it (verified: same element, animation
            uninterrupted). 282 tests green.
2026-09-23  Question types finalised. docs/QUESTIONS.md rewritten from a
            45-item aspirational catalog into THIRTEEN shipping archetypes
            plus three blocked on client input, each with a contract: what
            the prompt may claim, what computes it, what it rejects.
            The contract exists because the bank was breaking it. Audited all
            217 ready questions and found 12 real mismatches (the other 28 my
            checker flagged were spelling variants working as designed):
            · 8 asked "how many times" but `count` counts MESSAGES, so
              "goodnight goodnight" was one. Five now pass
              mode = "occurrences"; three reworded to "how many messages"
              because they count episodes, not utterances.
            · 5 quoted one phrase but counted a category — "who says wait
              more" against a lexicon holding hold on / hang on / one sec.
              Reworded to name the category.
            validate.py now enforces the checkable half as a warning.
            Balance is the brief for the rebuild, not volume: 169 shipping,
            46% show a real message, and two shapes (Who Does It More 33, The
            Count 33) are over-represented while What Happened Next has 1 and
            The Arc has 6. No new counts, no new who-says-more.
            282 tests green.
2026-09-23  Applied the bar he set: every question either shows something
            or is fun to answer, nothing static unless it is genuinely
            interesting. Cut 41 — 17 "who brings up X more" (a topic is not a
            trait), 14 topic counts, 8 duplicates of questions already kept,
            one number with no story, and `photos-sent`, which was actively
            WRONG: extract.py drops photo-only messages so it reported ~460
            against a real figure far higher.
            Three new types, all on existing mechanics so no client work:
            · CALLBACK — the same 4-word phrase in exactly two messages, 2+
              years apart. Which came first. She said "u ever just not wanna
              sleep cus u dont want it to be tomorrow" in 2022 and again,
              almost word for word, in 2026.
            · WHOSE TURN — a real three-message exchange, both sides, no
              names. Who opened it. The opener is tell-filtered; the replies
              are not, because by then the round is decided.
            · ESCALATION — three consecutive messages from one person,
              shuffled. The first cut returned any three in a row and the
              order was unguessable, so it now requires the heat to actually
              BUILD across the run.
            Two lexicon bugs found while pulling examples, both of which had
            been answering questions wrongly:
            · the first "I love you" was a drunk happy-birthday text — "love
              u homie" — four months before the real one. Six questions
              pointed at a message sent to a friend. Platonic excludes added;
              "girl" deliberately NOT excluded, they use it constantly.
            · "nilu" counted as a pet name. It is her name.
            Balance now: 152 shipping, 125 his, 67% show a real message (was
            46%), 140 distinct prompts of 152. 282 tests green.
2026-09-23  Rebalanced. Cut 14 more — five Who Said It bubbles that carry
            no joke standing alone, four exact-duplicate messages across two
            question types, and three lexicon misfires ("we can decide when
            we eat" was standing in for the first talk about the far future).
            Built up the two starved types: What Happened Next 1 -> 9,
            The Arc 6 -> 15. Four new year-aware resolvers behind the arc
            questions, and the best one is a genuine reversal — she sent the
            first message of the day on 63% of days in 2022; he sends it on
            60% now, and it flipped around 2024.
            Two bugs, both the same shape as ones caught before: a guard
            built for one thing misfiring on another.
            · `share_of_messages` silently IGNORED `year`, so a question
              saying "this year" reported the all-time figure. Fixed, and
              validate.py now errors when `year` goes to a resolver that
              does not honour it — there is a declared YEAR_AWARE set.
            · the min_answer=20 guard was killing 11 arc questions whose
              answers are legitimately small (2%, 5%, 9 seconds). Guard is
              right for counts, wrong for rates: the eleven percentages are
              now `percent`, which scores on a flat 30-point tolerance, and
              the four durations keep `number` with an explicit override.
            Bank: 145 shipping, 125 his, 65% show a real message, no type
            over 17. 28 more questions are authored and waiting on client
            input — 20 of them percent. 282 tests green.
2026-09-23  THE CLIENT CAUGHT UP WITH THE SCORER. Every type in the bank is
            now playable and `format` is finally read. 145 shipping -> 173.
            · PERCENT (S3.6). A 0-100 slider on the phone, the month slider's
              shape without the histogram. 20 questions, including the arc
              ones. The verdict line was scoring it relatively while the
              scorer scores it on a flat 30-point band — it called a guess
              that paid out 565 "wildly over". Both read the same 30 now.
            · MUTUAL (S4.6). In PLAYABLE, 6 questions. Both screens say out
              loud that there is no right answer, or a round you both "lose"
              reads as trivia you both got wrong. The host lights a tile only
              when they agreed, and dims nothing when they didn't: neither of
              them was wrong.
            · THE FINAL RECEIPT (S3.7). Round 15 of 14. Wagers are held out of
              the body of the game entirely and one is appended as the closer,
              so it can never land at round 3. Stake, then pick, in one
              message — two messages would let a client stake, watch the
              board, and answer afterwards. No speed bonus, and a loss cannot
              take you below zero, because there is no round after it and a
              negative number is a bad last screen of the night.
            · `format` (S3.11). It had been dead metadata: `redacted`,
              `compare` and `thread` all rendered as one plain bubble, and for
              the multi-message ones that meant three messages run together
              into one sentence. `shared.js/messageBlock` is the only reader.
              `thread` renders a column with nobody's name on it rather than
              alternating sides — the format covers both a two-person exchange
              and one person's run of three, and sides would be a guess that
              gives the answer away on half of them.
            Three bugs, all the same shape as ones caught before — a guard or
            a check that was true for the wrong reason:
            · `resolve_source` reported `hits=1`, so the min_hits guard of 3
              dropped every `source` question. That silently included the
              Final Receipt, invisible for as long as wagers were also being
              dropped one step earlier as unplayable. hits=None now, same as
              the extremum resolvers.
            · `questions/config.toml [deal]` was never read by anything.
              `main.py` built `DealRules()` from defaults, and `questions/` is
              not in the Docker image, so `final_receipt` and `max_per_kind`
              were decoration. The block rides in the dataset now
              (`meta.deal`), which is the only channel that reaches the
              server.
            · the running clock under a `timestamp` question never ticked:
              `S` is a top-level `let`, which does not put it on `window`, and
              the guard tested `window.S`.
            Also: three status.py checks were greps for a word in game.py
            (`percent`, `wager`, `mutual`) — true from the day the scorer was
            written and still true through months in which no client could
            play any of them. They check PLAYABLE and the phone now.
            295 tests green. Verified in Chrome over CDP, two phones and a
            host: a percent round, an agreeing and a disagreeing mutual, a
            full game to a Final Receipt that changed the lead on the last
            round, and all six formats on both screens.
2026-09-24  PHOTOS (S3.12). extract.py had known about `attachment` and
            `message_attachment_join` for a year and queried neither, so every
            photograph in five years was invisible — a picture with no caption
            was dropped as "undecodable" and one with a caption kept nothing
            but an `att` flag. Four steps now, each somewhere different:
            extract joins the tables and records absolute paths in
            corpus.json; `make photos` downscales into a gitignored `photos/`
            with `sips` (macOS built-in, reads HEIC, and this can only ever run
            on the Mac that has chat.db); compile.py embeds the ones a question
            names into the dataset, so they seal with it; `/photo/current`
            serves the round on screen.
            Three decisions worth keeping:
            · BY NAME, not by index. `k` renumbers on every re-extraction, and
              a question pointing at the wrong photograph is the same failure
              curate.py bakes context to avoid.
            · NOT in the snapshot. That dict goes out on every heartbeat,
              every answer and every reconnect; a 120 KB image in it would be
              sent dozens of times a round. The client gets a flag and fetches
              once. Verified: the round's snapshot is 120 bytes.
            · NO `/photo/{id}`. An id is the only thing that would let a
              player pull a picture out of a round nobody has played, and one
              of the two players designed this deck unspoiled.
            Keeping captionless messages means the corpus gains rows and
            counts move slightly — correct, a photograph is a message. The one
            place it would have lied is `words_per_message`, which would have
            reported that the messages got shorter when what happened is that
            more of them were pictures. Filtered at the point of use, per the
            habit that has paid off twice before.
            One bug, found in the browser and not by a test: the host rendered
            the message block only `if (q.text)`, so a photo with no caption
            put nothing on the big screen while the phone showed it fine.
            311 tests green. The photo path is verified against a synthetic
            chat.db and a real browser; it has never run against the real
            thread, because chat.db is unreadable from this shell.
2026-09-24  ALL IN and ICE IN THE VEINS. The two awards superlatives.py had
            been carrying a docstring apology for since Stage 4 — both need
            `PlayerResult.stake`, which the Final Receipt now sets. 20 awards
            -> 22.
            Measured against the CAP, not against the score. DESIGN says "≥90%
            of their score", but Game.stake_cap floors everyone at 500, so a
            player on 300 points who shoves 500 has put in everything they
            were allowed to — against their score that reads as 166% and
            against 90% of it the award would fire for a player who risked
            nothing they could not afford. Against the cap it says the true
            thing: you put in everything available to you.
            Exclusive by construction rather than by suppression, the same way
            wire_to_wire and quietly_devastating are: All In takes the ones
            who shoved and lost, Ice in the Veins takes the ones who shoved
            and won, and between them each player who went all in gets exactly
            one card. Both can be shared when both of you shove.
            320 tests green. Driven in a real browser both ways — a winning
            shove fires Ice in the Veins first of five, a losing one fires All
            In, and the cards render on the podium. The losing run also
            confirmed the below-zero clamp live: 500 staked on 0 points landed
            as +0, not -500.
2026-09-24  Re-extracted against her thread with attachments on: 251,357
            messages (was 248,345 — the difference is photo-only messages,
            which used to be dropped) and 3,140 photographs.
            DUPLICATE AUDIT, on his call that the bank repeats itself. The
            finding that mattered was not repetition, it was a spoiler chain:
            `lex.love_you` carried EIGHT questions, four of them built on the
            same single message, and two of those put that message on screen
            and dated it. The Final Receipt asks who said it first and always
            plays, so a game could answer its own closer at round 4.
            Cut 11, all reversible (`status = "draft"` with the reason above
            it, so `git diff` and `make status` both show them):
            · 5 pairs computing literally the same number under two prompts.
              Where the pair spanned mine.toml and auto/, the auto one went —
              provenance is the directory.
            · `my-ily-first-who` and `my-ily-first-when`, which hand over the
              closer.
            · `top-word`, which names the word `same-page-overused` asks the
              two of you to guess.
            · `share-with-emoji`, a third telling of what the arc pair covers.
            · two questions showing a bubble another question already showed.
              251k messages; there is no excuse.
            · `goodnight-count`, a third question on one word, and a bare count.
            Reworded 14 rather than cutting them. callback/esc/turn had eight
            questions each sharing four prompt templates — the messages were
            all different, only the wording repeated, and cutting would have
            thrown away twelve rounds that put a real message on the big
            screen. Also `arc-emoji-now` ("And now?") and `arc-latenight-now`
            ("And this year?"), whose pairs sit in different `kind` buckets, so
            the interleave actively pushes them apart and either could be dealt
            alone as a round with no question in it.
            THE STRUCTURAL FIX, which is what stops this recurring:
            `max_per_kind` caps the eyebrow label, not the fact. Three
            questions about what gets sent after midnight, filed under Deep
            cut, The archive and Chronically online, were free to land in the
            same fourteen rounds. compile.py now derives `subject` from the
            resolver behind each question — the lexicon, or the resolver plus
            its argument — and `max_per_subject = 1` caps on it. A question
            baked from one real message has no subject and is never blocked,
            because it can only collide with itself. The Final Receipt is now
            chosen BEFORE the body is drawn and owns its subject, so the closer
            can no longer be pre-answered.
            Verified over 400 deals of the real deck: zero games containing the
            same subject twice, zero closers pre-answered, decks still 15
            rounds. Bank 173 -> 163, all 163 prompts distinct, 96 showing a
            real message. 340 tests green.
2026-09-24  Six more Final Receipts, on his call that he liked the mechanic and
            wanted better questions. 2 wagers -> 8, so the closer is a
            different question on the second night.
            All resolver-backed, which for the wager is a rule and not a
            preference: an answer baked into the block cannot be audited by the
            people playing it. `first_use_sender` on a milestone lexicon puts
            the real first message on screen and works out the sender at
            compile time — marriage, the far future, "I miss you", the
            distance — plus `who_says_more` on reassurance and a `busiest_year`
            choice for shape.
            THREE OF THE SIX MISFIRED and the bubbles showed it, which is the
            argument for reading the audit output rather than trusting a clean
            compile:
            · lex.future held "when we", which matched "we can decide when we
              eat" — a subordinate clause, not a statement about the future.
              The drift log had already recorded this exact phrase as a
              misfire once.
            · lex.long_distance held "call me", which matched "they call me
              jeffrey" — the naming sense, not the telephone one.
            · lex.marriage matched somebody else's wedding, because at their
              age most early mentions are. Split: `marriage` still answers "how
              often does it come up", and a new first-person `marriage_us`
              answers "who raised it about US first".
            One prompt reworded rather than chased: the first long-distance hit
            is as likely to be a grumble about FaceTime as a declaration, so
            the prompt names the category instead of promising a milestone.
            Checked every closer bubble for tells — no names, no spelling the
            deck asks about elsewhere, all under 28 words. Eight body questions
            share a subject with some closer; over 300 deals not one was ever
            dealt alongside it. 340 tests green.
2026-09-24  Same Page, on his call: it is the round he likes and it was the
            round that read as trivia you both got wrong.
            · WHOEVER AGREES FIRST NOW SCORES MORE — 500 for matching, 750 if
              you were first to lock in. The flat 500 was deliberate ("a co-op
              round shouldn't reward buzzing in") and is now overruled, with
              the reasoning left in the code so it reads as a decision rather
              than a drift. The bonus is relative, not a speed curve: it goes
              to whoever was earliest AMONG THOSE WHO AGREED, nobody who
              disagreed can earn it, and an exact tie pays nobody — the same
              tie rule superlatives.py uses. The phone works out who got it
              from the board rather than from a new server field.
            · A BANNER ON BOTH SCREENS, above the prompt, before anyone can
              answer: "No right answer · match each other · first in scores
              more". It leads with the rule because the eyebrow directly above
              it already says Same page.
            · 6 mutual questions -> 14. These carry no answer, so there is
              nothing in them to spoil either player, and they filled three of
              the areas status.py had been flagging as thin. All 14 share one
              kind and max_per_kind is 3, so at most three land per game.
2026-09-24  THE MUSIC IS GONE. sound.js had grown musical beds under the
            lobby, the question and the outro — a lookahead scheduler, a bus
            to ramp down, the lot. They were rewritten this same day from
            ambient sine pads to a Kahoot-ish major-pentatonic pluck at
            108 BPM, and then cut entirely on his call: the game wanted sound
            effects and not a soundtrack. ~126 lines removed rather than left
            dormant; git log has them.
            What survives is every one-shot, including two the game never had:
            `correct` when both of them scored and `wrong` when neither did,
            fired 420ms after the reveal so the room hears what happened
            rather than being told before it can see it. A split gets neither,
            because that is not a moment. `tick` now CLIMBS through the last
            five seconds instead of thudding flat, and `Sound.audition()`
            plays every cue in order so they can be judged without playing a
            whole game — which matters, because the one thing that cannot be
            verified from here is whether any of it sounds good.
            Verified instead by counting oscillators: the lobby schedules zero
            notes and is still at zero four seconds later, the count holds
            flat across three idle seconds mid-question, and 28 notes fire
            across three rounds where the musical version fired 145. S4.8 kept
            its ID and now checks the cue set and the *absence* of beds.
            343 tests green.
2026-09-24  A photograph of the two of them on the lobby, above the join code,
            which is the answer the title has been asking for since Stage 0.
            `static/us.jpg`, downscaled to 1200px with sips.
            IT IS GITIGNORED, and that is the whole decision: this repo is
            PUBLIC on GitHub and static/ is committed, so dropping it in would
            have published a picture of them permanently — history keeps it
            after a delete. The Dockerfile copies static/ wholesale at build
            time and .dockerignore does not touch it, so an ignored file still
            ships to Fly: the deployed game has the photo and the public repo
            does not. The cost is that a fresh clone has no photo, so the
            frame removes itself on error rather than leaving a broken box on
            the first screen of the night. Verified both ways — present and
            loaded at 1200x800, and absent with no console error.
2026-09-24  Haptics on the phone: a tick when you pick an option, a firmer one
            when the answer goes, a nudge when a question opens, and two
            different patterns at the reveal depending on whether you scored.
            Host gets none — it is a television.
            THE OBVIOUS API DOES NOTHING ON THE PHONES THIS GAME IS FOR.
            `navigator.vibrate` is Android and desktop Chrome; iOS Safari has
            never implemented it, and a game built out of iMessage is a game
            both players are holding an iPhone for. So there is a second
            backend: since iOS 17.4 a checkbox with the `switch` attribute
            fires the system haptic when it toggles, and a programmatic click
            on its label counts. Undocumented, wrapped in try/catch, feature
            detected with `"switch" in input`, and the element has to be
            rendered so it is parked off-screen rather than display:none.
            Everything degrades to silence.
            Verified by spying on Haptic itself rather than on the browser:
            every call site fires exactly once and in order, `tap` correctly
            stays quiet on slider rounds that have no options to tap, and a
            re-render mid-reveal does not buzz twice. The iOS path cannot be
            verified from here at all — it needs a real iPhone, and if Apple
            has changed the behaviour the game simply has no haptics.
            343 tests green.
2026-09-24  Professional-feel pass, on his call. The first item was not polish
            at all — it was a bug that would have ruined the night.
            · THE GHOST PLAYER. Phone identity lived in `sessionStorage`,
              which is per TAB. Tapping the link a second time from iMessage —
              how anyone reopens anything on a phone — minted a second
              identity and joined as a THIRD player who never answers. Proved
              it in a browser: three players, two called Nilu, and the tug of
              war gone for the rest of the night because it draws only for
              exactly two. Now localStorage, wrapped because Safari throws on
              it in private browsing. One device is one player however it
              arrives. Side effect worth knowing: two tabs in one browser
              profile can no longer be two players, which broke the test
              harness until it planted a distinct id per tab.
            · HOST CONTROLS. `skip` had been in the protocol since main.py was
              written and NOTHING EVER SENT IT, so a question that rendered
              badly could only be waited out. There is now a `⋯` menu on the
              topbar: skip this question, remove a player, start over.
              `Game.drop_player` also purges the player from the round log —
              leaving them in would hand a ghost a run of zeros that
              superlatives.py would award Ice Cold for.
            · The whole-screen `.fade` was unconditional, so a state message
              arriving mid-reveal re-faded everything already on screen. It
              now fires only when the phase or round actually changed. (The
              earlier claim that phases hard-cut was wrong — the transition
              was always there, it was just firing for data updates too.)
            · Totals count up instead of teleporting, easing out over 620ms
              from the score before the round, starting as the delta lands.
              Verified climbing 4,200 -> 4,950 across 15 frames.
            · theme-color, an SVG favicon and a 180px apple-touch-icon — a
              message bubble with a delivered tick and a read one. Drawn as
              SVG and rasterised through the headless Chrome already in use
              rather than adding an image dependency. The phone tab title now
              says what is happening: "Your turn 3/15", "Locked in", "The
              answer".
            · A round marker before each question — "Round 7 of 15 · Deep cut",
              and "the last one" on the Final Receipt.
            · The join screen asks for the name first, which is what its own
              copy had been asking for while the code field sat above it, and
              carries the photo so the first screen is a picture rather than a
              form.
            Deliberately NOT done: stripping the question text off the phone.
            Proposed it twice; he likes it there.
            345 tests green.
2026-09-24  Two fixes off one question each.
            · THE LOBBY ANIMATED TWICE. Measured it rather than guessed: two
              `pop` animations firing at 61ms, the roster chip and the lobby
              photograph. The chip popping means somebody arrived; the photo
              is fixed decoration that never changes and had no business
              having an entrance. Entry animation dropped from `.usphoto` and
              `.joinphoto`. One animation on the lobby now.
            · FRESHNESS WAS NEVER FED. `config.toml [deal] freshness` and
              `freshness_window` have promised since Stage 3 that replays
              would differ, and `main.py` called `g.deal()` with no `seen`
              argument — so the parameter existed, the down-weighting existed,
              and nothing ever passed the history in. Replays differed by luck.
              `History.seen(dataset, window)` now counts question ids across
              the recent games of that dataset (and only that dataset, so a
              demo rehearsal cannot age the real deck), `freshness_window`
              rides in `meta.deal` like the rest of the block, and start passes
              it.
              Measured over 300 three-game runs on the real deck: game two
              repeated 1.5 of 15 questions before, 0.8 after; game three
              repeated 2.8 before, 1.6 after. Small either way — 177 questions
              against 15 rounds is a wide bank — but it is now the rule doing
              it rather than the odds.
              Worth remembering: this reads `data/history.jsonl`, which is on
              the machine's ephemeral disk. Without a Fly volume every redeploy
              wipes it and freshness starts cold again.
            348 tests green.
2026-09-25  THE THREAD UNDER EVERY QUOTED MESSAGE (tools/rethread.py,
            `make rethread`). Half the deck put a bubble on the big screen at
            the reveal with no conversation around it: 100 questions showed a
            message and only 50 showed where it came from. curate.py bakes
            context at mint time; the families written by script — escalation,
            whose turn, what happened next, finish the sentence — never did.
            The repair could not use the ids. Several of them END IN the
            corpus index they were minted from, and after the September
            re-extraction EVERY ONE OF THOSE 36 INDICES WAS WRONG — pointing
            at a different evening, exactly the failure curate.py bakes
            context to avoid. Text is the only anchor that survives, and it
            has to be fuzzy: the quoted lines differ from the corpus by an
            apostrophe or an emoji, enough to break an exact compare and not
            enough to be a different message. Measured the near-misses at 0.97
            and 0.98 before trusting them.
            24 of 48 baked; 50 -> 72 of the 100 message-showing questions now
            carry their conversation. The other 24 are left alone and say why,
            because a thread on the wrong evening is worse than none:
            · 15 are Finish the Sentence, which quotes a PHRASE said over and
              over — 144 messages start with one of them. There is no single
              conversation behind a habit. This is the honest "does not make
              sense" case, not a matcher that gave up.
            · the rest are too short to identify or have several equally close
              candidates.
            Skipped by design: `compare` (Callback), where two messages sit
            years apart and showing one thread would say which came first; and
            every question with no message at all — counts, shares, Same Page.
            Still reveal-only. Context during the question would hand over who
            sent what, which is the answer to half the deck.
            Verified in a browser: nothing at question time, five messages at
            the reveal with the source highlighted and the standalone bubble
            removed so it is not shown twice. 362 tests green.
2026-09-25  The reveal thread is TEN either side, and it scrolls. Two proved
            the message was real; ten is enough to read the evening it happened
            in, which is what the reveal is for. Span changed in compile.py,
            curate.py and rethread.py, and `make rethread RESPAN=1 WRITE=1`
            rebuilt the ones already baked narrower — anchored on the
            `self = true` entry, which names the exact message better than any
            probe could. 72 threads, 18-21 messages each, and real.json is
            still 0.23 MB.
            On the host it opens centred on the message the question was about
            and scrolls both ways, with a mask fade top and bottom so a
            television does not need a scrollbar to say there is more. Only the
            three either side of the source stagger in — at 0.09s each,
            twenty-one would take two seconds to finish arriving.
            Three bugs on the way there, each found by measuring rather than
            by looking:
            · the regex that replaces a `context = [...]` ended `\s*$`, and
              being greedy it ate the newline after the bracket — pulling the
              next `[[q]]` onto the same line. It only showed on blocks where
              context was the last field. The rollback guard caught it and
              refused the write rather than corrupting mine.toml, which is why
              that guard is there.
            · `offsetTop` is measured from the nearest POSITIONED ancestor, and
              `.thread` was not one, so the centring arithmetic was against the
              wrong element.
            · then the arithmetic was right and the scroll still would not
              take, because it ran in `requestAnimationFrame` — WHICH DOES NOT
              FIRE IN A TAB THAT IS NOT BEING PAINTED. Every test tab, and any
              window sitting behind another. Moved to a retrying setTimeout,
              which is also more robust for the real thing.
            And one layout consequence: at 1920x1080 a 34vh thread pushed
            "Next round" off the bottom of the screen. A control the host has
            to scroll to find is a control that does not exist. 20vh — about
            five messages visible, sixteen a scroll away — and the page fits.
            364 tests green.
```
