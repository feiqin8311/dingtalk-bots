from __future__ import annotations

import re
import zipfile
from collections import OrderedDict
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .rules import SplitRule


def process_pdf_to_zip(source_pdf: str | Path, rules: list[SplitRule], output_root: str | Path) -> Path:
    source_path = Path(source_pdf)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(source_path))
    total_pages = len(reader.pages)
    grouped_pages = _collect_company_pages(rules, total_pages)

    for company_name, zero_based_pages in grouped_pages.items():
        writer = PdfWriter()
        for page_index in zero_based_pages:
            writer.add_page(reader.pages[page_index])
        output_name = _build_output_pdf_name(source_path.stem, company_name)
        output_pdf = output_root / output_name
        with output_pdf.open("wb") as fh:
            writer.write(fh)

    zip_path = output_root / f"{sanitize_filename(source_path.stem)}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(output_root.rglob("*.pdf")):
            zf.write(file_path, file_path.relative_to(output_root))
    return zip_path


def _collect_company_pages(rules: list[SplitRule], total_pages: int) -> OrderedDict[str, list[int]]:
    grouped: OrderedDict[str, list[int]] = OrderedDict()
    for rule in rules:
        page_indexes = _expand_page_spec(rule.page_spec, total_pages, rule.line_number)
        grouped.setdefault(rule.company_name, [])
        for page_index in page_indexes:
            if page_index not in grouped[rule.company_name]:
                grouped[rule.company_name].append(page_index)
    return grouped


def _expand_page_spec(page_spec: str, total_pages: int, line_number: int) -> list[int]:
    result: list[int] = []
    chunks = [chunk.strip() for chunk in page_spec.split(",") if chunk.strip()]
    if not chunks:
        raise ValueError(f"Invalid page range at line {line_number}: empty page range")

    for chunk in chunks:
        if "-" in chunk:
            start_str, end_str = [part.strip() for part in chunk.split("-", 1)]
            if not start_str.isdigit() or not end_str.isdigit():
                raise ValueError(f"Invalid page range at line {line_number}: {chunk}")
            start = int(start_str)
            end = int(end_str)
            if start > end:
                raise ValueError(f"Invalid page range at line {line_number}: {chunk}")
            if start < 1 or end > total_pages:
                raise ValueError(
                    f"Invalid page range at line {line_number}: {chunk} is outside 1-{total_pages}"
                )
            values = list(range(start, end + 1))
        else:
            if not chunk.isdigit():
                raise ValueError(f"Invalid page range at line {line_number}: {chunk}")
            values = [int(chunk)]

        for value in values:
            if value < 1 or value > total_pages:
                raise ValueError(
                    f"Invalid page number at line {line_number}: {value} is outside 1-{total_pages}"
                )
            result.append(value - 1)
    return result


def sanitize_filename(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip()
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized or "unnamed"


def _build_output_pdf_name(source_stem: str, company_name: str) -> str:
    sanitized_source = sanitize_filename(source_stem)
    sanitized_company = sanitize_filename(company_name)
    if company_name.strip() == "仓库发":
        return f"{sanitized_source}-{sanitized_company}.pdf"
    return f"{sanitized_source}-{sanitized_company}-一式两份.pdf"
