"""
Domain data model for attendance reports.

Design decision
---------------
This file is the ONLY place the pipeline's data shape is defined.
Stages 3-5 (parsers, rules, generators) all import from here.
Changing a field means changing it in exactly one place.

AttendanceRecord  – one line in the working-day table
AttendanceReport  – the full document (header meta + list of records)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class AttendanceRecord:
    """One attendance row: a single work day for one employee."""

    date_text: str          # original date string as it appeared in the source
    start_time: str         # "HH:MM"
    end_time: str           # "HH:MM"
    daily_hours: str = ""   # "HH:MM" – filled/corrected by the rules engine
    employee: str = ""      # populated by parsers that embed names per row
    raw_line: str = ""      # the original OCR/extracted line (debug aid)
    break_hours: str = ""   # "HH:MM" or decimal – break duration
    anomalies: list[str] = field(default_factory=list)  # human-readable issues


@dataclass
class AttendanceReport:
    """
    Full parsed representation of one attendance PDF.

    report_type   – mirrors ReportType enum value (string so models.py has
                    no dependency on type_detector.py – avoids circular imports)
    employee      – name/ID of the employee (document-level header)
    period_start  – first date of the reporting period
    period_end    – last date of the reporting period
    records       – ordered list of AttendanceRecord rows
    total_hours   – declared or computed grand total "HH:MM"
    source_pages  – number of PDF pages the text came from
    """

    report_type: str
    employee: str = ""
    period_start: date | None = None
    period_end: date | None = None
    records: list[AttendanceRecord] = field(default_factory=list)
    total_hours: str = "00:00"
    source_pages: int = 0
