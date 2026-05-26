#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Aliyun OCR API client helper (OpenAPI 2021-07-07).

Default endpoint: ocr-api.cn-hangzhou.aliyuncs.com
Environment:
  - ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET
  - Optional: ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET
  - Optional: ALIYUN_OCR_ENDPOINT
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:
    # Reuse project env loading if available.
    from . import config  # noqa: F401
except Exception:
    # Allow running as a standalone script.
    for candidate in (Path(__file__).resolve().parent, *Path(__file__).resolve().parents):
        if (candidate / "shared").is_dir():
            sys.path.append(str(candidate))
            break
    try:
        from core.integrations import config  # noqa: F401
    except Exception:
        config = None  # type: ignore

from alibabacloud_ocr_api20210707.client import Client as OcrClient
from alibabacloud_ocr_api20210707 import models as ocr_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models


def _get_env(primary: str, *fallbacks: str) -> str:
    for key in (primary, *fallbacks):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


class AliyunOCRClient:
    """Aliyun OCR client wrapper for RecognizeAllText."""

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        access_key_secret: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        access_key_id = access_key_id or _get_env("ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIYUN_ACCESS_KEY_ID")
        access_key_secret = access_key_secret or _get_env("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "ALIYUN_ACCESS_KEY_SECRET")
        if not access_key_id or not access_key_secret:
            raise RuntimeError("缺少 AccessKey，请设置 ALIBABA_CLOUD_ACCESS_KEY_ID/SECRET 或 ALIYUN_ACCESS_KEY_ID/SECRET。")

        config_model = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        config_model.endpoint = endpoint or _get_env("ALIYUN_OCR_ENDPOINT") or "ocr-api.cn-hangzhou.aliyuncs.com"
        self._client = OcrClient(config_model)

    def recognize_all_text(
        self,
        *,
        url: Optional[str] = None,
        file_path: Optional[str] = None,
        image_type: str = "Advanced",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Recognize text from image.

        Args:
            url: Public image URL (url/body must choose one).
            file_path: Local file path (url/body must choose one).
            image_type: OCR type, e.g. "Advanced", "IdCard".
            **kwargs: Extra request fields (e.g., output_figure, output_coordinate).
        """
        if bool(url) == bool(file_path):
            raise ValueError("url 与 file_path 必须二选一。")

        body = None
        if file_path:
            with open(file_path, "rb") as f:
                body = f.read()

        request = ocr_models.RecognizeAllTextRequest(
            url=url,
            body=body,
            type=image_type,
            **kwargs,
        )
        runtime = util_models.RuntimeOptions()
        response = self._client.recognize_all_text_with_options(request, runtime)
        return _serialize_body(response.body)


def _serialize_body(body: Any) -> Dict[str, Any]:
    if hasattr(body, "to_map"):
        return body.to_map()
    if hasattr(body, "to_dict"):
        return body.to_dict()
    data = getattr(body, "data", None)
    if data is not None:
        return {"data": data}
    return {"body": body}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aliyun OCR RecognizeAllText helper")
    parser.add_argument("--url", help="Public image URL")
    parser.add_argument("--file", dest="file_path", help="Local image file path")
    parser.add_argument("--type", dest="image_type", default="Advanced", help="OCR type, e.g. Advanced/IdCard")
    parser.add_argument("--endpoint", help="Override endpoint, default: ocr-api.cn-hangzhou.aliyuncs.com")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    client = AliyunOCRClient(endpoint=args.endpoint)
    result = client.recognize_all_text(
        url=args.url,
        file_path=args.file_path,
        image_type=args.image_type,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
