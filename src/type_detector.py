"""
Report-type detection.

Design decisions
----------------
* ReportType is a StrEnum so it can be used as a dict key, printed, stored in
  AttendanceReport.report_type as a plain string, and matched with match/case.

* detect() is a pure function (no state, no side effects).  It scores the
  extracted text against per-type signal sets and returns the highest-scoring
  type.  Ties favour TYPE_A.

* Signal sets use both English and Hebrew column-header words so the detector
  works whether Tesseract returned Latin or Hebrew characters.

Adding a new report type
------------------------
1. Add a variant to ReportType.
2. Add a _SIGNALS_<TYPE> frozenset.
3. Register it in _SIGNAL_MAP at the bottom of this file.
That is all - no other file needs to change.
"""

from __future__ import annotations

import re
from enum import StrEnum

_TIME_PATTERN_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


class ReportType(StrEnum):
    TYPE_A = "type_a"
    TYPE_B = "type_b"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Signal tables
# ---------------------------------------------------------------------------

# Type A: Hebrew clock-in/out timesheet (no overtime columns)
_SIGNALS_TYPE_A: frozenset[str] = frozenset(
    {
        # Hebrew keywords distinctive to Type-A
        "הערות",
        "יום בשבוע",
        "שעת כניסה",
        "שעת יציאה",
        "כרטיס עובד",
        "מחיר לשעה",
        "שם העובד",
        "ימי עבודה לחודש"


    }
)

# Type B: Hebrew RTL payroll sheet with 100%/125%/150% overtime columns
_SIGNALS_TYPE_B: frozenset[str] = frozenset(
    {
        # Overtime percentage columns – unique to Type-B
        # Both LTR ("100%") and RTL OCR artifact ("% 100") forms are listed.
        "100%",
        "125%",
        "150%",
        "% 100",
        "% 125",
        "% 150",
        # Hebrew keywords distinctive to Type-B
        "בונוס",
        "נסיעות",
        "הפסקה",
        "נ.ע. הנשר כח אדם",
        "גונן",

    }
)

# Map every concrete type to its signal set
_SIGNAL_MAP: dict[ReportType, frozenset[str]] = {
    ReportType.TYPE_A: _SIGNALS_TYPE_A,
    ReportType.TYPE_B: _SIGNALS_TYPE_B,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(text: str) -> ReportType:
    """
    Detect which report variant *text* belongs to.

    Algorithm
    ---------
    1. Lower-case the full extracted text once.
    2. For each registered type, count how many of its signals appear in the
       text (each signal counted at most once regardless of occurrences).
    3. Return the type with the highest score.
    4. If all scores are zero but >=3 HH:MM time tokens are present, use
       heuristics to choose TYPE_A or TYPE_B.
    5. Ties are broken by the iteration order of _SIGNAL_MAP (TYPE_A wins).
    """
    lowered = text.lower()
    best_type = ReportType.UNKNOWN
    best_score = 0

    for report_type, signals in _SIGNAL_MAP.items():
        score = 0
        for signal in signals:
            # Replace spaces with \s+ so multi-word signals match even when
            # OCR inserts newlines or extra spaces between words.
            pattern = signal.lower().replace(" ", r"\s+")
            if re.search(pattern, lowered):
                score += 1

        if score > best_score:
            best_score = score
            best_type = report_type

    # Fallback: no keywords matched but text contains time tokens.
    if best_score == 0:
        times_found = len(_TIME_PATTERN_RE.findall(text))
        if times_found >= 3:
            # Explicit overtime percentage markers -> Type-B.
            # Matches LTR "150%", spaced "150 %", and RTL OCR artifact "% 150".
            if re.search(r"%\s*(100|125|150)|\b(100|125|150)\s*%", text):
                return ReportType.TYPE_B
            return ReportType.TYPE_A

    return best_type
