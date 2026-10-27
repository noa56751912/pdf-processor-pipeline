"""
Table-aware OCR for scanned pages.

Full-page OCR reads a ruled table poorly: it merges neighbouring cells, drops
decimal points and confuses similar digits (8/3, 1/4).  This module instead

1. finds the table's vertical ruling lines (long unbroken runs of ink),
2. finds its rows (text bands in the rightmost column, which every row fills),
3. reads every cell on its own, with a character whitelist chosen from the
   column header (date, time, hours), and
4. fixes single misread digits so that clock-out - clock-in == hours.

The result is plain text in the layout full-page OCR would give, one table
row per line ("| date | day | in | out | hours |"), with the text above the
table first, so the parsers need no changes.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from PIL import Image

logger = logging.getLogger(__name__)

_INK = 140              # grey level below which a pixel counts as ink
_LINE_MERGE_PX = 15     # ruling lines closer than this are one line
_CELL_INSET_PX = 10     # stay clear of the ruling lines when cropping a cell
_CELL_SCALE = 2         # Tesseract reads these digits best at twice the size

_WHITELISTS = {
    "date": "0123456789/",
    "time": "0123456789:",
    "hours": "0123456789.",
}
_FORMATS = {
    "date": re.compile(r"^\d{1,2}/\d{1,2}/(\d{2}|\d{4})$"),
    "time": re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$"),
    "hours": re.compile(r"^\d{1,2}\.\d{2}$"),
}
# Header word stems -> column kind, checked in this order.  Stems, because OCR
# often misreads a title's last letter ("תארין" for "תאריך").
_HEADER_KINDS = [
    ("תאר", "date"),
    ("כניס", "time"),
    ("יציא", "time"),
    ("שעות", "hours"),
    ("יום", "day"),
]
# Digits Tesseract mistakes for one another on these scans
_CONFUSABLE = {
    "0": "689", "1": "47", "3": "58", "4": "1", "5": "36",
    "6": "058", "7": "1", "8": "036", "9": "0",
}


@dataclass
class _Column:
    x0: int
    x1: int
    kind: str = "text"


class TableOCR:
    """
    Reads the ruled table on a scanned page cell by cell.

    Parameters
    ----------
    ocr_engine : TesseractOCREngine
        Used for every Tesseract call, so executable discovery stays in one place.
    lang : str
        Language for header and text cells (default ``'heb+eng'``).
    """

    def __init__(self, ocr_engine, lang: str = "heb+eng") -> None:
        self._ocr = ocr_engine
        self.lang = lang

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_page(self, image: Image.Image) -> str | None:
        """Return the page as text, or None when no ruled table is found."""
        gray = self._deskew(image.convert("L"))
        ink = gray.point(lambda v: 1 if v < _INK else 0)

        xs = self._vertical_lines(ink)
        if len(xs) < 3:
            logger.info("Table OCR: no ruled table found (%d lines).", len(xs))
            return None
        top, bottom = self._table_span(ink, xs)
        columns = [_Column(a, b) for a, b in zip(xs, xs[1:])]

        bands = self._text_bands(ink, columns[-1], top, bottom)
        first = self._first_data_band(gray, columns[-1], bands)
        if first is None or first == 0:
            logger.info("Table OCR: no header row followed by dated rows.")
            return None
        header, data_bands = bands[first - 1], bands[first:]
        logger.debug(
            "Table OCR: lines at x=%s, table y=%d..%d, header at y=%d, %d data bands.",
            xs, top, bottom, header[0], len(data_bands),
        )

        rows_top = self._midpoint(header, data_bands[0])
        # A two-line column title can rise one text line above the date title
        header_top = max(header[0] - 60, bands[first - 2][1] if first >= 2 else top)
        self._classify_columns(gray, columns, header_top, rows_top)
        edges = self._row_edges(data_bands, rows_top, bottom)
        top = header_top

        spans = list(zip(edges, edges[1:]))
        rows = [[""] * len(columns) for _ in spans]
        for c, col in enumerate(columns):
            for r, text in self._read_column(gray, col, spans).items():
                rows[r][c] = text
        self._fill_dates(rows, columns)
        self._reconcile_times(rows, columns)
        self._blank_invalid(rows, columns)

        above = self._ocr.extract_text(self._scaled(gray.crop((0, 0, gray.width, top))), self.lang)
        # Hebrew tables read right to left: emit the rightmost column first
        lines = ["| " + " | ".join(reversed(row)) + " |" for row in rows]
        logger.info(
            "Table OCR: %d columns (%s), %d rows.",
            len(columns), ", ".join(c.kind for c in reversed(columns)), len(rows),
        )
        return above + "\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Finding the table
    # ------------------------------------------------------------------

    @staticmethod
    def _deskew(gray: Image.Image) -> Image.Image:
        """
        Straighten a slightly rotated scan.  The right angle is the one at which
        the vertical ruling lines are sharpest: the column-wise ink profile then
        has the tallest peaks (largest sum of squares).
        """
        small = gray.resize((gray.width // 4, gray.height // 4))

        def sharpness(angle: float) -> int:
            turned = small.rotate(angle, resample=Image.BILINEAR, fillcolor=255)
            ink = turned.point(lambda v: 255 if v < _INK else 0)
            profile = ink.resize((ink.width, 1), Image.BOX).getdata()
            return sum(v * v for v in profile)

        angles = [a / 10 for a in range(-20, 21)]          # -2.0° .. +2.0°
        best = max(angles, key=sharpness)
        if best == 0:
            return gray
        logger.debug("Table OCR: deskewing by %.1f degrees.", best)
        return gray.rotate(best, resample=Image.BICUBIC, fillcolor=255)

    @staticmethod
    def _vertical_lines(ink: Image.Image) -> list[int]:
        """x positions whose longest unbroken ink run is long enough to be a ruling line."""
        w, h = ink.size
        data = ink.tobytes()
        best = [0] * w
        run = [0] * w
        for y in range(h):
            row = data[y * w:(y + 1) * w]
            for x in range(w):
                if row[x]:
                    run[x] += 1
                    if run[x] > best[x]:
                        best[x] = run[x]
                else:
                    run[x] = 0

        min_run = h // 12
        lines: list[int] = []
        start = None
        for x, length in enumerate(best + [0]):
            if length >= min_run and start is None:
                start = x
            elif length < min_run and start is not None:
                centre = (start + x - 1) // 2
                if lines and centre - lines[-1] < _LINE_MERGE_PX:
                    lines[-1] = (lines[-1] + centre) // 2
                else:
                    lines.append(centre)
                start = None
        return lines

    @staticmethod
    def _table_span(ink: Image.Image, xs: list[int]) -> tuple[int, int]:
        """Top and bottom of the table: the rows where most ruling lines have ink."""
        w, h = ink.size
        data = ink.tobytes()
        need = len(xs) // 2 + 1
        inside = []
        for y in range(h):
            row = data[y * w:(y + 1) * w]
            hits = sum(1 for x in xs if any(row[max(x - 3, 0):x + 4]))
            inside.append(hits >= need)
        # Group into blocks, bridging gaps in the scanned lines up to about a row
        blocks: list[list[int]] = []
        for y, on in enumerate(inside):
            if not on:
                continue
            if blocks and y - blocks[-1][1] <= 60:
                blocks[-1][1] = y
            else:
                blocks.append([y, y])
        if not blocks:
            return 0, h
        top, bottom = max(blocks, key=lambda b: b[1] - b[0])
        return top, bottom

    @staticmethod
    def _text_bands(ink: Image.Image, col: _Column, top: int, bottom: int) -> list[tuple[int, int]]:
        """Bands of text inside *col*, skipping full-width ruling lines."""
        x0, x1 = col.x0 + _CELL_INSET_PX, col.x1 - _CELL_INSET_PX
        w = x1 - x0
        data = ink.crop((x0, top, x1, bottom)).tobytes()
        bands: list[tuple[int, int]] = []
        start = None
        for y in range(bottom - top + 1):
            n = sum(data[y * w:(y + 1) * w]) if y < bottom - top else 0
            on = 3 <= n < w * 0.8
            if on and start is None:
                start = y
            elif not on and start is not None:
                if y - start >= 12:          # taller than a ruling line
                    bands.append((top + start, top + y))
                start = None
        return bands

    def _first_data_band(self, gray, col: _Column, bands) -> int | None:
        """
        Index of the first band whose cell in *col* reads like a date.  In a
        right-to-left table the rightmost column holds the row's date.
        """
        for i, (y0, y1) in enumerate(bands):
            words = self._ocr.extract_words(
                self._scaled(self._crop(gray, col, y0 - 6, y1 + 6)), "eng", _WHITELISTS["date"]
            )
            text = "".join(word for _, word in words)
            if "/" in text and sum(ch.isdigit() for ch in text) >= 3:
                return i
        return None

    def _classify_columns(self, gray, columns: list[_Column], top: int, rows_top: int) -> None:
        for col in columns:
            title = self._ocr.extract_text(self._crop(gray, col, top, rows_top), self.lang)
            col.kind = next((kind for word, kind in _HEADER_KINDS if word in title), "text")
        # Rows were found by the dates in the rightmost column, so that is the date column
        if not any(c.kind == "date" for c in columns):
            columns[-1].kind = "date"

    @staticmethod
    def _midpoint(a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] + a[1] + b[0] + b[1]) // 4

    def _row_edges(self, bands, rows_top: int, bottom: int) -> list[int]:
        """Row boundaries halfway between neighbouring text bands."""
        inner = [self._midpoint(a, b) for a, b in zip(bands, bands[1:])]
        if inner:
            pitch = (inner[-1] - inner[0]) // max(len(inner) - 1, 1)
        else:
            pitch = bands[0][1] - bands[0][0] + 24
        last = min(bottom, (bands[-1][0] + bands[-1][1]) // 2 + pitch // 2)
        return [rows_top] + inner + [last]

    # ------------------------------------------------------------------
    # Reading cells
    # ------------------------------------------------------------------

    def _read_column(self, gray, col: _Column, spans) -> dict[int, str]:
        """
        Read every non-empty cell of *col* in a single OCR call: the cells are
        stacked one under another on a white sheet, and each word is matched
        back to its cell by height.  One call per column instead of one per
        cell makes a page about ten times faster.
        """
        crops: dict[int, Image.Image] = {}
        for r, (y0, y1) in enumerate(spans):
            # Look a little above the row too: digits often sit high in their cell
            box = self._tight_box(gray, col, y0 - 25, y1 + 5)
            if box is not None:
                crops[r] = self._scaled(gray.crop(box))
        if not crops:
            return {}

        slot = max(img.height for img in crops.values()) + 30
        sheet = Image.new("L", (max(img.width for img in crops.values()), slot * len(crops)), 255)
        order = list(crops)
        for i, r in enumerate(order):
            sheet.paste(crops[r], (0, i * slot))

        whitelist = _WHITELISTS.get(col.kind, "")
        lang = "eng" if whitelist else self.lang
        words: dict[int, list[str]] = {}
        for y, word in self._ocr.extract_words(sheet, lang, whitelist):
            i = min(y // slot, len(order) - 1)
            words.setdefault(order[i], []).append(word)
        # Kept raw, even if malformed: the fixes below may still repair it
        sep = " " if not whitelist else ""
        return {r: sep.join(ws) for r, ws in words.items()}

    @staticmethod
    def _tight_box(gray, col: _Column, y0: int, y1: int):
        """Shrink the cell to its tallest band of ink rows, or None if it is empty."""
        x0, x1 = col.x0 + _CELL_INSET_PX, col.x1 - _CELL_INSET_PX
        w = x1 - x0
        data = gray.crop((x0, y0, x1, y1)).point(lambda v: 1 if v < _INK else 0).tobytes()
        best, start = None, None
        for y in range(y1 - y0 + 1):
            n = sum(data[y * w:(y + 1) * w]) if y < y1 - y0 else 0
            on = 2 <= n < w * 0.6
            if on and start is None:
                start = y
            elif not on and start is not None:
                if best is None or y - start > best[1] - best[0]:
                    best = (start, y)
                start = None
        if best is None or best[1] - best[0] < 12:
            return None
        return (x0, y0 + best[0] - 6, x1, y0 + best[1] + 6)

    @staticmethod
    def _crop(gray, col: _Column, y0: int, y1: int):
        return gray.crop((col.x0 + _CELL_INSET_PX, y0, col.x1 - _CELL_INSET_PX, y1))

    @staticmethod
    def _scaled(img: Image.Image) -> Image.Image:
        big = img.resize((img.width * _CELL_SCALE, img.height * _CELL_SCALE), Image.LANCZOS)
        padded = Image.new("L", (big.width + 40, big.height + 40), 255)
        padded.paste(big, (20, 20))
        return padded

    # ------------------------------------------------------------------
    # Fixing what OCR got wrong, using the table itself
    # ------------------------------------------------------------------

    @staticmethod
    def _fill_dates(rows: list[list[str]], columns: list[_Column]) -> None:
        """
        A timesheet lists days in order.  When two dates k rows apart are also
        k days apart, the rows between them must be the days between them.
        This fills dates OCR could not read and replaces ones it misread
        ("13/1/23" between 18/1 and 20/1).
        """
        idx = next((i for i, c in enumerate(columns) if c.kind == "date"), None)
        if idx is None:
            return

        def parse(text: str) -> date | None:
            for fmt in ("%d/%m/%y", "%d/%m/%Y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    pass
            return None

        dates = [parse(row[idx]) for row in rows]
        known = [i for i, d in enumerate(dates) if d]
        # Pairs of known dates that agree with each other, nearest first
        for a in known:
            for b in known:
                if b - a < 2 or dates[b] - dates[a] != timedelta(days=b - a):
                    continue
                for i in range(a + 1, b):
                    expected = dates[a] + timedelta(days=i - a)
                    if dates[i] != expected:
                        logger.debug("Table OCR: date %r -> %s from its neighbours.",
                                     rows[i][idx], expected)
                        rows[i][idx] = f"{expected.day}/{expected.month}/{expected:%y}"
                        dates[i] = expected
                break

    @staticmethod
    def _reconcile_times(rows: list[list[str]], columns: list[_Column]) -> None:
        """
        Where clock-out - clock-in disagrees with the hours column, change
        misread digits until they agree: first one digit in one cell, then one
        digit in each of two cells.  When several fixes work, keep the one
        whose new values look most like the rest of their columns.
        """
        times = [i for i, c in enumerate(columns) if c.kind == "time"]
        hours = next((i for i, c in enumerate(columns) if c.kind == "hours"), None)
        if len(times) != 2 or hours is None:
            return
        # Right-to-left table: the clock-in column is to the right of clock-out
        out_i, in_i = sorted(times)
        cells = (in_i, out_i, hours)

        def as_hours(col: int, text: str) -> float | None:
            if col == hours:
                return float(text) if _FORMATS["hours"].match(text) else None
            if not _FORMATS["time"].match(text):
                return None
            h, m = text.split(":")
            return int(h) + int(m) / 60

        def consistent(values: dict[int, str]) -> bool:
            start, end, worked = (as_hours(c, values[c]) for c in cells)
            if None in (start, end, worked):
                return False
            return abs((end - start) % 24 - worked) <= 0.011

        def variants(text: str):
            """Every text one OCR slip away: a confused digit, or a dropped one."""
            for i, ch in enumerate(text):
                for alt in _CONFUSABLE.get(ch, ""):
                    yield text[:i] + alt + text[i + 1:]
            for i in range(len(text) + 1):
                for digit in "0123456789":
                    yield text[:i] + digit + text[i:]

        # The typical value of each cell, to choose between competing fixes
        typical = {}
        for c in cells:
            seen = sorted(v for row in rows if (v := as_hours(c, row[c])) is not None)
            typical[c] = seen[len(seen) // 2] if seen else 0.0

        def oddness(fix: dict[int, str]) -> float:
            return sum(abs(as_hours(c, v) - typical[c]) for c, v in fix.items())

        for row in rows:
            values = {c: row[c] for c in cells}
            if not all(values.values()) or consistent(values):
                continue
            singles = [{c: v} for c in cells for v in variants(values[c])]
            pairs = [{a: va, b: vb}
                     for a, b in ((cells[0], cells[1]), (cells[0], cells[2]), (cells[1], cells[2]))
                     for va in variants(values[a]) for vb in variants(values[b])]
            for candidates in (singles, pairs):
                fixes = [f for f in candidates if consistent({**values, **f})]
                if fixes:
                    best = min(fixes, key=oddness)
                    logger.debug("Table OCR: %s -> %s so the row adds up.",
                                 {c: values[c] for c in best}, best)
                    for c, v in best.items():
                        row[c] = v
                    break

    @staticmethod
    def _blank_invalid(rows: list[list[str]], columns: list[_Column]) -> None:
        """Clear cells still not in their column's format: stray marks, not data."""
        for row in rows:
            for i, col in enumerate(columns):
                fmt = _FORMATS.get(col.kind)
                if fmt is not None and not fmt.match(row[i]):
                    row[i] = ""
