from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from dedup_store import TrackStateStore  # noqa: E402
from excel_export import ReportItem  # noqa: E402
from runner import _checkpoint_bucket, _item_from_dict  # noqa: E402


class PendingCheckpointTests(unittest.TestCase):
    def test_checkpoint_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.sqlite3"
            store = TrackStateStore(db)
            items = [
                ReportItem(
                    shipment_key="AL0-1",
                    event_key="lz:pod",
                    message="m",
                    user_ids=["u1", "u2"],
                    detail="已到达卸货港",
                    event_keys=["lz:pod"],
                ),
                ReportItem(
                    shipment_key="AL0-2",
                    event_key="query_error",
                    message="fail",
                    user_ids=["u1"],
                ),
            ]
            _checkpoint_bucket(store, items)
            self.assertEqual(store.pending_count(), 2)
            store.close()

            store2 = TrackStateStore(db)
            loaded = store2.load_pending_items()
            self.assertEqual(len(loaded), 2)
            restored = [_item_from_dict(r) for r in loaded]
            self.assertEqual(restored[0].shipment_key, "AL0-1")
            self.assertEqual(restored[0].user_ids, ["u1", "u2"])
            self.assertEqual(restored[0].event_keys, ["lz:pod"])
            store2.clear_pending_for([("AL0-1", "lz:pod")])
            self.assertEqual(store2.pending_count(), 1)
            store2.clear_all_pending()
            self.assertEqual(store2.pending_count(), 0)
            store2.close()


if __name__ == "__main__":
    unittest.main()
