from pathlib import Path

from openpyxl import Workbook


def write_shipment(path: Path) -> Path:
    """A shipment with two full cartons followed by one partial SKU."""
    wb = Workbook()
    detail = wb.active
    detail.title = "发货单详情"
    detail.append(["发货单号", "发货仓库（单据）", "SKU", "MSKU", "发货量", "国家", "店铺", "物流渠道"])
    for sku, qty in [("FULL", 40), ("PART", 5)]:
        detail.append(["SPTEST1", "仓库 A", sku, f"M-{sku}", qty, "美国", "测试店铺", "测试渠道"])
    packing = wb.create_sheet("装箱信息")
    packing.append(["发货单号", "SKU", "发货数量", "单箱数量", "箱子毛重（kg）", "箱子长度（cm）", "箱子宽度（cm）", "箱子高度（cm）"])
    for sku, qty in [("FULL", 40), ("PART", 5)]:
        packing.append(["SPTEST1", sku, qty, 20, 10, 40, 30, 20])
    wb.save(path)
    wb.close()
    return path
