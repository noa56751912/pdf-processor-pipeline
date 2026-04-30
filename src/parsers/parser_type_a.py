"""
Parser for Type-A attendance reports (simple clock-in/out timesheet).

Row layout (RTL PDF, extracted left-to-right):
    [decimals...] [break_HH:MM] [clock-out HH:MM] [clock-in HH:MM] [day] [date]
    date formats: DD/MM/YYYY  or  D/M/YY
"""
from __future__ import annotations

import re
from datetime import date, datetime

from src.models import AttendanceRecord, AttendanceReport
from src.parsers.base_parser import BaseParser

_DATE_RE    = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
_TIME_RE    = re.compile(r"\b(\d{1,2}:\d{2})\b")
_DECIMAL_RE = re.compile(r"\b(\d{1,3}\.\d{2})\b")
_EMP_ID_RE  = re.compile(r"\b(\d{9})\b")


def _repair_time(token: str) -> str:
    """Fix common OCR digit corruption (41:03->11:03, 10:67->10:57)."""
    try:
        h, m = token.split(":")
        h, m = int(h), int(m)
        if h > 23 and (h - 30) >= 0:
            h -= 30
        if m > 59 and (m - 10) >= 0:
            m -= 10
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except (ValueError, AttributeError):
        pass
    return token


class ParserTypeA(BaseParser):
    def parse(self, text: str) -> AttendanceReport:
        lines = [ln.strip() for ln in text.splitlines()]
        pages = text.count("\f") + 1
        employee = self._extract_employee(lines)
        records, period_start, period_end = self._extract_records(lines)
        total_hours = self._extract_total(lines)
        return AttendanceReport(
            report_type="type_a",
            employee=employee,
            period_start=period_start,
            period_end=period_end,
            records=records,
            total_hours=total_hours,
            source_pages=pages,
        )

    def _extract_employee(self, lines: list[str]) -> str:
        for line in lines:
            m = _EMP_ID_RE.search(line)
            if m:
                return m.group(1)
        return ""

    def _extract_records(
        self, lines: list[str]
    ) -> tuple[list[AttendanceRecord], date | None, date | None]:
        records: list[AttendanceRecord] = []
        period_start: date | None = None
        period_end: date | None = None
        for line in lines:
            m = _DATE_RE.search(line)
            if not m:
                continue
            date_text = m.group(1)
            try:
                fmt = "%d/%m/%Y" if len(date_text) == 10 else "%d/%m/%y"
                parsed_date = datetime.strptime(date_text, fmt).date()
            except ValueError:
                continue
            # RTL PDFs: left-to-right extraction order is [break, clock-out, clock-in]
            times    = [_repair_time(t) for t in _TIME_RE.findall(line)]
            decimals = _DECIMAL_RE.findall(line)
            start_time  = times[-1]   if len(times) >= 1 else ""
            end_time    = times[-2]   if len(times) >= 2 else ""
            break_hours = times[0]    if len(times) >= 3 else ""
            daily_hours = decimals[0] if decimals else ""
            records.append(AttendanceRecord(
                date_text=date_text,
                start_time=start_time,
                end_time=end_time,
                break_hours=break_hours,
                daily_hours=daily_hours,
                raw_line=line,
            ))
            if period_start is None or parsed_date < period_start:
                period_start = parsed_date
            if period_end is None or parsed_date > period_end:
                period_end = parsed_date
        return records, period_start, period_end

    def _extract_total(self, lines: list[str]) -> str:
        for line in reversed(lines):
            if _DATE_RE.search(line):
                continue
            decimals = _DECIMAL_RE.findall(line)
            if decimals:
                return max(decimals, key=lambda v: float(v))
        return "0.00"
