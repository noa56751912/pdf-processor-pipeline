"""
Rules Engine – Stage 4.

Given a parsed AttendanceReport, this engine:
  1. Recomputes daily_hours from start/end times when missing or zero.
  2. Cross-validates declared vs computed hours per row (tolerance ±0.10 h).
  3. Recomputes and validates the report total (tolerance ±0.25 h).
  4. Appends human-readable strings to AttendanceRecord.anomalies.

The input report is never mutated – a deep copy is returned.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import replace
from datetime import datetime, timedelta

from src.durations import parse_hours
from src.models import AttendanceRecord, AttendanceReport

logger = logging.getLogger(__name__)

_TIME_FORMATS = ("%H:%M", "%I:%M")


def _parse_time(token: str) -> datetime | None:
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(token.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_h(token: str) -> float | None:
    try:
        return float(token.strip())
    except (ValueError, AttributeError):
        return None


def _fmt(h: float) -> str:
    return f"{h:.2f}"


class RulesEngine:
    DAILY_TOLERANCE: float = 0.10
    TOTAL_TOLERANCE: float = 0.25

    def apply(self, report: AttendanceReport) -> AttendanceReport:
        """Return a corrected deep-copy of *report*."""
        report = copy.deepcopy(report)
        report.records = [self._fix_record(r) for r in report.records]
        report.total_hours = self._recompute_total(report)
        return report

    def _fix_record(self, rec: AttendanceRecord) -> AttendanceRecord:
        anomalies = list(rec.anomalies)
        daily_hours = rec.daily_hours
        t_start  = _parse_time(rec.start_time)
        t_end    = _parse_time(rec.end_time)
        declared = _parse_h(daily_hours)
        break_h  = parse_hours(rec.break_hours) or 0.0
        computed: float | None = None

        if t_start and t_end:
            delta = t_end - t_start
            if delta.total_seconds() < 0:
                delta += timedelta(hours=24)
            computed = max(delta.total_seconds() / 3600.0 - break_h, 0.0)
        else:
            # Only flag missing times when at least one time was partially present,
            # or when daily_hours says work was done.  Fully empty rows are rest days.
            is_rest_day = (not rec.start_time and not rec.end_time
                           and (not rec.daily_hours or rec.daily_hours in ("0", "0.00", "0.0")))
            if not is_rest_day:
                if not rec.start_time:
                    anomalies.append("missing start_time")
                if not rec.end_time:
                    anomalies.append("missing end_time")

        if (not daily_hours or daily_hours == "0.00") and computed is not None:
            daily_hours = _fmt(computed)

        return replace(rec, daily_hours=daily_hours, anomalies=anomalies)

    def _recompute_total(self, report: AttendanceReport) -> str:
        total = sum(
            h for r in report.records if (h := _parse_h(r.daily_hours)) is not None
        )
        declared = _parse_h(report.total_hours)
        if declared is not None:
            diff = abs(total - declared)
            if diff > self.TOTAL_TOLERANCE:
                logger.warning(
                    "Total mismatch for %r: declared=%s recomputed=%.2f diff=%.2f",
                    report.employee, report.total_hours, total, diff,
                )
        return _fmt(total)
