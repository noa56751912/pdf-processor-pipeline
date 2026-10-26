# Attendance Report Synthesizer

Reads a Hebrew attendance report (PDF, text-based or scanned) and generates a
new document **in the same format**, with slightly varied clock times. It is
used to produce realistic synthetic data in a specific report format, without
copying the source document.

## How it works

```
PDF ──► read ──► detect type ──► parse ──► validate ──► vary times ──► generate
        text/OCR   by headers     records    rules        ±5 min       PDF / Excel
```

1. **Read** – text PDFs are read directly with PyMuPDF; scanned pages are
   rendered and read with Tesseract OCR (Hebrew + English).
2. **Detect** – the report type is chosen by scoring the column headers
   (`type_detector.py`), so new types can be added without touching the rest.
3. **Parse** – a parser per type turns lines into `AttendanceRecord`s,
   repairing common OCR errors (`41:03` → `11:03`, missing colons).
4. **Validate** – the rules engine fills missing daily hours and flags
   anomalies such as a missing clock-out.
5. **Vary** – each clock-in/out moves by 1–5 minutes; daily hours and the
   monthly total are recomputed (overnight shifts and breaks included).
6. **Generate** – Type A is written as a right-to-left Hebrew PDF (ReportLab),
   Type B as an Excel workbook (openpyxl).

| Type | Source | Output |
|---|---|---|
| A | Scanned clock-in/out timesheet | PDF |
| B | Payroll sheet with 100% / 125% / 150% columns | Excel (.xlsx) |

## Example

`samples/a_r_25.pdf` (Type B) → `samples/a_r_25_out.xlsx`

| Date | Source | Generated |
|---|---|---|
| 01/02/2023 | 08:00 – 16:00 · 7.50 h | 08:05 – 15:56 · 7.35 h |
| 13/02/2023 | 08:00 – 15:00 · 6.50 h | 08:02 – 15:04 · 6.53 h |
| **Total**  | **110.50 h** | **110.18 h** |

## Run it

Requires Python 3.11+ and [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
with the Hebrew language pack (`heb.traineddata`).

```bash
git clone https://github.com/noa56751912/pdf-processor-pipeline.git
cd pdf-processor-pipeline
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py samples/a_r_25.pdf
```

Options: `--out <path>` sets the output file, `--print-text` prints the
extracted text (add `--page-break` to mark pages).

## Tests

```bash
python -m unittest
```

Covers the duration parsing, the time variation (breaks, overnight shifts) and
the time pattern used by both parsers, using real lines from the samples.

## Project layout

```
src/
  readers/      PDF text extraction and OCR (factory by file extension)
  parsers/      one parser per report type (registry)
  rules/        validation and missing-value repair
  generators/   one generator per report type (registry)
  type_detector.py   header-based type detection
  time_jitter.py     clock-time variation
tests/          unit tests
samples/        example inputs and generated outputs
```

## Tech

Python · PyMuPDF · Tesseract OCR · ReportLab · python-bidi · openpyxl
