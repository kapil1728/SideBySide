"""Document text extraction with source locations for precise highlighting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pymupdf as fitz
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from matcher import normalize_word


@dataclass(frozen=True)
class RunFragment:
    """A character range within one Word run."""

    run: Run
    start: int
    end: int


@dataclass(frozen=True)
class TokenLocation:
    """The position of an extracted word in its source document."""

    segment_id: int
    char_start: int
    char_end: int
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    run_fragments: tuple[RunFragment, ...] = ()


@dataclass
class WordToken:
    """A source word and its normalized comparison form."""

    original: str
    normalized: str
    location: TokenLocation
    sentence_id: int = 0


@dataclass(frozen=True)
class Sentence:
    """A sentence-sized display range inside an extracted text segment."""

    text: str
    segment_id: int
    char_start: int
    char_end: int


@dataclass
class DocumentText:
    """Extracted document content and source document state."""

    tokens: list[WordToken] = field(default_factory=list)
    sentences: list[Sentence] = field(default_factory=list)
    kind: str = ""
    source_document: Any = None


class DocumentReadError(ValueError):
    """Raised when a supported document has no readable text."""


def _sentence_ranges(text: str) -> list[tuple[int, int]]:
    """Split a segment at sentence punctuation while retaining punctuation."""
    ranges: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"[.!?]+(?:[\"')\]]*)\s*", text):
        end = match.end()
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            ranges.append((start, end))
        start = match.end()
    while start < len(text) and text[start].isspace():
        start += 1
    end = len(text.rstrip())
    if end > start:
        ranges.append((start, end))
    return ranges or ([(0, len(text))] if text else [])


def _append_segment(
    result: DocumentText,
    text: str,
    segment_id: int,
    page_number: int | None = None,
    pdf_positions: list[tuple[float, float, float, float]] | None = None,
    runs: list[tuple[Run, int, int]] | None = None,
) -> None:
    """Append words and sentence ranges from one PDF page or Word paragraph."""
    sentence_ids: list[tuple[int, int, int]] = []
    for start, end in _sentence_ranges(text):
        sentence_id = len(result.sentences)
        result.sentences.append(Sentence(text[start:end], segment_id, start, end))
        sentence_ids.append((start, end, sentence_id))

    for word_index, match in enumerate(re.finditer(r"\S+", text)):
        original = match.group()
        normalized = normalize_word(original)
        if not normalized:
            continue
        fragments: list[RunFragment] = []
        if runs:
            for run, run_start, run_end in runs:
                overlap_start = max(match.start(), run_start)
                overlap_end = min(match.end(), run_end)
                if overlap_start < overlap_end:
                    fragments.append(
                        RunFragment(run, overlap_start - run_start, overlap_end - run_start)
                    )
        sentence_id = next(
            (identifier for start, end, identifier in sentence_ids if start <= match.start() < end),
            sentence_ids[-1][2] if sentence_ids else 0,
        )
        bbox = pdf_positions[word_index] if pdf_positions and word_index < len(pdf_positions) else None
        result.tokens.append(
            WordToken(
                original=original,
                normalized=normalized,
                location=TokenLocation(
                    segment_id=segment_id,
                    char_start=match.start(),
                    char_end=match.end(),
                    page_number=page_number,
                    bbox=bbox,
                    run_fragments=tuple(fragments),
                ),
                sentence_id=sentence_id,
            )
        )


def read_pdf(path: str | Path) -> DocumentText:
    """Read PDF pages in text order and retain each word's bounding box."""
    result = DocumentText(kind="pdf")
    try:
        with fitz.open(str(path)) as pdf:
            for page_index, page in enumerate(pdf):
                words = [word for word in page.get_text("words", sort=True) if word[4].strip()]
                text = " ".join(word[4] for word in words)
                boxes = [(word[0], word[1], word[2], word[3]) for word in words]
                _append_segment(result, text, page_index, page_index + 1, boxes)
    except (fitz.FileDataError, RuntimeError) as error:
        raise DocumentReadError("File is not a readable PDF document.") from error
    if not result.tokens:
        raise DocumentReadError(
            "File 1 or File 2 is an empty or scanned PDF with no extractable text."
        )
    return result


def _paragraphs(root: Any, parent: Any) -> Iterator[Paragraph]:
    """Yield paragraphs from a document body, including nested table cells."""
    for element in root.iter(qn("w:p")):
        yield Paragraph(element, parent)


def _paragraph_runs(paragraph: Paragraph) -> list[Run]:
    """Wrap all runs in XML order, including runs inside hyperlinks."""
    return [Run(element, paragraph) for element in paragraph._p.iter(qn("w:r"))]


def read_docx(path: str | Path) -> DocumentText:
    """Read body, table, header, and footer paragraphs from a DOCX file."""
    try:
        document = Document(str(path))
    except Exception as error:
        raise DocumentReadError("File is not a readable DOCX document.") from error

    result = DocumentText(kind="docx", source_document=document)
    segment_id = 0
    roots: list[tuple[Any, Any]] = [(document.element.body, document)]
    seen_roots = {id(document.element.body)}
    for section in document.sections:
        for story in (section.header, section.footer):
            root = story._element
            if id(root) not in seen_roots:
                roots.append((root, story))
                seen_roots.add(id(root))

    for root, parent in roots:
        for paragraph in _paragraphs(root, parent):
            paragraph_runs = _paragraph_runs(paragraph)
            run_ranges: list[tuple[Run, int, int]] = []
            pieces: list[str] = []
            offset = 0
            for run in paragraph_runs:
                value = run.text
                pieces.append(value)
                run_ranges.append((run, offset, offset + len(value)))
                offset += len(value)
            text = "".join(pieces)
            if text.strip():
                _append_segment(result, text, segment_id, runs=run_ranges)
                segment_id += 1

    if not result.tokens:
        raise DocumentReadError("The DOCX document contains no extractable text.")
    return result
