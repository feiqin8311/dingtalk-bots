#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / 'pdf_zip_bot').is_dir():
            return candidate
    raise RuntimeError('Could not locate repo root containing pdf_zip_bot')


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pdf_zip_bot import parse_rules_table, process_pdf_to_zip  # noqa: E402


def run(source_pdf: str | Path, rules_file: str | Path, output_dir: str | Path) -> Path:
    source_pdf = Path(source_pdf)
    rules_file = Path(rules_file)
    output_dir = Path(output_dir)
    rules_text = rules_file.read_text(encoding='utf-8')
    rules = parse_rules_table(rules_text)
    return process_pdf_to_zip(source_pdf, rules, output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description='Split a PDF by company/page rules and package the results as a ZIP.')
    parser.add_argument('source_pdf', type=Path, help='Path to the original PDF')
    parser.add_argument('rules_file', type=Path, help='UTF-8 rules file: company, code, page range')
    parser.add_argument('--output-dir', type=Path, default=Path('skill-output'), help='Directory for generated PDFs and ZIP')
    args = parser.parse_args()

    zip_path = run(args.source_pdf, args.rules_file, args.output_dir)
    print(zip_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
