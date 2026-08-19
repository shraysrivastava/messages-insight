# Read Receipts — POC Handover

A Kahoot-style guessing game built from a private iMessage thread. Big screen
hosts, phones play. This document hands off a working proof of concept and
scopes the move to a deployed web app.

**Status:** POC complete and playtested end to end (two simulated phones, full
game loop, zero JS errors). Not production code. Single global game object, no
auth, no persistence, no rooms.

**Where it's going:** a GitHub repo, deployed to the web, with a button on the
deployed instance to switch between test and real data. Questions will be
hand-authored rather than auto-generated.

---

## 1. What exists

```
server.py            FastAPI + WebSocket. Authoritative game state, timers, scoring.
build_game.py        Reads ~/Library/Messages/chat.db -> game_data.json.
make_fake_data.py    Generates a fake game_data.json with the same shape.
static/host.html     Big screen: lobby, countdown, question, reveal, podium.
static/player.html   Phone: join, answer, per-player result.
static/shared.js     WebSocket client, reconnect, DOM + formatting helpers.
static/app.css       Design tokens and shared components.
```

Run locally:

```bash
pip install fastapi "uvicorn[standard]" segno
python3 make_fake_data.py --out game_data.json
python3 server.py --data game_data.json --seconds 25 --rounds 14
```

### What works

- Lobby with QR join, live roster, host-triggered start
- 3-2-1 countdown, server-authoritative timer, clock-skew corrected on clients
- Four input mechanics (below), speed-weighted scoring, reveal with per-player
  deltas, running leaderboard, podium
- Phone reconnect with score retention (player id in `sessionStorage`)
- Question bank larger than rounds-per-game, reshuffled each play
- Host page rewrites its own QR/join URL to match the origin it loaded from, so
  it works unchanged behind a tunnel

### What's deliberately missing

- **Rooms.** One global game per process. `Game.code` is generated but unused.
- **Auth.** Anyone with the URL joins. Fine on LAN, not fine deployed.
- **Persistence.** Server restart wipes the game.
- **Per-question timing.** `--seconds` is global.
- **Host reconnect nuance.** Host refresh mid-question re-renders correctly but
  restarts the timer bar animation from the current remaining time (cosmetic).

---

## 2. The data contract

This is the important part, since questions are moving to hand-authored. The
server and both clients only ever see `game_data.json`. Nothing else about the
pipeline matters.

```json
{
  "meta": {
    "p1": "Shray",
    "p2": "Nilu",
    "months": ["2021-03", "2021-04", "..."],
    "rounds": 14,
    "total": 48213,
    "first": "March 2021",
    "last": "August 2026"
  },
  "questions": [ /* see below */ ]
}
```

`meta.months` must be a **contiguous, ascending** list of `YYYY-MM` strings. It
defines the slider domain for `month` questions and is indexed by their answers.
`total`, `first`, `last` are lobby copy only. `rounds` is the default
rounds-per-game and is overridable with `--rounds`.

### Two independent fields

- **`type`** drives mechanics: which input renders, how scoring works. Four
  values, listed below. Adding a fifth means touching the server's `accuracy()`
  and both clients.
- **`kind`** is a free-text label. It renders as the eyebrow above the question
  and is used to interleave the deck so the same category doesn't land three
  times in a row. **Invent as many as you like — no code changes needed.**

So "Who said it", "Fill in the blank", "Deep cut", "Petty grievances" are all
just strings. The presentation you liked is the `type`; the flavour is `kind`.

### The four types

**`binary`** — two options, all-or-nothing. On phones each option is tinted with
that player's colour, so the choice is legible at a glance.

```json
{
  "type": "binary",
  "kind": "Who said it",
  "prompt": "Who sent this?",
  "text": "the dog next door barked all night i got maybe four hours of sleep",
  "options": ["Shray", "Nilu"],
  "answer": 0,
  "reveal": "Nilu · March 19, 2021"
}
```

**`choice`** — 2–4 options, all-or-nothing. If every option is a short
non-alphanumeric string it auto-renders as large emoji tiles.

```json
{
  "type": "choice",
  "kind": "Fill in the blank",
  "prompt": "Nilu sent this. What's the missing word?",
  "text": "come over later i am making that ▁▁▁▁▁ you liked with the lemon",
  "options": ["pasta", "coffee", "picture", "playlist"],
  "answer": 0,
  "reveal": "“come over later i am making that pasta you liked with the lemon” · May 2023"
}
```

**`number`** — numeric entry, scored by proximity.
`accuracy = max(0, 1 - |guess - answer| / max(answer, 1))`.

```json
{
  "type": "number",
  "kind": "Guess the number",
  "prompt": "How many times have we said “I love you”?",
  "answer": 1877,
  "reveal": "1,877 times, and counting."
}
```

**`month`** — slider over `meta.months`, scored by proximity. `answer` is an
**index into `meta.months`**, not a date string.
`accuracy = max(0, 1 - |guess - answer| / (len(months) / 3))`, so being a third
of the thread's lifetime off scores zero.

```json
{
  "type": "month",
  "kind": "First time we said it",
  "prompt": "When did one of us first say “Goodnight”?",
  "text": "goodnight my love text me when you get home safe please",
  "answer": 7,
  "reveal": "Nilu, October 2021"
}
```

### Field reference

| Field | Required | Notes |
| --- | --- | --- |
| `type` | yes | One of the four above. |
| `kind` | yes | Free text. Eyebrow label + deck interleaving key. |
| `prompt` | yes | The question. Renders in the display serif — keep under ~22 words. |
| `text` | no | Renders as a message bubble. Omit for pure-trivia questions. |
| `options` | `binary`/`choice` | 2–4 strings. |
| `answer` | yes | Option index, raw number, or month index depending on type. |
| `reveal` | yes | Shown after scoring. This is where the payoff lives — write these like punchlines, not captions. |

**Scoring, for reference.** Up to 1000 a round:
`points = round(1000 × accuracy × speed)` where
`speed = 1 - 0.5 × min(1, elapsed / seconds)`. Answering instantly is worth
double a last-second answer. Zero accuracy scores zero regardless of speed.

---

## 3. Target state

> **Superseded.** This section described a public multi-tenant product. The
> actual target — two players, one deployed instance, no rooms or accounts —
> is in `docs/PLAN.md`. Kept here for the reasoning only.

### 3.1 Repo structure

```
read-receipts/
├── app/
│   ├── main.py            FastAPI app factory, routes
│   ├── game.py            Game state machine (extracted from server.py)
│   ├── rooms.py           Room registry — NEW
│   ├── datasets.py        Dataset discovery + loading — NEW
│   └── schema.py          Pydantic models for the data contract — NEW
├── static/                host.html, player.html, shared.js, app.css
├── datasets/
│   ├── demo.json          Committed. Fake data, safe to deploy publicly.
│   └── real.json          GITIGNORED. Never commit.
├── tools/
│   ├── build_from_imessage.py   (was build_game.py) — optional
│   ├── make_demo_data.py        (was make_fake_data.py)
│   └── validate.py              Schema validation — NEW
├── tests/
├── .env.example
├── Dockerfile
├── requirements.txt
├── CLAUDE.md
└── README.md
```

Put `datasets/real.json` and `*.db` in `.gitignore` before the first commit.
This repo will contain the entire text history of a relationship if that slips.

### 3.2 The test/prod toggle

The requirement is a button on the deployed instance that switches datasets.

**Design:**

- `datasets.py` scans `datasets/*.json` at boot, validates each against the
  schema, and exposes `{id, label, question_count, protected: bool}`.
- `GET /api/datasets` returns the list. Never returns question content.
- Host lobby renders a segmented control from that list.
- Selecting one sends `{"t": "dataset", "id": "demo"}` over the socket.
- **Server must reject this outside the `lobby` phase.** Swapping mid-game
  desyncs the deck against in-flight answers.
- Switching resets the deck and scores but keeps joined players.

**Gating the real dataset.** A public URL that serves your actual messages to
anyone who guesses it is the main risk in this whole project. Any dataset
matching a configured pattern (or flagged in a sidecar) should be `protected`,
and selecting it should require a passphrase from `REAL_DATA_PASSPHRASE`,
prompted on the host screen only. If the env var is unset, protected datasets
don't appear in the list at all — that way a fresh deploy is safe by default.

Consider not deploying `real.json` at all: deploy with `demo.json` only, and run
the real game from your Mac behind a tunnel, which is what the POC already
supports.

### 3.3 Rooms

Required once it's on a public URL. Replace the module-level `game` global with
`rooms: dict[str, Game]`.

- `POST /api/rooms` creates one, returns a 4-letter code
- `/ws?room=ABCD` scopes the socket
- Phones join at `/play?room=ABCD`; the QR already encodes the full URL
- Reap rooms idle for N minutes so memory doesn't grow unbounded

The code generator already exists in `Game.__init__`.

### 3.4 Deployment

The server holds game state in memory and runs asyncio timer tasks. That
constrains the platform more than it looks:

| Platform | Verdict |
| --- | --- |
| Fly.io / Railway / Render | **Recommended.** Long-lived process, native WebSockets. Pin to a single replica or rooms will land on different machines. |
| A small VM + Caddy | Fine. Most control, most setup. |
| Vercel / Netlify | **Won't work as-is.** No long-lived WebSocket connections. |
| Cloudflare Workers | Possible but a rewrite — game state has to become a Durable Object. |

Single replica is the constraint to remember. If you ever need to scale past
one, move room state to Redis and the timers to a scheduler; don't try to make
in-memory state work across replicas.

Health check at `GET /healthz` for the platform's probe.

---

## 4. Suggested task order

> Superseded by `docs/PLAN.md` §9. Kept for the reasoning.

1. **Extract and test the state machine.** Pull `Game` out of `server.py` into
   `app/game.py` with no framework imports. Unit-test `accuracy()` and `grade()`
   directly — scoring is the thing most likely to break silently and the thing
   you'll least want to debug live.
2. **Add `schema.py` + `tools/validate.py`.** Pydantic models for the contract
   above. Validate on load and fail loudly. This matters more than usual because
   you're hand-authoring: a `month` answer that's out of range or an `answer`
   index past the end of `options` should fail at boot, not at round 9.
3. **Author your question set.** Write into `datasets/real.json` (or a directory
   of per-kind files that `validate.py` merges). Start with 3× your
   rounds-per-game so replays differ.
4. **Datasets module + `/api/datasets` + host toggle.** Lobby-only switching.
5. **Passphrase gate for protected datasets.**
6. **Rooms.**
7. **Dockerfile + deploy to one of the recommended platforms.**
8. **Playwright smoke test** driving one host and two phones through a full
   game, asserting final scores. The POC was verified this way and it caught
   real bugs; worth keeping in CI.

Items 1–3 are worth doing before anything deploy-related. The question content
is the actual product; the infrastructure is replaceable.

---

## 5. Authoring notes

Things learned building the generated version that apply to hand-written
questions:

- **`reveal` is the payoff.** The mechanic is a pretext for showing her a
  message she forgot about. Spend effort here.
- **Mix proximity and all-or-nothing.** A deck of only multiple choice makes
  scores lurch by 1000. The `number` and `month` types produce close finishes.
- **Bubble text under ~28 words.** Longer doesn't fit the big screen at the
  sizes the design uses.
- **Don't make the first `month` answer index 0.** The slider defaults to the
  midpoint, and answers at either extreme are guessable from the range alone.
- **For `choice`, distractors should be plausible in context.** Random words are
  instantly eliminable, which makes the round free points.
- **Interleaving is by `kind`.** If you write 20 questions all with the same
  `kind`, the deck can't interleave and it'll feel repetitive. Vary the label
  even for the same mechanic.

---

## 6. Design system

Defined in `static/app.css`. Keep it if you like it; the tokens are all in
`:root`.

- **Palette:** night plum ground (`#191325`), raised surface (`#241C36`), warm
  amber (`#F2A65A`) and cool periwinkle (`#8B8CE8`) as the two player tints, six
  colours total in `COLORS` in the server for extra players.
- **Type:** Fraunces (display, variable optical size), Karla (body and message
  bubbles), Space Mono (timestamps, scores, meta). Loaded from Google Fonts with
  Georgia/system fallbacks. **Self-host these if you deploy** — one less
  third-party dependency and it works offline.
- **Signature element:** the iMessage typing indicator. It's the loading state,
  the waiting state, and the beat before a reveal. It's the one thing that ties
  the interface to the source material — worth preserving.
- **Motion:** everything is behind `prefers-reduced-motion`.

Known gaps: player identity is conveyed by colour alone in a few places (add a
shape or initial for accessibility), and the timer bar has no non-visual
equivalent.

---

## 7. Privacy

Stating it plainly since it's easy to lose track of once this is a normal-feeling
web app:

- The real dataset is a searchable archive of a private relationship. Treat the
  JSON like a credential.
- `.gitignore` it before the first commit, not after. Git history is forever.
- Deployed instances should default to demo data with no path to real data
  unless an env var is set.
- `build_from_imessage.py` copies `chat.db` to a temp dir and never writes back,
  but the temp copy isn't cleaned up on exit — worth fixing if you keep it.
- If you deploy the real dataset anywhere, be certain you'd be comfortable with
  the hosting provider having it.
