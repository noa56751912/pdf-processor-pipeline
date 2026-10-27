import unittest

from src.parsers.parser_type_a import ParserTypeA

# The summary block of samples/n_r_10_n.pdf, as the table OCR reads it
LINES = [
    'סה:"כ ימי עבודה לחודש \\ | .21',
    'סה:"כ שעות חודשיות 63.02',
    '\\ מחיר לשעה | | 32.35 ₪',
    'סה"כ לתשלום . 2,038.59',
]


class SummaryTests(unittest.TestCase):
    def test_reads_all_four_fields(self):
        summary = ParserTypeA()._extract_summary(LINES)
        self.assertEqual(summary, {
            "total_working_days": "21",
            "total_monthly_hours": "63.02",
            "hourly_rate": "32.35",
            "total_payment": "2,038.59",
        })


if __name__ == "__main__":
    unittest.main()
