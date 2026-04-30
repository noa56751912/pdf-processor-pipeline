"""
Time Jitter – Stage 4b.

Applies small random offsets (up to ±MAX_MINUTES) to every record's
start_time and end_time so the output looks like a naturally-recorded
document rather than a verbatim copy.

Rules applied to keep the result coherent:
  • Each time is nudged independently by a whole number of minutes in
    [-MAX_MINUTES, -1] ∪ [1, MAX_MINUTES]  (zero is excluded so the
    value always changes).
  • daily_hours is recomputed from the new start / end / break so the
    column total stays internally consistent.
  • If the nudge would push a time past midnight (rare edge case), the
    direction is flipped so the day boundary is not crossed.
  • Records that are missing either start or end are left untouched.
"""
from __future__ import annotations

import copy
import random
from dataclasses import replace
from datetime import datetime, timedelta

from src.models import AttendanceRecord, AttendanceReport

MAX_MINUTES: int = 10          # maximum offset in either direction
_TIME_FORMAT = "%H:%M"


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse(token: str) -> datetime | None:
    try:
        return datetime.strptime(token.strip(), _TIME_FORMAT)
    except (ValueError, AttributeError):
        return None


def _fmt_time(dt: datetime) -> str:
    return dt.strftime(_TIME_FORMAT)


def _random_delta() -> timedelta:
    """Return a non-zero random offset in [-MAX_MINUTES, MAX_MINUTES] minutes."""
    minutes = random.randint(1, MAX_MINUTES) * random.choice([-1, 1])
    return timedelta(minutes=minutes)


def _safe_nudge(dt: datetime, delta: timedelta) -> datetime:
    """
    Apply *delta* to *dt*.  If the result leaves the [00:00, 23:59] range,
    flip the sign so the value always stays within a single calendar day.
    """
    result = dt + delta
    # reference date used by strptime is 1900-01-01; keep within that day
    base = datetime(1900, 1, 1)
    if result.date() != base.date():
        result = dt - delta          # flip direction
    # final safety clamp
    lo = datetime(1900, 1, 1, 0, 0)
    hi = datetime(1900, 1, 1, 23, 59)
    if result < lo:
        result = lo
    if result > hi:
        result = hi
    return result


def _recompute_daily(start: datetime, end: datetime, break_hours_str: str) -> str:
    """
    Recompute daily hours as a decimal string ("HH.FF") after nudging.
    Break hours is expected to be a decimal string (e.g. "0.50").
    """
    delta = end - start
    if delta.total_seconds() < 0:
        delta += timedelta(hours=24)
    worked = delta.total_seconds() / 3600.0
    try:
        break_h = float(break_hours_str.strip())
    except (ValueError, AttributeError):
        break_h = 0.0
    return f"{max(worked - break_h, 0.0):.2f}"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def jitter_record(rec: AttendanceRecord) -> AttendanceRecord:
    """Return a copy of *rec* with slightly nudged times."""
    t_start = _parse(rec.start_time)
    t_end   = _parse(rec.end_time)

    if t_start is None or t_end is None:
        return rec                   # can't nudge without both times

    new_start = _safe_nudge(t_start, _random_delta())
    new_end   = _safe_nudge(t_end,   _random_delta())

    # Ensure end > start (at least 1 minute of work remains)
    if new_end <= new_start:
        new_end = new_start + timedelta(minutes=1)

    new_daily = _recompute_daily(new_start, new_end, rec.break_hours)

    return replace(
        rec,
        start_time=_fmt_time(new_start),
        end_time=_fmt_time(new_end),
        daily_hours=new_daily,
    )


def apply_jitter(report: AttendanceReport) -> AttendanceReport:
    """Return a deep-copied *report* with jittered times in every record."""
    report = copy.deepcopy(report)
    report.records = [jitter_record(r) for r in report.records]

    # Recompute grand total from new daily values
    total = 0.0
    for r in report.records:
        try:
            total += float(r.daily_hours)
        except (ValueError, AttributeError):
            pass
    report.total_hours = f"{total:.2f}"

    return report
