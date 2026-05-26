from __future__ import annotations

import argparse
from pathlib import Path

from .processor import process_pdf_to_zip
from .rules import parse_rules_table


def main() -> int:
    parser = argparse.ArgumentParser(description="Split a PDF by company rows and return a ZIP package.")
    parser.add_argument("pdf", type=Path, help="Source PDF path")
    parser.add_argument("rules", type=Path, help="UTF-8 text file with 3 columns: company, code, page range")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="Directory for generated files")
    args = parser.parse_args()

    raw_rules = args.rules.read_text(encoding="utf-8")
    rules = parse_rules_table(raw_rules)
    zip_path = process_pdf_to_zip(args.pdf, rules, args.output_dir)
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
