#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""One-shot shipment document check entrypoint for OpenClaw agents."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import List, Optional

def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


ROOT_DIR = _find_repo_root(Path(__file__).resolve().parent)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from shared.logging import setup_logger
from handler import ShipmentQueryHandler, _extract_shipment_sns, _summarize_lingxing_response
from shipment_service import fetch_shipment_detail_with_fallback


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one CP shipment check and print reply text.")
    parser.add_argument("shipment_sns", nargs="+", help="Shipment numbers, e.g. SP260421012")
    parser.add_argument("--user-id", default="", help="DingTalk sender user id for usage logging")
    parser.add_argument("--user-name", default="", help="DingTalk sender name for usage logging")
    parser.add_argument(
        "--include-file-markers",
        action="store_true",
        help="Print DINGTALK_FILE markers for generated shipment images.",
    )
    return parser.parse_args()


def _normalize_requested_sns(raw_items: List[str]) -> List[str]:
    shipment_sns: List[str] = []
    for item in raw_items:
        shipment_sns.extend(_extract_shipment_sns(item))
    seen = set()
    result: List[str] = []
    for shipment_sn in shipment_sns:
        if shipment_sn in seen:
            continue
        seen.add(shipment_sn)
        result.append(shipment_sn)
    return result


async def _run_check(
    *,
    shipment_sns: List[str],
    user_id: Optional[str],
    user_name: Optional[str],
    include_file_markers: bool,
) -> int:
    previous_log_level = config.LOG_LEVEL
    config.LOG_LEVEL = "WARNING"
    logger = setup_logger(config.LOG_FORMAT, "WARNING")
    config.LOG_LEVEL = previous_log_level
    for log_handler in logger.handlers:
        if isinstance(log_handler, logging.StreamHandler):
            log_handler.setStream(sys.stderr)
    logging.getLogger("dingtalk_stream").setLevel(logging.WARNING)
    request_id = f"openclaw-{uuid.uuid4().hex[:12]}"

    handler = ShipmentQueryHandler(logger=logger)
    handler._log_request_event(
        request_id=request_id,
        message_id=None,
        user_id=user_id,
        user_name=user_name,
        event_type="RECEIVED",
        ack_status=None,
        shipment_sns=shipment_sns,
        detail="openclaw logistics agent one-shot check",
    )

    response = await handler._retry_async(
        "LingXing fetch shipment detail",
        lambda: fetch_shipment_detail_with_fallback(handler.client, shipment_sns),
        request_id,
    )
    logger.info("[req=%s] LingXing summary: %s", request_id, _summarize_lingxing_response(response))
    reply_result = await asyncio.to_thread(handler._build_reply_with_ocr, response, shipment_sns, request_id)

    output_parts: List[str] = []
    if reply_result.summary_text:
        output_parts.append(reply_result.summary_text)
    output_parts.extend(reply_result.shipment_messages)
    output_parts.extend(reply_result.selection_messages)

    print("\n\n".join(part for part in output_parts if part).strip())

    if include_file_markers:
        for path in reply_result.shipment_images:
            if not path.exists():
                continue
            safe_name = path.name
            print(f'[DINGTALK_FILE]{{"path":"file://{path}","fileName":"{safe_name}","fileType":"png"}}[/DINGTALK_FILE]')

    return 0


def main() -> int:
    args = _parse_args()
    shipment_sns = _normalize_requested_sns(args.shipment_sns)
    if not shipment_sns:
        print("未识别到发货单号，请发送类似 SP260421012 的单号。")
        return 2
    if not config.LINGXING_API_KEY or not config.LINGXING_API_SECRET:
        print("领星 API 配置缺失，无法查询发货单。")
        return 2

    return asyncio.run(
        _run_check(
            shipment_sns=shipment_sns,
            user_id=args.user_id.strip() or None,
            user_name=args.user_name.strip() or None,
            include_file_markers=args.include_file_markers,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
