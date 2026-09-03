from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "apps") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps"))


class LclDeleteStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        from lcl_bot.state_manager import StateManager, WorkflowState

        self.WorkflowState = WorkflowState
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = StateManager(state_file_path=str(Path(self._tmp.name) / "workflow_state.json"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_delete_status_preserved_across_logistics_reset(self):
        ops_id = "17839075860894598"
        job = {
            "packing_result_path": "/fake/SP260903004 拼箱数据.xlsx",
            "shipping_numbers": "SP260903004 SP260903003",
            "logistics_user_id": "17409662804279906",
            "status": "WAIT_AMAZON",
        }
        self.sm.activate_ops_job(ops_id, job)
        self.sm.release_logistics_session()

        # Ops uploads and completes, enters delete confirmation
        self.sm.set_operation_uploaded(ops_id, "/fake/Amazon_result.xlsx")
        self.sm.set_waiting_for_delete_confirmation(ops_id)

        self.assertEqual(self.sm.get_status(), self.WorkflowState.WAIT_DELETE_CONFIRMATION)
        self.assertTrue(self.sm.is_waiting_for_delete_confirmation(ops_id))
        self.assertEqual(
            self.sm.state["ops_active"][ops_id]["status"],
            self.WorkflowState.WAIT_DELETE_CONFIRMATION,
        )

        # Logistics performs reset
        self.sm.reset_logistics_only()

        # After logistics reset, status should still be WAIT_DELETE_CONFIRMATION
        self.assertEqual(self.sm.get_status(), self.WorkflowState.WAIT_DELETE_CONFIRMATION)
        self.assertTrue(self.sm.is_waiting_for_delete_confirmation(ops_id))
        self.assertTrue(self.sm.is_waiting_for_delete_confirmation())

    def test_is_waiting_for_delete_confirmation_with_active_job(self):
        ops_id = "ops_test_1"
        self.sm.state["ops_active"] = {
            ops_id: {
                "status": self.WorkflowState.WAIT_DELETE_CONFIRMATION,
                "shipping_numbers": "SP123",
            }
        }
        self.sm.state["status"] = self.WorkflowState.IDLE

        self.assertTrue(self.sm.is_waiting_for_delete_confirmation(ops_id))
        self.assertFalse(self.sm.is_waiting_for_delete_confirmation("other_ops"))


if __name__ == "__main__":
    unittest.main()
