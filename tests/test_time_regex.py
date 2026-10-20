import unittest

from src.parsers import parser_type_a, parser_type_b

# Real lines from samples/a_r_25.pdf, and what should be read as times
CASES = [
    ("‎‘wan on 01/02/2023‏ גונן 08:00 16:00 00:30 7.50 7.50 0.00", ["08:00", "16:00", "00:30"]),
    ("Sa posh[ pow os ee 77xN | 100%| 125%| 150%|שבת", []),
    ("15 07:30 110.50 110.50 0.00 0.00 0.00 .", ["07:30"]),
    ("0800 1600 0030", ["0800", "1600", "0030"]),  # OCR lost the colons
    ("end at 16:00.", ["16:00"]),
]


class TimeRegexTests(unittest.TestCase):
    def test_both_parsers(self):
        for module in (parser_type_a, parser_type_b):
            for line, expected in CASES:
                with self.subTest(parser=module.__name__, line=line):
                    self.assertEqual(module._TIME_RE.findall(line), expected)


if __name__ == "__main__":
    unittest.main()
