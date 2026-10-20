"""
Parser for Type-B attendance reports (daily clock-in / clock-out timesheet).

Row layout (English-only OCR):
    211123  8:01  11:05  3.07
    DDMMYY  in    out    duration-hours
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from src.models import AttendanceRecord, AttendanceReport
from src.parsers.base_parser import BaseParser

_DATE_SLASH_RE   = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\b")
_DATE_COMPACT_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})$")
_TIME_RE         = re.compile(r"\b(\d{1,2}:?\d{2})\b")
_DECIMAL_RE      = re.compile(r"\b(\d{1,3}\.\d{2})\b")
_MONETARY_RE     = re.compile(r"\b(\d{1,3}(?:,\d{3})+(?:\.\d{2})?)\b")
_EMP_ID_RE       = re.compile(r"\b(\d{9})\b")


def _repair_time(token: str) -> str:
    """Fix common OCR digit corruption (41:03->11:03, 10:67->10:57).

    Also handles tokens without a colon (e.g. '803' -> '8:03', '1057' -> '10:57').
    """
    try:
        if ":" in token:
            h, m = token.split(":")
        else:
            # Last 2 digits are minutes, everything before is hours.
            h, m = token[:-2], token[-2:]
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


def _parse_compact(token: str) -> tuple[date, str] | None:
    m = _DATE_COMPACT_RE.match(token.strip())
    if not m:
        return None
    dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(2000 + yy, mm, dd), token
    except ValueError:
        return None


class ParserTypeB(BaseParser):
    def parse(self, text: str) -> AttendanceReport:
        lines = [ln.strip() for ln in text.splitlines()]
        pages = text.count("\f") + 1
        employee = self._extract_employee(lines)
        records, period_start, period_end = self._extract_records(lines)
        total_hours = self._extract_monetary_total(lines)
        return AttendanceReport(
            report_type="type_b",
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

    def _extract_date(self, line: str) -> tuple[date, str] | None:
        m = _DATE_SLASH_RE.search(line)
        if m:
            raw = m.group(1)
            fmt = "%d/%m/%Y" if len(raw) == 10 else "%d/%m/%y"
            try:
                return datetime.strptime(raw, fmt).date(), raw
            except ValueError:
                pass
        for token in line.split():
            if len(token) == 6 and token.isdigit():
                result = _parse_compact(token)
                if result:
                    return result
        return None

    # Maps Hebrew day names to Python weekday() values (0=Monday … 6=Sunday)
    _HEB_WEEKDAY: dict[str, int] = {
        "ראשון":  6,  # Sunday
        "שני":    0,  # Monday
        "שלישי": 1,  # Tuesday
        "רביעי": 2,  # Wednesday
        "חמישי": 3,  # Thursday
        "שישי":  4,  # Friday
        "שבת":   5,  # Saturday
    }

    def _extract_records(
        self, lines: list[str]
    ) -> tuple[list[AttendanceRecord], date | None, date | None]:
        # ------------------------------------------------------------------ #
        # Pass 1 – collect rows; keep any line with ≥2 time tokens even when
        # no date could be parsed (parsed_date will be None for those rows).
        # ------------------------------------------------------------------ #
        raw_rows: list[tuple[date | None, str, AttendanceRecord]] = []
        for line in lines:
            times    = [_repair_time(t) for t in _TIME_RE.findall(line)]
            result   = self._extract_date(line)
            # Require at least 2 time tokens OR a valid date to treat as a
            # data row (avoids pulling in header / footer lines).
            if result is None and len(times) < 2:
                continue
            parsed_date: date | None
            date_text: str
            if result is not None:
                parsed_date, date_text = result
            else:
                parsed_date, date_text = None, ""
            decimals    = _DECIMAL_RE.findall(line)
            # LTR extraction order: [clock-in, clock-out, break]
            start_time  = times[0] if len(times) >= 1 else ""
            end_time    = times[1] if len(times) >= 2 else ""
            break_hours = times[2] if len(times) >= 3 else ""
            daily_hours = decimals[0] if decimals else ""
            raw_rows.append((
                parsed_date,
                date_text,
                AttendanceRecord(
                    date_text=date_text,
                    start_time=start_time,
                    end_time=end_time,
                    break_hours=break_hours,
                    daily_hours=daily_hours,
                    raw_line=line,
                ),
            ))

        # ------------------------------------------------------------------ #
        # Pass 2 – interpolate missing dates.
        # Strategy: for each None-date row, start from the last known date
        # and walk forward (+1 day at a time).  If the raw_line contains a
        # Hebrew day name, keep advancing until the candidate weekday matches.
        # ------------------------------------------------------------------ #
        parsed_dates: list[date | None] = [r[0] for r in raw_rows]
        last_known: date | None = None
        for i, (pd, dt_text, rec) in enumerate(raw_rows):
            if pd is not None:
                last_known = pd
            else:
                if last_known is not None:
                    candidate = last_known + timedelta(days=1)
                    # Check for a Hebrew day-name hint in the raw line.
                    target_weekday: int | None = None
                    for heb, wd in self._HEB_WEEKDAY.items():
                        if heb in rec.raw_line:
                            target_weekday = wd
                            break
                    if target_weekday is not None:
                        # Advance at most 7 days to reach the matching weekday.
                        for _ in range(7):
                            if candidate.weekday() == target_weekday:
                                break
                            candidate += timedelta(days=1)
                    parsed_dates[i] = candidate
                    last_known = candidate

        # ------------------------------------------------------------------ #
        # Pass 3 – build final records list and compute period bounds.
        # ------------------------------------------------------------------ #
        records: list[AttendanceRecord] = []
        period_start: date | None = None
        period_end:   date | None = None
        for i, (_, _, rec) in enumerate(raw_rows):
            pd = parsed_dates[i]
            if pd is not None:
                inferred_text = pd.strftime("%d/%m/%Y")
                rec = AttendanceRecord(
                    date_text=inferred_text,
                    start_time=rec.start_time,
                    end_time=rec.end_time,
                    break_hours=rec.break_hours,
                    daily_hours=rec.daily_hours,
                    raw_line=rec.raw_line,
                )
                if period_start is None or pd < period_start:
                    period_start = pd
                if period_end is None or pd > period_end:
                    period_end = pd
            records.append(rec)
        return records, period_start, period_end

    def _extract_monetary_total(self, lines: list[str]) -> str:
        for line in reversed(lines):
            m = _MONETARY_RE.search(line)
            if m:
                return m.group(1)
        return "0.00"
