"""Flask application for private, local document comparison."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import pymupdf as fitz
from flask import Flask, Response, abort, render_template, request, send_from_directory, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from highlighters import highlight_docx, highlight_pdf
from matcher import MatchSpan, find_matches
from readers import DocumentReadError, DocumentText, Sentence, read_docx, read_pdf

APP_NAME = "SideBySide"
MAX_FILE_BYTES = 20 * 1024 * 1024
TEMP_ROOT = Path(tempfile.gettempdir()) / "sidebyside_requests"
ALLOWED_MIME = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 42 * 1024 * 1024


def cleanup_expired_requests(now: float | None = None) -> None:
    """Remove per-request workspaces older than one hour."""
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    current_time = time.time() if now is None else now
    for directory in TEMP_ROOT.iterdir():
        try:
            if directory.is_dir() and current_time - directory.stat().st_mtime > 3600:
                shutil.rmtree(directory, ignore_errors=True)
        except OSError:
            continue


@app.before_request
def _cleanup_before_request() -> None:
    """Prune old request workspaces before handling a request."""
    cleanup_expired_requests()


def _is_valid_file(storage: FileStorage, extension: str) -> bool:
    """Validate the browser-provided MIME type and the file's container signature."""
    if storage.mimetype not in ALLOWED_MIME[extension]:
        return False
    storage.stream.seek(0)
    signature = storage.stream.read(8)
    storage.stream.seek(0)
    if extension == ".pdf":
        return signature.startswith(b"%PDF-")
    try:
        return zipfile.is_zipfile(storage.stream)
    finally:
        storage.stream.seek(0)


def _save_upload(storage: FileStorage, destination: Path) -> None:
    """Save one upload and enforce its individual size limit."""
    storage.save(destination)
    if destination.stat().st_size > MAX_FILE_BYTES:
        destination.unlink(missing_ok=True)
        raise ValueError("Each file must be 20 MB or smaller.")


def _sentence_html(document: DocumentText, token_indices: range) -> str:
    """Render source sentences with escaped text and matched source words marked."""
    sentence_ids: list[int] = []
    for index in token_indices:
        sentence_id = document.tokens[index].sentence_id
        if sentence_id not in sentence_ids:
            sentence_ids.append(sentence_id)

    rendered: list[str] = []
    for sentence_id in sentence_ids:
        sentence = document.sentences[sentence_id]
        ranges: list[tuple[int, int]] = []
        for index in token_indices:
            token = document.tokens[index]
            location = token.location
            if token.sentence_id == sentence_id and location.segment_id == sentence.segment_id:
                ranges.append(
                    (
                        max(0, location.char_start - sentence.char_start),
                        min(len(sentence.text), location.char_end - sentence.char_start),
                    )
                )
        ranges.sort()
        cursor = 0
        chunks: list[str] = []
        for start, end in ranges:
            if start < cursor or start >= end:
                continue
            chunks.append(html.escape(sentence.text[cursor:start]))
            chunks.append(f"<mark>{html.escape(sentence.text[start:end])}</mark>")
            cursor = end
        chunks.append(html.escape(sentence.text[cursor:]))
        rendered.append("".join(chunks))
    return " ".join(rendered)


def _page_label(document: DocumentText, start: int, end: int) -> str | None:
    pages = sorted(
        {
            token.location.page_number
            for token in document.tokens[start : end + 1]
            if token.location.page_number is not None
        }
    )
    return ", ".join(str(page) for page in pages) if pages else None


def _result_rows(
    document1: DocumentText, document2: DocumentText, matches: list[MatchSpan]
) -> tuple[list[dict[str, object]], int, int]:
    """Build safe display rows and unique matched-word counts."""
    rows: list[dict[str, object]] = []
    matched1: set[int] = set()
    matched2: set[int] = set()
    for match in matches:
        range1 = range(match.start1, match.end1 + 1)
        range2 = range(match.start2, match.end2 + 1)
        matched1.update(range1)
        matched2.update(range2)
        rows.append(
            {
                "matched_text": match.matched_text,
                "sentence1": _sentence_html(document1, range1),
                "sentence2": _sentence_html(document2, range2),
                "page1": _page_label(document1, match.start1, match.end1),
                "page2": _page_label(document2, match.start2, match.end2),
            }
        )
    return rows, len(matched1), len(matched2)


def _validate_upload(storage: FileStorage, label: str) -> tuple[str, str]:
    """Return a secure filename and extension after upload checks."""
    if not storage or not storage.filename:
        raise ValueError(f"Choose {label} before submitting.")
    safe_name = secure_filename(storage.filename)
    if not safe_name:
        raise ValueError(f"{label} has an invalid filename.")
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_MIME:
        raise ValueError(f"{label} must be a PDF or DOCX file.")
    if not _is_valid_file(storage, extension):
        raise ValueError(f"{label} does not have a valid {extension[1:].upper()} MIME type or file signature.")
    return safe_name, extension


def _read_document(path: Path, extension: str) -> DocumentText:
    """Dispatch to the matching format reader."""
    return read_pdf(path) if extension == ".pdf" else read_docx(path)


def _render_error(message: str, status: int = 400) -> tuple[str, int]:
    """Render a user-facing error on the comparison page."""
    return render_template("index.html", app_name=APP_NAME, error=message), status


@app.get("/")
def index() -> str:
    """Render the initial comparison form."""
    return render_template("index.html", app_name=APP_NAME)


@app.post("/")
def compare() -> str | tuple[str, int] | Response:
    """Validate uploads, compare documents, and render results."""
    raw_size = request.form.get("word_count", "").strip()
    try:
        size = int(raw_size)
    except ValueError:
        return _render_error("Number of consecutive words must be a whole number.")
    if size < 2:
        return _render_error("Number of consecutive words must be at least 2.")

    try:
        safe_names = [_validate_upload(request.files.get(key), label) for key, label in (("file1", "File 1"), ("file2", "File 2"))]
    except ValueError as error:
        return _render_error(str(error))

    request_id = uuid.uuid4().hex
    work_dir = TEMP_ROOT / request_id
    work_dir.mkdir(parents=True, exist_ok=False)
    try:
        upload_paths: list[Path] = []
        for number, ((safe_name, extension), key) in enumerate(zip(safe_names, ("file1", "file2")), start=1):
            upload_path = work_dir / f"source{number}_{safe_name}"
            _save_upload(request.files[key], upload_path)
            upload_paths.append(upload_path)

        documents = [
            _read_document(upload_paths[index], safe_names[index][1]) for index in range(2)
        ]
        matches = find_matches(documents[0].tokens, documents[1].tokens, size)
        output_names: list[dict[str, str]] = []
        for index, (source, (original_name, extension)) in enumerate(zip(upload_paths, safe_names)):
            output_name = f"{Path(original_name).stem}_highlighted{extension}"
            output_path = work_dir / f"result{index + 1}{extension}"
            if extension == ".pdf":
                highlight_pdf(source, output_path, documents[index], matches, index + 1)
            else:
                highlight_docx(output_path, documents[index], matches, index + 1)
            output_names.append({"path": output_path.name, "download_name": output_name})

        (work_dir / "manifest.json").write_text(json.dumps(output_names), encoding="utf-8")
        rows, matched1, matched2 = _result_rows(documents[0], documents[1], matches)
        total1, total2 = len(documents[0].tokens), len(documents[1].tokens)
        result = {
            "matches": rows,
            "total_phrases": len(matches),
            "matched_words1": matched1,
            "matched_words2": matched2,
            "coverage1": round(matched1 * 100 / total1, 1) if total1 else 0,
            "coverage2": round(matched2 * 100 / total2, 1) if total2 else 0,
            "total_words1": total1,
            "total_words2": total2,
            "download1": url_for("download", request_id=request_id, file_number=1),
            "download2": url_for("download", request_id=request_id, file_number=2),
            "output_name1": f"{Path(safe_names[0][0]).stem}_highlighted{safe_names[0][1]}",
            "output_name2": f"{Path(safe_names[1][0]).stem}_highlighted{safe_names[1][1]}",
        }
        return render_template("index.html", app_name=APP_NAME, result=result, submitted_size=size)
    except (ValueError, OSError, fitz.FileDataError, zipfile.BadZipFile) as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        message = str(error) if isinstance(error, (ValueError, DocumentReadError)) else "The files could not be processed. Check that they are valid PDF or DOCX documents."
        return _render_error(message)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        app.logger.exception("Document comparison failed")
        return _render_error("The files could not be processed. Check that they are valid PDF or DOCX documents.")


@app.get("/download/<request_id>/<int:file_number>")
def download(request_id: str, file_number: int) -> Response:
    """Send one highlighted copy using its original-based download name."""
    if not re.fullmatch(r"[0-9a-f]{32}", request_id) or file_number not in (1, 2):
        abort(404)
    work_dir = TEMP_ROOT / request_id
    manifest_path = work_dir / "manifest.json"
    try:
        output_names = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = output_names[file_number - 1]
        filename = entry["path"]
        download_name = entry["download_name"]
    except (OSError, ValueError, IndexError, KeyError, TypeError):
        abort(404)
    if Path(filename).name != filename or not (work_dir / filename).is_file():
        abort(404)
    return send_from_directory(work_dir, filename, as_attachment=True, download_name=download_name)


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error: RequestEntityTooLarge) -> tuple[str, int]:
    """Display a clear message when the combined upload limit is exceeded."""
    return _render_error("The combined upload is too large. Each file must be 20 MB or smaller.", 413)


if __name__ == "__main__":
    debug_enabled = os.getenv("FLASK_DEBUG", "").lower() in {"1", "true"}
    app.run(debug=debug_enabled)
