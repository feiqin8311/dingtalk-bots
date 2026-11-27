"""Shared LingXing request signing helpers.

Both shipment clients use the same canonical parameter and AES/MD5 signature
contract. Keeping it here prevents subtle differences between bot branches.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Callable, Mapping

import aiohttp

from Crypto.Cipher import AES

BLOCK_SIZE = 16


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def format_params(params: Mapping[str, Any] | None, *, serialize: Callable[[Any], str] = _json_dumps) -> str:
    if not params:
        return ""
    parts = []
    for key in sorted(params):
        value = params[key]
        if value == "":
            continue
        parts.append(f"{key}={serialize(value) if isinstance(value, (dict, list)) else value}")
    return "&".join(parts)


def generate_sign(
    encrypt_key: str, params: Mapping[str, Any] | None, *, serialize: Callable[[Any], str] = _json_dumps
) -> str:
    canonical = format_params(params, serialize=serialize)
    digest = hashlib.md5(canonical.encode("utf-8")).hexdigest().upper()
    pad = BLOCK_SIZE - len(digest) % BLOCK_SIZE
    encrypted = AES.new(encrypt_key.encode("utf-8"), AES.MODE_ECB).encrypt(
        (digest + chr(pad) * pad).encode("utf-8")
    )
    return base64.b64encode(encrypted).decode("ascii")


async def fetch_access_token(url: str, token_key: str, *, ssl: bool | None = None) -> str:
    """Read a token from the configured gateway, which owns its lifetime."""
    async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.post(url, json={"api_key": token_key}, ssl=ssl) as response:
            if response.status != 200:
                raise RuntimeError(f"获取领星 token 失败，状态码: {response.status}")
            payload = await response.json()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("获取领星 token 失败，返回中未包含 access_token")
    return token
