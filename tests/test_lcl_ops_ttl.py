from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "apps") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps"))


class LclOpsTtlTest(unittest.TestCase):
    def setUp(self) -> None:
        from lcl_bot.state_manager import StateManager

        self._tmp = tempfile.TemporaryDirectory()
        self.sm = StateManager(state_file_path=str(Path(self._tmp.name) / "workflow_state.json"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _job(self, path: str, *, status="WAIT_AMAZON", age_days=0, created=True):
        now = datetime.now() - timedelta(days=age_days)
        job = {
            "packing_result_path": path,
            "status": status,
        }
        if created:
            job["created_at"] = now.isoformat()
            job["updated_at"] = now.isoformat()
        return job

    def test_expire_old_wait_amazon(self):
        self.sm.state["ops_active"] = {
            "staff": self._job("/a.xlsx", age_days=4),
            "fresh": self._job("/b.xlsx", age_days=1),
            "delete": self._job("/c.xlsx", status="WAIT_DELETE_CONFIRMATION", age_days=10),
        }
        dropped = self.sm.expire_stale_ops_jobs(ttl_sec=3 * 86400)
        self.assertEqual(dropped, ["staff"])
        active = self.sm.state["ops_active"]
        self.assertIn("fresh", active)
        self.assertIn("delete", active)
        self.assertNotIn("staff", active)

    def test_expire_missing_timestamp_wait_amazon(self):
        self.sm.state["ops_active"] = {"ghost": self._job("/g.xlsx", created=False)}
        dropped = self.sm.expire_stale_ops_jobs(ttl_sec=3 * 86400)
        self.assertEqual(dropped, ["ghost"])
        self.assertEqual(self.sm.state["ops_active"], {})

    def test_drop_ops_jobs_removes_alias_same_file(self):
        path = "/same.xlsx"
        self.sm.state["ops_active"] = {
            "17839075860894598": self._job(path),
            "$:LWCP_v1:$abc": self._job(path),
            "other": self._job("/other.xlsx"),
        }
        dropped = self.sm.drop_ops_jobs("17839075860894598")
        self.assertCountEqual(dropped, ["17839075860894598", "$:LWCP_v1:$abc"])
        self.assertEqual(list(self.sm.state["ops_active"]), ["other"])

    def test_ops_is_busy_false_after_expire(self):
        self.sm.state["ops_active"] = {"ops1": self._job("/old.xlsx", age_days=6)}
        self.assertFalse(self.sm.ops_is_busy("ops1"))
        self.assertEqual(self.sm.state["ops_active"], {})


if __name__ == "__main__":
    unittest.main()
