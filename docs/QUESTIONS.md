# Read Receipts — Question Catalog

**Thirteen archetypes ship. Three are blocked on client input.** Every question
in the bank is one of them; anything that is not one of them is the kind of
question that made the deck feel random, and was cut.

This is the contract, not a menu of ideas. Each archetype below says what the
prompt is allowed to claim, what computes the answer, and what the reveal owes
you. Most of the bugs found in this bank were a prompt claiming something the
resolver did not compute — a question asking "how many times" answered by a
count of *messages*, or naming one phrase and counting twelve.

```
questions/
├── config.toml     names, dealing rules, dedup policy, fairness guards
├── lexicons.toml   the matching layer
├── mine.toml       YOURS. priority. 65% of every game comes from here.
├── auto/           generated. filler. yields to yours.
└── inbox.md        raw idea dump → becomes mine.toml
```

**Provenance is the directory.** Anything in `mine.toml` is yours and wins;
anything in `auto/` is generated and yields. To delete a generated question you
do not like, write your own with the same `topic` — it vanishes silently.

**One game never asks the same thing twice.** `compile.py` derives a `subject`
for every resolver-backed question — the lexicon it counts, or the resolver
plus its argument — and the dealer allows one question per subject per game
(`config.toml [deal] max_per_subject`). This is separate from `kind`, which is
only the eyebrow: "what share goes out after midnight" filed under *Deep cut*,
*The archive* and *Chronically online* is one question in three costumes, and
`max_per_kind` could never see that. A question baked from a real message has
no subject and is never blocked — it is about that message and can only collide
with itself. Set `subject` by hand only to force two questions apart when they
share a fact the resolvers cannot see, or together when they share no resolver.

So **you may still write two questions about one phrase.** The bank keeps six
on `lex.love_you`. You will just never be asked two of them in one night, and
across replays you get a different one each time.

---

## The two fields, again

- **`type`** = mechanics. Seven, and all seven now play: `binary`, `choice`,
  `number`, `month`, `percent`, `mutual`, `wager`. Adding more costs code —
  a scorer in `game.py`, an input on the phone, and the name in `PLAYABLE`.
- **`kind`** = flavour. Free text. Renders as the eyebrow, and `Game.deal()`
  interleaves the deck by it so the same category never lands three rounds running.
  **Invent as many as you want.**

### Kind labels to spread across the bank

Aim for 10+ so interleaving has something to work with:

`Who said it` · `Fill in the blank` · `Deep cut` · `Petty grievances` ·
`By the numbers` · `First time we said it` · `Receipts` · `Chronically online` ·
`Same page` · `Ancient history` · `Character witness` · `The archive` ·
`Damning evidence` · `Soft launch` · `Cold open` · `Final receipt`

---

## Coverage

Two axes, both reported by `python3 tools/status.py --bank`.

**`area`** — what the question is *about*. The bank skewed meta-linguistic early
on (lots of "who says X more"), which is why `auto/life.toml` exists: it's
organised by subject rather than mechanic. Current spread:

`language` · `archive` · `milestones` · `affection` · `habits` · `humor` ·
`conflict` · `travel` · `media` · `long-distance` · `people` · `sleep` · `work` ·
`health` · `logistics` · `food` · `money` · `weather`

Thin areas get flagged in the status output. Thin is fine — it just tells you
where a new question adds most.

**`kind`** — the eyebrow label, and the deck's interleaving key. 26 in use.
`Game.deal()` buckets by `kind` and round-robins, so a bank with only four labels
can't stop a category landing three rounds running. Invent freely; it's free.

## Presentation formats

Same mechanics, six very different-looking rounds. `format` is a rendering hint
read by `shared.js/messageBlock`, and by nothing else; unknown values fall back
to `bubble`, so it can never break a game.

| `format` | Renders as |
| --- | --- |
| `bubble` | one message, centred and large |
| `blank` | one message with a word knocked out |
| `redacted` | one message, several words knocked out |
| `compare` | two bubbles side by side, labelled A and B |
| `thread` | the messages of a real exchange, in order, stacked |
| `timestamp` | the message, then `Delivered` and a clock that keeps running |
| `photo` | a real photograph from the thread, and its caption if it had one |

`blank` and `redacted` draw each `▁▁▁▁▁` run as a filled slot the width of the
missing word — a row of low underscores is invisible across a room.

`photo` is the one format with something outside `text` behind it. A block
names a file — `photo = "IMG_0042.HEIC"` — `compile.py` looks it up in the
corpus and embeds the downscaled copy in the dataset, and the client fetches it
from `/photo/current` rather than being handed 120 KB on every heartbeat. It
needs a corpus extracted after 2026-09-24 and one run of `make photos`; see
PLAN §S3.12. Any `type` can wear it: who sent this, when was it taken, what was
the caption.

`compare` splits `text` on its newline and parses the `A:` / `B:` labels
`curate.py` writes in. `thread` splits on newlines too, and renders the lines
as a column of separate bubbles with **nobody's name on them**. It does not put
them on alternating sides, and that is deliberate: the questions carrying this
format are a mix — Whose Turn is two people taking turns, Escalation is one
person sending three in a row — and `format` alone does not say which. Sides
would be a guess, and on the ones it guessed wrong it would either give the
answer away or destroy it. Telling them apart needs one more bit in the data.

Rotate them deliberately. Three `bubble` rounds in a row is the same failure as
three rounds of the same `kind`.

## Writing rules

1. **The `reveal` is the question.** Everything before it is a delivery mechanism.
   Write it like a punchline: short, specific, and ideally slightly mean.
   - Bad: `"Nilu · March 19, 2021"`
   - Good: `"You. Three weeks in, and you were already complaining about the dog."`
2. **Bubble text under 28 words.** Longer breaks the big-screen layout.
3. **Prompts under 22 words.** They render in the display serif.
4. **Distractors must be plausible in context.** Random words are free points.
   Pull them from real messages of similar length and register.
5. **Never put a `month` answer at index 0 or the last index.** The slider defaults
   to the midpoint and the extremes are guessable from the range alone.
6. **Vary the `kind` even for the same mechanic.** Twenty questions labelled
   "Who said it" makes an un-interleavable deck.
7. **Write the reveal first.** If you can't think of a payoff, the question
   isn't worth a round.
8. **The prompt may not claim more than the resolver computes.** This is the
   rule the bank broke most, and it breaks in exactly two ways:
   - *"How many times" on a `count`.* `count` counts **messages containing at
     least one match**, so "goodnight goodnight" is one. Either say "how many
     messages", or pass `mode = "occurrences"` and keep the wording.
   - *A quoted phrase on a category lexicon.* "Who says “wait” more" is a lie
     when the lexicon also holds *hold on*, *hang on*, *one sec*. Either name
     the category ("who stalls more") or narrow the lexicon. Quoting a phrase
     is fine when every term is a **spelling** of it — `ily` is a spelling of
     *I love you*; `munchkin` is not a spelling of *nu*.
9. **The reveal must not assert a fact it didn't compute.** If the reveal
   states something, that something comes from a template var. `make lint`
   cannot check the ones written in prose, so this one is on you.

---

# The thirteen

Counts are what currently compiles against her thread.

## A. The message is the question  (79 / 169 — aim for half the deck)

These put a real bubble on the big screen. They are the reason the game is
about *them* and not about statistics, and they are the ones worth adding to.

### 1. Who Said It — `binary` · 25 questions
A real message, unattributed. Guess the sender.

- **Prompt may claim:** anything about the message that is visible in it.
- **Answer:** baked at mint time (`curate.py`), never a resolver.
- **Reveal owes:** the sender, the date, and the surrounding thread.
- **Rejects:** any message containing a tell the deck asks about elsewhere
  (`cus`, `yea`, `imma`, 😹). Quoting one and then asking who sent it gives the
  same answer away twice.

### 2. Finish the Sentence — `choice` · 15
A phrase one of them says constantly, cut off before the last word.

- **Answer:** `g_finish_sentence` in `mine.py`.
- **Distractors:** other completions *the same person actually used after the
  same prefix*. Never invented, never from a frequency band.
- **Rejects:** function-word answers. "what ya up ___" has one legal
  completion and tests nothing. Rejects elongation variants as separate
  options — `much` / `muchhhh` are one answer, not three.

### 3. Fill the Blank — `choice` · 6
One content word removed from a real message.

### 4. Redact — `choice` · 3
Three words removed instead of one. Same shape, harder, better on a big screen.

### 5. Reply Roulette — `choice` · 3
Shows the reply; guess what caused it. The only round that runs backwards.

### 6. What Happened Next — `choice` · 1
Shows the message; guess the reply. **Under-built — the first place to add.**

### 7. Date This — `month` · 22
A real message. Slide to the month.

- **Rejects:** answers in the outer 10% of the range — guessable from the
  slider alone.

### 8. Left Hanging — `number` or `binary` · 4
A question that sat unanswered for six hours or more.

- **Answer:** `g_unanswered` in `mine.py`.
- The only archetype where the funny part is the silence, not the message.

---

## B. The archive is the question  (90 / 169)

Computed over all 248,345 messages. Resolver-backed, so the answer is never in
the file — these are the ones safe to read while unspoiled.

### 9. The Tell — `binary` · 8
Same word, two spellings, one each. `yea`/`yeah`, `imma`/`ima`, `bc`/`cus`.

- **The strongest signal in this thread** — margins in the hundreds to one.
- **Prompt may name both spellings.** That is not a mismatch; the lexicon
  measures one side and the comparison is the question.

### 10. Who Does It More — `binary` · 33
A habit, compared. `who_says_more` or `who_more`.

- **Prompt may claim:** the *category*, not a single phrase — unless the
  lexicon contains only spellings of that phrase. "Who says `wait` more" is
  wrong when the lexicon also holds *hold on*, *hang on*, *one sec*. Say "who
  stalls more" or narrow the lexicon.
- **Rejects:** anything closer than 1.25×. A coin flip in costume.

### 11. The Count — `number` · 33 (with #13)
How many messages match a category.

- **Prompt must say "how many messages"**, not "how many times" — `count`
  counts *messages containing at least one match*, so a message saying
  "goodnight goodnight" counts once. Say "how many times" only with
  `mode = "occurrences"`.
- **Rejects:** answers under 20. Proximity scoring on a small number is noise.

### 12. The First — `month` or `binary` · 4
When, or by whom, something was said for the first time.

### 13. The Arc — `number` · 6
Something that *changed* across five years: reply speed, message length,
vocabulary, reciprocation.

- **The only archetype whose reveal is allowed to be sincere.** Every other
  type scores a point; this one tells them something about themselves they
  could not have stated out loud. **Worth more of the deck than it has.**

### 14. The Extremum — `number` (counted in #11)
The single longest, biggest, quietest thing.

- **`hits` must be `None`.** An extremum has one match by definition, and
  reporting `1` makes the `min_hits` guard drop the question silently.

---

## C. The three that were blocked on client input

All three ship now. `PLAYABLE` in `app/game.py` holds every type, and the
phone has an input for each.

| | | |
| --- | --- | --- |
| **Mutual** | `mutual` · 6 | No correct answer — you score 500 each by picking the *same* option. Both screens say so, because otherwise it reads as a trivia question you happened to both get wrong. The only round that is about the two of them rather than the archive. |
| **Percent** | `percent` · 20 | A 0–100 slider, the same shape as the month one without the histogram. Scored on a flat 30-point band, and the phone's verdict reads off the same 30 so it can't call a near miss "wildly over" while paying out 500. |
| **Wager / Final Receipt** | `wager` · 2 | Round 15 of 14, always last. Stake first, then answer: win the stake or lose it, no speed bonus, and a loss cannot take you below zero. See PLAN §S3.7. |

Two more wagers would be worth writing. There are only two, so the closer is
the same question on the second night.

---

## Cut, and why

Not archetypes. If a question is one of these, it does not belong in the bank.

- **Topic counts** — "how many messages about food / pets / weather". An
  arbitrary number with no payoff, and ten of them in a row is what made the
  deck feel random. Eleven were removed.
- **Anything with a margin under 1.25×** — a binary whose answer is 53/47 is
  a coin flip wearing a question's clothes.
- **Duplicate prompts** — four messages all asking "Who sent this?" reads as a
  template. Every message question gets a prompt about *that* message.
- **Any question whose reveal asserts a fact not drawn from a template var.**
  "Sunday scaries are real" shipped on a thread whose busiest day was
  Wednesday.

## Mutual, when it lands

The three written already — funnier / more dramatic / worse texter — plus these
if the mechanic ships:

- **Favourite era.** "Which year was our best year?" Matching is the point.
- **Predict her guess.** "Nilu, how many times do you think Shray has said
  sorry?" and "Shray, what number will Nilu guess?" Deranged, and very funny.

---

# Bank composition

**169 shipping, 89 his.** Against a 60-question floor and 14-round games, the
bank is not the constraint any more — balance is.

| | now | wanted |
| --- | --- | --- |
| Shows a real message | 46% | **~50%** |
| The Arc | 6 | **more** — best reveals in the deck |
| What Happened Next | 1 | **more** — under-built |
| Who Does It More | 33 | fine, do not add |
| The Count | 33 | fine, do not add |

Two shapes are over-represented and two are under-built. That is the whole
brief for the rebuild: **no new counts, no new who-says-more.** Add message
rounds and arc questions, and re-home anything that violates a contract above.

**Read the reveals in one sitting at the end.** Ninety payoff lines back to back
is the only way to catch the ones that are captions instead of punchlines, and
it is the difference between a game and a gift.
