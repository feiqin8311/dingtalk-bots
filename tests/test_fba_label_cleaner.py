from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]

from apps.fba_label_bot.cleaner import clean_pdf_bytes, output_file_name  # noqa: E402


class FbaLabelCleanerTests(unittest.TestCase):
    def test_output_file_name(self):
        self.assertEqual(output_file_name("FBA19N1J52YL.pdf"), "FBA19N1J52YL-已处理.pdf")
        self.assertEqual(output_file_name("FBA1.PDF"), "FBA1-已处理.pdf")
        self.assertEqual(output_file_name("FBA1-已处理.pdf"), "FBA1-已处理.pdf")

    def test_non_label_pdf_is_untouched(self):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "hello")
        data = doc.tobytes()
        doc.close()
        result = clean_pdf_bytes(data)
        self.assertEqual(result.pages, 1)
        self.assertIsNone(result.content)


if __name__ == "__main__":
    unittest.main()
