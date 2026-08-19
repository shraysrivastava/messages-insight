# Read Receipts — Question Catalog

45 archetypes to author against. Each one gives you a template, a real example,
and the mining note that tells `mine.py` how to find candidates for it.

**→ The questions themselves live in [`questions/`](../questions/)** — 156 of them.
This document is the reasoning behind them.

```
questions/
├── config.toml     names, dealing rules, dedup policy, fairness guards
├── lexicons.toml   45 robust phrase sets — the matching layer
├── mine.toml       YOURS. priority. 65% of every game comes from here.
├── auto/           generated. filler. yields to yours.
│   ├── who.toml         34   who-says-more
│   ├── numbers.toml     27   counts
│   ├── percentages.toml  8   shares
│   ├── firsts.toml      18   first time we said it
│   ├── life.toml        31   topic coverage: work, travel, illness, money…
│   ├── messages.toml    25   curate.py targets, all six formats
│   └── finale.toml       8   wagers and Same Page rounds
└── inbox.md        raw idea dump → becomes mine.toml
```

**Provenance is the directory.** Anything in `mine.toml` is yours and wins;
anything in `auto/` is generated and yields. No field to remember. To delete a
generated question you don't like, write your own with the same `topic` — it
vanishes silently and you never open `auto/`. Full mechanism in `PLAN.md` §5.

**How to use this:** these are patterns, not a finished bank. Pick the archetypes
that fit your thread, let `mine.py` surface candidates for the mechanical ones, and
hand-write the ones marked ✍️ — those are the ones only you can write, and they'll
be the best questions in the game.

---

## The two fields, again

- **`type`** = mechanics. Six values once `percent` and `wager` land: `binary`,
  `choice`, `number`, `month`, `percent`, `wager` (plus `mutual` if built). Adding
  more costs code.
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

Same four mechanics, six very different-looking rounds. `format` is a rendering
hint; unknown values fall back to `bubble`, so it can never break a game.

| `format` | Renders as |
| --- | --- |
| `bubble` | one message, centred and large |
| `blank` | one message with a word knocked out |
| `redacted` | one message, several words knocked out |
| `compare` | two bubbles stacked, A above B |
| `thread` | three messages; the question is about the middle |
| `timestamp` | no message at all — just `3:41 AM · a Tuesday in 2023` |

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
7. **Write the reveal first for the ✍️ ones.** If you can't think of a payoff, the
   question isn't worth a round.

---

# `binary` — two options, all-or-nothing

### 1. Who said it
The workhorse. `kind: "Who said it"`
```json
{ "type": "binary", "kind": "Who said it",
  "prompt": "Who sent this?",
  "text": "the dog next door barked all night i got maybe four hours of sleep",
  "options": ["Shray", "Nilu"], "answer": 1,
  "reveal": "Nilu. March 19, 2021 — nineteen days in and already at war with a dog." }
```
*Mine:* any message 6–28 words with no proper nouns that give the sender away.
Rank by "voice ambiguity" — messages whose vocabulary appears in both senders' history.

### 2. Voice swap ✍️
A message that sounds exactly like the *other* person. Same shape as #1, but you
pick it by hand because the joke is that it's misattributable.
> *reveal:* `"You. Everyone gets this one wrong. You have one (1) sentence that sounds like her."`

### 3. Who texted first
`kind: "Cold open"`
```json
{ "type": "binary", "kind": "Cold open",
  "prompt": "On the morning of your first anniversary — who texted first?",
  "options": ["Shray", "Nilu"], "answer": 0,
  "reveal": "You, at 6:04am. She replied at 11:40." }
```
*Mine:* first message of each day; pick days with meaning (anniversaries, birthdays,
the day after a fight).

### 4. Who apologised
`kind: "Damning evidence"` — show the exchange, ask who said sorry.
*Mine:* messages containing sorry/my bad/i was wrong, with the ±3 context.

### 5. Which came first
Two bubbles, A and B, in date order or not.
```json
{ "type": "binary", "kind": "Ancient history",
  "prompt": "Which of these came first?",
  "text": "A: “i think i might be in love with you”\nB: “can you bring me a coffee”",
  "options": ["A", "B"], "answer": 1,
  "reveal": "The coffee. By four months. Romance is a marathon." }
```
*Mine:* pair a sentimental message with a mundane one from the opposite era.

### 6. Autocorrect victim
`kind: "Chronically online"` — who sent this typo.
*Mine:* messages with a real word that's an edit-distance-1 neighbour of a common word,
or the classic `ducking`.

### 7. Who says it more
No bubble. Pure trivia.
```json
{ "type": "binary", "kind": "By the numbers",
  "prompt": "Who has said “lol” more?",
  "options": ["Shray", "Nilu"], "answer": 0,
  "reveal": "You. 1,204 to her 380. She types “haha” like an adult." }
```
*Mine:* any token with a ≥2× ratio between senders. Generates dozens for free.

### 8. Double text
> "Who double-texts more?" *Mine:* consecutive messages from the same sender with
no reply between, gap > 5 min.

### 9. Left on read
> "Who has left the other on read for longer?" *Mine:* max reply gap by sender.

### 10. Emoji ownership
> "Whose 🥺 is this?" *Mine:* per-sender emoji frequency with a strong skew.

### 11. Real or fabricated ✍️
Two messages, one real, one you wrote. Cruel and excellent.
> *reveal:* `"The real one is B. You genuinely sent that."`

---

# `choice` — 2–4 options, all-or-nothing

### 12. Fill in the blank
The single best mechanic in the game. `kind: "Fill in the blank"`
```json
{ "type": "choice", "kind": "Fill in the blank",
  "prompt": "Nilu sent this. What's the missing word?",
  "text": "come over later i am making that ▁▁▁▁▁ you liked with the lemon",
  "options": ["pasta", "chicken", "risotto", "salmon"], "answer": 0,
  "reveal": "“…that pasta you liked with the lemon.” May 2023. You asked for it every week after." }
```
*Mine:* blank a mid-frequency content word (not a stopword, not a hapax).
Distractors from the same part of speech and similar length, drawn from the corpus.

### 13. Fill in the blank — emoji
Same, blanking an emoji. Auto-renders as big emoji tiles.

### 14. What happened next
```json
{ "type": "choice", "kind": "Deep cut",
  "prompt": "You sent this. What did she reply?",
  "text": "i think i left my keys at your place can you check",
  "options": ["“they're in the fridge”", "“no”", "“come get them”", "“i'm at work”"],
  "answer": 0,
  "reveal": "“they're in the fridge.” Still unexplained." }
```
*Mine:* messages whose reply is short and surprising. Distractors from other replies
by the same sender.

### 15. Reply roulette
Inverted #14: show the *reply*, guess which message prompted it.

### 16. Top emoji
> "Which emoji have we used most?" — renders as four big emoji tiles.

### 17. Most-used word
> "Which of these do we say most?" *Mine:* four content words from adjacent frequency bands.

### 18. What was I complaining about ✍️
Four options, one real. Pull from a genuinely unhinged rant.

### 19. Guess the year
Cheaper cousin of `month` — four years as tiles. Good for very old messages where a
month slider is unfairly precise.

### 20. Odd one out
Three real messages, one fabricated. `prompt: "Which of these did we never send?"`

### 21. Where were we
> "This message was sent from where?" Four places. *Mine:* messages mentioning
travel, plus your own memory for the answer. Mostly ✍️.

### 22. Nickname origin ✍️
> "Which of these came first?" — four nicknames, chronological.
*Mine:* first appearance date of each term of endearment. Assembles itself.

### 23. Busiest day of the week
> "Which day do we text most?" Seven becomes four options — include Sunday, it's usually the answer.

### 24. The longest word
> "What's the longest word either of us has ever texted?" Four options, three plausible.

### 25. Whose phone died ✍️
Any recurring domestic disaster, four candidates.

---

# `number` — proximity-scored

Always give an **anchor** in the prompt (see DESIGN.md §2.3) — a blind number guess
isn't a decision, it's a coin flip with extra steps.

### 26. Total messages
```json
{ "type": "number", "kind": "By the numbers",
  "prompt": "How many messages have we sent each other in five years?",
  "answer": 48213,
  "reveal": "48,213. About 26 a day, every day, since the day we met." }
```

### 27. Times we said "I love you"
```json
{ "type": "number", "kind": "Receipts",
  "prompt": "How many times have we said “I love you”?",
  "answer": 1877,
  "reveal": "1,877. You said it first 1,102 of those times. Noted." }
```

### 28. Longest silence
> "What's the longest we've gone without texting? (in hours)"
*Reveal is the good part:* what was happening that week.

### 29. Busiest single day
> "Most messages in one day?" *Reveal:* the date, and why.

### 30. Sorry count
> "How many times has Shray said 'sorry'?" *Mine:* per-sender token count. Ask about
whichever of you it's funnier for.

### 31. Photos sent
### 32. Longest message, in words
### 33. Times we said "goodnight"
### 34. Longest daily streak
> "Most consecutive days in a row we both texted?" — a genuinely sweet number.
### 35. Distinct emoji used
### 36. Times we said each other's names
### 37. Average messages per day
### 38. 3am club
> "How many messages have we sent between 2am and 5am?"
### 39. Question marks
> "How many questions has Nilu asked you?" *Mine:* count `?`-terminated messages.
### 40. The "haha" index
> "How many times has one of us typed 'haha' or some variant?" *Mine:* regex `ha(ha)+`.

---

# `month` — slider over `meta.months`, proximity-scored

With the density histogram behind it (DESIGN.md §2.3), these become the best-looking
rounds in the game.

### 41. First "I love you"
```json
{ "type": "month", "kind": "First time we said it",
  "prompt": "When did one of us first say “I love you”?",
  "text": "ok i'm going to say it and you can do whatever you want with it. i love you",
  "answer": 7,
  "reveal": "October 2021. You sent it at 1:14am and then went offline for nine minutes." }
```

### 42. First time we said [anything] ✍️
The most generative archetype here. Nominate any phrase — a nickname, an inside joke,
a city, "move in", "your mom", the name of your cat — and `mine.py` finds its first
appearance and the message it appeared in. **One nominated word = one finished
question.** Write a list of 20 words and you have 20 questions.

### 43. Date this message
> "When was this sent?" Any message with era-specific content.

### 44. Our busiest month
> "Which month did we text the most?" *Reveal:* what was going on.

### 45. Our quietest month
Same, inverted. Often the more interesting reveal.

---

# `percent` — tug-of-war slider *(stage 3, `S3.6`)*

```json
{ "type": "percent", "kind": "By the numbers",
  "prompt": "What share of our 48,213 messages did Shray send?",
  "answer": 46, "unit": "%",
  "reveal": "46%. She has out-texted you every single year." }
```

Good ones: share of messages by sender · share sent after midnight · share that are
one word · share containing an emoji · share of your messages she replied to within
a minute · share of days in five years with at least one message *(this one is the
sweetest number in the game — get it in)*.

---

# `mutual` — no correct answer, you score by matching *(stage 4, `S4.6`)*

### The most "us" message
Four candidate messages, both pick one, match to score.

### Favourite era
> "Which year was our best year?" — slider or four options. Matching is the point.

### Predict her guess
> "Nilu — how many times do you think Shray has said 'sorry'?" and
> "Shray — what number will Nilu guess?" Deranged and very funny.

---

# `wager` — the Final Receipt *(stage 3, `S3.7`)*

Always round 14, exactly one per game. Stake, then answer. Make it a question
that's *guessable but not certain* — a `binary` or a `choice`, never a `number`.

```json
{ "type": "wager", "kind": "Final receipt",
  "prompt": "Final Receipt. Who sent the very first message between us?",
  "text": "hey — this is Shray from saturday. hope this is the right number",
  "options": ["Shray", "Nilu"], "answer": 0,
  "reveal": "You. March 1, 2021, 4:47pm. She replied in under a minute. Five years ago tonight." }
```

Write 4–5 of these so replays don't end the same way. Save your single best reveal
for one of them — it's the last thing either of you reads.

---

# Bank composition

For 14-round games with 5 distinct playthroughs:

| Type | Count | Notes |
| --- | --- | --- |
| `binary` | 24 | Archetypes 1–11. #7 alone generates a dozen. |
| `choice` | 20 | Fill-in-the-blank should be half of these. |
| `month` | 20 | #42 generates these in bulk from a word list. |
| `number` | 16 | Every one needs an anchor. |
| `percent` | 6 | |
| `mutual` | 5 | If built. |
| `wager` | 5 | One per game, drawn last. |
| **Total** | **~90** | 60 is the hard floor. |

Current state: **156 authored, 98 shippable.** The gap is 26 slots waiting on
`curate.py` to drop a real message in, and 11 drafts waiting on you. Check with
`python3 tools/status.py --bank`.

**Fastest path to a full bank:** archetypes #7, #42, and the `number` family are
close to automatic — a word list and a few queries produce 40+ questions. That
leaves ~40 to curate and ~10 to hand-write, which is one evening plus three.

**Author the reveals in one sitting at the end.** Reading 90 payoff lines back to
back is the only way to catch the ones that are captions instead of punchlines, and
it's the difference between a game and a gift.
