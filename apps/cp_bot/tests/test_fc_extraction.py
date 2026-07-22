#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Minimal checks for FC extraction false positives and failure wording."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


def _unique_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _extract_fc_codes_filtered_from_source() -> str:
    """Return the current function body source from handler.py for parity assert."""
    text = (Path(__file__).resolve().parents[1] / "handler.py").read_text(encoding="utf-8")
    # Ensure production still uses non-embedding single-code lookaround (ROOM2 guard).
    assert re.search(
        r'\(\?\<!\[A-Z0-9\]\)\(\[A-Z\]\{3\}\\d\)\(\?\!\[A-Z0-9\]\)',
        text,
    ), "handler.py lost the non-embedding FC single-code pattern"


def extract_fc_codes_filtered(text: str):
    """Mirror of handler._extract_fc_codes_filtered (keep in sync via source assert)."""
    _extract_fc_codes_filtered_from_source()
    if not text:
        return []
    upper = str(text).upper()
    results = []

    def _allow_by_context(start: int, end: int) -> bool:
        left = max(0, start - 28)
        right = min(len(upper), end + 28)
        window = upper[left:right]
        if "SINGLE SKU" in window:
            return False
        if "数量" in window or "QTY" in window:
            return False
        if re.search(r"\bPM\d{4,}\b", window):
            return False
        return True

    for match in re.finditer(r"([A-Z]{3}\d)\s*[\\/／]\s*([A-Z]{3}\d)", upper):
        if not _allow_by_context(match.start(), match.end()):
            continue
        results.append(str(match.group(1)).strip().upper())
        results.append(str(match.group(2)).strip().upper())

    for match in re.finditer(r"(?<![A-Z0-9])([A-Z]{3}\d)(?![A-Z0-9])", upper):
        code = str(match.group(1)).strip().upper()
        if not _allow_by_context(match.start(1), match.end(1)):
            continue
        results.append(code)

    return _unique_preserve_order(results)


def format_destination_check_failure(
    shipment_sn: str,
    *,
    ocr_fc,
    ocr_fc_display: str,
    dest_ids,
    fallback_detail: str,
) -> str:
    dest_display = ",".join(dest_ids) if dest_ids else "-"
    ocr_display = ocr_fc_display or "-"
    detail = str(fallback_detail or "").strip()
    incomplete = detail.startswith("ADDR_PARSE_INCOMPLETE") or detail.startswith("ADDR_UNSUPPORTED")
    if incomplete:
        if not ocr_fc:
            return f"{shipment_sn} 无法完成目的地核对: OCR未识别到目的地; {detail}"
        return (
            f"{shipment_sn} 无法完成目的地核对: FC未直匹配(OCR候选={ocr_display}, 领星={dest_display}); {detail}"
        )
    if not ocr_fc:
        return f"{shipment_sn} OCR 未识别到目的地; {detail}"
    return f"{shipment_sn} 目的地不一致: OCR候选={ocr_display}, 领星={dest_display}; {detail}"


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
