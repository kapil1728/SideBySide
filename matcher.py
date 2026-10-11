"""Efficient normalized N-gram matching for two token streams."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol, Sequence


class MatchToken(Protocol):
    """The token fields required by the matching algorithm."""

    original: str
    normalized: str


@dataclass(frozen=True)
class MatchSpan:
    """A shared passage and its inclusive token bounds in both documents."""

    start1: int
    end1: int
    start2: int
    end2: int
    matched_text: str


def normalize_word(word: str) -> str:
    """Lowercase a word and remove punctuation and underscores for comparison."""
    return "".join(character for character in word.casefold() if character.isalnum())


def _ngrams(tokens: Sequence[MatchToken], size: int) -> dict[tuple[str, ...], list[int]]:
    """Index each distinct N-gram to its start positions."""
    positions: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for start in range(len(tokens) - size + 1):
        gram = tuple(token.normalized for token in tokens[start : start + size])
        if all(gram):
            positions[gram].append(start)
    return positions


def _merge_shared_ngrams(
    tokens: Sequence[MatchToken], other_ngrams: set[tuple[str, ...]], size: int
) -> list[tuple[int, int]]:
    """Merge overlapping or directly adjacent shared N-gram windows."""
    spans: list[tuple[int, int]] = []
    for start in range(len(tokens) - size + 1):
        gram = tuple(token.normalized for token in tokens[start : start + size])
        if gram not in other_ngrams:
            continue
        end = start + size - 1
        if spans and start <= spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    return spans


def find_matches(
    tokens1: Sequence[MatchToken], tokens2: Sequence[MatchToken], size: int
) -> list[MatchSpan]:
    """Find shared N-gram passages and merge neighboring windows into phrases.

    The index is linear in document length for a fixed N. Repeated passages are
    represented as separate occurrences without expanding every cross-product.
    """
    if size < 2 or len(tokens1) < size or len(tokens2) < size:
        return []

    index2 = _ngrams(tokens2, size)
    index1 = _ngrams(tokens1, size)
    spans1 = _merge_shared_ngrams(tokens1, set(index2), size)
    spans2 = _merge_shared_ngrams(tokens2, set(index1), size)

    occurrences1: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    occurrences2: dict[tuple[str, ...], list[tuple[int, int]]] = defaultdict(list)
    for start, end in spans1:
        phrase = tuple(token.normalized for token in tokens1[start : end + 1])
        occurrences1[phrase].append((start, end))
    for start, end in spans2:
        phrase = tuple(token.normalized for token in tokens2[start : end + 1])
        occurrences2[phrase].append((start, end))

    matches: list[MatchSpan] = []
    for phrase, left_spans in occurrences1.items():
        right_spans = occurrences2.get(phrase)
        if not right_spans:
            continue
        left_spans.sort()
        right_spans.sort()
        # Pair occurrences in document order and retain every occurrence on either side.
        for occurrence in range(max(len(left_spans), len(right_spans))):
            start1, end1 = left_spans[occurrence % len(left_spans)]
            start2, end2 = right_spans[occurrence % len(right_spans)]
            original = " ".join(token.original for token in tokens1[start1 : end1 + 1])
            matches.append(MatchSpan(start1, end1, start2, end2, original))

    return sorted(matches, key=lambda match: (match.start1, match.start2))
