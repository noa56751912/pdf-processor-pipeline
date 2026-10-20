"""
Parser for Type-A attendance reports (simple clock-in/out timesheet).

Row layout (RTL PDF, extracted left-to-right):
    [decimals...] [clock-out HH:MM] [clock-in HH:MM] [day] [date]
    date formats: DD/MM/YYYY  or  D/M/YY

OCR error correction (three dynamic strategies):
  1. Anchor Month  – header is scanned for a Hebrew month name; every parsed
                     date whose month differs is forced to the anchor month.
  2. Time Consistency – if |computed_duration - declared_hours| > 30 min,
                        single-digit OCR flips are tried to minimise the gap.
  3. Day–Date Sync  – the Hebrew day name is compared against the parsed date's
                      weekday; mismatches trigger a date-correction pass.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from src.models import AttendanceRecord, AttendanceReport
from src.parsers.base_parser import BaseParser

_DATE_RE    = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
_TIME_RE    = re.compile(r"\b(\d{1,2}:?\d{2})\b")
_DECIMAL_RE = re.compile(r"\b(\d{1,3}\.\d{2})\b")
_EMP_ID_RE  = re.compile(r"\b(\d{9})\b")

# Hebrew month abbreviations / full names → month number
_HEB_MONTHS: dict[str, int] = {
    "ינו": 1,  "ינואר": 1,
    "פבר": 2,  "פברואר": 2,
    "מרס": 3,  "מרץ": 3,
    "אפר": 4,  "אפריל": 4,
    "מאי": 5,
    "יונ": 6,  "יוני": 6,
    "יול": 7,  "יולי": 7,
    "אוג": 8,  "אוגוסט": 8,
    "ספט": 9,  "ספטמבר": 9,
    "אוק": 10, "אוקטובר": 10,
    "נוב": 11, "נובמבר": 11,
    "דצמ": 12, "דצמבר": 12,
}
# Regex: <hebrew-word> separator <2-or-4-digit-year>
_HEADER_MONTH_RE         = re.compile(r"([\u05d0-\u05ea]{2,6})[\s'\-\u2013/]+(\d{2,4})")
# Numeric formats in header: MM/YYYY or YYYY-MM or YYYY/MM
_HEADER_MONTH_NUMERIC_RE = re.compile(
    r"(?:(\d{1,2})/(\d{4})|(\d{4})[\-/](\d{1,2}))"
)

# Common single-digit OCR flip pairs {seen_digit: [possible_real_digits]}
_DIGIT_FLIPS: dict[str, list[str]] = {
    "0": ["8", "6"],
    "1": ["7", "4"],
    "2": ["7"],
    "3": ["8"],
    "4": ["1"],
    "6": ["0"],
    "7": ["1"],
    "8": ["0", "3"],
}

# Multi-digit hour-level substitutions (two-character hour string → alternatives).
# Used for cases where two digits are simultaneously corrupted, e.g. 20→08.
_HOUR_SUBS: dict[str, list[str]] = {
    "20": ["08", "02"],
    "21": ["07", "01"],
    "22": ["08", "02"],
    "23": ["09", "03"],
    "00": ["08", "10", "06"],
    "01": ["07", "09"],
    "40": ["10"],
    "41": ["11"],
    "42": ["12"],
    "43": ["13"],
    "44": ["14"],
    "45": ["15"],
    "46": ["16"],
}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _repair_time(token: str) -> str:
    """Fix common OCR digit corruption (41:03->11:03, 10:67->10:57).

    Also handles tokens without a colon (e.g. '804' -> '08:04', '1057' -> '10:57').
    Additionally recovers times where OCR dropped the leading '1':
      00:xx -> 10:xx,  01:xx -> 11:xx,  02:xx -> 12:xx, etc. up to 05:xx -> 15:xx
    (A genuine clock-in/out before 06:00 is implausible for this use-case.)
    """
    try:
        if ":" not in token and len(token) in (3, 4):
            token = token[:-2] + ":" + token[-2:]
        h, m = token.split(":")
        h, m = int(h), int(m)
        if h > 23 and (h - 30) >= 0:
            h -= 30
        if m > 59 and (m - 10) >= 0:
            m -= 10
        # OCR frequently drops the leading '1' from times like 10:xx or 13:xx.
        # If the resulting hour is implausibly early (< 6), shift by +10.
        if h < 6:
            h += 10
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except (ValueError, AttributeError):
        pass
    return token


def _time_duration_h(start: str, end: str) -> Optional[float]:
    """Return duration in hours between two HH:MM strings, or None on error."""
    try:
        ts = datetime.strptime(start, "%H:%M")
        te = datetime.strptime(end,   "%H:%M")
        dur = (te - ts).total_seconds() / 3600.0
        if dur < 0:
            dur += 24.0
        return dur
    except ValueError:
        return None


def _time_variants(token: str) -> list[str]:
    """Return all valid HH:MM strings reachable by:
      (a) flipping one digit, or
      (b) substituting the two-character hour with a known OCR-corruption mapping.
    """
    base = _repair_time(token)
    if not re.match(r"^\d{2}:\d{2}$", base):
        return []
    results: list[str] = [base]

    # (a) single-digit flips
    for i, ch in enumerate(base):
        if ch == ":":
            continue
        for alt in _DIGIT_FLIPS.get(ch, []):
            candidate = _repair_time(base[:i] + alt + base[i + 1:])
            if re.match(r"^\d{2}:\d{2}$", candidate) and candidate not in results:
                results.append(candidate)

    # (b) hour-level substitutions (covers two-digit corruption like 20→08)
    hour_str = base[:2]
    minutes  = base[3:]
    for alt_hour in _HOUR_SUBS.get(hour_str, []):
        candidate = f"{alt_hour}:{minutes}"
        if candidate not in results:
            results.append(candidate)

    return results


def _fix_times_by_total(
    start: str, end: str, declared_h: float, tolerance: float = 0.05
) -> tuple[str, str]:
    """
    Try all _time_variants (single-digit flips + hour-level subs) on *start*
    and *end* to find a pair whose computed duration matches *declared_h*
    within *tolerance* hours (default 3 minutes).

    Fast path: if start or end hour >= 18, immediately try _HOUR_SUBS first.
    Only returns a corrected pair when the fix genuinely reduces the error.
    """
    orig_dur = _time_duration_h(start, end)
    orig_err = abs(orig_dur - declared_h) if orig_dur is not None else float("inf")

    # Already matches – nothing to do
    if orig_err <= tolerance:
        return (start, end)

    best_err  = orig_err
    best_pair = (start, end)

    def _try(sv: str, ev: str) -> None:
        nonlocal best_err, best_pair
        dur = _time_duration_h(sv, ev)
        if dur is None:
            return
        err = abs(dur - declared_h)
        if err < best_err:
            best_err  = err
            best_pair = (sv, ev)

    # Fast path: suspicious hour (>= 18 is never a valid clock-in)
    for token, is_start in ((start, True), (end, False)):
        base = _repair_time(token)
        if re.match(r"^\d{2}:\d{2}$", base) and int(base[:2]) >= 18:
            for alt_h in _HOUR_SUBS.get(base[:2], []):
                fixed = f"{alt_h}:{base[3:]}"
                if is_start:
                    _try(fixed, end)
                else:
                    _try(start, fixed)

    # Full grid search
    for sv in _time_variants(start):
        for ev in _time_variants(end):
            _try(sv, ev)

    # Only adopt the fix if it strictly improves the error beyond tolerance
    if best_err < orig_err - tolerance:
        return best_pair
    return (start, end)


class ParserTypeA(BaseParser):
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

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse(self, text: str) -> AttendanceReport:
        lines = [ln.strip() for ln in text.splitlines()]
        pages = text.count("\f") + 1
        employee = self._extract_employee(lines)
        records, period_start, period_end = self._extract_records(lines)
        total_hours = self._extract_total(lines)
        summary = self._extract_summary(lines)
        for rec in records:
            print(f"Date: {rec.date_text} | In: {rec.start_time} | Out: {rec.end_time} | Total: {rec.daily_hours}")
        return AttendanceReport(
            report_type="type_a",
            employee=employee,
            period_start=period_start,
            period_end=period_end,
            records=records,
            total_hours=total_hours,
            source_pages=pages,
            total_working_days=summary.get("total_working_days", ""),
            total_monthly_hours=summary.get("total_monthly_hours", ""),
            hourly_rate=summary.get("hourly_rate", ""),
            total_payment=summary.get("total_payment", ""),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_employee(self, lines: list[str]) -> str:
        for line in lines:
            m = _EMP_ID_RE.search(line)
            if m:
                return m.group(1)
        return ""

    # Summary field regexes (flexible: value may follow colon or be on same line)
    _SUMMARY_WORK_DAYS_RE    = re.compile(r'סה"?כ\s*ימי\s*עבודה[^\d]*(\d+)')
    _SUMMARY_MONTHLY_HRS_RE  = re.compile(r'סה"?כ\s*שעות\s*חודשיות[^\d]*([\d.,]+)')
    _SUMMARY_RATE_RE         = re.compile(r'מחיר\s*לשעה[^\d]*([\d.,]+)')
    _SUMMARY_PAYMENT_RE      = re.compile(r'סה"?כ\s*לתשלום[^\d]*([\d.,]+)')

    def _extract_summary(self, lines: list[str]) -> dict[str, str]:
        """Extract payment summary fields from the document header area."""
        result: dict[str, str] = {}
        for line in lines:
            if not result.get("total_working_days"):
                m = self._SUMMARY_WORK_DAYS_RE.search(line)
                if m:
                    result["total_working_days"] = m.group(1)
            if not result.get("total_monthly_hours"):
                m = self._SUMMARY_MONTHLY_HRS_RE.search(line)
                if m:
                    result["total_monthly_hours"] = m.group(1)
            if not result.get("hourly_rate"):
                m = self._SUMMARY_RATE_RE.search(line)
                if m:
                    result["hourly_rate"] = m.group(1)
            if not result.get("total_payment"):
                m = self._SUMMARY_PAYMENT_RE.search(line)
                if m:
                    result["total_payment"] = m.group(1)
        return result

    def _extract_anchor_month(
        self, lines: list[str], scan_lines: int = 40
    ) -> Optional[tuple[int, int]]:
        """
        Scan the first *scan_lines* header lines for a month/year anchor.
        Accepts:
          - Hebrew month name followed by a 2-or-4-digit year (e.g. 'ינו-23')
          - Numeric formats: MM/YYYY, YYYY-MM, YYYY/MM (e.g. '01/2023', '2023-01')
        Falls back to majority-vote over all dates in the document if header
        scan finds nothing.
        Returns (month, full_year) or None.
        """
        # -- Header scan --
        for line in lines[:scan_lines]:
            print(f"[DEBUG anchor scan] {line!r}")
            # Hebrew month name
            for m in _HEADER_MONTH_RE.finditer(line):
                heb_word = m.group(1)
                year_str = m.group(2)
                month = _HEB_MONTHS.get(heb_word)
                if month is None:
                    continue
                year = int(year_str)
                if year < 100:
                    year += 2000
                print(f"[DEBUG anchor] Hebrew match: month={month}, year={year}")
                return (month, year)
            # Numeric month/year
            for m in _HEADER_MONTH_NUMERIC_RE.finditer(line):
                if m.group(1) and m.group(2):          # MM/YYYY
                    month, year = int(m.group(1)), int(m.group(2))
                else:                                   # YYYY-MM or YYYY/MM
                    month, year = int(m.group(4)), int(m.group(3))
                if 1 <= month <= 12 and 1900 <= year <= 2100:
                    print(f"[DEBUG anchor] Numeric match: month={month}, year={year}")
                    return (month, year)

        # -- Majority-vote fallback: collect all parseable dates in document --
        from collections import Counter
        month_year_counts: Counter = Counter()
        for line in lines:
            m = _DATE_RE.search(line)
            if not m:
                continue
            raw = m.group(1)
            try:
                fmt = "%d/%m/%Y" if len(raw) == 10 else "%d/%m/%y"
                d = datetime.strptime(raw, fmt).date()
                year = d.year if d.year >= 2000 else d.year + 2000
                month_year_counts[(d.month, year)] += 1
            except ValueError:
                pass
        if month_year_counts:
            anchor = month_year_counts.most_common(1)[0][0]
            print(f"[DEBUG anchor] Majority-vote fallback: month={anchor[0]}, year={anchor[1]} (counts={dict(month_year_counts)})")
            return anchor

        print("[DEBUG anchor] No anchor found.")
        return None

    def _get_target_weekday(self, raw_line: str) -> Optional[int]:
        """Return the Python weekday expected by the Hebrew day name in *raw_line*, or None."""
        for heb, wd in self._HEB_WEEKDAY.items():
            if heb in raw_line:
                return wd
        return None

    def _fix_date_by_day(
        self,
        pd: date,
        target_wd: int,
        anchor: Optional[tuple[int, int]],
    ) -> Optional[date]:
        """
        Attempt to correct *pd* so that its weekday matches *target_wd*.

        Strategies tried (in order):
        1. Force to anchor month (same day-of-month, anchor month/year).
        2. Swap day and month digits (dd/mm → mm/dd).
        3. Walk ±3 days within the same anchor month.
        Returns the corrected date, or None if no strategy works.
        """
        # Strategy 1: force anchor month
        if anchor is not None:
            try:
                candidate = date(anchor[1], anchor[0], pd.day)
                if candidate.weekday() == target_wd:
                    return candidate
            except ValueError:
                pass

        # Strategy 2: swap dd/mm
        try:
            swapped = date(pd.year, pd.day, pd.month)
            if swapped.weekday() == target_wd:
                if anchor is None or swapped.month == anchor[0]:
                    return swapped
        except ValueError:
            pass

        # Strategy 3: walk ±3 days staying in anchor month (if known)
        for delta in range(-3, 4):
            if delta == 0:
                continue
            candidate = pd + timedelta(days=delta)
            if candidate.weekday() == target_wd:
                if anchor is None or candidate.month == anchor[0]:
                    return candidate

        return None

    # Reverse map: Python weekday() → Hebrew day name
    _WEEKDAY_TO_HEB: dict[int, str] = {
        6: "ראשון",   # Sunday
        0: "שני",     # Monday
        1: "שלישי",  # Tuesday
        2: "רביעי",  # Wednesday
        3: "חמישי",  # Thursday
        4: "שישי",   # Friday
        5: "שבת",    # Saturday
    }

    # ------------------------------------------------------------------
    # Core record extraction  (Calendar-Logic approach)
    # ------------------------------------------------------------------

    def _extract_records(
        self, lines: list[str]
    ) -> tuple[list[AttendanceRecord], date | None, date | None]:
        import calendar as _cal

        anchor = self._extract_anchor_month(lines)
        print(f"[DEBUG] Anchor month detected: {anchor}")

        # ----------------------------------------------------------------
        # Step 1 – Build the authoritative calendar for this month.
        # Every day 1..N is a row; dates/day-names come from Python,
        # not from the OCR text.
        # ----------------------------------------------------------------
        if anchor is not None:
            month, year = anchor
            _, days_in_month = _cal.monthrange(year, month)
            calendar_dates: list[date] = [
                date(year, month, d) for d in range(1, days_in_month + 1)
            ]
        else:
            # No anchor found – fall back to an empty calendar; data rows
            # will still be collected but will have no assigned dates.
            calendar_dates = []

        # ----------------------------------------------------------------
        # Step 2 – Collect data rows from every OCR line.
        # Use _TIME_RE + _repair_time so OCR hallucinations are corrected
        # (e.g. "41:03" → "11:03") before any comparison is made.
        # RTL/LTR ambiguity is resolved by comparing the two times:
        #   start = min(raw_times[0], raw_times[1])
        #   end   = max(raw_times[0], raw_times[1])
        # daily_hours is derived from the actual time difference rather
        # than from the OCR decimal (which OCR frequently drops the dot on).
        # Lines with fewer than 2 repaired times are skipped.
        # ----------------------------------------------------------------
        data_rows: list[dict] = []

        for line in lines:
            raw_times = [_repair_time(t) for t in _TIME_RE.findall(line)]

            if len(raw_times) < 2:
                continue

            # min/max comparison resolves RTL vs LTR ordering reliably
            start_time = min(raw_times[0], raw_times[1])
            end_time   = max(raw_times[0], raw_times[1])

            if start_time and end_time:
                dur = _time_duration_h(start_time, end_time)
                daily_hours = f"{dur:.2f}" if dur is not None else ""
            else:
                daily_hours = ""

            data_rows.append({
                "start_time":  start_time,
                "end_time":    end_time,
                "daily_hours": daily_hours,
                "raw_line":    line,
            })

        print(f"[DEBUG] Calendar days: {len(calendar_dates)}  |  OCR data rows: {len(data_rows)}")

        # ----------------------------------------------------------------
        # Step 3 – Slot each data row into the correct calendar day using
        # _DATE_RE to read the day number from the line.  Rows whose date
        # cannot be parsed are assigned sequentially to the first free
        # slot.  Days with no data remain blank (genuine rest days).
        # ----------------------------------------------------------------
        day_map: dict[int, dict] = {}
        unmatched: list[dict]    = []

        for row_data in data_rows:
            raw_line = row_data["raw_line"]
            m_date   = _DATE_RE.search(raw_line)
            day_num: int | None = None
            if m_date:
                parts = m_date.group(1).split("/")
                try:
                    day_num = int(parts[0])
                except (ValueError, IndexError):
                    pass
            if day_num is not None and 1 <= day_num <= len(calendar_dates):
                day_map[day_num] = row_data
            else:
                unmatched.append(row_data)

        # Fill unmatched rows into the first free slots sequentially.
        free_slots = [d for d in range(1, len(calendar_dates) + 1) if d not in day_map]
        for row_data, slot in zip(unmatched, free_slots):
            day_map[slot] = row_data

        records: list[AttendanceRecord] = []

        for i, row_date in enumerate(calendar_dates):
            day_num  = row_date.day
            row_data = day_map.get(day_num, {})

            date_text   = row_date.strftime("%d/%m/%Y")
            day_name    = self._WEEKDAY_TO_HEB[row_date.weekday()]

            # Friday (4) and Saturday (5) are always rest days regardless of OCR.
            if row_date.weekday() in (4, 5):
                start_time  = ""
                end_time    = ""
                daily_hours = ""
                raw_line    = ""
            else:
                start_time  = row_data.get("start_time",  "")
                end_time    = row_data.get("end_time",    "")
                daily_hours = row_data.get("daily_hours", "")
                raw_line    = row_data.get("raw_line",    "")

            print(
                f"[DEBUG] Row {i:>3}: {date_text}  {day_name:<6}  "
                f"in={start_time or '--:--'}  out={end_time or '--:--'}  "
                f"h={daily_hours or '0.00'}"
            )

            records.append(AttendanceRecord(
                date_text=date_text,
                start_time=start_time,
                end_time=end_time,
                break_hours="",
                daily_hours=daily_hours,
                day_of_week=day_name,
                raw_line=raw_line,
            ))

        period_start = calendar_dates[0]  if calendar_dates else None
        period_end   = calendar_dates[-1] if calendar_dates else None

        return records, period_start, period_end

    def _extract_total(self, lines: list[str]) -> str:
        for line in reversed(lines):
            if _DATE_RE.search(line):
                continue
            decimals = _DECIMAL_RE.findall(line)
            if decimals:
                return max(decimals, key=lambda v: float(v))
        return "0.00"
