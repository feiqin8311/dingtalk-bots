#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Entrypoint for DingTalk CP Bot."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from typing import Optional
from pathlib import Path

def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


ROOT_DIR = _find_repo_root(Path(__file__).resolve().parent)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import dingtalk_stream

import config
from shared.logging import setup_logger
from handler import ShipmentQueryHandler, _DEFAULT_NOTIFIER


def define_options():
    parser = argparse.ArgumentParser(description="DingTalk CP Bot")
    parser.add_argument("--client_id", dest="client_id", required=False)
    parser.add_argument("--client_secret", dest="client_secret", required=False)
    return parser.parse_args()


def _notify_tech_users(logger: logging.Logger, *, stage: str, exc: Exception) -> None:
    if not config.DING_TECH_USER_IDS:
        return
    trace_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    if len(trace_text) > 1800:
        trace_text = trace_text[-1800:]
    message = (
        "[CP机器人异常告警]\n"
        "request_id: app-runtime\n"
        f"stage: {stage}\n"
        f"error: {type(exc).__name__}: {exc}"
    )
    if trace_text:
        message += f"\n\n{trace_text}"
    for tech_user_id in config.DING_TECH_USER_IDS:
        try:
            _DEFAULT_NOTIFIER.send_user_text(tech_user_id, message)
        except Exception as notify_exc:
            logger.warning("Tech alert send failed(user=%s): %s", tech_user_id, notify_exc)


def main(client_id: Optional[str] = None, client_secret: Optional[str] = None) -> None:
    logger = setup_logger(config.LOG_FORMAT, config.LOG_LEVEL)
    logger.info("=" * 40)
    logger.info("Starting DingTalk CP Bot...")
    logger.info("=" * 40)
    logger.info("Config module: %s", getattr(config, "__file__", "unknown"))
    logger.info(
        "Env check: LINGXING_API_KEY=%s LINGXING_API_SECRET=%s",
        "SET" if config.LINGXING_API_KEY else "MISSING",
        "SET" if config.LINGXING_API_SECRET else "MISSING",
    )

    try:
        options = define_options()
    except Exception:
        options = None

    if client_id is None:
        client_id = (options.client_id if options else None) or config.CLIENT_ID
    if client_secret is None:
        client_secret = (options.client_secret if options else None) or config.CLIENT_SECRET

    if not client_id or not client_secret:
        logger.error("Missing client_id or client_secret.")
        sys.exit(1)

    credential = dingtalk_stream.Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)

    handler = ShipmentQueryHandler(logger=logger)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        handler,
    )

    logger.info("Bot is running. Waiting for messages...")

    try:
        client.start_forever()
    except KeyboardInterrupt:
        logger.info("Stopping...")
    except Exception as exc:
        logger.error("Runtime error: %s", exc, exc_info=True)
        _notify_tech_users(logger, stage="app_start_forever", exc=exc)
        sys.exit(1)


if __name__ == "__main__":
    main(config.CLIENT_ID, config.CLIENT_SECRET)
