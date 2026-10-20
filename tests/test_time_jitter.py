import random
import unittest

from src.durations import parse_hours
from src.models import AttendanceRecord
from src.time_jitter import MAX_MINUTES, jitter_record

# Each of start and end moves at most MAX_MINUTES, so the day's hours
# can change by at most twice that (plus rounding to two decimals).
MAX_CHANGE = 2 * MAX_MINUTES / 60 + 0.01


class ParseHoursTests(unittest.TestCase):
    def test_both_formats(self):
        self.assertEqual(parse_hours("00:30"), 0.5)
        self.assertEqual(parse_hours("0.50"), 0.5)
        self.assertEqual(parse_hours("1:45"), 1.75)

    def test_empty_or_invalid(self):
        self.assertIsNone(parse_hours(""))
        self.assertIsNone(parse_hours("abc"))


class JitterTests(unittest.TestCase):
    def setUp(self):
        random.seed(0)

    def assert_hours_close(self, start, end, brk, expected):
        rec = AttendanceRecord(date_text="01/01/2023", start_time=start,
                               end_time=end, break_hours=brk)
        for _ in range(200):
            daily = float(jitter_record(rec).daily_hours)
            self.assertAlmostEqual(daily, expected, delta=MAX_CHANGE)

    def test_day_shift_deducts_hhmm_break(self):
        self.assert_hours_close("08:00", "16:00", "00:30", 7.5)

    def test_day_shift_deducts_decimal_break(self):
        self.assert_hours_close("08:00", "16:00", "0.50", 7.5)

    def test_overnight_shift_keeps_its_length(self):
        self.assert_hours_close("20:00", "08:00", "", 12.0)


if __name__ == "__main__":
    unittest.main()
