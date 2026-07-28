#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把拼箱结果写入亚马逊「包装箱包装信息」表（运营上传的 STA 装箱表）。"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Union

from openpyxl import load_workbook

from packing import PackingRow

PathLike = Union[str, Path]

CM_TO_INCH = 0.393701
KG_TO_LB = 2.20462
SHEET_NAME = "包装箱包装信息"
START_COL = 13  # 包装箱 1 数量
SKU_HEADER_ROW = 5
SKU_DATA_START_ROW = 6


@dataclass
class BoxPlan:
    """单箱计划（全局第 n 个包装箱）。"""

    sku_keys: set[str]  # 可匹配的 SKU / MSKU
    units: int
    weight_lb: float
    width_in: float  # 亚马逊表：宽/长/高 行顺序与参考一致
    length_in: float
    height_in: float


def expand_packing_rows_to_boxes(rows: Sequence[PackingRow]) -> list[BoxPlan]:
    """每条拼箱结果行按箱数展开为独立包装箱。"""
    boxes: list[BoxPlan] = []
    for row in rows:
        n_boxes = int(round(row.box_count)) if row.box_count else 1
        n_boxes = max(n_boxes, 1)
        units = int(round(row.units_per_box))
        keys = {str(row.sku).strip(), str(row.msku or "").strip()}
        keys.discard("")
        weight_lb = round(float(row.box_weight_kg) * KG_TO_LB, 10)
        # 参考表：宽度行=宽(cm)，长度行=长(cm)
        width_in = round(float(row.width_cm) * CM_TO_INCH, 10)
        length_in = round(float(row.length_cm) * CM_TO_INCH, 10)
        height_in = round(float(row.height_cm) * CM_TO_INCH, 10)
        for _ in range(n_boxes):
            boxes.append(
                BoxPlan(
                    sku_keys=set(keys),
                    units=units,
                    weight_lb=weight_lb,
                    width_in=width_in,
                    length_in=length_in,
                    height_in=height_in,
                )
            )
    return boxes


def fill_amazon_packaging_file(
    amazon_path: PathLike,
    packing_rows: Sequence[PackingRow],
    output_path: PathLike,
) -> Path:
    """复制运营上传的表，按拼箱结果写入箱列与箱规。"""
    src = Path(amazon_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != out.resolve():
        shutil.copy2(src, out)

    boxes = expand_packing_rows_to_boxes(packing_rows)
    if not boxes:
        raise ValueError("拼箱结果为空，无法填写包装箱包装信息")

    wb = load_workbook(out)
    if SHEET_NAME not in wb.sheetnames:
        raise ValueError(f"文件缺少工作表「{SHEET_NAME}」，请上传亚马逊装箱信息表")
    ws = wb[SHEET_NAME]

    total = len(boxes)
    # 包装箱总数（参考：C3 旁 M3 / 第 13 列）
    ws.cell(3, START_COL, total)

    # 表头与箱名
    for idx in range(total):
        col = START_COL + idx
        ws.cell(SKU_HEADER_ROW, col, f"包装箱 {idx + 1} 数量")

    # 找到规格区起始行：含「包装箱名称」
    name_row = _find_row_by_label(ws, "包装箱名称")
    weight_row = _find_row_by_label(ws, "包装箱重量")
    width_row = _find_row_by_label(ws, "包装箱宽度")
    length_row = _find_row_by_label(ws, "包装箱长度")
    height_row = _find_row_by_label(ws, "包装箱高度")
    if name_row is None:
        raise ValueError("未找到「包装箱名称」行")

    for idx in range(total):
        col = START_COL + idx
        ws.cell(name_row, col, f"P1 - B{idx + 1}")
        box = boxes[idx]
        if weight_row:
            ws.cell(weight_row, col, box.weight_lb)
        if width_row:
            ws.cell(width_row, col, box.width_in)
        if length_row:
            ws.cell(length_row, col, box.length_in)
        if height_row:
            ws.cell(height_row, col, box.height_in)

    # SKU 数据行：清旧箱列并写入
    sku_end = name_row - 1 if name_row else ws.max_row
    data_rows: list[tuple[int, str]] = []
    for r in range(SKU_DATA_START_ROW, sku_end + 1):
        sku = ws.cell(r, 1).value
        if sku is None or str(sku).strip() == "":
            break
        if str(sku).strip() in {"包装箱名称", "STOP"}:
            break
        data_rows.append((r, str(sku).strip()))

    # 清空动态箱区
    for r, _ in data_rows:
        for idx in range(max(total, 20)):
            ws.cell(r, START_COL + idx, None)

    for r, amazon_sku in data_rows:
        packed = 0
        for idx, box in enumerate(boxes):
            if _sku_matches(amazon_sku, box.sku_keys):
                ws.cell(r, START_COL + idx, box.units)
                packed += box.units
        # 装箱数量 = 各箱合计（参考中等于预计数量）
        expected = ws.cell(r, 10).value
        ws.cell(r, 11, packed if packed else expected)

    wb.save(out)
    return out


def is_amazon_packaging_workbook(path: PathLike) -> bool:
    try:
        wb = load_workbook(path, read_only=True)
        ok = SHEET_NAME in wb.sheetnames
        wb.close()
        return ok
    except Exception:
        return False


def _find_row_by_label(ws, prefix: str) -> int | None:
    for r in range(1, min((ws.max_row or 1) + 1, 80)):
        val = ws.cell(r, 1).value
        if val is not None and str(val).strip().startswith(prefix):
            return r
    return None


def _sku_matches(amazon_sku: str, keys: set[str]) -> bool:
    a = amazon_sku.strip()
    if a in keys:
        return True
    for k in keys:
        if not k:
            continue
        if a == k or a.startswith(k) or k.startswith(a):
            return True
    return False
