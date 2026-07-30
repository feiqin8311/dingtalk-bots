#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LingXing API helper - wrapper for Common library LingXingClient."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from . import config as lcl_config

_workspace_root = getattr(lcl_config, "COMMON_ROOT", None) or Path(__file__).resolve().parents[3]
if str(_workspace_root) not in sys.path:
    sys.path.insert(0, str(_workspace_root))

try:
    from Common.api.lingxing_client import LingXingClient  # type: ignore
    from Common.api import config as lingxing_config  # type: ignore
except ImportError:  # pragma: no cover
    LingXingClient = None  # type: ignore
    lingxing_config = None  # type: ignore


async def delete_shipment_list(shipment_nos: List[str]) -> Dict[str, Any]:
    """Delete shipment list from LingXing using Common library."""
    if LingXingClient is None or lingxing_config is None:
        raise RuntimeError("Common.api.lingxing_client 不可用，请配置 LCL_COMMON_ROOT")
    if not lingxing_config.LINGXING_API_HOST:
        raise ValueError("领星OpenAPI配置缺失，请检查 Common/.env 文件")

    client = LingXingClient(
        host=lingxing_config.LINGXING_API_HOST,
        app_id=lingxing_config.LINGXING_API_KEY,
        app_secret=lingxing_config.LINGXING_API_SECRET,
        token_url=lingxing_config.LINGXING_TOKEN_URL,
        token_key=lingxing_config.LINGXING_TOKEN_REQUEST_KEY,
        ssl_verify=lingxing_config.LINGXING_SSL_VERIFY,
    )
    return await client.delete_shipment_list(shipment_nos)
