#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""不分仓拼箱：独立算法（与 dingtalk-lcl-bot 不同）。

依据桌面业务说明 + 参考发货单/拼箱样例：
- 从「装箱信息」判断箱数比 r = 发货数量 / 单箱数量
- 从「发货单详情」取仓库 / MSKU 等（不同仓库不互拼）
- 非整箱：整数箱保留原箱规，余数/不足一箱按单箱重体积重算
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, Side

PathLike = Union[str, Path]

MIN_BOX_WEIGHT_KG = 1.0
MAX_BOX_WEIGHT_KG = 18.0
MIN_SIDE_CM = 15.0
MAX_SIDE_CM = 62.0
SMALL_VOLUME_CM3 = 10000.0
DEFAULT_SIDE_CM = 20.0

# 拼箱结果表列：与业务参考表一致（不含整箱原箱行、不含 MSKU/备注）
PACKING_HEADERS = (
    "发货仓库",
    "SKU",
    "发货数量",
    "单箱数量",
    "箱数",
    "单箱毛重",
    "长",
    "宽",
    "高",
)


@dataclass(frozen=True)
class ProductSpec:
    """产品主数据（可选）。缺省时用发货单装箱信息字段。"""

    sku: str
    units_per_box: Optional[float] = None
    box_weight_kg: Optional[float] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None


@dataclass
class LineItem:
    shipment_sn: str
    warehouse: str
    sku: str
    msku: str
    product_name: str
    qty: float
    units_per_box: float
    box_weight_kg: float
    length_cm: float
    width_cm: float
    height_cm: float


@dataclass
class PackingRow:
    warehouse: str
    sku: str
    msku: str
    qty: float
    units_per_box: float
    box_count: float
    box_weight_kg: float
    length_cm: float
    width_cm: float
    height_cm: float
    remark: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "发货仓库": self.warehouse,
            "SKU": self.sku,
            "发货数量": _num(self.qty),
            "单箱数量": _num(self.units_per_box),
            "箱数": _num(self.box_count),
            "单箱毛重": _round1(self.box_weight_kg),
            "长": _round1(self.length_cm),
            "宽": _round1(self.width_cm),
            "高": _round1(self.height_cm),
        }


@dataclass
class PackingResult:
    """rows = 拼箱结果表（仅非整箱需处理行）；all_rows = 含原箱，供亚马逊完整清单。"""

    rows: list[PackingRow] = field(default_factory=list)
    all_rows: list[PackingRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def amazon_rows(self) -> list[PackingRow]:
        return list(self.all_rows or self.rows)


def process_shipment_file(
    input_path: PathLike,
    *,
    product_specs: Optional[Mapping[str, ProductSpec]] = None,
) -> PackingResult:
    """读发货单 xlsx，返回拼箱结果。"""
    wb = load_workbook(filename=str(input_path), data_only=True, read_only=True)
    try:
        pack_sheet = _require_sheet(wb, "装箱信息")
        detail_sheet = _require_sheet(wb, "发货单详情")
        pack_rows = list(pack_sheet.iter_rows(values_only=True))
        detail_rows = list(detail_sheet.iter_rows(values_only=True))
    finally:
        wb.close()

    items = _build_line_items(pack_rows, detail_rows, product_specs or {})
    return compute_packing(items)


def compute_packing(items: Sequence[LineItem]) -> PackingResult:
    result = PackingResult()
    for item in items:
        if item.units_per_box <= 0:
            result.warnings.append(f"{item.sku}: 单箱数量无效，已跳过")
            continue
        ratio = item.qty / item.units_per_box
        if _is_integer(ratio) and ratio >= 1:
            # 整箱：不进拼箱结果表（参考表只列需处理行）；仍进 all_rows 供亚马逊
            row = PackingRow(
                warehouse=item.warehouse,
                sku=item.sku,
                msku=item.msku or item.sku,
                qty=item.qty,
                units_per_box=item.units_per_box,
                box_count=ratio,
                box_weight_kg=item.box_weight_kg,
                length_cm=item.length_cm,
                width_cm=item.width_cm,
                height_cm=item.height_cm,
                remark="原箱",
            )
            result.all_rows.append(row)
            continue

        if ratio > 1:
            full_boxes = int(math.floor(ratio))
            full_qty = full_boxes * item.units_per_box
            rem_qty = item.qty - full_qty
            chunk: list[PackingRow] = []
            if full_boxes > 0:
                chunk.append(
                    PackingRow(
                        warehouse=item.warehouse,
                        sku=item.sku,
                        msku=item.msku or item.sku,
                        qty=full_qty,
                        units_per_box=item.units_per_box,
                        box_count=float(full_boxes),
                        box_weight_kg=item.box_weight_kg,
                        length_cm=item.length_cm,
                        width_cm=item.width_cm,
                        height_cm=item.height_cm,
                        remark="原箱-整数部分",
                    )
                )
            if rem_qty > 0:
                chunk.append(_repack_partial(item, rem_qty, remark="余数改箱"))
            result.rows.extend(chunk)
            result.all_rows.extend(chunk)
            continue

        if 0 < ratio < 1:
            row = _repack_partial(item, item.qty, remark="不足一箱改箱")
            result.rows.append(row)
            result.all_rows.append(row)
            continue

        result.warnings.append(f"{item.sku}: 发货数量异常 qty={item.qty}")

    # 余数箱毛重 < 1kg：从整数箱借一箱再并（同 SKU）；同步更新 all_rows 中对应改箱行
    result.rows = _borrow_full_box_if_too_light(result.rows)
    # all_rows：原箱保留 + 改箱行用处理后的 rows 替换
    originals = [r for r in result.all_rows if r.remark == "原箱"]
    result.all_rows = originals + list(result.rows)
    return result


def write_packing_workbook(result: PackingResult, output_path: PathLike) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "拼箱结果"
    thin = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    center = Alignment(horizontal="center", vertical="center")
    for col, header in enumerate(PACKING_HEADERS, start=1):
        cell = ws.cell(1, col, header)
        cell.font = Font(bold=True)
        cell.border = thin
        cell.alignment = center
    for r_idx, row in enumerate(result.rows, start=2):
        data = row.as_dict()
        for c_idx, key in enumerate(PACKING_HEADERS, start=1):
            cell = ws.cell(r_idx, c_idx, data.get(key))
            cell.border = thin
            cell.alignment = center
    if result.warnings:
        ws2 = wb.create_sheet("警告")
        ws2.append(["警告"])
        for msg in result.warnings:
            ws2.append([msg])
    wb.save(path)
    return path


# --- internals ---


def _repack_partial(item: LineItem, qty: float, *, remark: str) -> PackingRow:
    unit_w = item.box_weight_kg / item.units_per_box if item.units_per_box else 0.0
    unit_vol = (item.length_cm * item.width_cm * item.height_cm) / item.units_per_box if item.units_per_box else 0.0
    box_weight = unit_w * qty
    box_vol = unit_vol * qty
    length, width, height = _dims_for_volume(box_vol, item.length_cm, item.width_cm, item.height_cm)
    return PackingRow(
        warehouse=item.warehouse,
        sku=item.sku,
        msku=item.msku or item.sku,
        qty=qty,
        units_per_box=qty,
        box_count=1.0,
        box_weight_kg=box_weight,
        length_cm=length,
        width_cm=width,
        height_cm=height,
        remark=remark,
    )


def _dims_for_volume(volume_cm3: float, orig_l: float, orig_w: float, orig_h: float) -> tuple[float, float, float]:
    """非原箱规尺寸：小体积用 20³；否则固定原长宽推高，并夹到 15~62。"""
    if volume_cm3 <= 0:
        return (
            _clamp_side(orig_l or DEFAULT_SIDE_CM),
            _clamp_side(orig_w or DEFAULT_SIDE_CM),
            _clamp_side(orig_h or DEFAULT_SIDE_CM),
        )
    if volume_cm3 < SMALL_VOLUME_CM3:
        return DEFAULT_SIDE_CM, DEFAULT_SIDE_CM, DEFAULT_SIDE_CM

    length = _clamp_side(orig_l or DEFAULT_SIDE_CM)
    width = _clamp_side(orig_w or DEFAULT_SIDE_CM)
    height = volume_cm3 / (length * width) if length * width else DEFAULT_SIDE_CM
    if MIN_SIDE_CM <= height <= MAX_SIDE_CM:
        return _round1(length), _round1(width), _round1(height)

    # 高度越界时退回 20×20 推高，再夹边
    length = width = DEFAULT_SIDE_CM
    height = volume_cm3 / (length * width)
    height = _clamp_side(height)
    # 若仍无法用 20×20 容纳，略调长宽
    if height >= MAX_SIDE_CM and volume_cm3 > MAX_SIDE_CM * length * width:
        side = math.ceil(volume_cm3 ** (1.0 / 3.0))
        side = _clamp_side(float(side))
        return side, side, _clamp_side(volume_cm3 / (side * side))
    return _round1(length), _round1(width), _round1(height)


def _borrow_full_box_if_too_light(rows: list[PackingRow]) -> list[PackingRow]:
    """若余数/改箱毛重 < 1kg，且同 SKU 有整数原箱，则借 1 箱合并。"""
    by_sku: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        by_sku.setdefault(row.sku, []).append(idx)

    drop: set[int] = set()
    extras: list[PackingRow] = []

    for sku, indices in by_sku.items():
        light_idxs = [
            i
            for i in indices
            if rows[i].remark in {"余数改箱", "不足一箱改箱"} and rows[i].box_weight_kg < MIN_BOX_WEIGHT_KG
        ]
        full_idxs = [i for i in indices if rows[i].remark in {"原箱-整数部分", "原箱"} and rows[i].box_count >= 1]
        if not light_idxs or not full_idxs:
            continue
        light_i = light_idxs[0]
        full_i = full_idxs[0]
        full = rows[full_i]
        light = rows[light_i]
        if full.box_count < 1:
            continue
        unit = full.units_per_box
        # 借走 1 箱
        new_full_count = full.box_count - 1
        merged_qty = light.qty + unit
        unit_w = full.box_weight_kg  # 原箱单箱重
        # 合并后按单品重估算：原箱单箱重/原单箱数量 * 合并数量
        unit_item_w = unit_w / unit if unit else 0.0
        unit_vol = (full.length_cm * full.width_cm * full.height_cm) / unit if unit else 0.0
        merged_weight = unit_item_w * merged_qty
        length, width, height = _dims_for_volume(unit_vol * merged_qty, full.length_cm, full.width_cm, full.height_cm)

        drop.add(light_i)
        if new_full_count <= 0:
            drop.add(full_i)
        else:
            rows[full_i] = PackingRow(
                warehouse=full.warehouse,
                sku=full.sku,
                msku=full.msku,
                qty=new_full_count * unit,
                units_per_box=unit,
                box_count=new_full_count,
                box_weight_kg=full.box_weight_kg,
                length_cm=full.length_cm,
                width_cm=full.width_cm,
                height_cm=full.height_cm,
                remark=full.remark,
            )
        extras.append(
            PackingRow(
                warehouse=light.warehouse,
                sku=light.sku,
                msku=light.msku,
                qty=merged_qty,
                units_per_box=merged_qty,
                box_count=1.0,
                box_weight_kg=merged_weight,
                length_cm=length,
                width_cm=width,
                height_cm=height,
                remark="借箱合并",
            )
        )

    out = [row for i, row in enumerate(rows) if i not in drop]
    out.extend(extras)
    return out


def _build_line_items(
    pack_rows: Sequence[Sequence[Any]],
    detail_rows: Sequence[Sequence[Any]],
    product_specs: Mapping[str, ProductSpec],
) -> list[LineItem]:
    pack_header = [_cell_str(c) for c in pack_rows[0]] if pack_rows else []
    detail_header = [_cell_str(c) for c in detail_rows[0]] if detail_rows else []
    pack_idx = _header_index(pack_header)
    detail_idx = _header_index(detail_header)

    detail_by_sku: dict[str, dict[str, Any]] = {}
    last_wh = ""
    last_sn = ""
    for raw in detail_rows[1:]:
        if not raw or all(v is None or str(v).strip() == "" for v in raw):
            continue
        sku = _cell_str(_get(raw, detail_idx, "SKU"))
        if not sku:
            continue
        wh = _cell_str(_get(raw, detail_idx, "发货仓库（单据）")) or _cell_str(
            _get(raw, detail_idx, "发货仓库（单据明细）")
        )
        sn = _cell_str(_get(raw, detail_idx, "发货单号"))
        if wh:
            last_wh = wh
        else:
            wh = last_wh
        if sn:
            last_sn = sn
        else:
            sn = last_sn
        detail_by_sku[sku] = {
            "warehouse": wh,
            "shipment_sn": sn,
            "msku": _cell_str(_get(raw, detail_idx, "MSKU")) or sku,
            "product_name": _cell_str(_get(raw, detail_idx, "品名")),
            "qty": _to_float(_get(raw, detail_idx, "发货量")),
        }

    items: list[LineItem] = []
    last_wh = ""
    last_sn = ""
    for raw in pack_rows[1:]:
        if not raw or all(v is None or str(v).strip() == "" for v in raw):
            continue
        sku = _cell_str(_get(raw, pack_idx, "SKU"))
        if not sku:
            continue
        wh = _cell_str(_get(raw, pack_idx, "发货仓库（单据）"))
        sn = _cell_str(_get(raw, pack_idx, "发货单号"))
        if wh:
            last_wh = wh
        else:
            wh = last_wh
        if sn:
            last_sn = sn
        else:
            sn = last_sn

        detail = detail_by_sku.get(sku, {})
        warehouse = wh or str(detail.get("warehouse") or "")
        shipment_sn = sn or str(detail.get("shipment_sn") or "")
        msku = str(detail.get("msku") or sku)
        product_name = _cell_str(_get(raw, pack_idx, "品名")) or str(detail.get("product_name") or "")

        qty = _to_float(_get(raw, pack_idx, "发货数量"))
        if qty is None:
            qty = _to_float(detail.get("qty"))
        units = _to_float(_get(raw, pack_idx, "单箱数量"))
        box_w = _to_float(_get(raw, pack_idx, "箱子毛重（kg）"))
        length = _to_float(_get(raw, pack_idx, "箱子长度（cm）"))
        width = _to_float(_get(raw, pack_idx, "箱子宽度（cm）"))
        height = _to_float(_get(raw, pack_idx, "箱子高度（cm）"))

        # 产品表常以 MSKU/裸 SKU 建档（如发货 SKU=801905N，表内=801905）
        spec = product_specs.get(sku) or product_specs.get(msku)
        if spec:
            units = spec.units_per_box if spec.units_per_box is not None else units
            box_w = spec.box_weight_kg if spec.box_weight_kg is not None else box_w
            length = spec.length_cm if spec.length_cm is not None else length
            width = spec.width_cm if spec.width_cm is not None else width
            height = spec.height_cm if spec.height_cm is not None else height

        if qty is None or units is None or units <= 0:
            continue
        items.append(
            LineItem(
                shipment_sn=shipment_sn,
                warehouse=warehouse or "未知仓库",
                sku=sku,
                msku=msku,
                product_name=product_name,
                qty=float(qty),
                units_per_box=float(units),
                box_weight_kg=float(box_w or 0.0),
                length_cm=float(length or 0.0),
                width_cm=float(width or 0.0),
                height_cm=float(height or 0.0),
            )
        )
    return items


def _require_sheet(wb: Any, name: str) -> Any:
    if name not in wb.sheetnames:
        raise ValueError(f"发货单缺少工作表：{name}（现有：{', '.join(wb.sheetnames)}）")
    return wb[name]


def _header_index(headers: Sequence[str]) -> dict[str, int]:
    return {h: i for i, h in enumerate(headers) if h}


def _get(row: Sequence[Any], idx: Mapping[str, int], key: str) -> Any:
    i = idx.get(key)
    if i is None or i >= len(row):
        return None
    return row[i]


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_integer(value: float, tol: float = 1e-9) -> bool:
    return abs(value - round(value)) <= tol


def _clamp_side(value: float) -> float:
    return max(MIN_SIDE_CM, min(MAX_SIDE_CM, float(value)))


def _round1(value: float) -> float:
    return round(float(value), 1)


def _num(value: float) -> float | int:
    if _is_integer(value):
        return int(round(value))
    return _round1(value)
