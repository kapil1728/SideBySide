"""Unit tests for normalized N-gram matching and span merging."""

from readers import TokenLocation, WordToken
from matcher import find_matches, normalize_word


def tokens(text: str) -> list[WordToken]:
    return [
        WordToken(word, normalize_word(word), TokenLocation(0, index, index + len(word)))
        for index, word in enumerate(text.split())
    ]


def test_overlapping_ngrams_merge_into_one_passage() -> None:
    passage = "one two three four five six seven eight nine ten eleven twelve"
    matches = find_matches(tokens(f"start {passage} finish"), tokens(f"other {passage} end"), 5)

    assert len(matches) == 1
    assert matches[0].matched_text == passage
    assert matches[0].end1 - matches[0].start1 + 1 == 12


def test_n_larger_than_shorter_document_has_no_matches() -> None:
    assert find_matches(tokens("one two three"), tokens("one two"), 3) == []


def test_punctuation_and_case_are_ignored_for_comparison() -> None:
    matches = find_matches(tokens("Alpha, BETA! gamma."), tokens("alpha beta GAMMA"), 3)

    assert len(matches) == 1
    assert matches[0].matched_text == "Alpha, BETA! gamma."


def test_repeated_phrases_are_kept_as_distinct_occurrences() -> None:
    matches = find_matches(
        tokens("red green blue then red green blue"),
        tokens("red green blue"),
        3,
    )

    assert len(matches) == 2
    assert [match.start1 for match in matches] == [0, 4]


def test_normalization_strips_punctuation_and_case() -> None:
    assert normalize_word("Can't—STOP!") == "cantstop"
