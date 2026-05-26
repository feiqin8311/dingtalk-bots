# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LingXing OpenAPI Client.

This module provides a reusable client for LingXing ERP API,
including authentication, signature generation, and common operations.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Union

import aiohttp

try:
    import orjson
    def json_dumps(obj):
        return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
except ImportError:
    import json
    def json_dumps(obj):
        return json.dumps(obj, sort_keys=True).encode()

from Crypto.Cipher import AES

BLOCK_SIZE = 16  # Bytes


def _do_pad(text: str) -> str:
    return text + (BLOCK_SIZE - len(text) % BLOCK_SIZE) * chr(BLOCK_SIZE - len(text) % BLOCK_SIZE)


def _aes_encrypt(key: str, data: str) -> str:
    key_bytes = key.encode("utf-8")
    data = _do_pad(data)
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    result = cipher.encrypt(data.encode())
    encode_str = base64.b64encode(result)
    return encode_str.decode("utf-8")


def _md5_encrypt(text: str) -> str:
    md = hashlib.md5()
    md.update(text.encode("utf-8"))
    return md.hexdigest()


class HttpBase:
    """Base HTTP client with async support."""

    def __init__(self, default_timeout: int = 30):
        self.default_timeout = default_timeout

    async def request(
        self,
        method: str,
        req_url: str,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        timeout = kwargs.pop("timeout", self.default_timeout)
        ssl = kwargs.pop("ssl", None)
        data = json_dumps(json) if json else None

        proxy_url = os.getenv("LINGXING_PROXY")
        if proxy_url and proxy_url.startswith("socks5://") and not proxy_url.startswith("socks5h://"):
            proxy_url = "socks5h" + proxy_url[len("socks5"):]
        
        connector = None
        if proxy_url:
            try:
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(proxy_url, verify_ssl=ssl is not False)
            except ImportError as exc:
                raise RuntimeError("需要安装 aiohttp_socks 才能使用 SOCKS 代理: pip install aiohttp_socks") from exc

        async with aiohttp.ClientSession(connector=connector, trust_env=True) as aio_session:
            async with aio_session.request(
                method=method,
                url=req_url,
                params=params,
                data=data,
                timeout=timeout,
                headers=headers,
                ssl=ssl,
                **kwargs,
            ) as resp:
                if resp.status != 200:
                    raise ValueError(f"Response error, status code: {resp.status}, body: {await resp.text()}")
                return await resp.json()


class SignBase:
    """Signature generation for LingXing API."""

    @classmethod
    def generate_sign(cls, encrypt_key: str, request_params: dict) -> str:
        canonical_querystring = cls.format_params(request_params)
        md5_str = _md5_encrypt(canonical_querystring).upper()
        return _aes_encrypt(encrypt_key, md5_str)

    @classmethod
    def format_params(cls, request_params: Union[None, dict] = None) -> str:
        if not request_params or not isinstance(request_params, dict):
            return ""
        canonical_strs = []
        sort_keys = sorted(request_params.keys())
        for key in sort_keys:
            value = request_params[key]
            if value == "":
                continue
            if isinstance(value, (dict, list)):
                canonical_strs.append(f"{key}={json_dumps(value).decode()}")
            else:
                canonical_strs.append(f"{key}={value}")
        return "&".join(canonical_strs)


class LingXingClient:
    """
    LingXing OpenAPI Client.

    Usage:
        client = LingXingClient(
            host="https://openapi.lingxing.com",
            app_id="your_app_id",
            app_secret="your_app_secret",
            token_url="your_token_url",
            token_key="your_token_key",
        )
        detail = await client.fetch_shipment_detail("SP260119001")
    """

    # Common API routes
    ROUTE_SHIPMENT_DETAIL = "/erp/sc/routing/storage/shipment/getInboundShipmentListMwsDetail"
    ROUTE_SHIPMENT_UPDATE = "/erp/sc/routing/storage/shipment/updateInboundShipmentListMws"
    ROUTE_LOCAL_PRODUCT = "/erp/sc/routing/data/local_inventory/batchGetProductInfo"
    ROUTE_PRODUCT_INFO = "/erp/sc/routing/data/local_inventory/productInfo"
    ROUTE_SHIPMENT_LIST_DETAIL = "/erp/sc/routing/storage/shipment/getInboundShipmentListMwsDetailList"
    ROUTE_COMMON_FILE_DOWNLOAD = "/erp/sc/routing/common/file/download"

    def __init__(
        self,
        host: str,
        app_id: str,
        app_secret: str,
        token_url: str,
        token_key: Optional[str] = None,
        ssl_verify: bool = True,
    ):
        self.host = host
        self.app_id = app_id
        self.app_secret = app_secret
        self.token_url = token_url
        self.token_key = token_key or app_id
        self.ssl_verify = ssl_verify
        self.request_kwargs = {} if ssl_verify else {"ssl": False}

    async def _fetch_access_token(self) -> str:
        """Fetch access token from token server."""
        ssl = None if self.ssl_verify else False
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(self.token_url, json={"api_key": self.token_key}, ssl=ssl) as resp:
                token_resp = await resp.json()
        access_token = token_resp.get("access_token")
        if not access_token:
            raise RuntimeError(f"获取领星 access_token 失败: {token_resp}")
        return access_token

    async def _request(
        self,
        route_name: str,
        method: str = "POST",
        req_params: Optional[dict] = None,
        req_body: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        """Make authenticated API request."""
        access_token = await self._fetch_access_token()
        req_url = self.host + route_name
        headers = kwargs.pop("headers", {})

        req_params = req_params or {}
        gen_sign_params = copy.deepcopy(req_body) if req_body else {}
        if req_params:
            gen_sign_params.update(req_params)

        sign_params = {
            "app_key": self.app_id,
            "access_token": access_token,
            "timestamp": f"{int(time.time())}",
        }
        gen_sign_params.update(sign_params)
        sign = SignBase.generate_sign(self.app_id, gen_sign_params)
        sign_params["sign"] = sign
        req_params.update(sign_params)

        if req_body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        merged_kwargs = {**self.request_kwargs, **kwargs}
        return await HttpBase().request(
            method,
            req_url,
            params=req_params,
            headers=headers,
            json=req_body,
            **merged_kwargs,
        )

    # ==================== Shipment APIs ====================

    async def fetch_shipment_detail(self, shipment_sn: str) -> dict:
        """Fetch shipment detail by shipment number."""
        if not shipment_sn:
            raise ValueError("缺少发货单号(shipment_sn)。")
        return await self._request(self.ROUTE_SHIPMENT_DETAIL, req_body={"shipment_sn": shipment_sn})

    async def fetch_shipment_list_detail(self, shipment_sns: list[str]) -> dict:
        """Batch fetch shipment details."""
        if not shipment_sns:
            raise ValueError("缺少发货单号列表。")
        return await self._request(self.ROUTE_SHIPMENT_LIST_DETAIL, req_body={"shipment_sns": shipment_sns})

    async def get_shipment_remark(self, shipment_sn: str) -> Optional[str]:
        """Get remark field from shipment detail."""
        detail = await self.fetch_shipment_detail(shipment_sn)
        data = detail.get("data")
        if isinstance(data, dict):
            return data.get("remark")
        if isinstance(data, list) and data:
            if isinstance(data[0], dict):
                return data[0].get("remark")
        return None

    async def update_shipment_remark(self, shipment_sn: str, remark: str) -> dict:
        """Update shipment remark."""
        if not shipment_sn:
            raise ValueError("缺少发货单号(shipment_sn)。")
        if not remark:
            raise ValueError("缺少备注内容(remark)。")
        return await self._request(
            self.ROUTE_SHIPMENT_UPDATE,
            req_body={"shipment_sn": shipment_sn, "remark": remark},
        )

    async def update_shipment_items(self, shipment_sn: str, remark: str, items: list[dict]) -> dict:
        """Update shipment items with quantities and remark."""
        if not shipment_sn:
            raise ValueError("缺少发货单号(shipment_sn)。")
        if not items:
            raise ValueError("缺少 items 列表。")
        payload = {"shipment_sn": shipment_sn, "remark": remark, "items": items}
        return await self._request(self.ROUTE_SHIPMENT_UPDATE, req_body=payload)

    async def append_shipment_remark(self, shipment_sn: str, append_text: str) -> dict:
        """Append text to existing shipment remark."""
        current_data = await self.get_shipment_data(shipment_sn)
        current = (current_data.get("remark") or "").strip()
        target = f"{current}\n{append_text}".strip() if current else append_text
        return await self.update_shipment_remark(shipment_sn, target)
    
    async def lock_shipment_stock(self, shipment_nos: list[str]) -> dict:
        """
        Lock stock for shipment list.

        Args:
            shipment_nos: List of shipment numbers to lock (e.g., ["SP260119001"]).

        Returns:
            API response dict

        Raises:
            ValueError: If shipment_nos is empty
        """
        if not shipment_nos:
            raise ValueError("缺少发货单号列表。")
        return await self._request(
            "/erp/sc/routing/storage/shipment/lockStock",
            "POST",
            req_body={"shipment_nos": shipment_nos}
        )

    async def delete_shipment_list(self, shipment_nos: list[str]) -> dict:
        """
        Delete shipment list from LingXing.
        
        Args:
            shipment_nos: List of shipment numbers to delete (e.g., ["SP260119001", "SP260119002"])
            
        Returns:
            API response dict
            
        Raises:
            ValueError: If shipment_nos is empty
        """
        if not shipment_nos:
            raise ValueError("缺少发货单号列表。")
        return await self._request(
            "/basicOpen/openapi/fbaShipment/deleteShipmentList",
            "POST",
            req_body={"shipment_nos": shipment_nos}
        )

    async def get_shipment_data(self, shipment_sn: str) -> dict:
        """
        Get key data from shipment detail.
        
        Returns:
            dict with keys:
                - remark: str (备注)
                - total_box_num: int (总箱数)
                - total_box_weight: str (总重量)
                - total_box_volume: str (总体积)
                - shipment_id: str (货件ID)
                - status: int (状态)
        """
        detail = await self.fetch_shipment_detail(shipment_sn)
        data = detail.get("data")
        if isinstance(data, list) and data:
            data = data[0]
        
        result = {
            "remark": None,
            "total_box_num": None,
            "total_box_weight": None,
            "total_box_volume": None,
            "shipment_id": None,
            "status": None,
            "box_list": [],
        }
        
        if isinstance(data, dict):
            result["remark"] = data.get("remark")
            result["status"] = data.get("status")
            # 从 items 中提取 shipment_id
            items = data.get("items", [])
            if items and isinstance(items[0], dict):
                result["shipment_id"] = items[0].get("shipment_id")
            # 从 box_total 中提取箱数信息
            box_total = data.get("box_total", {})
            if box_total:
                result["total_box_num"] = box_total.get("total_box_num")
                result["total_box_weight"] = box_total.get("total_box_weight")
                result["total_box_volume"] = box_total.get("total_box_volume")

            # Extract box_list details
            box_list = data.get("box_list") or []
            if isinstance(box_list, list):
                extracted_boxes = []
                for box in box_list:
                    if not isinstance(box, dict):
                        continue
                    box_skus = box.get("box_skus") or []
                    extracted_skus = []
                    if isinstance(box_skus, list):
                        for sku_item in box_skus:
                            if not isinstance(sku_item, dict):
                                continue
                            extracted_skus.append(
                                {
                                    "sku": sku_item.get("sku"),
                                    "quantity_in_case": sku_item.get("quantity_in_case"),
                                }
                            )
                    extracted_boxes.append(
                        {
                            "box_num": box.get("box_num"),
                            "cg_box_length": box.get("cg_box_length"),
                            "cg_box_width": box.get("cg_box_width"),
                            "cg_box_height": box.get("cg_box_height"),
                            "cg_box_weight": box.get("cg_box_weight"),
                            "box_skus": extracted_skus,
                        }
                    )
                result["box_list"] = self.merge_box_list(extracted_boxes)
        
        return result

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(float(str(value)))
        except Exception:
            return 0

    @staticmethod
    def _box_skus_key(box_skus: list) -> tuple:
        items = []
        for sku_item in box_skus:
            if not isinstance(sku_item, dict):
                continue
            sku = str(sku_item.get("sku") or "").strip()
            qty = str(sku_item.get("quantity_in_case") or "").strip()
            items.append((sku, qty))
        return tuple(sorted(items))

    @classmethod
    def merge_box_list(cls, box_list: list[dict]) -> list[dict]:
        """
        Merge duplicate boxes by dimensions + weight + box_skus, sum box_num.
        """
        merged = []
        index = {}
        for box in box_list:
            if not isinstance(box, dict):
                continue
            key = (
                str(box.get("cg_box_length") or "").strip(),
                str(box.get("cg_box_width") or "").strip(),
                str(box.get("cg_box_height") or "").strip(),
                str(box.get("cg_box_weight") or "").strip(),
                cls._box_skus_key(box.get("box_skus") or []),
            )
            if key not in index:
                new_box = box.copy()
                new_box["box_num"] = cls._to_int(box.get("box_num"))
                merged.append(new_box)
                index[key] = new_box
            else:
                index[key]["box_num"] = cls._to_int(index[key].get("box_num")) + cls._to_int(box.get("box_num"))
        return merged

    # ==================== Product APIs ====================

    async def get_product_info(self, sku: str) -> dict:
        """Get local product info by SKU."""
        if not sku:
            raise ValueError("缺少 SKU。")
        return await self._request(self.ROUTE_PRODUCT_INFO, req_body={"sku": sku})

    async def batch_get_local_product_info(self, skus: list[str]) -> dict:
        """Batch get local product info by SKUs."""
        if not skus:
            raise ValueError("缺少 SKU 列表。")
        return await self._request(self.ROUTE_LOCAL_PRODUCT, req_body={"skus": skus})

    # ==================== Common APIs ====================

    async def download_common_file(self, file_id: str) -> dict:
        """Download common file by file_id."""
        if not file_id:
            raise ValueError("缺少文件 ID(file_id)。")
        return await self._request(self.ROUTE_COMMON_FILE_DOWNLOAD, req_body={"file_id": file_id})

    # ==================== Helper Methods ====================

    @staticmethod
    def get_next_saturday(from_date: datetime = None) -> str:
        """
        获取最近的周六日期。
        
        如果今天是周六，返回今天；否则返回下一个周六。
        
        Returns:
            日期字符串，格式: "1月25日"
        """
        if from_date is None:
            from_date = datetime.now()
        
        # 0=周一, 5=周六, 6=周日
        days_until_saturday = (5 - from_date.weekday()) % 7
        if days_until_saturday == 0 and from_date.weekday() != 5:
            days_until_saturday = 7
        
        next_saturday = from_date + timedelta(days=days_until_saturday)
        return f"{next_saturday.month}月{next_saturday.day}日"

    async def update_shipment_remark_with_template(
        self,
        shipment_sn: str,
        template: str = "资料已上传，箱唛一式两份，{total_box_num}箱，{date}，平谊提货",
    ) -> dict:
        """
        使用模板更新发货单备注。
        
        Args:
            shipment_sn: 发货单号
            template: 备注模板，支持占位符:
                - {total_box_num}: 总箱数
                - {date}: 最近周六日期
        
        Returns:
            dict with keys: shipment_sn, old_remark, new_remark, response
        """
        # 获取发货单数据
        data = await self.get_shipment_data(shipment_sn)
        old_remark = data.get("remark") or ""
        total_box_num = data.get("total_box_num") or 0
        
        # 生成新备注内容
        next_saturday = self.get_next_saturday()
        new_content = template.format(
            total_box_num=total_box_num,
            date=next_saturday,
        )
        
        # 拼接备注（新内容追加到现有备注前面）
        if old_remark.strip():
            new_remark = f"{new_content}\n{old_remark.strip()}"
        else:
            new_remark = new_content
        
        # 更新备注
        response = await self.update_shipment_remark(shipment_sn, new_remark)
        
        return {
            "shipment_sn": shipment_sn,
            "old_remark": old_remark,
            "new_remark": new_remark,
            "response": response,
        }
