from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "apps") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps"))


class LclProcessSerializedTest(unittest.TestCase):
    def test_messages_never_overlap_even_when_handler_awaits(self):
        """Heavy lcl steps run in threads; the process lock must keep messages one-at-a-time,
        otherwise a 2nd shipment could slip past the 'logistics busy' check mid-packing."""
        from lcl_bot.handlers import WorkflowBotHandler

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


if __name__ == "__main__":
    unittest.main()
