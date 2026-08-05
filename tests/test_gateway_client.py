from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from gateway_client import LogisticsGatewayClient, normalize_agl_time  # noqa: E402


SAMPLE_AGL = {
    "success": True,
    "data": {
        "物流编号": "AL0-UC54XYYFYNEW2",
        "命中平台": "agl",
        "物流查询结果": {
            "平台": "AGL",
            "查询值": "AL0-UC54XYYFYNEW2",
            "账号来源": "AGL_YPLUS",
            "最新轨迹": {
                "时间": "2026年8月4日 GMT+8 12:29",
                "内容": "在CFS收到货物",
            },
            "物流轨迹": [
                {"时间": "2026年8月4日 GMT+8 12:29", "内容": "在CFS收到货物"},
                {"时间": "2026年7月30日 GMT+8 11:24", "内容": "收到预订"},
                {"时间": "—", "内容": "已装船"},
            ],
        },
    },
    "error": None,
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


class GatewayClientTests(unittest.TestCase):
    def test_normalize_agl_time(self):
        self.assertEqual(normalize_agl_time("2026年8月4日 GMT+8 12:29"), "2026-08-04")
        self.assertEqual(normalize_agl_time("—"), "")
        self.assertEqual(normalize_agl_time("2026-06-18 10:00"), "2026-06-18")

    def test_query_longzhou_parses_and_sorts(self):
        client = LogisticsGatewayClient("http://example.test", "token")
        captured: dict = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["key"] = req.headers.get("X-api-key") or req.headers.get("X-Api-Key")
            return FakeResponse(SAMPLE_AGL)

        with patch("gateway_client.urllib.request.urlopen", side_effect=fake_urlopen):
            shipment = client.query_longzhou(
                "AL0-UC54XYYFYNEW2", brand="YPLUS", platform="agl"
            )

        self.assertIsNotNone(shipment)
        assert shipment is not None
        self.assertEqual(captured["body"]["logistics_no"], "AL0-UC54XYYFYNEW2")
        self.assertEqual(captured["body"]["brand"], "YPLUS")
        self.assertEqual(captured["body"]["platform"], "agl")
        self.assertNotIn("fba_code", captured["body"])
        self.assertEqual(len(shipment.events), 3)
        # 有日期的排在前
        self.assertEqual(shipment.events[0].description, "收到预订")
        self.assertEqual(shipment.events[0].occur_date, "2026-07-30")
        line = shipment.format_notify_line(shipment.events[1], fba_code="AL0-UC54XYYFYNEW2")
        self.assertIn("AL0-UC54XYYFYNEW2", line)
        self.assertIn("在CFS收到货物", line)


if __name__ == "__main__":
    unittest.main()
