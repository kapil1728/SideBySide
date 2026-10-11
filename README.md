# SideBySide

SideBySide is a local web app for finding shared passages in two PDF or DOCX documents. Choose how many consecutive words must match, review the matching passages and sentence context, then download highlighted copies of both files.

## Features

- Configurable consecutive-word matching, with case and punctuation normalization
- Overlapping matches merged into longer passages
- Matched-word totals and document coverage percentages
- Sentence context, PDF page numbers, and highlighted PDF/DOCX downloads
- Local processing with no external document service
- Responsive comparison form and results view

## Requirements

- Python 3.11 or newer
- Windows, macOS, or Linux

## Install

Create a virtual environment and install the project dependencies.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS or Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Upload two PDF or DOCX documents (up to 20 MB each) and set the minimum match length to an integer of at least 2. The default is 5 words. Debug mode is off by default; set `FLASK_DEBUG=1` only when actively debugging locally.

Text-based PDFs are supported. Scanned PDFs without an OCR text layer cannot be compared. Request files are stored in unique temporary directories and removed after one hour.

## Tests

Run the test suite with:

```bash
python -m pytest
```

Tests cover normalization, N-gram matching and span merging, repeated phrases, PDF/DOCX comparison, highlighted downloads, and the homepage branding. GitHub Actions runs the suite on Python 3.11, 3.12, and 3.13.

## Project layout

```text
app.py                  Flask routes, validation, and request lifecycle
matcher.py              Normalization and shared N-gram matching
readers.py              PDF/DOCX extraction and source positions
highlighters.py         Highlighted PDF and DOCX output
templates/index.html    Jinja2 page
static/styles.css       Responsive interface styles
tests/                  Unit and end-to-end tests
pyproject.toml           Pytest configuration
.github/workflows/       GitHub Actions test workflow
```

## Privacy and deployment

Documents are processed by this application and are not sent to external services. The local development server is not intended for public production traffic. A deployed service should use a production WSGI server, HTTPS, authentication, and an appropriate upload-retention policy.

## GitHub upload

Create an empty repository on GitHub, then run these commands from the project directory. Replace `<YOUR_USERNAME>` with your GitHub username.

```bash
git init
git branch -M main
git add .
git commit -m "Initial SideBySide project"
git remote add origin https://github.com/<YOUR_USERNAME>/SideBySide.git
git push -u origin main
```

## License

SideBySide is released under the MIT License. You may use, modify, and redistribute it, including commercially, provided the copyright and license notices are retained. See [LICENSE](LICENSE) for the full terms.
