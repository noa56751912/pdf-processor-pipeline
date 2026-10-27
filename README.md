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

1. **Read** – pages are rendered and read with Tesseract OCR (Hebrew +
   English). Scanned timesheets (Type A) are straightened, their table is
   located by its ruling lines, and every column is read on its own, limited
   to the characters it may hold (digits and `/` for dates, digits and `:` for
   times). A row whose clock-out − clock-in disagrees with its hours is
   repaired by the one OCR slip that makes it add up (`8:04` misread as
   `3:04`), and unreadable dates are filled from their neighbours.
2. **Detect** – the report type is chosen by scoring the column headers
   (`type_detector.py`), so new types can be added without touching the rest.
3. **Parse** – a parser per type turns lines into `AttendanceRecord`s,
   repairing common OCR errors (`41:03` → `11:03`, missing colons).
4. **Validate** – the rules engine fills missing daily hours and flags
   anomalies such as a missing clock-out.
5. **Vary** – each clock-in/out moves by 1–5 minutes; daily hours, the
   monthly total and the payment (hours × rate) are recomputed, so the new
   document still adds up (overnight shifts and breaks included).
6. **Generate** – Type A is written as a right-to-left Hebrew PDF (ReportLab),
   Type B as an Excel workbook (openpyxl).

| Type | Source | Output |
|---|---|---|
| A | Scanned clock-in/out timesheet | PDF |
| B | Payroll sheet with 100% / 125% / 150% columns | Excel (.xlsx) |

## Examples

`samples/n_r_10_n.pdf` (Type A, scanned) → `samples/n_r_10_n_out.pdf`

| | Source | Generated |
|---|---|---|
| 01/01/2023 | 8:01 – 11:05 · 3.07 h | 07:59 – 11:09 · 3.17 h |
| 02/01/2023 | 8:03 – 11:03 · 3.00 h | 08:04 – 11:08 · 3.07 h |
| **Monthly hours** | **63.02** | **63.30** |
| **Payment** (× 32.35) | **2,038.59** | **2,047.76** |

`samples/a_r_25.pdf` (Type B) → `samples/a_r_25_out.xlsx`

| | Source | Generated |
|---|---|---|
| 01/02/2023 | 08:00 – 16:00 · 7.50 h | 07:56 – 16:01 · 7.58 h |
| 13/02/2023 | 08:00 – 15:00 · 6.50 h | 08:04 – 15:04 · 6.50 h |
| **Total**  | **110.50 h** | **110.33 h** |

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

Covers the table-OCR repairs (dates, misread and dropped digits), the summary
block, the time variation (breaks, overnight shifts, recomputed payment) and the
time pattern used by both parsers. One end-to-end test reads the scanned sample
and compares all 31 rows with a hand transcription; it takes about 15 seconds
and is skipped when Tesseract is not installed.

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
