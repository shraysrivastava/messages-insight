"""
lexicon.py — the matching layer.

Naive substring matching undercounts everything: "i love you" misses ily, i love
u, iloveyou, and "i loveeee youuu". Three mechanisms fix that, in order.

1. NORMALISE  every message and every phrase through the same function, so the
   comparison is apples to apples.
2. EXPAND     each literal phrase into a repeat- and space-tolerant regex, so
   you write "i love you" and get \\bi+\\s*l+o+v+e+\\s*y+o+u+\\b for free.
3. LEXICONS   a named set of phrases, emoji and raw regex for the things
   expansion can't reach — real synonyms and abbreviations.

Counting counts MESSAGES containing at least one match, so overlapping variants
("love you" inside "i love you") never double-count.
"""

from __future__ import annotations

import re
import unicodedata

# Skin tone modifiers and the emoji variation selector. Stripping these means
# ❤️ and ❤ are the same heart, and 👍🏽 and 👍 are the same thumb.
_SKIN = re.compile("[\U0001f3fb-\U0001f3ff]")
_VS16 = "️"
_APOS = re.compile("['‘’ʼ]")
_KEEP = re.compile(r"[^0-9a-z\s\U00000080-\U0010ffff]")
_WS = re.compile(r"\s+")

EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff❤♥]"
)


def normalise(text: str) -> str:
    """One text pipeline, used for messages and for phrases alike.

    NFKC, lowercase, apostrophes dropped so "I'm" and "im" unify, emoji stripped
    of variation selectors and skin tones, punctuation to spaces.
    """
    t = unicodedata.normalize("NFKC", text).lower()
    t = _APOS.sub("", t)
    t = t.replace(_VS16, "")
    t = _SKIN.sub("", t)
    t = _KEEP.sub(" ", t)
    return _WS.sub(" ", t).strip()


def expand(phrase: str) -> str:
    """Literal phrase -> tolerant regex.

    Every letter may repeat, every space is optional. "i love you" then matches
    "iloveyou" and "i loveeee youuu" — but the boundary guards still refuse
    "i love your hair", because `you` there is followed by a word character.
    """
    out = []
    for ch in normalise(phrase):
        if ch == " ":
            out.append(r"\s*")
        elif ch.isalpha() and ch.isascii():
            out.append(re.escape(ch) + "+")
        else:
            out.append(re.escape(ch))
    return "".join(out)


# \b doesn't work next to emoji, so use explicit lookarounds instead.
LEFT, RIGHT = r"(?<![0-9a-z])", r"(?![0-9a-z])"


def _alternation(phrases, emoji, raws, at_start=False):
    parts = []
    # Longest first: regex alternation is leftmost-*first*, not longest, so
    # without this "love you" would shadow "i love you" and skew the counts.
    for p in sorted(phrases, key=len, reverse=True):
        if p.strip():
            parts.append(expand(p))
    for e in emoji:
        n = normalise(e)
        if n:
            parts.append(re.escape(n))
    if not parts and not raws:
        return None
    pieces = []
    if parts:
        pieces.append(f"{LEFT}(?:{'|'.join(parts)}){RIGHT}")
    pieces.extend(raws)
    body = "|".join(f"(?:{p})" for p in pieces)
    anchor = r"^\s*" if at_start else ""
    return re.compile(anchor + f"(?:{body})")


class Lexicon:
    """One way of saying one thing, in all its forms."""

    def __init__(self, name: str, spec: dict):
        self.name = name
        self.label = spec.get("label", name.replace("_", " "))
        self.at_start = bool(spec.get("at_start", False))
        self.draft = spec.get("status") == "draft" or "TODO" in str(
            spec.get("any", [])
        )
        self.include = _alternation(
            spec.get("any", []), spec.get("emoji", []), spec.get("regex", []),
            self.at_start,
        )
        self.exclude = _alternation(spec.get("exclude", []), [], [], False)

    def _scrub(self, norm: str) -> str:
        """Delete exclusions before matching.

        Subtracting counts afterwards would be wrong — "i love your hair"
        contains no "i love you" match to subtract. Removing the excluded span
        first is the only version that gets this right.
        """
        return self.exclude.sub(" ", norm) if self.exclude else norm

    def hits(self, norm: str) -> int:
        """Number of non-overlapping matches in one normalised message."""
        if not self.include:
            return 0
        return len(self.include.findall(self._scrub(norm)))

    def matches(self, norm: str) -> bool:
        if not self.include:
            return False
        return self.include.search(self._scrub(norm)) is not None


class PhraseLex(Lexicon):
    """A one-off literal phrase, still normalised and expanded."""

    def __init__(self, phrase: str):
        super().__init__(phrase, {"any": [phrase]})


class RegexLex(Lexicon):
    def __init__(self, pattern: str):
        super().__init__(pattern, {"regex": [pattern]})


def load_lexicons(spec: dict) -> dict[str, Lexicon]:
    return {name: Lexicon(name, body) for name, body in spec.items()}
