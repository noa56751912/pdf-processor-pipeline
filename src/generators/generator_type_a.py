"""
Generator for Type-A reports (monthly payroll with overtime columns).

Table columns: Date | Clock-in | Break | Clock-out | Reg. hours | Flags
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.models import AttendanceReport
from src.generators.base_generator import BaseGenerator

_HEADER_BG  = colors.HexColor("#2E4057")
_ROW_ALT_BG = colors.HexColor("#F2F4F8")
_WARN_BG    = colors.HexColor("#FFE0E0")


def _base_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  _HEADER_BG),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0),  9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT_BG]),
        ("FONTSIZE",       (0, 1), (-1, -1), 8),
        ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
    ])


class GeneratorTypeA(BaseGenerator):
    def generate(self, report: AttendanceReport, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            str(output_path), pagesize=A4,
            leftMargin=1.5*cm, rightMargin=1.5*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )
        story = []
        story.append(Paragraph("<b>Type-A Payroll Attendance Report</b>", styles["Title"]))
        story.append(Spacer(1, 0.3*cm))
        for line in [
            f"<b>Employee:</b> {report.employee or '—'}",
            f"<b>Period:</b> {report.period_start} → {report.period_end}",
            f"<b>Total hours:</b> {report.total_hours}",
            f"<b>Records:</b> {len(report.records)}",
        ]:
            story.append(Paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 0.5*cm))

        data = [["Date", "Clock-in", "Break", "Clock-out", "Hours", "Flags"]]
        for rec in report.records:
            data.append([
                rec.date_text, rec.start_time,
                rec.break_hours or "—", rec.end_time,
                rec.daily_hours, "; ".join(rec.anomalies),
            ])

        tbl = Table(data, colWidths=[2.8*cm, 2*cm, 1.8*cm, 2*cm, 1.8*cm, None], repeatRows=1)
        tbl.setStyle(_base_style())
        for idx, rec in enumerate(report.records, start=1):
            if rec.anomalies:
                tbl.setStyle(TableStyle([("BACKGROUND", (0, idx), (-1, idx), _WARN_BG)]))
        story.append(tbl)
        doc.build(story)
