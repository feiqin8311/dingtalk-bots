from __future__ import annotations

import importlib.util
import logging
import shutil
import sys
import tempfile
import types
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

    pinxiang_mod = types.ModuleType("pinxiang_bot_handler")

    def _make_handler(*_a, **_k):
        h = MagicMock()
        h.has_pending = MagicMock(return_value=False)
        return h

    pinxiang_mod.PinxiangBotHandler = MagicMock(side_effect=_make_handler)

    lcl_handlers_mod = types.ModuleType("lcl_bot.handlers")
    lcl_handlers_mod.WorkflowBotHandler = MagicMock(side_effect=_make_handler)
    lcl_pkg = types.ModuleType("lcl_bot")
    lcl_pkg.handlers = lcl_handlers_mod

    class _Loader:
        def exec_module(self, mod):
            mod.PinxiangBotHandler = pinxiang_mod.PinxiangBotHandler

    class _Spec:
        loader = _Loader()

    with patch.dict(
        sys.modules,
        {
            "dingtalk_stream": MagicMock(),
            "dingtalk_stream.chatbot": MagicMock(),
            "handler": MagicMock(ShipmentQueryHandler=MagicMock()),
            "Bot.handler": MagicMock(PdfSplitBotHandler=MagicMock()),
            "Bot.runtime": MagicMock(collect_download_codes=lambda payload: payload.get("downloadCodes", [])),
            "Utils.dingtalk_api": MagicMock(),
            "pinxiang_bot_handler": pinxiang_mod,
            "lcl_bot": lcl_pkg,
            "lcl_bot.handlers": lcl_handlers_mod,
        },
    ):
        sys.modules["dingtalk_stream"].ChatbotHandler = object
        sys.modules["dingtalk_stream"].AckMessage = SimpleNamespace(STATUS_OK="OK")
        with patch("importlib.util.spec_from_file_location", return_value=_Spec()):
            with patch("importlib.util.module_from_spec", return_value=pinxiang_mod):
                spec.loader.exec_module(module)
    return module


class LogisticsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_router_module()
        self._state_dir = Path(tempfile.mkdtemp())
        self._state_path = self._state_dir / "selected_branch.json"
        self._path_patch = patch.object(self.module, "_BRANCH_STATE_PATH", self._state_path)
        self._path_patch.start()
        self.router = self.module.LogisticsRouter(
            logger=logging.getLogger("test"),
            config=SimpleNamespace(robot_code="", workspace="/tmp", pinxiang_workspace="/tmp"),
        )
        self.router.pinxiang_handler.has_pending = MagicMock(return_value=False)
        self.router.lcl_handler.has_pending = MagicMock(return_value=False)

    def tearDown(self) -> None:
        self._path_patch.stop()
        shutil.rmtree(self._state_dir, ignore_errors=True)

    def test_menu_choice_selects_cp_branch(self):
        self.assertEqual(self.router._route({"text": {"content": "1"}}, user_id="u1"), "select_cp")

    def test_menu_choice_selects_split_branch(self):
        self.assertEqual(self.router._route({"text": {"content": "2. 标签拆分"}}, user_id="u1"), "select_split")

    def test_menu_choice_selects_pinxiang_branch(self):
        self.assertEqual(self.router._route({"text": {"content": "3"}}, user_id="u1"), "select_pinxiang")

    def test_menu_choice_selects_lcl_branch(self):
        self.assertEqual(self.router._route({"text": {"content": "4"}}, user_id="u1"), "select_lcl")

    def test_lcl_branch_keeps_messages(self):
        self.router._set_branch("u1", "lcl")
        self.assertEqual(self.router._route({"text": {"content": "确认"}}, user_id="u1"), "lcl")
        self.assertEqual(
            self.router._route({"downloadCodes": ["x"], "text": {"content": ""}}, user_id="u1"),
            "lcl",
        )

    def test_selected_branch_routes_plain_text_to_cp(self):
        self.router._set_branch("u1", "cp")
        self.assertEqual(self.router._route({"text": {"content": "SP260204001"}}, user_id="u1"), "cp")

    def test_pinxiang_branch_keeps_confirm(self):
        self.router._set_branch("u1", "pinxiang")
        self.assertEqual(self.router._route({"text": {"content": "确认"}}, user_id="u1"), "pinxiang")
        self.assertEqual(
            self.router._route({"downloadCodes": ["x"], "text": {"content": ""}}, user_id="u1"),
            "pinxiang",
        )

    def test_stale_pinxiang_branch_yields_to_lcl_pending(self):
        """不分仓已结束、分支仍停在 pinxiang 时，模板2 / 装箱表进分仓。"""
        self.router._set_branch("u1", "pinxiang")
        self.router.pinxiang_handler.has_pending = MagicMock(return_value=False)
        self.router.lcl_handler.has_pending = MagicMock(return_value=True)
        self.assertEqual(self.router._route({"text": {"content": "模板2"}}, user_id="u1"), "lcl")
        self.assertEqual(
            self.router._route({"downloadCodes": ["x"], "text": {"content": ""}}, user_id="u1"),
            "lcl",
        )

    def test_stale_pinxiang_without_lcl_stays_pinxiang(self):
        self.router._set_branch("u1", "pinxiang")
        self.router.pinxiang_handler.has_pending = MagicMock(return_value=False)
        self.router.lcl_handler.has_pending = MagicMock(return_value=False)
        self.assertEqual(self.router._route({"text": {"content": "模板2"}}, user_id="u1"), "pinxiang")

    def test_pinxiang_pending_ops_choice_not_stolen_by_menu(self):
        """选运营时回复 1 不得进入发货单核对。"""
        self.router.pinxiang_handler.has_pending = MagicMock(return_value=True)
        self.assertEqual(self.router._route({"text": {"content": "1"}}, user_id="u1"), "pinxiang")
        self.assertEqual(self.router._route({"text": {"content": "2"}}, user_id="u1"), "pinxiang")

    def test_first_use_shipment_number_shows_menu(self):
        self.assertEqual(self.router._route({"text": {"content": "SP260204001"}}, user_id="u1"), "help")

    def test_first_use_split_keyword_shows_menu(self):
        self.assertEqual(self.router._route({"text": {"content": "帮我拆分PDF"}}, user_id="u1"), "help")

    def test_reset_command_resets_current_user(self):
        self.router._set_branch("u1", "split")
        self.assertEqual(self.router._route({"text": {"content": "重置"}}, user_id="u1"), "reset")
        self.router._reset_user("u1")
        self.assertNotIn("u1", self.router._selected_branch_by_user)

    def test_reset_then_menu_works_while_lcl_pending(self):
        """重置清的是分支，不该被分仓进行中任务卡住无法选菜单。"""
        self.router._set_branch("u1", "pinxiang")
        self.router.lcl_handler.has_pending = MagicMock(return_value=True)
        self.router._reset_user("u1")
        self.assertEqual(self.router._route({"text": {"content": "1"}}, user_id="u1"), "select_cp")

    def test_pinxiang_lcl_workbook_handoff_redispatches(self):
        import asyncio

        self.router._set_branch("u1", "pinxiang")
        self.router._extract_user_id = lambda _payload: "u1"
        self.router._route = lambda _payload, user_id="": "pinxiang"
        self.router._log_route_event = lambda *_a, **_k: None
        seen: list[str] = []

        async def _px(_cb):
            seen.append("px")
            return "OK", "HANDOFF_LCL"

        async def _lcl(_cb):
            seen.append("lcl")
            return "OK", "LCL_OK"

        self.router.pinxiang_handler.process = _px
        self.router.lcl_handler.process = _lcl
        status, ack = asyncio.run(self.router.process(MagicMock(data={"senderStaffId": "u1"})))
        self.assertEqual(seen, ["px", "lcl"])
        self.assertEqual((status, ack), ("OK", "LCL_OK"))
        self.assertEqual(self.router._selected_branch_by_user.get("u1"), "lcl")

    def test_branch_selection_persists_across_restart(self):
        self.router._set_branch("u1", "pinxiang")
        self.assertTrue(self._state_path.is_file())
        reloaded = self.module.LogisticsRouter(
            logger=logging.getLogger("test"),
            config=SimpleNamespace(robot_code="", workspace="/tmp", pinxiang_workspace="/tmp"),
        )
        reloaded.pinxiang_handler.has_pending = MagicMock(return_value=False)
        self.assertEqual(
            reloaded._route({"downloadCodes": ["x"], "text": {"content": ""}}, user_id="u1"),
            "pinxiang",
        )


if __name__ == "__main__":
    unittest.main()
