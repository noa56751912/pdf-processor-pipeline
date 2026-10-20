"""
Generator for Type-A reports (monthly payroll with overtime columns).

Hebrew rendering
----------------
ReportLab cannot render Hebrew out of the box.  Two things are required:
  1. A Unicode TTF font that includes Hebrew glyphs (Arial, DejaVuSans …).
     _register_hebrew_font() probes common OS paths and registers the first
     one it finds under the name 'HebFont' / 'HebFontBold'.
  2. The BiDi algorithm must be applied to every Hebrew string before it is
     passed to ReportLab, otherwise glyphs appear right-to-left in the wrong
     order.  _h() does this via the python-bidi library (graceful fallback
     when the library is absent).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.models import AttendanceReport
from src.generators.base_generator import BaseGenerator

logger = logging.getLogger(__name__)

_HEADER_BG  = colors.HexColor("#2E4057")
_ROW_ALT_BG = colors.HexColor("#F2F4F8")
_WARN_BG    = colors.HexColor("#FFE0E0")

# ---------------------------------------------------------------------------
# Font registration
# ---------------------------------------------------------------------------

# Search order: Windows system fonts first, then Linux/macOS paths
_FONT_CANDIDATES: list[tuple[str, str, str]] = [
    ("Arial",      "Arial Bold",
     r"C:\Windows\Fonts\arial.ttf"),
    ("Arial",      "Arial Bold",
     r"C:\Windows\Fonts\ARIAL.TTF"),
    ("DejaVuSans", "DejaVuSans",
     r"C:\Windows\Fonts\DejaVuSans.ttf"),
    ("DejaVuSans", "DejaVuSans",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("DejaVuSans", "DejaVuSans",
     "/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ("FreeSans",   "FreeSans",
     "/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
]
# Bold variants searched separately
_BOLD_CANDIDATES: list[tuple[str, str]] = [
    ("Arial Bold",       r"C:\Windows\Fonts\arialbd.ttf"),
    ("Arial Bold",       r"C:\Windows\Fonts\ARIALBD.TTF"),
    ("DejaVuSans-Bold",  r"C:\Windows\Fonts\DejaVuSans-Bold.ttf"),
    ("DejaVuSans-Bold",  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]

_HEB_FONT      = "Helvetica"       # resolved at import time
_HEB_FONT_BOLD = "Helvetica-Bold"


def _register_hebrew_font() -> tuple[str, str]:
    """Register the best available Unicode TTF; return (normal, bold) font names."""
    global _HEB_FONT, _HEB_FONT_BOLD

    normal_name: str | None = None
    bold_name:   str | None = None

    for reg_name, _bname, path in _FONT_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(reg_name, path))
            normal_name = reg_name
            logger.debug("Hebrew font registered: %s (%s)", reg_name, path)
            break
        except Exception as exc:
            logger.debug("Could not register font %s: %s", path, exc)

    for reg_name, path in _BOLD_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(reg_name, path))
            bold_name = reg_name
            break
        except Exception:
            pass

    if normal_name:
        _HEB_FONT = normal_name
    if bold_name:
        _HEB_FONT_BOLD = bold_name
    elif normal_name:
        _HEB_FONT_BOLD = normal_name   # use normal as bold fallback

    return _HEB_FONT, _HEB_FONT_BOLD


# Run once at import
_register_hebrew_font()


# ---------------------------------------------------------------------------
# BiDi helper
# ---------------------------------------------------------------------------

try:
    from bidi.algorithm import get_display as _bidi_display
    def _h(text: str) -> str:
        """Apply the Unicode BiDi algorithm so Hebrew renders left-to-right in ReportLab."""
        return _bidi_display(str(text))
except ImportError:
    logger.warning(
        "python-bidi not installed; Hebrew text may display reversed. "
        "Run: pip install python-bidi"
    )
    def _h(text: str) -> str:   # type: ignore[misc]
        return str(text)


# ---------------------------------------------------------------------------
# ReportLab styles
# ---------------------------------------------------------------------------

def _make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    normal = ParagraphStyle(
        "HebNormal",
        parent=base["Normal"],
        fontName=_HEB_FONT,
        fontSize=10,
        leading=14,
        alignment=2,   # RIGHT
    )
    title = ParagraphStyle(
        "HebTitle",
        parent=base["Title"],
        fontName=_HEB_FONT_BOLD,
        fontSize=14,
        leading=18,
        alignment=2,   # RIGHT
    )
    return {"normal": normal, "title": title}


def _base_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  _HEADER_BG),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  _HEB_FONT_BOLD),
        ("FONTSIZE",       (0, 0), (-1, 0),  9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT_BG]),
        ("FONTNAME",       (0, 1), (-1, -1), _HEB_FONT),
        ("FONTSIZE",       (0, 1), (-1, -1), 8),
        ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",          (0, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
    ])


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class GeneratorTypeA(BaseGenerator):
    def generate(self, report: AttendanceReport, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        styles = _make_styles()
        doc = SimpleDocTemplate(
            str(output_path), pagesize=A4,
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )
        story: list = []
        story.append(Paragraph(_h("דוח נוכחות סוג א׳"), styles["title"]))
        story.append(Spacer(1, 0.3*cm))
        summary_meta = [
            _h(f"שם העובד: {report.employee or '—'}"),
            _h(f"תקופה: {report.period_start} – {report.period_end}"),
        ]
        if report.total_working_days:
            summary_meta.append(_h(f'סה"כ ימי עבודה לחודש: {report.total_working_days}'))
        if report.total_monthly_hours:
            summary_meta.append(_h(f'סה"כ שעות חודשיות: {report.total_monthly_hours}'))
        if report.hourly_rate:
            summary_meta.append(_h(f'מחיר לשעה: {report.hourly_rate}'))
        if report.total_payment:
            summary_meta.append(_h(f'סה"כ לתשלום: {report.total_payment}'))
        else:
            summary_meta.append(_h(f'סה"כ שעות לתשלום: {report.total_hours}'))
        for line in summary_meta:
            story.append(Paragraph(line, styles["normal"]))
        story.append(Spacer(1, 0.5*cm))

        # Table: columns in REVERSED order so Date appears on the right (RTL simulation).
        # הפסקה (break) column is not used in Type-A and is omitted.
        # Column order RTL: תאריך | יום בשבוע | כניסה | יציאה | סה"כ | הערות
        col_headers = [_h(c) for c in [
            "הערות/חריגות", 'סה"כ שעות', "יציאה", "כניסה", "יום בשבוע", "תאריך",
        ]]
        data = [col_headers]
        for rec in report.records:
            data.append([
                "",
                rec.daily_hours,
                rec.end_time,
                rec.start_time,
                _h(rec.day_of_week),
                rec.date_text,
            ])

        tbl = Table(
            data,
            colWidths=[None, 1.8*cm, 2*cm, 2*cm, 2*cm, 2.8*cm],
            repeatRows=1,
        )
        tbl.setStyle(_base_style())
        story.append(tbl)
        doc.build(story)
