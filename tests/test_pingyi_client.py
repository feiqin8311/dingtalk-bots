from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from pingyi_client import PingyiClient, TrackEvent  # noqa: E402


SAMPLE_TRACK = {
    "success": 1,
    "cnmessage": "获取跟踪记录成功",
    "data": [
        {
            "shipper_hawbcode": "FBA19JTBN929",
            "server_hawbcode": "PY1196336835",
            "destination_country": "US",
            "track_status": "NC",
            "track_status_name": "清关中",
            "details": [
                {
                    "track_occur_date": "2026-07-28 13:44:30",
                    "track_location": "CNNBG",
                    "track_description": "货件在国内完成出口报关",
                    "track_code": "BG",
                    "track_status": "NC",
                    "track_status_cnname": "清关中",
                },
                {
                    "track_occur_date": "2026-07-27 14:52:38",
                    "track_location": "",
                    "track_description": "快件电子信息已经收到",
                    "track_code": "IR",
                    "track_status": "NO",
                    "track_status_cnname": "未上网",
                },
            ],
        }
    ],
}


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PingyiClientTests(unittest.TestCase):
    def test_get_track_parses_and_sorts(self):
        client = PingyiClient("token", "key")

        def fake_urlopen(req, timeout=0):
            return FakeResponse(SAMPLE_TRACK)

        with patch("pingyi_client.urllib.request.urlopen", side_effect=fake_urlopen):
            shipment = client.get_track("FBA19JTBN929")

        assert shipment is not None
        self.assertEqual(shipment.reference_no, "FBA19JTBN929")
        self.assertEqual(shipment.tracking_no, "PY1196336835")
        self.assertEqual(shipment.track_status_name, "清关中")
        self.assertEqual(len(shipment.events), 2)
        self.assertEqual(shipment.events[0].track_code, "IR")
        self.assertEqual(shipment.events[1].track_code, "BG")
        line = shipment.format_notify_line(shipment.events[1], fba_code="FBA19JTBN929")
        self.assertEqual(line, "FBA19JTBN929 2026-07-28 货件在国内完成出口报关")

    def test_missing_number_returns_none(self):
        client = PingyiClient("token", "key")

        def fake_urlopen(req, timeout=0):
            return FakeResponse(
                {"success": 0, "cnmessage": "跟踪号码不存在", "data": None}
            )

        with patch("pingyi_client.urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertIsNone(client.get_track("NOPE"))

    def test_event_dedup_key(self):
        event = TrackEvent(
            occur_date="2026-07-28 13:44:30",
            location="CNNBG",
            description="货件在国内完成出口报关",
            track_code="BG",
            track_status="NC",
            track_status_name="清关中",
        )
        self.assertIn("BG", event.dedup_key)


if __name__ == "__main__":
    unittest.main()
