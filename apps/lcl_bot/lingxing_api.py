#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LingXing OpenAPI helper for shipment deletion.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import aiohttp

from . import config
from shared.lingxing import fetch_access_token, generate_sign


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class LingXingApiError(RuntimeError):
    """LingXing API error."""


class LingXingClient:
    def __init__(self) -> None:
        self.host = config.LINGXING_API_HOST
        self.app_key = config.LINGXING_API_KEY
        self.app_secret = config.LINGXING_API_SECRET
        self.token_url = config.LINGXING_TOKEN_URL
        self.token_key = config.LINGXING_TOKEN_REQUEST_KEY or self.app_key
        self.ssl_verify = config.LINGXING_SSL_VERIFY

        if not self.host or not self.app_key or not self.token_url or not self.token_key:
            raise LingXingApiError(
                "领星OpenAPI配置缺失，请检查环境变量 "
                "LINGXING_API_HOST/LINGXING_API_KEY/LINGXING_TOKEN_URL/LINGXING_TOKEN_REQUEST_KEY"
            )

    async def _get_access_token(self) -> str:
        try:
            return await fetch_access_token(self.token_url, self.token_key, ssl=self.ssl_verify)
        except RuntimeError as exc:
            raise LingXingApiError(str(exc)) from exc

    async def request(self, route_name: str, method: str = "POST",
                      req_params: Optional[Dict[str, Any]] = None,
                      req_body: Optional[Dict[str, Any]] = None,
                      timeout: int = 30) -> Dict[str, Any]:
        req_params = req_params or {}
        req_body = req_body or {}
        access_token = await self._get_access_token()

        sign_params = {
            "app_key": self.app_key,
            "access_token": access_token,
            "timestamp": f"{int(time.time())}",
        }
        gen_sign_params = dict(req_body)
        gen_sign_params.update(req_params)
        gen_sign_params.update(sign_params)

        sign = generate_sign(self.app_key, gen_sign_params)
        req_params.update(sign_params)
        req_params["sign"] = sign

        headers = {}
        data = _json_dumps(req_body) if req_body else None
        if data:
            headers["Content-Type"] = "application/json"

        url = f"{self.host}{route_name}"
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.request(
                method,
                url,
                params=req_params,
                data=data,
                headers=headers,
                timeout=timeout,
                ssl=self.ssl_verify,
            ) as resp:
                if resp.status != 200:
                    raise LingXingApiError(f"领星接口返回错误，状态码: {resp.status}")
                return await resp.json()


async def delete_shipment_list(shipment_nos: List[str]) -> Dict[str, Any]:
    if not shipment_nos:
        raise LingXingApiError("缺少发货单号列表")
    client = LingXingClient()
    payload = {"shipment_nos": shipment_nos}
    return await client.request("/basicOpen/openapi/fbaShipment/deleteShipmentList", "POST", req_body=payload)
