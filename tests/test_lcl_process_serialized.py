from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class LclProcessSerializedTest(unittest.TestCase):
    def test_messages_never_overlap_even_when_handler_awaits(self):
        """Heavy lcl steps run in threads; the process lock must keep messages one-at-a-time,
        otherwise a 2nd shipment could slip past the 'logistics busy' check mid-packing."""
        from apps.lcl_bot.handlers import WorkflowBotHandler

        handler = WorkflowBotHandler.__new__(WorkflowBotHandler)  # skip DingTalk/state init
        handler._process_lock = asyncio.Lock()
        active = 0
        max_active = 0
        order: list[str] = []

        async def fake_unlocked(callback):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            order.append(f"start-{callback}")
            await asyncio.sleep(0.01)  # stands in for to_thread(packing)
            order.append(f"end-{callback}")
            active -= 1
            return "OK", callback

        handler._process_unlocked = fake_unlocked

        async def run():
            return await asyncio.gather(handler.process("a"), handler.process("b"))

        results = asyncio.run(run())

        self.assertEqual(max_active, 1)
        self.assertEqual(order, ["start-a", "end-a", "start-b", "end-b"])
        self.assertEqual(results, [("OK", "a"), ("OK", "b")])

    def test_reset_waits_for_upload_and_preserves_operations_jobs(self):
        from apps.lcl_bot.handlers import WorkflowBotHandler
        from apps.lcl_bot.state_manager import StateManager

        async def run(folder):
            handler = WorkflowBotHandler.__new__(WorkflowBotHandler)
            handler.logger = logging.getLogger(__name__)
            handler._process_lock = asyncio.Lock()
            handler.state_manager = state = StateManager(str(folder / "state.json"))
            workflow = folder / "logistics"
            workflow.mkdir()
            state.activate_ops_job("ops", {"packing_result_path": "active.xlsx"})
            state.enqueue_ops_job("ops", {"packing_result_path": "queued.xlsx"})
            started, resume = asyncio.Event(), asyncio.Event()

            async def upload(_):
                started.set()
                await resume.wait()
                state.set_logistics_uploaded("owner", "in.xlsx", "out.xlsx", "chat", workflow_folder_path=str(workflow))

            handler._process_unlocked = upload
            uploading = asyncio.create_task(handler.process(None))
            await started.wait()
            resetting = asyncio.create_task(handler.reset_logistics_for_user("owner"))
            await asyncio.sleep(0)
            self.assertFalse(resetting.done())
            resume.set()
            await asyncio.gather(uploading, resetting)

            self.assertEqual(state.logistics_phase(), "IDLE")
            self.assertTrue(workflow.exists())
            self.assertEqual(state.state["ops_active"]["ops"]["packing_result_path"], "active.xlsx")
            self.assertEqual(state.state["ops_queue"]["ops"][0]["packing_result_path"], "queued.xlsx")

            state.set_logistics_uploaded("owner", "in.xlsx", "out.xlsx", "chat")
            await handler.reset_logistics_for_user("other-user")
            self.assertEqual(state.logistics_phase(), "UPLOADED")

        with TemporaryDirectory() as tmp:
            asyncio.run(run(Path(tmp)))

    def test_slow_reply_does_not_block_other_messages(self):
        from apps.lcl_bot.handlers import WorkflowBotHandler
        from apps.lcl_bot.utils import DingTalkAPI

        async def run():
            handler = WorkflowBotHandler.__new__(WorkflowBotHandler)
            handler.logger = logging.getLogger(__name__)
            loop = asyncio.get_running_loop()
            loop_thread = get_ident()
            started, release = asyncio.Event(), Event()
            thread_ids = []

            def post(*_, **__):
                thread_ids.append(get_ident())
                loop.call_soon_threadsafe(started.set)
                release.wait(2)
                return Mock(json=Mock(return_value={"errcode": 0}))

            handler.dingtalk_api = DingTalkAPI("id", "secret")
            message = SimpleNamespace(session_webhook="https://webhook.test", sender_staff_id="staff")
            with patch("apps.lcl_bot.utils.requests.post", side_effect=post) as request:
                replying = asyncio.create_task(handler._send_text_reply("reply", message))
                try:
                    await asyncio.wait_for(started.wait(), timeout=2)
                    self.assertFalse(replying.done())
                finally:
                    release.set()
                    await replying
                self.assertEqual(len(thread_ids), 1)
                self.assertNotEqual(thread_ids[0], loop_thread)
                self.assertEqual(request.call_args.kwargs["timeout"], 10)
                self.assertEqual(request.call_args.kwargs["json"]["at"], {"atUserIds": ["staff"]})

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
