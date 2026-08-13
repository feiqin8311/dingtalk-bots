from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "apps") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps"))


class LclLingxingDeleteTest(unittest.TestCase):
    def test_helper_is_in_repo_client(self):
        helper = importlib.import_module("lcl_bot.lingxing_helper")
        api = importlib.import_module("lcl_bot.lingxing_api")
        self.assertIs(helper.delete_shipment_list, api.delete_shipment_list)

    def test_delete_posts_shipment_list(self):
        api = importlib.import_module("lcl_bot.lingxing_api")

        async def _run():
            client = object.__new__(api.LingXingClient)
            client.request = AsyncMock(return_value={"code": 0, "message": "ok"})
            with patch.object(api, "LingXingClient", return_value=client):
                resp = await api.delete_shipment_list(["SP260119001"])
            self.assertEqual(resp["code"], 0)
            client.request.assert_awaited_once_with(
                "/basicOpen/openapi/fbaShipment/deleteShipmentList",
                "POST",
                req_body={"shipment_nos": ["SP260119001"]},
            )

        asyncio.run(_run())

    def test_delete_rejects_empty(self):
        api = importlib.import_module("lcl_bot.lingxing_api")
        with self.assertRaises(api.LingXingApiError):
            asyncio.run(api.delete_shipment_list([]))


if __name__ == "__main__":
    unittest.main()
