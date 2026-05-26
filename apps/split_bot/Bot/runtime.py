from __future__ import annotations

import asyncio
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


ROOT_DIR = _find_repo_root(Path(__file__).resolve().parent)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pdf_zip_bot import process_pdf_to_zip
from pdf_zip_bot.rules import SplitRule
from shared.dedup import MessageDeduplicator


@dataclass(frozen=True)
class PreparedArchive:
    file_name: str
    content_bytes: bytes


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


async def run_split_job(source_pdf: Path, rules: list[SplitRule], job_root: Path) -> PreparedArchive:
    output_root = job_root / "output"
    try:
        zip_path = await asyncio.get_running_loop().run_in_executor(
            None,
            process_pdf_to_zip,
            source_pdf,
            rules,
            output_root,
        )
        return PreparedArchive(file_name=zip_path.name, content_bytes=zip_path.read_bytes())
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


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
