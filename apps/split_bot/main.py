#!/usr/bin/env python
from __future__ import annotations

import asyncio
import json
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
import websockets

from Bot.handler import PdfSplitBotHandler
from shared.env import load_env_files
from shared.logging import setup_logger


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


class ResilientDingTalkStreamClient(dingtalk_stream.DingTalkStreamClient):
    def __init__(self, credential: dingtalk_stream.Credential, ping_interval: int, ping_timeout: int):
        super().__init__(credential)
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout

    async def start(self):
        self.pre_start()
        while True:
            try:
                connection = self.open_connection()
                if not connection:
                    await asyncio.sleep(10)
                    continue
                uri = f"{connection['endpoint']}?ticket={connection['ticket']}"
                async with websockets.connect(
                    uri,
                    ping_interval=self._ping_interval,
                    ping_timeout=self._ping_timeout,
                    close_timeout=10,
                ) as websocket:
                    self.websocket = websocket
                    asyncio.create_task(self.keepalive(websocket))
                    async for raw_message in websocket:
                        asyncio.create_task(self.background_task(json.loads(raw_message)))
            except KeyboardInterrupt:
                break
            except Exception:
                await asyncio.sleep(3)
                continue


def main() -> None:
    config = _load_config_from_env()
    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = ResilientDingTalkStreamClient(
        credential,
        ping_interval=config.stream_ws_ping_interval,
        ping_timeout=config.stream_ws_ping_timeout,
    )
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        PdfSplitBotHandler(config=config),
    )
    client.start_forever()


if __name__ == "__main__":
    main()
