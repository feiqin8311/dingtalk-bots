"""DingTalk Stream client with logged reconnects and tracked background tasks."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Coroutine, Optional
from urllib.parse import quote_plus

import dingtalk_stream
import websockets

_RECONNECT_DELAY_SEC = 3
_OPEN_CONNECTION_RETRY_SEC = 10


class ResilientDingTalkStreamClient(dingtalk_stream.DingTalkStreamClient):
    """Same protocol as the SDK client, but:

    - every reconnect reason is logged (the old copy swallowed all exceptions);
    - per-message tasks are held in a set so they cannot be garbage-collected mid-run;
    - the keepalive task of a dead connection is cancelled instead of piling up;
    - the blocking ``open_connection`` HTTP call runs in a worker thread.
    """

    def __init__(
        self,
        credential: dingtalk_stream.Credential,
        ping_interval: int,
        ping_timeout: int,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(credential, logger=logger)
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def start(self):
        self.pre_start()
        while True:
            keepalive: Optional[asyncio.Task] = None
            try:
                connection = await asyncio.to_thread(self.open_connection)
                if not connection:
                    self.logger.error("stream open_connection failed, retry in %ss", _OPEN_CONNECTION_RETRY_SEC)
                    await asyncio.sleep(_OPEN_CONNECTION_RETRY_SEC)
                    continue
                uri = f"{connection['endpoint']}?ticket={quote_plus(connection['ticket'])}"
                async with websockets.connect(
                    uri,
                    ping_interval=self._ping_interval,
                    ping_timeout=self._ping_timeout,
                    close_timeout=10,
                ) as websocket:
                    self.websocket = websocket
                    self.logger.info("stream connected")
                    keepalive = asyncio.create_task(self.keepalive(websocket))
                    async for raw_message in websocket:
                        try:
                            message = json.loads(raw_message)
                        except ValueError:
                            self.logger.warning("stream dropped non-JSON frame: %.200r", raw_message)
                            continue
                        self._spawn(self.background_task(message))
                self.logger.warning("stream websocket closed, reconnecting")
                await asyncio.sleep(1)  # avoid a hot loop if the server keeps closing at once
            except KeyboardInterrupt:
                break
            except Exception:
                self.logger.exception("stream connection error, reconnect in %ss", _RECONNECT_DELAY_SEC)
                await asyncio.sleep(_RECONNECT_DELAY_SEC)
            finally:
                if keepalive is not None:
                    keepalive.cancel()
