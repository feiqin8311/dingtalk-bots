from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent.parent
for path in (str(APP_DIR), str(ROOT_DIR), str(ROOT_DIR / "apps" / "split_bot")):
    if path not in sys.path:
        sys.path.insert(0, path)

from shared.dedup import MessageDeduplicator  # noqa: E402


def collect_download_codes(payload: Any) -> list[str]:
    found: list[str] = []
    _walk_download_codes(payload, found)
    deduped: list[str] = []
    seen: set[str] = set()
    for code in found:
        if code and code not in seen:
            deduped.append(code)
            seen.add(code)
    return deduped


def collect_file_names_by_download_code(payload: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    _walk_file_names(payload, found)
    return found


def _walk_download_codes(value: Any, found: list[str]) -> None:
    if isinstance(value, dict):
        download_code = value.get("downloadCode")
        if isinstance(download_code, str):
            found.append(download_code)
        for nested in value.values():
            _walk_download_codes(nested, found)
    elif isinstance(value, list):
        for item in value:
            _walk_download_codes(item, found)


def _walk_file_names(value: Any, found: dict[str, str]) -> None:
    if isinstance(value, dict):
        download_code = value.get("downloadCode")
        file_name = value.get("fileName") or value.get("filename") or value.get("file_name")
        if isinstance(download_code, str) and isinstance(file_name, str) and file_name.strip():
            found[download_code] = file_name.strip()
        for nested in value.values():
            _walk_file_names(nested, found)
    elif isinstance(value, list):
        for item in value:
            _walk_file_names(item, found)


__all__ = [
    "MessageDeduplicator",
    "collect_download_codes",
    "collect_file_names_by_download_code",
]
