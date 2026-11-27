"""OCR destination extraction and result text for shipment checks."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

def _unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _extract_ocr_text(result: Dict[str, Any]) -> str:
    data = result.get("data") or result.get("Data") or result.get("body") or result
    if isinstance(data, dict):
        content = data.get("content") or data.get("Content")
        if content:
            return str(content)
        for key in ("prism_wordsInfo", "prism_words_info", "wordsInfo", "words_info"):
            words_info = data.get(key)
            if isinstance(words_info, list):
                words = []
                for item in words_info:
                    if not isinstance(item, dict):
                        continue
                    word = item.get("word") or item.get("words") or item.get("text") or item.get("content")
                    if word:
                        words.append(str(word))
                if words:
                    return "\n".join(words)
    return ""


def _extract_fc_code(text: str) -> Optional[str]:
    if not text:
        return None
    upper = text.upper()
    patterns = [
        r"FBA[:\s]*([A-Z]{3}\d)",
        r"目的地[:\s]*([A-Z]{3}\d)",
        r"\b([A-Z]{3}\d)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, upper)
        if match:
            return match.group(1)
    return None


def _extract_fc_codes(text: str) -> List[str]:
    if not text:
        return []
    upper = str(text).upper()
    matches = re.findall(r"\b([A-Z]{3}\d)\b", upper)
    return _unique_preserve_order([str(item).strip().upper() for item in matches if str(item).strip()])


def _extract_fc_codes_filtered(text: str) -> List[str]:
    if not text:
        return []
    upper = str(text).upper()
    results: List[str] = []

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

    # Capture pair forms first, e.g. "LBA8/IMN1" (including connected text like ServicesLBA8/IMN1).
    for match in re.finditer(r"([A-Z]{3}\d)\s*[\\/／]\s*([A-Z]{3}\d)", upper):
        if not _allow_by_context(match.start(), match.end()):
            continue
        results.append(str(match.group(1)).strip().upper())
        results.append(str(match.group(2)).strip().upper())

    # Single codes must not be embedded in longer alphanumerics.
    # Blocks false positives like ROOM2 -> OOM2; pair form above still covers ServicesLBA8/IMN1.
    for match in re.finditer(r"(?<![A-Z0-9])([A-Z]{3}\d)(?![A-Z0-9])", upper):
        code = str(match.group(1)).strip().upper()
        if not _allow_by_context(match.start(1), match.end(1)):
            continue
        results.append(code)

    return _unique_preserve_order(results)


def _format_destination_check_failure(
    shipment_sn: str,
    *,
    ocr_fc: Optional[str],
    ocr_fc_display: str,
    dest_ids: List[str],
    fallback_detail: str,
) -> str:
    """Prefer 'unable to verify' when address-book/parse is incomplete; reserve 'mismatch' for real rejects."""
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
