from __future__ import annotations

import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import dingtalk_stream
import requests

from shared import stream_client
from shared.stream_client import ResilientDingTalkStreamClient


class _StopLoop(BaseException):
    """Breaks the client's infinite reconnect loop from inside a test."""


class _FakeWebsocket:
    def __init__(self, frames):
        self._frames = list(frames)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _client() -> ResilientDingTalkStreamClient:
    client = ResilientDingTalkStreamClient(
        dingtalk_stream.Credential("id", "secret"),
        ping_interval=30,
        ping_timeout=120,
        logger=MagicMock(spec=logging.Logger),
    )
    client.pre_start = MagicMock()
    return client


class StreamClientTests(unittest.TestCase):
    def test_dispatches_json_frames_skips_bad_ones_and_cancels_keepalive(self):
        client = _client()
        client.open_connection = MagicMock(return_value={"endpoint": "wss://x", "ticket": "a+b"})
        handled: list[dict] = []

        async def background_task(message):
            handled.append(message)

        keepalive_cancelled = asyncio.Event()

        async def keepalive(_ws):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                keepalive_cancelled.set()
                raise

        client.background_task = background_task
        client.keepalive = keepalive
        connect = MagicMock(return_value=_FakeWebsocket(['{"type": "CALLBACK"}', "not-json"]))

        async def run():
            real_sleep = asyncio.sleep

            async def fake_sleep(_delay):
                await real_sleep(0)  # let spawned tasks and the cancellation run
                raise _StopLoop

            with patch.object(stream_client.websockets, "connect", connect), patch.object(
                stream_client.asyncio, "sleep", fake_sleep
            ):
                with self.assertRaises(_StopLoop):
                    await client.start()
            await real_sleep(0)

        asyncio.run(run())

        self.assertEqual(handled, [{"type": "CALLBACK"}])
        self.assertTrue(keepalive_cancelled.is_set())
        self.assertEqual(connect.call_args.args[0], "wss://x?ticket=a%2Bb")
        client.logger.warning.assert_any_call("stream websocket closed, reconnecting")
        self.assertEqual(client._tasks, set())

    def test_connection_errors_are_logged_not_swallowed(self):
        client = _client()
        client.open_connection = MagicMock(side_effect=RuntimeError("boom"))

        async def run():
            with patch.object(stream_client.asyncio, "sleep", AsyncMock(side_effect=_StopLoop)):
                with self.assertRaises(_StopLoop):
                    await client.start()

        asyncio.run(run())
        client.logger.exception.assert_called_once()

    def test_ticket_timeout_retries_with_same_subscriptions(self):
        client = _client()
        client._is_event_required = True
        client.callback_handler_map["/callback"] = object()
        client.get_host_ip = MagicMock(return_value="127.0.0.1")
        response = MagicMock()
        response.json.return_value = {"endpoint": "wss://stream.test", "ticket": "new-ticket"}
        connected = MagicMock(side_effect=_StopLoop)

        async def run():
            with patch.object(stream_client.requests, "post", side_effect=[requests.Timeout(), response]) as post, patch.object(
                stream_client.websockets, "connect", connected
            ), patch.object(stream_client.asyncio, "sleep", AsyncMock()) as sleep:
                with self.assertRaises(_StopLoop):
                    await client.start()
                self.assertEqual(post.call_count, 2)
                for call in post.call_args_list:
                    self.assertEqual(call.kwargs["timeout"], 10)
                    self.assertEqual(call.kwargs["json"]["subscriptions"], [
                        {"type": "EVENT", "topic": "*"},
                        {"type": "CALLBACK", "topic": "/callback"},
                    ])
                sleep.assert_awaited_once_with(stream_client._RECONNECT_DELAY_SEC)

        asyncio.run(run())
        response.raise_for_status.assert_called_once_with()
        client.logger.exception.assert_called_once()
        self.assertEqual(connected.call_args.args[0], "wss://stream.test?ticket=new-ticket")


if __name__ == "__main__":
    unittest.main()
