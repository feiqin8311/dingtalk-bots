#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从发货单提取店铺/国家/运输方式，供拼箱文案使用。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class ShipmentInfo:
    shop: str
    shop_full: str
    country: str
    transport_method: str

    @property
    def folder_name(self) -> str:
        return f"{self.country}{self.transport_method} 平谊"

    @property
    def remark(self) -> str:
        return f"{self.country}{self.transport_method}"

    def get_shop_type(self) -> Optional[str]:
        shop_upper = self.shop.upper()
        if shop_upper.startswith("EZARC"):
            return "EZARC"
        if shop_upper.startswith("TOLESA"):
            return "TOLESA"
        return None


def extract_shipment_info(excel_path: str, sheet_name: str = "发货单详情") -> ShipmentInfo:
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    required_cols = ["店铺", "国家", "运输方式"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"发货单详情缺少必需列: {', '.join(missing_cols)}")

    if df.empty:
        raise ValueError("发货单详情工作表为空")

    first_row = df.iloc[0]

    shop_full = str(first_row["店铺"]).strip()
    country = str(first_row["国家"]).strip()
    transport = str(first_row["运输方式"]).strip()

    if not shop_full or shop_full == "nan":
        raise ValueError("店铺列数据为空")
    if not country or country == "nan":
        raise ValueError("国家列数据为空")
    if not transport or transport == "nan":
        raise ValueError("运输方式列数据为空")

    shop = shop_full.split()[0] if shop_full else ""

    return ShipmentInfo(
        shop=shop,
        shop_full=shop_full,
        country=country,
        transport_method=transport,
    )
