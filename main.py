"""
Entry point for the Attendance PDF Variant Tool.

Usage
-----
    python main.py <input.pdf> [--out <output>] [--print-text] [--page-break]

Type-A reports are written as PDF, Type-B reports as Excel (.xlsx).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.readers.pdf_reader import PDFReader
from src.readers.reader_factory import ReaderFactory
from src.type_detector import ReportType, detect
from src.parsers.parser_registry import ParserRegistry
from src.rules.rules_engine import RulesEngine
from src.generators.generator_registry import GeneratorRegistry
from src.time_jitter import apply_jitter

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read, parse, validate, and regenerate an attendance PDF."
    )
    p.add_argument("file", type=Path, help="Input PDF path.")
    p.add_argument(
        "--out", type=Path, default=None,
        help="Output path (default: <input>_out next to the input file; "
             "Type-B reports are written as .xlsx).",
    )
    p.add_argument("--print-text", action="store_true", help="Print raw extracted text.")
    p.add_argument("--page-break", action="store_true", help="Show page breaks in --print-text output.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path: Path = args.file

    # ── Stage 1: read ────────────────────────────────────────────────────
   
    try:
        logger.info("Reading: %s", input_path)
        text = ReaderFactory.read(input_path)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        return 1

    if args.print_text:
        display = text.replace("\f", "\n--- PAGE BREAK ---\n") if args.page_break else text
        print(display)

    # ── Stage 2: detect ──────────────────────────────────────────────────
    report_type = detect(text)
    if report_type is ReportType.UNKNOWN:
        logger.warning("Could not detect report type – aborting.")
        return 1
    logger.info("Detected: %s", report_type)

    # Scanned timesheets: re-read the table cell by cell (slower, far more accurate)
    if report_type is ReportType.TYPE_A:
        text = PDFReader(read_tables=True).read(input_path)

    # ── Stage 3: parse ───────────────────────────────────────────────────
    report = ParserRegistry.get(report_type).parse(text)
    logger.info(
        "Parsed | employee=%r | period=%s → %s | records=%d | total=%s",
        report.employee, report.period_start, report.period_end,
        len(report.records), report.total_hours,
    )

    # ── Stage 4: rules ───────────────────────────────────────────────────
    report = RulesEngine().apply(report)
    logger.info("Rules applied | total_hours=%s", report.total_hours)
    anomalous = [r for r in report.records if r.anomalies]
    if anomalous:
        logger.warning("%d record(s) with anomalies:", len(anomalous))
        for rec in anomalous:
            logger.warning("  %s → %s", rec.date_text, rec.anomalies)

    # ── Stage 4b: jitter ─────────────────────────────────────────────────
    report = apply_jitter(report)
    logger.info("Time jitter applied | new total_hours=%s", report.total_hours)

    # ── Stage 5: generate ────────────────────────────────────────────────
    out_path = args.out or input_path.with_stem(input_path.stem + "_out")
    written = GeneratorRegistry.get(report_type).generate(report, out_path)
    logger.info("Output written: %s", written)

    return 0


if __name__ == "__main__":
    sys.exit(main())
