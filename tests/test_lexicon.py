"""The matching layer. If this is wrong, every count in the game is wrong."""
import pytest

from tools.lexicon import Lexicon, PhraseLex, expand, normalise


def test_normalise_unifies_the_things_that_should_be_the_same():
    assert normalise("I'm") == normalise("im") == "im"
    assert normalise("I’m") == "im"           # curly apostrophe
    assert normalise("❤️") == normalise("❤")   # variation selector
    assert normalise("👍🏽") == normalise("👍")  # skin tone
    assert normalise("SO...  tired!!") == "so tired"


def test_expansion_tolerates_repeats_and_missing_spaces():
    lex = PhraseLex("i love you")
    for t in ("i love you", "iloveyou", "I LOVE YOU", "i  love   you",
              "i loveeee youuuu", "well i love you ok"):
        assert lex.matches(normalise(t)), t


def test_word_boundaries_still_hold():
    lex = PhraseLex("i love you")
    for t in ("i love your hair", "i love yourself"):
        assert not lex.matches(normalise(t)), t


def test_exclusions_remove_the_span_not_the_count():
    """Subtracting exclude-matches afterwards would be wrong: 'i love your hair'
    contains no 'i love you' hit to subtract from."""
    lex = Lexicon("l", {"any": ["i love you"], "exclude": ["i love your"]})
    assert not lex.matches(normalise("i love your hair"))
    assert lex.matches(normalise("i love you so much"))


def test_longest_variant_wins_so_counts_do_not_double():
    lex = Lexicon("l", {"any": ["love you", "i love you"]})
    assert lex.hits(normalise("i love you")) == 1


def test_at_start_only_matches_a_greeting():
    lex = Lexicon("gm", {"any": ["morning"], "at_start": True})
    assert lex.matches(normalise("morning babe"))
    assert not lex.matches(normalise("call me this morning"))


def test_emoji_matching_is_modifier_agnostic():
    lex = Lexicon("h", {"emoji": ["❤️"]})
    assert lex.matches(normalise("love it ❤"))
    assert lex.matches(normalise("love it ❤️"))


def test_a_draft_lexicon_is_flagged_not_silently_empty():
    assert Lexicon("x", {"any": ["TODO"]}).draft is True
    assert Lexicon("x", {"any": ["real phrase"]}).draft is False


def test_counting_counts_messages_by_default():
    lex = PhraseLex("sorry")
    assert lex.hits(normalise("sorry sorry sorry")) == 3   # occurrences
    assert lex.matches(normalise("sorry sorry sorry"))     # message-level
