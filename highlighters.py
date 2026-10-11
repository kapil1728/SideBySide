"""Write highlighted copies without changing uploaded source files."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import pymupdf as fitz
from docx.enum.text import WD_COLOR_INDEX
from docx.text.run import Run

from matcher import MatchSpan
from readers import DocumentText


def highlight_pdf(
    source_path: str | Path,
    output_path: str | Path,
    document: DocumentText,
    matches: list[MatchSpan],
    token_side: int,
) -> None:
    """Add yellow highlight annotations over matched PDF word rectangles."""
    token_ranges = [
        (match.start1, match.end1) if token_side == 1 else (match.start2, match.end2)
        for match in matches
    ]
    locations = {
        (token.location.page_number, token.location.bbox)
        for start, end in token_ranges
        for token in document.tokens[start : end + 1]
        if token.location.page_number is not None and token.location.bbox is not None
    }
    with fitz.open(str(source_path)) as pdf:
        for page_number, bbox in locations:
            page = pdf[page_number - 1]
            page.add_highlight_annot(fitz.Rect(bbox))
        pdf.save(str(output_path), garbage=4, deflate=True)


def highlight_docx(
    output_path: str | Path, document: DocumentText, matches: list[MatchSpan], token_side: int
) -> None:
    """Split only affected Word runs and highlight matched text fragments."""
    run_ranges: dict[int, tuple[Run, list[tuple[int, int]]]] = {}
    for match in matches:
        start, end = (match.start1, match.end1) if token_side == 1 else (match.start2, match.end2)
        for token in document.tokens[start : end + 1]:
            for fragment in token.location.run_fragments:
                key = id(fragment.run._r)
                if key not in run_ranges:
                    run_ranges[key] = (fragment.run, [])
                run_ranges[key][1].append((fragment.start, fragment.end))

    for run, ranges in run_ranges.values():
        element = run._r
        parent = element.getparent()
        insertion_index = parent.index(element)
        text = run.text
        normalized_ranges: list[tuple[int, int]] = []
        for start, end in sorted(ranges):
            start, end = max(0, start), min(len(text), end)
            if start >= end:
                continue
            if normalized_ranges and start <= normalized_ranges[-1][1]:
                normalized_ranges[-1] = (
                    normalized_ranges[-1][0], max(normalized_ranges[-1][1], end)
                )
            else:
                normalized_ranges.append((start, end))

        pieces: list[tuple[str, bool]] = []
        cursor = 0
        for start, end in normalized_ranges:
            if cursor < start:
                pieces.append((text[cursor:start], False))
            pieces.append((text[start:end], True))
            cursor = end
        if cursor < len(text):
            pieces.append((text[cursor:], False))
        if not pieces:
            continue

        for offset, (value, is_match) in enumerate(pieces):
            cloned_element = deepcopy(element)
            cloned_run = Run(cloned_element, run._parent)
            cloned_run.text = value
            if is_match:
                cloned_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            parent.insert(insertion_index + offset, cloned_element)
        parent.remove(element)

    if document.source_document is None:
        raise ValueError("DOCX source document is unavailable for highlighting.")
    document.source_document.save(str(output_path))
