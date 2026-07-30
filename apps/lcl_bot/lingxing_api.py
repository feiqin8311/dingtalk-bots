#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LingXing OpenAPI helper for shipment deletion.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

from . import config

try:
    from Crypto.Cipher import AES
except Exception:  # pragma: no cover - optional dependency
    AES = None

BLOCK_SIZE = 16


class LingXingApiError(RuntimeError):
    """LingXing API error."""


def _pad(text: str) -> str:
    pad_len = BLOCK_SIZE - len(text) % BLOCK_SIZE
    return text + (pad_len * chr(pad_len))


def _aes_encrypt(key: str, data: str) -> str:
    if AES is None:
        raise LingXingApiError("缺少Crypto依赖，无法执行领星签名加密")
    cipher = AES.new(key.encode('utf-8'), AES.MODE_ECB)
    padded = _pad(data)
    encrypted = cipher.encrypt(padded.encode('utf-8'))
    return base64.b64encode(encrypted).decode('utf-8')


def _md5_encrypt(text: str) -> str:
    md = hashlib.md5()
    md.update(text.encode('utf-8'))
    return md.hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def _format_params(params: Optional[Dict[str, Any]]) -> str:
    if not params:
        return ''
    canonical = []
    for key in sorted(params.keys()):
        value = params[key]
        if value == "":
            continue
        if isinstance(value, (dict, list)):
            canonical.append(f"{key}={_json_dumps(value)}")
        else:
            canonical.append(f"{key}={value}")
    return "&".join(canonical)


def _generate_sign(app_key: str, request_params: Dict[str, Any]) -> str:
    canonical_querystring = _format_params(request_params)
    md5_str = _md5_encrypt(canonical_querystring).upper()
    return _aes_encrypt(app_key, md5_str)


class LingXingClient:
    def __init__(self) -> None:
        self.host = config.LINGXING_API_HOST
        self.app_key = config.LINGXING_APP_KEY
        self.app_secret = config.LINGXING_APP_SECRET
        self.token_url = config.LINGXING_TOKEN_URL
        self.token_key = config.LINGXING_TOKEN_KEY or self.app_key
        self.ssl_verify = config.LINGXING_SSL_VERIFY

        if not self.host or not self.app_key or not self.token_url or not self.token_key:
            raise LingXingApiError("领星OpenAPI配置缺失，请检查环境变量 LINGXING_API_HOST/LINGXING_APP_KEY/LINGXING_TOKEN_URL/LINGXING_TOKEN_KEY")

    async def _get_access_token(self) -> str:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(self.token_url, json={"api_key": self.token_key}, ssl=self.ssl_verify) as resp:
                if resp.status != 200:
                    raise LingXingApiError(f"获取领星token失败，状态码: {resp.status}")
                token_resp = await resp.json()
        access_token = token_resp.get("access_token")
        if not access_token:
            raise LingXingApiError("获取领星token失败，返回中未包含 access_token")
        return access_token

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

        sign = _generate_sign(self.app_key, gen_sign_params)
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
    client = LingXingClient()
    payload = {"shipment_nos": shipment_nos}
    return await client.request("/basicOpen/openapi/fbaShipment/deleteShipmentList", "POST", req_body=payload)
