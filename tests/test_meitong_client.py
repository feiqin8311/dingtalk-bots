from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "track_notify"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from meitong_client import MeitongClient  # noqa: E402


SAMPLE_TRACK = {
    "success": True,
    "message": "查询成功",
    "code": 200,
    "data": [
        {
            "content": "您的订单已于2026-07-26 09:38:47离港。",
            "eventTime": "2026-07-26 09:38:47",
            "eventTimeType": "1",
            "location": "NINGBO",
        },
        {
            "content": "已下单",
            "eventTime": "2026-07-08 18:48:54",
            "eventTimeType": "1",
            "location": "国内地点",
        },
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


class MeitongClientTests(unittest.TestCase):
    def _client(self) -> MeitongClient:
        client = MeitongClient("user", "pass")
        client._token = "t"
        client._token_expire_at = time.time() + 3600
        return client

    def test_get_track_parses_and_sorts(self):
        client = self._client()

        def fake_urlopen(req, timeout=0):
            return FakeResponse(SAMPLE_TRACK)

        with patch("meitong_client.urllib.request.urlopen", side_effect=fake_urlopen):
            shipment = client.get_track("SHGB2607012839")

        assert shipment is not None
        self.assertEqual(shipment.reference_no, "SHGB2607012839")
        self.assertEqual(len(shipment.events), 2)
        self.assertEqual(shipment.events[0].description, "已下单")
        self.assertEqual(shipment.events[1].description, "您的订单已于2026-07-26 09:38:47离港。")
        self.assertEqual(shipment.events[1].location, "NINGBO")

    def test_missing_order_returns_none(self):
        client = self._client()
        payload = {
            "success": False,
            "code": 500,
            "message": "系统无此订单号对应的订单信息,请检查订单号是否正确",
            "data": None,
        }

        def fake_urlopen(req, timeout=0):
            return FakeResponse(payload)

        with patch("meitong_client.urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertIsNone(client.get_track("FBA15M0LXDZM"))
