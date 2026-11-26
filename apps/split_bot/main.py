#!/usr/bin/env python
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
import sys

def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


ROOT_DIR = _find_repo_root(Path(__file__).resolve().parent)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import dingtalk_stream

from Bot.handler import PdfSplitBotHandler
from shared.env import load_env_files
from shared.logging import setup_logger
from shared.stream_client import ResilientDingTalkStreamClient


logger = setup_logger("%(asctime)s %(name)s %(levelname)-8s %(message)s", "INFO")


@dataclass
class Config:
    client_id: str
    client_secret: str
    robot_code: str
    workspace: str
    stream_ws_ping_interval: int
    stream_ws_ping_timeout: int


def _load_env_files() -> None:
    load_env_files([Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"])


def _read_positive_int_env(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    parsed = int(raw)
    if parsed <= 0:
        raise RuntimeError(f"{key} must be > 0")
    return parsed


def _load_config_from_env() -> Config:
    _load_env_files()
    client_id = os.getenv("DING_CLIENT_ID", "").strip()
    client_secret = os.getenv("DING_CLIENT_SECRET", "").strip()
    robot_code = os.getenv("DING_ROBOT_CODE", "").strip()
    workspace = os.getenv("PDF_SPLIT_WORKSPACE", str(Path.cwd() / ".bot-workspace"))
    missing = [name for name, value in {
        "DING_CLIENT_ID": client_id,
        "DING_CLIENT_SECRET": client_secret,
        "DING_ROBOT_CODE": robot_code,
    }.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    return Config(
        client_id=client_id,
        client_secret=client_secret,
        robot_code=robot_code,
        workspace=workspace,
        stream_ws_ping_interval=_read_positive_int_env("DING_STREAM_WS_PING_INTERVAL", 30),
        stream_ws_ping_timeout=_read_positive_int_env("DING_STREAM_WS_PING_TIMEOUT", 120),
    )



def main() -> None:
    config = _load_config_from_env()
    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = ResilientDingTalkStreamClient(
        credential,
        ping_interval=config.stream_ws_ping_interval,
        ping_timeout=config.stream_ws_ping_timeout,
        logger=logger,
    )
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        PdfSplitBotHandler(config=config),
    )
    client.start_forever()


if __name__ == "__main__":
    main()
