from __future__ import annotations

import importlib.util
import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
LOGISTICS_DIR = ROOT / "apps" / "logistics_bot"
if str(LOGISTICS_DIR) not in sys.path:
    sys.path.insert(0, str(LOGISTICS_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_router_module():
    spec = importlib.util.spec_from_file_location("logistics_router_for_tests", LOGISTICS_DIR / "router.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with patch.dict(
        sys.modules,
        {
            "dingtalk_stream": MagicMock(),
            "dingtalk_stream.chatbot": MagicMock(),
            "handler": MagicMock(ShipmentQueryHandler=MagicMock()),
            "Bot.handler": MagicMock(PdfSplitBotHandler=MagicMock()),
            "Bot.runtime": MagicMock(collect_download_codes=lambda payload: payload.get("downloadCodes", [])),
            "Utils.dingtalk_api": MagicMock(),
        },
    ):
        sys.modules["dingtalk_stream"].ChatbotHandler = object
        sys.modules["dingtalk_stream"].AckMessage = SimpleNamespace(STATUS_OK="OK")
        spec.loader.exec_module(module)
    return module


class LogisticsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_router_module()
        self.router = self.module.LogisticsRouter(
            logger=logging.getLogger("test"),
            config=SimpleNamespace(robot_code="", workspace="/tmp"),
        )

    def test_menu_choice_selects_cp_branch(self):
        self.assertEqual(self.router._route({"text": {"content": "1"}}, user_id="u1"), "select_cp")

    def test_menu_choice_selects_split_branch(self):
        self.assertEqual(self.router._route({"text": {"content": "2. 标签拆分"}}, user_id="u1"), "select_split")

    def test_selected_branch_routes_plain_text_to_cp(self):
        self.router._selected_branch_by_user["u1"] = "cp"
        self.assertEqual(self.router._route({"text": {"content": "SP260204001"}}, user_id="u1"), "cp")

    def test_reset_command_resets_current_user(self):
        self.router._selected_branch_by_user["u1"] = "split"
        self.assertEqual(self.router._route({"text": {"content": "重置"}}, user_id="u1"), "reset")
        self.router._reset_user("u1")
        self.assertNotIn("u1", self.router._selected_branch_by_user)


if __name__ == "__main__":
    unittest.main()

