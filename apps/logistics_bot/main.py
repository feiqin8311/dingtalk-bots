#!/usr/bin/env python
from __future__ import annotations

import asyncio
import json
import sys
import threading
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
import websockets

from settings import load_config_from_env
from router import LogisticsRouter
from shared.logging import setup_logger


def _start_track_notify_daemon(logger) -> None:
    """Mon/Wed 00:00 轨迹查询，挂在主进程后台线程，不另起容器。"""
    import importlib.util

    track_main_path = ROOT_DIR / "apps" / "track_notify" / "main.py"
    if not track_main_path.is_file():
        logger.warning("track_notify: main.py missing, scheduler disabled")
        return
    spec = importlib.util.spec_from_file_location("track_notify_main", track_main_path)
    if not spec or not spec.loader:
        logger.warning("track_notify: cannot load main.py, scheduler disabled")
        return
    mod = importlib.util.module_from_spec(spec)
    sys.modules["track_notify_main"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        logger.exception("track_notify: import failed, scheduler disabled")
        return
    run_daemon = getattr(mod, "run_daemon", None)
    if not callable(run_daemon):
        logger.warning("track_notify: run_daemon missing, scheduler disabled")
        return

    def _target() -> None:
        try:
            run_daemon(dry_run=False)
        except Exception:
            logger.exception("track_notify daemon crashed")

    threading.Thread(target=_target, name="track-notify", daemon=True).start()
    logger.info("track_notify background scheduler started (Mon/Wed 00:00 Asia/Shanghai)")


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
    logger = setup_logger("%(asctime)s %(name)s %(levelname)-8s %(message)s", "INFO")
    config = load_config_from_env()
    _start_track_notify_daemon(logger)
    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = ResilientDingTalkStreamClient(
        credential,
        ping_interval=config.stream_ws_ping_interval,
        ping_timeout=config.stream_ws_ping_timeout,
    )
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        LogisticsRouter(logger=logger, config=config),
    )
    logger.info("Logistics bot is running. Waiting for messages...")
    client.start_forever()


if __name__ == "__main__":
    main()
