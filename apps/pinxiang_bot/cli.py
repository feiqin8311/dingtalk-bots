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

from pinxiang_config import (  # noqa: E402
    PRODUCT_INFO_PATH,
    SMB_CLIENT_NAME,
    SMB_PASSWORD,
    SMB_PORT,
    SMB_TIMEOUT_SEC,
    SMB_USERNAME,
)
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
    args = parser.parse_args(argv)

    if not args.shipment.is_file():
        print(f"发货单不存在: {args.shipment}", file=sys.stderr)
        return 1

    product_specs = {}
    if PRODUCT_INFO_PATH:
        try:
            product_specs = load_product_specs(
                PRODUCT_INFO_PATH,
                smb_username=SMB_USERNAME,
                smb_password=SMB_PASSWORD,
                smb_port=SMB_PORT,
                smb_timeout_sec=SMB_TIMEOUT_SEC,
                smb_client_name=SMB_CLIENT_NAME,
            )
            print(f"已加载产品信息: {PRODUCT_INFO_PATH} ({len(product_specs)} SKU)")
        except Exception as exc:
            print(f"产品信息未就绪，使用发货单箱规: {exc}")
    else:
        print("产品信息路径为空，使用发货单箱规")

    result = process_shipment_file(args.shipment, product_specs=product_specs)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    packing_path = args.out_dir / f"{result.result_basename(fallback=args.shipment.stem)}.xlsx"
    write_packing_workbook(result, packing_path)
    print(f"拼箱结果: {packing_path}  rows={len(result.rows)}")
    if result.warnings:
        for w in result.warnings:
            print(f"  warn: {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
