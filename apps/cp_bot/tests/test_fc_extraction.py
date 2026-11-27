#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Minimal checks for FC extraction false positives and failure wording."""

from __future__ import annotations

import unittest

from apps.cp_bot.destination_ocr import (
    _extract_fc_codes_filtered as extract_fc_codes_filtered,
    _format_destination_check_failure as format_destination_check_failure,
)


class FcExtractionTests(unittest.TestCase):
    def test_room2_address_does_not_yield_oom2(self):
        ocr = (
            "FBA 目的地： 发货地： Amazon EU SARL(UK) 10Oyster Road Room2-3026 "
            "NOTTINGHAM NG163UA England UK"
        )
        self.assertNotIn("OOM2", extract_fc_codes_filtered(ocr))
        self.assertEqual(extract_fc_codes_filtered(ocr), [])

    def test_standalone_fc_still_extracted(self):
        self.assertEqual(extract_fc_codes_filtered("目的地： EMA3 发货地： Hangzhou"), ["EMA3"])
        self.assertEqual(extract_fc_codes_filtered("LBA8/IMN1"), ["LBA8", "IMN1"])
        self.assertEqual(extract_fc_codes_filtered("ServicesLBA8/IMN1"), ["LBA8", "IMN1"])

    def test_incomplete_message_is_not_hard_mismatch(self):
        msg = format_destination_check_failure(
            "SP260721008",
            ocr_fc=None,
            ocr_fc_display="-",
            dest_ids=["EMA3"],
            fallback_detail="ADDR_PARSE_INCOMPLETE: 加载地址簿失败: timed out",
        )
        self.assertIn("无法完成目的地核对", msg)
        self.assertNotIn("目的地不一致", msg)

    def test_hard_mismatch_keeps_inconsistent_wording(self):
        msg = format_destination_check_failure(
            "SP1",
            ocr_fc="ABC1",
            ocr_fc_display="ABC1",
            dest_ids=["XYZ9"],
            fallback_detail="ADDR_HARD_MISMATCH: reason=postal; top_score=10.0; fc=XYZ9",
        )
        self.assertIn("目的地不一致", msg)


if __name__ == "__main__":
    unittest.main()
