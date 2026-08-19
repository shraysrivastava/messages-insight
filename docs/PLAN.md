# Read Receipts — Build Plan

**Occasion:** 5-year meetaversary, ~mid-September 2026. Four weeks from 2026-08-18.
**Players:** two, in different states, over the internet.
**Deployment:** one always-on instance on a public URL. No database, no accounts.
**Content:** authored in `questions/`, compiled to JSON.

| | |
| --- | --- |
| What it feels like | [`DESIGN.md`](DESIGN.md) |
| How to write questions | [`QUESTIONS.md`](QUESTIONS.md) |
| What's done right now | [`STATUS.md`](STATUS.md) · `python3 tools/status.py` |
| The original POC handover | [`HANDOVER.md`](HANDOVER.md) — §2 data contract still authoritative |

**Task IDs in this document are the same IDs `tools/status.py` verifies.** `S2.6`
here is `S2.6` there. There is one list, and the script checks it against the
filesystem so it can't drift.

---

## 0. The governing rule

**The game must be playable at the end of every stage.** Not in theory —
playable as in you could run it that night if you had to. The POC already clears
that bar on fake data, so this plan is not "build until done"; it's *keep a
shippable game at all times and raise its quality.*

Two consequences that shape everything below:

1. **Stage 2 is the ship line.** Stages 3 and 4 are upside. Stop at any Sunday
   and you still have a real game.
2. **Author content for mechanics that may never exist.** `compile.py` skips
   question types the server doesn't support and reports what it dropped, so the
   `percent` and `wager` questions sitting in the bank today cost nothing if you
   never build those types.

---

## 1. Decisions locked

| Question | Decision | Consequence |
| --- | --- | --- |
| Rooms | **Cut.** One global game per process. | `Game.code` becomes a join code. |
| Auth | **Cut accounts.** Join code for phones, passphrase for real data. | ~40 lines, no auth library. |
| Persistence | **Cut.** In-memory plus a JSONL file. | No Postgres, no Redis. |
| Real data on the server | **Ships encrypted.** No plaintext on the host, ever. | Passphrase lives in your head. §4. |
| Question source | `questions/` → `compile.py` → JSON. Miner and review UI feed it. | §3. |
| Question priority | **Yours beat generated ones**, structurally. | §5. |
| Bank size | **60 to ship, 90+ to be proud of.** | 156 authored, 98 shippable today. |

### Two things worth changing your mind about

**An unguessable URL is not access control.** Once the real dataset is on a public
host, the only thing between five years of your messages and a stranger is that
nobody has typed your URL. §4 fixes it in about an hour, and done that way the
hosting provider never holds anything readable either. It's in the MVP.

**The POC penalises whoever has worse latency.** `grade()` computes speed from
`p["answered_at"] = time.time()` — when her tap *reaches the server*. She's in
another state: a 30–80ms handicap every round, on a model where answering fast is
worth 2×. `S2.4` fixes it. Small diff, and it's the difference between a fair game
and one she narrowly loses for invisible reasons.

---

## 2. Repo shape

```
read-receipts/
├── README.md            start here
├── docs/
│   ├── PLAN.md          this file — what to build, in what order
│   ├── DESIGN.md        what it feels like — screens, motion, awards
│   ├── QUESTIONS.md     how to write questions
│   ├── STATUS.md        manual checkboxes; the rest is automated
│   └── HANDOVER.md      original POC handover (archive)
├── app/                 the server
│   ├── main.py          FastAPI app, routes, websocket
│   ├── game.py          state machine — no framework imports
│   ├── datasets.py      discovery, decryption, caching
│   ├── schema.py        the data contract as pydantic models
│   ├── superlatives.py  [stage 4] awards over the round log
│   └── history.py       [stage 4] past games
├── questions/           the content
│   ├── config.toml      names, dealing rules, dedup policy, guards
│   ├── lexicons.toml    45 robust phrase sets
│   ├── mine.toml        YOUR questions — priority
│   ├── auto/            generated questions — filler
│   └── inbox.md         raw idea dump
├── tools/
│   ├── extract.py       chat.db  → corpus.json          (local only)
│   ├── mine.py          corpus   → candidates.json      (local only)
│   ├── curate.py        review UI → mine.toml
│   ├── compile.py       questions/ + corpus → real.json
│   ├── seal.py          real.json ↔ real.json.enc
│   ├── validate.py      schema check
│   └── status.py        ← the dashboard. already works.
├── static/              host.html, player.html, shared.js, app.css, fonts/
├── datasets/
│   ├── demo.json        committed, fake, safe to deploy
│   └── real.json.enc    committed, encrypted, ciphertext only
├── data/history.jsonl   [stage 4] Fly volume, gitignored
├── poc/                 the original proof of concept, kept runnable
└── tests/
```

**Everything has one home.** Docs in `docs/`, content in `questions/`, scripts in
`tools/`, server in `app/`. The POC stays in `poc/` so you can always fall back to
something that runs.

**`.gitignore` before the first commit** (`S1.1`). No commits exist yet, so this is
free now and permanent if you miss it:

```gitignore
chat.db*
corpus.json
candidates.json
questions/mine.toml
questions/inbox.md
datasets/real.json
data/
*.sqlite
.env
```

Note what is *not* ignored: `datasets/real.json.enc`, and `questions/auto/`.
Deliberate — the generated questions contain no message text, only lexicons.

**One tension to resolve at `S2.6`.** `mine.toml` is gitignored because it will
contain real message text — but it's also the most valuable thing you'll produce,
and gitignoring it means your best work has no version control and no backup. Fix
it the same way as the dataset: have `seal.py` also encrypt
`questions/mine.toml` → `questions/mine.toml.enc` and commit *that*. Same
passphrase, ten extra lines, and a month of authoring survives a dead laptop.
Until then, back it up somewhere that isn't this folder.

---

## 3. The content pipeline

```
chat.db ──extract──▶ corpus.json ──mine──▶ candidates.json
                          │                      │
                          │                 curate.py ◀── you, judging
                          │                      │
                          │                      ▼
                          └────────────▶  questions/mine.toml ◀── you, writing
                                                 │
                                          + questions/auto/
                                                 │
                                            compile.py
                                                 ▼
                                        datasets/real.json ──seal──▶ .enc ──▶ deploy
```

`chat.db` never leaves your Mac. What reaches the server is ~90 snippets you
personally approved, encrypted.

### 3.1 `extract.py` (`S1.3`)

`build_game.py`'s db layer, minus question generation. Keep `open_db()` and
`decode_attributed_body()` verbatim — they work and they were the hard part. Fix
the temp-dir leak (HANDOVER §7) with `tempfile.TemporaryDirectory()`. Drop
tapbacks, attachment-only, URL-only, and anything under 3 words. **Keep the `i`
index and ordering** — curation and reveals need `i±5` context. Also emit
`meta.months` and `meta.density` (messages per month); density is free here and
powers the slider histogram in stage 3.

### 3.2 `mine.py` (`S1.11`)

The `build_game.py` generators become *candidate* producers. Over-generate (40–60
each, not `rounds+1`) and attach provenance: source index, date, ±5 context. Rank
by rough interestingness so the good ones surface in the first hundred you see.

### 3.3 `curate.py` (`S2.1`)

A localhost FastAPI page. **The highest-leverage thing in the plan** — it turns
"author 90 questions from memory" into "make 300 fast judgments." One day.

1. Keyboard only: J reject, K accept, E edit.
2. Context window always visible — you can't write a payoff without it.
3. Resumable. Appends to `mine.toml`, tracks reviewed ids in a sidecar.
4. **Free-text search mode.** Type `goodnight`, see every hit with dates, mint a
   question from any of them. Your best 15 questions come from here.
5. Validates on accept.

### 3.4 `compile.py` (`S1.12`)

The bridge from authoring to game. Its job:

- **Merge** `mine.toml` + `auto/*.toml`, tagging origin by directory.
- **Normalise** before matching: NFKC, lowercase, apostrophes dropped so `I'm` and
  `im` unify, emoji stripped of variation selectors and skin tones, punctuation
  gone. Then expand every literal phrase into a repeat- and space-tolerant regex —
  `i love you` → `\bi+\s*l+o+v+e+\s*y+o+u+\b`, catching `iloveyou` and
  `i loveeee youuu` while still refusing `i love your hair`.
- **Resolve** computed answers against `corpus.json` through named lexicons.
  `{ count = "love_you" }` covers ily/ilysm/i love u/luv u as one set, counting each
  message once so overlapping variants never double-count. 98 questions in the
  bank resolve themselves this way.
- **Deduplicate**, preferring yours (§5).
- **Enforce the fairness guards** from `config.toml [guards]`: drop `who_*`
  questions closer than 1.25× (a coin flip in costume), `number` answers under 20
  (proximity scoring is degenerate), `month` answers in the first or last 10% of
  the timeline (guessable from the slider range alone), and anything with a `TODO`
  reveal. Report every drop with its reason.
- **Skip unsupported types** with a clear line: `skipped 17 (percent, wager,
  mutual — not built yet)`.
- **Validate** survivors against `schema.py` and fail loudly.
- **Print a composition summary** — counts by type, kind, area, and origin.

Resolvers used by the current bank, for reference when implementing:
`count`, `count_phrase`, `count_regex`, `count_emoji`, `total_messages`,
`distinct_emoji`, `attachments`, `messages_between`, `longest_message_words`,
`longest_gap_hours`, `max_day_count`, `longest_streak_days`, `avg_per_day`,
`days_until`, `question_count`, `share_of_messages`, `share_between`,
`share_with_emoji`, `share_one_word`, `share_days_covered`, `share_questions`,
`share_weekend`, `share_quick_reply`, `first_use`, `first_use_sender`,
`busiest_month` (with optional `within = "<lexicon>"`), `quietest_month`,
`busiest_year`, `peak_hour`, `who_says_more`, `who_more`, `top_emoji`, `top_word`,
`busiest_weekday`, and `source = { mine = … | search = … | first_message = true }`.

---

## 4. Getting real data deployed, safely

- `seal.py` (`S2.6`) encrypts `real.json` → `.enc` with a passphrase (Fernet +
  scrypt, both in `cryptography`). Commit the ciphertext.
- **The server has no key.** Not an env var, not a Fly secret, not on disk.
- Host toggle: `[ Demo ] [ Real 🔒 ]`. Clicking Real prompts for the passphrase.
  Server derives the key, decrypts into memory, caches for the process lifetime,
  never writes plaintext.
- Wrong passphrase → generic failure. Rate-limit 5/minute.

**Why not an env var:** a compromised host holds ciphertext; the `.enc` in git
history is a non-event, which removes the scariest failure mode in the project (an
accidental `git add .` at 1am); and the passphrase is both the gate *and* the key,
so there's no way for one to pass while the other holds. Cost: you type it once
per game night.

**Join code** (`S2.3`). `Game.code` already generates one that nothing uses. Wire
it up — a stray visitor sees a join screen instead of your messages. Encode it in
the QR so her scan skips the typing.

---

## 5. Question priority — yours win

You said you won't audit the generated questions. So the system is built to make
that unnecessary.

**Provenance is the directory.** `questions/mine.toml` is yours.
`questions/auto/*.toml` is generated. There is no field to remember and no way to
mislabel anything.

**Dealing** (`S3.8`, `config.toml [deal]`):

- `authored_share = 0.65` — the dealer fills 65% of every 14-round game from
  `mine.toml` first, then tops up from `auto/`. Write 30 and ~9 of every 14 rounds
  are yours; write 60 and it's your game with generated filler.
- `weight_mine = 4` — for the remaining slots yours are sampled at 4× weight.
- `max_per_kind = 3` — no category dominates a single game.
- `freshness = true` — prefer questions not seen in the last 3 games, read from
  `history.jsonl`. This is what makes five replays feel like five games.
- `final_receipt = true` — always end on a wager if any are available.

**Deduplication** (`config.toml [dedup]`):

- Every question has a `topic`, defaulting to its `id`. Two questions sharing a
  topic are duplicates and the generated one is **dropped silently**.
- So: to kill a generated question you don't like, write your own with the same
  `topic`. That's the entire mechanism, and it means you never open `auto/`.
- Beyond exact topics, prompts are compared. Above 0.82 similarity the pair is
  *reported*, never auto-dropped — too easy to lose something you wanted.
- Two of *yours* colliding is an error, not a silent drop.

`tools/status.py --bank` shows whether you've written enough for the dealer to hit
its authored share, so you always know if the game is yours or the robot's.

---

## 6. Stages

Every stage ends playable. IDs match `tools/status.py`.

### Stage 1 — Foundations · *playable locally, on real data*

| ID | Task |
| --- | --- |
| `S1.1` | `.gitignore` protecting real data |
| `S1.2` | First commit |
| `S1.3` | `tools/extract.py` |
| `S1.4` | `corpus.json` built from the real thread |
| `S1.5` | `app/schema.py` — the data contract as pydantic models |
| `S1.6` | `tools/validate.py` |
| `S1.7` | `app/game.py` extracted from `poc/server.py`, no framework imports |
| `S1.8` | **The round log.** `grade()` appends a `RoundRecord` (DESIGN §0) |
| `S1.9` | Scoring tests: every type, boundaries, everyone-answered-early |
| `S1.10` | Tests pass |
| `S1.11` | `tools/mine.py` |
| `S1.12` | `tools/compile.py` |
| `S1.13` | `datasets/real.json` compiles clean |

`S1.8` is the only thing here that pays forward rather than out. It does nothing
on its own, but superlatives, history, the score graph and the receipts reel are
all pure functions over it — and retrofitting it later means reopening scoring
code you've already tested. One hour now, saves a day in stage 4.

**Gate:** you can play a rough game on your laptop, on real data.

### Stage 2 — MVP · *she can play from another state*

| ID | Task |
| --- | --- |
| `S2.1` | `tools/curate.py` |
| `S2.2` | 60+ shippable questions |
| `S2.3` | Join code enforced |
| `S2.4` | Client-timestamped answers, server-clamped to the question window |
| `S2.5` | WebSocket heartbeat, ping every 25s |
| `S2.6` | `tools/seal.py` |
| `S2.7` | `datasets/real.json.enc` committed |
| `S2.8` | `app/datasets.py` + lobby-only toggle |
| `S2.9` | `datasets/demo.json` committed |
| `S2.10` | Dockerfile |
| `S2.11` | `fly.toml` with `auto_stop_machines = false` |
| `S2.12` | Fonts self-hosted |

**`S2.11` is the #1 way game night goes wrong.** A lobby sits idle for minutes
while you both get settled; a machine that scales to zero under it kills the game
before it starts. Pair with `min_machines_running = 1` and pick a region between
your two states.

Platform: **Fly.io.** Long-lived process, native WebSockets, single replica
trivial. Railway and Render equivalent. Vercel and Netlify cannot host this.

**Gate:** a full 14-round game has been played on the deployed URL. **This is the
ship line.**

### Stage 3 — Feel · *the version worth showing people*

| ID | Task | Cost |
| --- | --- | --- |
| `S3.1` | Month slider density histogram | 2h |
| `S3.2` | Reveal choreography + context thread | 4h |
| `S3.3` | Locked / read-receipt state | 2h |
| `S3.4` | `app/superlatives.py` | 5h |
| `S3.5` | Superlatives tested against a synthetic log | 1h |
| `S3.6` | `percent` type | 0.5h |
| `S3.7` | `wager` / Final Receipt | 2h |
| `S3.8` | Weighted dealing — yours first | 1h |

`S3.1` is the highest payoff in the project: one bar per month behind the slider,
height = volume. She's sliding across a picture of your relationship and the spikes
are landmarks. The data is already in `meta.density`.

`S3.7` matters more than it looks — right now a 2,000-point deficit makes the last
round dead. A wager makes the endgame live.

**Gate:** the game feels designed rather than assembled.

### Stage 4 — The Arc · *history, awards, the emotional close*

| ID | Task | Cost |
| --- | --- | --- |
| `S4.1` | Score graph, inline SVG | 2h |
| `S4.2` | `app/history.py` + `history.jsonl` | 4h |
| `S4.3` | History shelf in the lobby | 2h |
| `S4.4` | Receipts reel | 3h |
| `S4.5` | Sound design | 3h |
| `S4.6` | `mutual` type — Same Page rounds | 4h |
| `S4.7` | Playwright smoke test in CI | 2h |

**Gate:** past games, awards, and a receipts reel.

### Game day

The `M5.x` checks in `STATUS.md`. Dress rehearsal on real data, alone, on the
deployed URL — that one is not optional.

---

## 7. Beyond game night

The thing you're building is annual. Worth knowing now, because two of these are
much cheaper if stage 4 lands.

- **Re-run it next year.** Re-extract, recompile, and the freshness rule in the
  dealer means year six draws different questions from a bigger corpus. The
  history shelf shows every previous meetaversary.
- **The reel as an artifact.** Print the receipts reel to PDF. Five years of these
  on a shelf.
- **Let her author.** A second `hers.toml` with the same priority as `mine.toml`,
  and a curate session she runs. The game gets better when it's not one-sided.
- **Other occasions.** The pipeline is chat-agnostic. Group chats work; a
  bachelor party version of this writes itself.

None of it is scheduled. It's here so stage 4 decisions don't accidentally
foreclose it.

---

## 8. Never doing

Rooms. Accounts. A database. Multi-tenancy. Browser dataset upload. Scaling past
one replica. Free-text answers. Each is real work nobody but the two of you would
ever benefit from.

---

## 9. Schedule

Two tracks. **Content** on evenings — low energy, no context switch. **Build** on
weekends. Content is the critical path.

| Week | Build | Content |
| --- | --- | --- |
| **1** Aug 18–24 | `brew install python@3.12` · Stage 1 complete | Fill `meta.p2`, `lex.pet_names`, `lex.inside_jokes` · write 10 in `mine.toml` |
| **2** Aug 25–31 | `S2.1`–`S2.7` | 3–4 evenings in `curate.py`, target 60 accepted |
| **3** Sep 1–7 | **Finish stage 2, play it deployed** · start stage 3 | Bank to 90 · write your Final Receipts |
| **4** Sep 8–14 | Stage 3 done · stage 4 top-down as time allows · dress rehearsal | Reread every reveal in one sitting; rewrite the weak ones |

### Prerequisite

Your `python3` is **3.9.6**, the macOS system Python. `tomllib` landed in 3.11.

```bash
brew install python@3.12
```

Match it in the Dockerfile. `tools/status.py` falls back to `tomli` if you'd
rather wait, but 3.9 is end-of-life this October.

**If you fall behind:** stop taking stages. Never cut below 60 questions, never
skip the dress rehearsal. A rough game that runs beats a beautiful one that
doesn't.
