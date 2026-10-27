import shutil
import unittest
from pathlib import Path

from src.readers.table_ocr import TableOCR, _Column

# A right-to-left timesheet: hours, clock-out, clock-in, date (left to right)
COLUMNS = [_Column(0, 1, "hours"), _Column(1, 2, "time"),
           _Column(2, 3, "time"), _Column(3, 4, "date")]
HOURS, OUT, IN, DATE = range(4)


def row(date="", t_in="", t_out="", hours=""):
    cells = [""] * 4
    cells[DATE], cells[IN], cells[OUT], cells[HOURS] = date, t_in, t_out, hours
    return cells


class FillDatesTests(unittest.TestCase):
    def test_fills_unread_and_replaces_misread_dates(self):
        rows = [row("18/1/23"), row("13/1/23"), row("20/1/23"), row(""), row(""), row("23/1/23")]
        TableOCR._fill_dates(rows, COLUMNS)
        self.assertEqual([r[DATE] for r in rows],
                         ["18/1/23", "19/1/23", "20/1/23", "21/1/23", "22/1/23", "23/1/23"])

    def test_leaves_dates_alone_when_neighbours_disagree(self):
        rows = [row("1/1/23"), row(""), row("9/1/23")]
        TableOCR._fill_dates(rows, COLUMNS)
        self.assertEqual(rows[1][DATE], "")


class ReconcileTimesTests(unittest.TestCase):
    def reconcile(self, *bad_rows):
        # Typical rows, so competing fixes can be judged against their columns
        rows = [row("", "8:01", "11:03", "3.03") for _ in range(5)] + list(bad_rows)
        TableOCR._reconcile_times(rows, COLUMNS)
        return rows[5:]

    def test_fixes_a_confused_digit(self):
        fixed, = self.reconcile(row("", "3:04", "11:01", "2.95"))
        self.assertEqual(fixed[IN], "8:04")

    def test_fixes_a_dropped_digit(self):
        fixed, = self.reconcile(row("", ":01", "11:03", "3.03"))
        self.assertEqual(fixed[IN], "8:01")

    def test_fixes_two_cells_in_one_row(self):
        fixed, = self.reconcile(row("", "3:02", "41:01", "2.98"))
        self.assertEqual((fixed[IN], fixed[OUT]), ("8:02", "11:01"))

    def test_prefers_the_fix_that_fits_its_column(self):
        # Either clock-in is 8:00 or hours are 8.17; clock-ins are around 8:00
        fixed, = self.reconcile(row("", "3:00", "11:10", "3.17"))
        self.assertEqual((fixed[IN], fixed[HOURS]), ("8:00", "3.17"))

    def test_leaves_a_consistent_row_alone(self):
        fixed, = self.reconcile(row("", "8:04", "10:57", "2.88"))
        self.assertEqual(fixed, row("", "8:04", "10:57", "2.88"))


SAMPLE = Path(__file__).parent.parent / "samples" / "n_r_10_n.pdf"
TESSERACT = shutil.which("tesseract") or Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()

# Hand transcription of the work days in samples/n_r_10_n.pdf: day -> (in, out, hours)
TRUTH = {1: ("8:01", "11:05", "3.07"), 2: ("8:03", "11:03", "3.00"),
         3: ("8:04", "10:57", "2.88"), 4: ("8:01", "10:59", "2.97"),
         8: ("8:02", "11:03", "3.02"), 9: ("8:00", "10:57", "2.95"),
         10: ("8:03", "11:01", "2.97"), 11: ("8:00", "11:02", "3.03"),
         15: ("8:04", "11:01", "2.95"), 16: ("8:02", "11:03", "3.02"),
         17: ("8:00", "11:01", "3.02"), 18: ("8:01", "11:02", "3.02"),
         19: ("8:06", "11:02", "2.93"), 22: ("8:02", "11:03", "3.02"),
         23: ("8:10", "11:12", "3.03"), 24: ("8:01", "11:04", "3.05"),
         25: ("8:06", "11:03", "2.95"), 26: ("8:02", "11:00", "2.97"),
         29: ("8:01", "11:03", "3.03"), 30: ("8:02", "11:01", "2.98"),
         31: ("8:00", "11:10", "3.17")}


@unittest.skipUnless(TESSERACT, "Tesseract is not installed")
class ScannedSampleTests(unittest.TestCase):
    """Reads the real scanned sample end to end (about 15 seconds)."""

    def test_every_row_matches_the_source(self):
        from src.readers.pdf_reader import PDFReader

        text = PDFReader(read_tables=True).read(SAMPLE)
        rows = [line for line in text.splitlines() if line.startswith("| ")]
        self.assertEqual(len(rows), 31)
        for day, line in enumerate(rows, start=1):
            # "| date | day | in | out | hours | notes |" -> keep empty cells
            cells = [c.strip() for c in line.strip()[1:-1].split("|")]
            with self.subTest(day=day):
                self.assertEqual((cells[0],) + tuple(cells[2:5]),
                                 (f"{day}/1/23",) + TRUTH.get(day, ("", "", "")))


if __name__ == "__main__":
    unittest.main()
