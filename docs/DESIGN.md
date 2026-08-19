# Read Receipts — Game Design

Companion to [`PLAN.md`](PLAN.md) (build sequence, stage IDs) and
[`HANDOVER.md`](HANDOVER.md) §2 (data contract). This document covers what the
game *feels* like: screens, motion, superlatives, the deck, and the history shelf.

Stage IDs referenced here (`S3.1`, `S4.2`…) are the same ones
`python3 tools/status.py` verifies.

---

## 0. The one thing that makes the rest free

Everything you asked for — superlatives, the game history, the score graph, the
receipts reel — is a *view* over a single structure the server doesn't currently
keep: **the round log.**

```python
# app/game.py
@dataclass
class RoundRecord:
    index: int
    kind: str                # "Petty grievances"
    type: str                # "binary"
    prompt: str
    reveal: str
    correct: Any             # q["answer"]
    text: str | None         # the message bubble, for the reel
    context: list | None     # ±2 surrounding messages, for the reel
    results: dict[str, PlayerResult]   # pid -> below

@dataclass
class PlayerResult:
    answer: Any
    points: int
    accuracy: float
    elapsed: float           # seconds from question open
    rank_after: int          # position on the board after this round
```

`grade()` appends one `RoundRecord`. That's the only server change any of this
needs. Superlatives are pure functions over `list[RoundRecord]`. The score graph
is a `map` over it. The reel is the log with the scoring stripped out. The history
shelf is a list of finished logs.

Build this in week 1 when you extract `game.py` — retrofitting it later means
touching scoring code you've already tested.

---

## 1. Screen flow

```
LOBBY ─→ COUNTDOWN ─→ QUESTION ─→ LOCKED ─→ REVEAL ─→ STANDINGS ─┐
  ↑                       └──────────────────────────────────────┘
  │                                    (×14)
  └──────── PODIUM ←─ SUPERLATIVES ←─ SCORE GRAPH ←─ FINAL RECEIPT
                 └─→ RECEIPTS REEL
```

Six of those are new. Each is small; the choreography is where the fun lives.

---

## 2. Screen by screen

### 2.1 Lobby — "Previously on Read Receipts"

The lobby currently shows a QR and a roster. Give it the history shelf:

```
┌────────────────────────────────────────────────────┐
│                  READ RECEIPTS                     │
│         48,213 messages · March 2021 – now         │
│                                                    │
│    ┌──────────┐   join at readreceipts.fly.dev     │
│    │ QR CODE  │   code  ▸ NILU ◂                   │
│    └──────────┘                                    │
│                                                    │
│  ● Shray  joined      ● Nilu  ···  (typing dots)   │
│                                                    │
│ ──── HEAD TO HEAD ───────────────────────────────  │
│         Shray  3 — 2  Nilu                         │
│                                                    │
│ ┌─ Aug 14 ──────┐ ┌─ Jul 2 ───────┐ ┌─ Jun 9 ────┐ │
│ │ 8,410 – 7,955 │ │ 6,201 – 9,110 │ │ 9,004–8,7… │ │
│ │ Nilu  👑      │ │ Shray 👑      │ │ Nilu 👑    │ │
│ │ "Fastest      │ │ "Comeback     │ │ "Perfect   │ │
│ │  Finger"      │ │  Kid"         │ │  Month"    │ │
│ └───────────────┘ └───────────────┘ └────────────┘ │
│                                                    │
│              [ dataset: Demo | Real 🔒 ]           │
│                     ( S T A R T )                  │
└────────────────────────────────────────────────────┘
```

- **Join code** is `Game.code`, which already exists unused. Force it to something
  pronounceable rather than random letters — seed a wordlist of your inside jokes.
- **The typing indicator** as the "waiting for her to join" state. handover §6 is
  right that it's the signature element; the lobby is where it earns its keep.
- **History cards are clickable** → opens that game's receipts reel. Five years of
  meetaversaries and this shelf becomes the actual artifact.

### 2.2 Countdown

Keep the 3-2-1 but make it thematic: three message bubbles land in sequence with
the iMessage *send* sound, then the question slides up. Round card first:

> **ROUND 5**
> *Petty Grievances*

That's a half-second card announcing the `kind`. Cheap, and it makes a deck of 14
feel like it has movement instead of being a list.

### 2.3 Question — per-type interaction

This is where "fun and interactive" is won or lost. Each type gets a real input,
not a generic form.

**`binary`** — two full-bleed tiles, each tinted with that player's colour. On the
phone they're thumb-sized and the whole tile is the hit target. Tapping commits
with a haptic-style bounce.

**`choice`** — 2–4 tiles. Already auto-renders as large emoji when the options are
emoji; keep that. Add a **staggered entrance** (40ms apart) so the options don't
all appear at once — it reads as dealing cards.

**`number`** — a big odometer-style entry. Digits roll rather than type. Below it,
a live "warmer/colder" is *not* possible (no feedback pre-reveal), so instead show
a **reference anchor**: "for scale: 48,213 total messages". Anchors turn a blind
guess into a real decision.

**`month`** — the slider is the best input in the game and it's currently plain.
Put a **message-density histogram** behind it: one bar per month, height = message
volume. She's now sliding across a picture of your relationship, and the spikes
(the summer you met, the month one of you moved) are legible landmarks. This is
the single highest-payoff UI change in this document. The data is free — you have
every timestamp in `corpus.json`; precompute `meta.density: [int]` alongside
`meta.months`.

**`percent`** — see §5. A 0–100 slider with the fill in your two player colours,
so "what share of our messages did I send?" is literally a tug-of-war bar.

### 2.3b Presentation formats

Four mechanics, but a deck of 14 rounds that all *look* the same is a deck that
feels like a form. `format` is a rendering hint on each question; unknown values
fall back to `bubble`, so adding one can never break a game.

| `format` | What renders | Used by |
| --- | --- | --- |
| `bubble` | one message, centred, big | who-said-it, date-this |
| `blank` | one message with a word knocked out | fill in the blank |
| `redacted` | one message, several words knocked out | deep cuts |
| `compare` | two bubbles stacked, A above B | which came first, real-or-fake |
| `thread` | three messages; the question is about the middle one | what happened next |
| `timestamp` | **no message at all** — just `3:41 AM · a Tuesday in 2023` | who was awake |

`timestamp` is the sleeper. Withholding the message entirely and giving only the
hour is a completely different kind of guess, and it costs nothing to render.

Rotate formats deliberately when authoring: three `bubble` rounds in a row is the
same failure as three rounds of the same `kind`.

### 2.4 Locked — the read receipt

The moment you answer, your screen changes to a waiting state. Use the actual
iMessage vocabulary:

- Your answer appears as a sent bubble, right-aligned, in your colour.
- Underneath, in Space Mono, grey: `Delivered`
- When she answers: it flips to `Read 9:42 PM` and the host screen shows her
  avatar dot fill in.
- While waiting, the typing indicator pulses under her name.

On the host screen, a compact row: `Shray ✓ locked in 3.2s · Nilu ···`. Do **not**
show whether the answer was right. The tension between "she answered fast" and
"was she right" is the whole hook.

### 2.5 Reveal — the payoff

handover §5 says the reveal is the point. Give it choreography rather than a
label swap:

1. Timer bar drains to zero and the room goes quiet for ~400ms. Silence is the
   effect.
2. The correct answer illuminates. Wrong tiles desaturate and shrink slightly.
3. **The context window animates in** — the ±2 real messages around the source
   message, as a small thread, with the answer message highlighted. This is why
   `curate.py` captures context: the reveal isn't "the answer was pasta", it's
   *the actual conversation from May 2023 where you said it*.
4. The `reveal` line types out with the typing indicator first, then lands.
5. Points fly from each player's tile into the leaderboard as `+847`, and the
   bars re-sort with a spring.

Per-player on phones: the delta, the streak state, and a one-line verdict that
varies by outcome — `Nailed it.` / `Off by one month.` / `Not even close, love.`

### 2.6 Standings

Horizontal bars, two of them, animating between rounds. Show the **gap**, not just
the totals — `Nilu leads by 340` is more dramatic than two numbers. Mark lead
changes with a flash. With two players the leaderboard is a tug-of-war, so draw it
as one: a single bar with a moving centre line.

### 2.7 Final Receipt — the wager round

Round 14 is a wager (§5). Before the question, each of you secretly stakes up to
your current score. Then the question. Then the reveal shows both wagers.

This is a five-line scoring change and it's the reason the game ends on a scream
instead of a shrug. A 2,000-point deficit going into the last round is currently
unrecoverable and the round is dead; with a wager it's live until the last second.

### 2.8 Score graph

A line chart, two lines, 14 rounds across the x-axis. Lead changes marked with a
dot. Biggest single round annotated. Draw it as raw inline SVG — it's ~40 lines and
a charting library is not worth the payload.

This is the "cool history of the game" in one image, and it's the thing worth
screenshotting.

### 2.9 Superlatives

See §3. Deal them one at a time as cards, ~2 seconds apart, with the reveal sound.

### 2.10 Podium

Confetti, both names, final scores, the winner's crown. Then, prominently:
**[ replay the receipts ]**.

### 2.11 Receipts reel

Every round from the game, scrollable, scoring stripped away: the message, its
context, the date, the reveal line. The mechanic was always a pretext for showing
her messages she forgot about — this is that with the game removed.

Make it linkable per-game so the lobby history cards open straight into it.

---

## 3. Superlatives

End-of-game awards computed from the round log. Rules:

- **Every award needs a threshold** so it doesn't fire on noise. "Fastest Finger"
  off a 0.1s average difference is not a joke, it's a rounding error.
- **Deal 4–6 per game**, not all of them. Score each fired award by how decisive it
  was and take the top ones. Different games surface different awards, which is what
  makes them feel earned.
- **Ties go unawarded.** Silence is better than a limp award.

### Catalog

| Award | Rule | Threshold |
| --- | --- | --- |
| **Fastest Finger** | Lowest mean `elapsed` | Gap ≥ 1.5s |
| **The Overthinker** | Highest mean `elapsed` on rounds they got *right* | ≥ 3 correct, gap ≥ 2s |
| **Buzzer Beater** | Most answers in the final 3 seconds | ≥ 3 |
| **Panic Button** | Fastest answer that scored zero | ≤ 2.0s |
| **Clairvoyant** | Exact hit on a `month` question | accuracy == 1.0 |
| **The Historian** | Best mean accuracy across `month` rounds | ≥ 3 month rounds, gap ≥ 0.15 |
| **The Accountant** | Best mean accuracy across `number` rounds | ≥ 3 number rounds, gap ≥ 0.15 |
| **Mind Reader** | Best on "who said it" rounds | ≥ 4 rounds, ≥ 80% |
| **Ice Cold** | Longest run of consecutive zeros | ≥ 3 |
| **On Fire** | Longest run of consecutive correct | ≥ 4 |
| **Comeback Kid** | Largest improvement in rank/gap from mid-game to final | trailed by ≥ 1500 and won |
| **Wire to Wire** | Led after every single round | 14/14 |
| **Same Page** | Most `mutual` rounds matched | ≥ 60% of mutual rounds |
| **Split Brain** | Rounds where you both answered *the same wrong thing* | ≥ 2 |
| **The Sniper** | Closest `number` guess of the game | within 5% |
| **Wildly Optimistic** | Largest overshoot on a `number` | ≥ 4× the answer |
| **Sentimental** | Best on rounds whose `kind` is a soft category | ≥ 3 rounds |
| **The Realist** | Best on rounds whose `kind` is "Petty grievances" | ≥ 3 rounds |
| **All In** | Wagered ≥ 90% of their score on the Final Receipt | — |
| **Ice in the Veins** | Won the Final Receipt after wagering everything | — |
| **Quietly Devastating** | Won without ever leading until the final round | — |
| **The Constant** | Lowest variance in per-round points | ≥ 8 scoring rounds |

Each award card carries the *evidence*: `Fastest Finger — Nilu, 4.1s average, 2.3s
faster than you`. Evidence is what makes it funny rather than generic.

**Implementation:** one module, `app/superlatives.py`, a list of
`(name, blurb_fn, evaluate_fn)`. Every `evaluate_fn` takes `list[RoundRecord]` and
returns `None` or `Award(winner, evidence, decisiveness)`. Trivially unit-testable
against a synthetic log, which you should do — an award that misfires live is worse
than no award.

---

## 4. Game history without a database

You're right that this doesn't need one. It needs a list and a file.

```python
# in memory
history: list[GameSummary]   # newest first, capped at 50
```

```python
@dataclass
class GameSummary:
    id: str                  # short slug, "aug14-2026"
    played_at: datetime
    dataset: str             # "real" | "demo" — never mix these in the record
    scores: dict[str, int]
    winner: str
    superlatives: list[Award]
    rounds: list[RoundRecord]     # the whole log, for the reel and the graph
```

**Persistence:** append the summary as one line of JSON to `data/history.jsonl` on
a Fly volume, load it at boot. That's twenty lines, no schema migrations, no ORM,
and it survives the deploys you'll be doing right up until game night. A file is
not a database.

**Keep demo and real history separate.** Filter the lobby shelf by the currently
selected dataset, or your test runs will pollute the record you actually care
about. Demo games can be discarded entirely on restart.

**Derived all-time stats** for the lobby, computed on the fly from the list:

- Head-to-head record
- Highest single game, highest single round
- Best-ever `month` guess
- Most-awarded superlative per person ("Nilu has been Fastest Finger 4 times")
- Questions seen, so you know when the bank is getting stale

**One privacy note:** `history.jsonl` contains the full round log, which contains
real message text. It lives on the server *decrypted*. Either accept that (it's a
handful of snippets you already approved), or encrypt each line with the same
session key — cheap, since the key is already in memory when a real game runs. I'd
encrypt it; it costs ten lines and keeps the "nothing readable at rest" property
that made §3 of `PLAN.md` worth doing.

---

## 5. New mechanics

New `kind` values are free — invent hundreds. New `type` values cost: server
`accuracy()` plus both clients. Here are the four worth paying for, ranked by
payoff per hour.

### `percent` — 30 minutes. Do it.

Barely a new type: it's `number` with `min`/`max`/`unit` fields and a slider skin.

```json
{ "type": "percent", "kind": "By the numbers",
  "prompt": "What share of our 48,213 messages did Shray send?",
  "answer": 46, "unit": "%",
  "reveal": "46%. She out-texts you and always has." }
```

Renders as a two-colour tug-of-war bar. Scoring: `1 - |guess - answer| / 30`.

### `wager` — 2 hours. Do it.

The Final Receipt. One per game, always last. Two phases: stake, then answer.
Phase machine gets one new state (`wager`), scoring becomes
`± stake × accuracy_sign`. Makes the endgame live.

### `mutual` — half a day. Do it if week 3 is calm.

**The best idea in this document for a two-player game.** There's no correct
answer — you both answer, and you score if you *match each other*.

```json
{ "type": "mutual", "kind": "Same page",
  "prompt": "Which of these is the most 'us' message?",
  "options": ["…", "…", "…", "…"],
  "reveal": "Both of you said the third one. Of course you did." }
```

It's the Newlywed Game. It's a co-op round inside a competitive game, which for a
meetaversary is thematically exactly right, and it produces the **Same Page**
superlative — the only stat in the game that's about the two of you rather than
one of you beating the other. Score 500 to each on a match.

### `order` — half a day. Skip unless you have time.

Drag 4 messages into chronological order. Score by pairwise-correct fraction.
Genuinely fun, genuinely fiddly to build touch-friendly drag on a phone.

### Deliberately not building

Free-text answers (fuzzy matching live is a rules argument waiting to happen),
rapid-fire timed rounds (fights the existing timer model), audio/voice-note rounds
(no data path).

---

## 6. Sound and motion

Sound is a disproportionate amount of the "fun" and it's an afternoon.

- iMessage **send** on answer commit, **receive** on reveal, on the host screen only
  — two devices playing the same sound at different latencies sounds broken.
- A low tick under the last 5 seconds. Nothing else during the question.
- Silence before the reveal. Then the receive sound. The pause is the joke.
- Podium: one flourish, not a loop.
- Autoplay policy: browsers require a gesture first. The host's START click is that
  gesture — initialise the audio context there.
- A visible mute toggle on the host screen. Non-negotiable if she's on a call with
  you while playing.

**Motion**, all behind `prefers-reduced-motion` as the POC already does: staggered
option entrances, spring on the leaderboard re-sort, points flying to the board,
typing dots everywhere there's a wait, confetti once.

**Haptics** on phones via `navigator.vibrate` — note this does nothing on iOS
Safari, so don't design a state that depends on it.

---

## 7. Accessibility

Carrying forward the known gaps from handover §6, since you're adding screens:

- Player identity is colour-only in several places. Add an initial or a shape to
  every dot. Two-player colour coding fails entirely for a colourblind player, and
  `binary` tiles are the core mechanic.
- The timer bar has no non-visual equivalent — the 5-second tick sound covers this
  if sound is on. Add a numeric countdown at ≤5s regardless.
- The month histogram needs a text alternative on the reveal.
- Everything animated needs a `prefers-reduced-motion` path, including the new
  superlative card deal and the score graph draw-on.

---

## 8. The deck — why priority is a design decision

A generated question is a decent question. A question you wrote is a *moment*.
The dealer knows the difference, and that's a design choice, not just a config
value.

**Provenance is the directory.** `questions/mine.toml` is his;
`questions/auto/*.toml` is generated. Nothing to tag, nothing to mislabel.

**What the dealer does** (`S3.8`, `questions/config.toml [deal]`):

1. Fill 65% of the 14 rounds from `mine.toml` first.
2. Top up from `auto/`, sampling yours at 4× weight for the remaining slots.
3. Cap any one `kind` at 3 per game so no category dominates.
4. Prefer questions unseen in the last 3 games, read from `history.jsonl`. **This
   is what makes five replays feel like five games rather than one game shuffled.**
5. End on a Final Receipt if any wagers are available.

**Dedup is how you delete a generated question without opening `auto/`.** Every
question has a `topic`, defaulting to its `id`. Write one of yours with the same
`topic` and the generated one vanishes. Silently, permanently, no audit required.

The felt result: the game opens with something only he could have written, the
filler is invisible, and the last thing she reads that night is his.

## 9. Effort

| Item | Cost | Verdict |
| --- | --- | --- |
| Round log in `game.py` | 1h | **Week 1.** Everything depends on it. |
| Month density histogram | 2h | **Do.** Highest payoff of anything here. |
| Reveal choreography + context thread | 4h | **Do.** This is the payoff screen. |
| Locked / read-receipt state | 2h | **Do.** Cheap, very on-theme. |
| Superlatives module + cards | 5h | **Do.** What you asked for. |
| History shelf + `history.jsonl` | 4h | **Do.** What you asked for. |
| Score graph (inline SVG) | 2h | **Do.** |
| Receipts reel | 3h | **Do.** The emotional close. |
| Sound design | 3h | **Do.** Disproportionate payoff. |
| `percent` type | 0.5h | **Do.** |
| `wager` / Final Receipt | 2h | **Do.** |
| `mutual` type | 4h | If week 3 is calm. |
| `order` type | 4h | Skip. |

Roughly 30 hours of UI on top of `PLAN.md`. That fits four weeks *only* because the
question bank runs in parallel on separate evenings — see the revised schedule in
`PLAN.md` §5.

If you fall behind, cut in this order: `order`, `mutual`, sound, receipts reel,
score graph. Never cut the round log, the histogram, or the reveal choreography.
