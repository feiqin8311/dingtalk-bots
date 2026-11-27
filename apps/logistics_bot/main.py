#!/usr/bin/env python
from __future__ import annotations

import sys
import threading
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


ROOT_DIR = _find_repo_root(Path(__file__).resolve().parent)

import dingtalk_stream

from apps.logistics_bot.settings import load_config_from_env
from apps.logistics_bot.router import LogisticsRouter
from shared.logging import setup_logger
from shared.stream_client import ResilientDingTalkStreamClient


_TRACK_NOTIFY_RESTART_BASE_SEC = 30
_TRACK_NOTIFY_RESTART_MAX_SEC = 30 * 60
# a run that lasted this long counts as healthy: reset the backoff
_TRACK_NOTIFY_HEALTHY_RUN_SEC = 10 * 60


def _start_track_notify_daemon(logger) -> None:
    """Mon/Wed 10:00 轨迹查询：子进程跑，让定时任务和 Stream 独立运行。

    子进程退出后按指数退避自动重启（30s → 最长 30min），否则调度会静默停掉。
    """
    import subprocess
    import time

    track_main_path = ROOT_DIR / "apps" / "track_notify" / "main.py"
    if not track_main_path.is_file():
        logger.warning("track_notify: main.py missing, scheduler disabled")
        return

    def _target() -> None:
        delay = _TRACK_NOTIFY_RESTART_BASE_SEC
        while True:
            started = time.monotonic()
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "apps.track_notify.main", "--daemon"],
                    cwd=str(ROOT_DIR),
                )
                code = proc.wait()
                logger.error("track_notify daemon exited code=%s", code)
            except Exception:
                logger.exception("track_notify daemon crashed")
            if time.monotonic() - started >= _TRACK_NOTIFY_HEALTHY_RUN_SEC:
                delay = _TRACK_NOTIFY_RESTART_BASE_SEC
            logger.warning("track_notify daemon restarting in %ss", delay)
            time.sleep(delay)
            delay = min(delay * 2, _TRACK_NOTIFY_RESTART_MAX_SEC)

    threading.Thread(target=_target, name="track-notify", daemon=True).start()
    logger.info("track_notify subprocess scheduler started (Mon/Wed 10:00 Asia/Shanghai)")


def main() -> None:
    logger = setup_logger("%(asctime)s %(name)s %(levelname)-8s %(message)s", "INFO")
    config = load_config_from_env()
    _start_track_notify_daemon(logger)
    credential = dingtalk_stream.Credential(config.client_id, config.client_secret)
    client = ResilientDingTalkStreamClient(
        credential,
        ping_interval=config.stream_ws_ping_interval,
        ping_timeout=config.stream_ws_ping_timeout,
        logger=logger,
    )
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        LogisticsRouter(logger=logger, config=config),
    )
    logger.info("Logistics bot is running. Waiting for messages...")
    client.start_forever()


if __name__ == "__main__":
    main()
