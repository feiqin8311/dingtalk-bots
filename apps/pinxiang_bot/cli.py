#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本地跑通拼箱：python -m cli 发货单.xlsx [--out-dir DIR]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from amazon_export import create_amazon_workbook  # noqa: E402
from config import AMAZON_TEMPLATE_PATH, PRODUCT_INFO_PATH  # noqa: E402
from packing import process_shipment_file, write_packing_workbook  # noqa: E402
from product_info_source import load_product_specs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="不分仓拼箱 CLI")
    parser.add_argument("shipment", type=Path, help="发货单 xlsx")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=APP_DIR / "output",
        help="输出目录（默认 apps/pinxiang_bot/output）",
    )
    parser.add_argument("--no-amazon", action="store_true", help="不生成亚马逊表")
    args = parser.parse_args(argv)

    if not args.shipment.is_file():
        print(f"发货单不存在: {args.shipment}", file=sys.stderr)
        return 1

    product_specs = {}
    if PRODUCT_INFO_PATH and Path(PRODUCT_INFO_PATH).is_file():
        product_specs = load_product_specs(PRODUCT_INFO_PATH)
        print(f"已加载产品信息: {PRODUCT_INFO_PATH} ({len(product_specs)} SKU)")
    else:
        print(f"产品信息未就绪，使用发货单箱规: {PRODUCT_INFO_PATH or '(空)'}")

    result = process_shipment_file(args.shipment, product_specs=product_specs)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    packing_path = args.out_dir / f"拼箱结果-{args.shipment.stem}.xlsx"
    write_packing_workbook(result, packing_path)
    print(f"拼箱结果: {packing_path}  rows={len(result.rows)}")
    if result.warnings:
        for w in result.warnings:
            print(f"  warn: {w}")

    if not args.no_amazon:
        amazon_path = args.out_dir / f"Amazon-{args.shipment.stem}.xlsx"
        create_amazon_workbook(
            template_source=AMAZON_TEMPLATE_PATH,
            output_path=amazon_path,
            result=result,
        )
        print(f"亚马逊表: {amazon_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
