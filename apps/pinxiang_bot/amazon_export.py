#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将拼箱结果写入 Amazon Manifest 上传模版（MPL2）。

模版结构与 dingtalk-lcl-bot 一致，本模块独立复制逻辑，不 import 外部项目。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Union

from openpyxl import load_workbook
from openpyxl.styles import Border, Side

from packing import PackingResult, PackingRow  # noqa: E402

PathLike = Union[str, Path]

CM_TO_INCH = 0.393701
KG_TO_LB = 2.20462

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

TEMPLATE_SHEET = "Create workflow – template"


def create_amazon_workbook(
    *,
    template_source: PathLike,
    output_path: PathLike,
    result: PackingResult,
    default_prep_owner: str = "Seller",
    default_labeling_owner: str = "Seller",
) -> Path:
    source = Path(template_source)
    if not source.is_file():
        raise FileNotFoundError(f"Amazon 模版不存在: {source}")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out)

    wb = load_workbook(out)
    if TEMPLATE_SHEET not in wb.sheetnames:
        raise ValueError(f"Amazon 模版缺少工作表: {TEMPLATE_SHEET}")
    ws = wb[TEMPLATE_SHEET]

    _apply_default_owners(ws, default_prep_owner, default_labeling_owner)

    header_row = _find_header_row(ws)
    data_row = header_row + 1
    for row in result.amazon_rows:
        _write_data_row(ws, data_row, row)
        data_row += 1

    wb.save(out)
    return out


def reformat_amazon_workbook(
    *,
    data_source: PathLike,
    template_source: PathLike,
    output_path: PathLike,
    default_prep_owner: str = "Seller",
    default_labeling_owner: str = "Seller",
) -> Path:
    """把已填模板的数据行原样拷到新壳子（模板2 与模板1 数据一致，仅格式不同）。"""
    src = Path(data_source)
    if not src.is_file():
        raise FileNotFoundError(f"Amazon 数据源不存在: {src}")
    shell = Path(template_source)
    if not shell.is_file():
        raise FileNotFoundError(f"Amazon 模版不存在: {shell}")

    src_wb = load_workbook(src, data_only=True)
    try:
        if TEMPLATE_SHEET not in src_wb.sheetnames:
            raise ValueError(f"数据源缺少工作表: {TEMPLATE_SHEET}")
        src_ws = src_wb[TEMPLATE_SHEET]
        src_header = _find_header_row(src_ws)
        rows: list[list] = []
        r = src_header + 1
        while True:
            sku = src_ws.cell(r, 1).value
            if sku is None or str(sku).strip() == "":
                break
            rows.append([src_ws.cell(r, c).value for c in range(1, 11)])
            r += 1
    finally:
        src_wb.close()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(shell, out)
    wb = load_workbook(out)
    if TEMPLATE_SHEET not in wb.sheetnames:
        raise ValueError(f"Amazon 模版缺少工作表: {TEMPLATE_SHEET}")
    ws = wb[TEMPLATE_SHEET]
    _apply_default_owners(ws, default_prep_owner, default_labeling_owner)
    header_row = _find_header_row(ws)
    for i, values in enumerate(rows):
        row_idx = header_row + 1 + i
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.border = THIN_BORDER
    wb.save(out)
    return out


def _apply_default_owners(ws, prep: str, labeling: str) -> None:
    for row_idx in range(1, 8):
        label = str(ws.cell(row_idx, 1).value or "").strip()
        if label == "Default prep owner":
            ws.cell(row_idx, 2, prep)
        elif label == "Default labeling owner":
            ws.cell(row_idx, 2, labeling)


def _find_header_row(ws) -> int:
    for row in range(1, (ws.max_row or 1) + 1):
        if str(ws.cell(row=row, column=1).value or "").strip() == "Merchant SKU":
            return row
    return 8


def _write_data_row(ws, row_idx: int, row: PackingRow) -> None:
    msku = row.msku or row.sku
    values = [
        msku,
        int(round(row.qty)) if abs(row.qty - round(row.qty)) < 1e-9 else row.qty,
        "",  # Expiration date
        "",  # Manufacturing lot code
        int(round(row.units_per_box)) if abs(row.units_per_box - round(row.units_per_box)) < 1e-9 else row.units_per_box,
        int(round(row.box_count)) if abs(row.box_count - round(row.box_count)) < 1e-9 else row.box_count,
        round(row.length_cm * CM_TO_INCH, 2) if row.length_cm else "",
        round(row.width_cm * CM_TO_INCH, 2) if row.width_cm else "",
        round(row.height_cm * CM_TO_INCH, 2) if row.height_cm else "",
        round(row.box_weight_kg * KG_TO_LB, 2) if row.box_weight_kg else "",
    ]
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row_idx, column=col, value=value)
        cell.border = THIN_BORDER
