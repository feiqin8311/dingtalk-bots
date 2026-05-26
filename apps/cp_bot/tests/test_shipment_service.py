import unittest

from shipment_service import fetch_shipment_detail_with_fallback


class FakeLingXingClient:
    ROUTE_SHIPMENT_LIST_DETAIL = "/routing/shipment/listDetail"

    def __init__(self, first_response):
        self.first_response = first_response
        self.calls = []

    async def fetch_shipment_list_detail(self, shipment_sns):
        self.calls.append(("normal", list(shipment_sns)))
        return self.first_response

    async def _request(self, route, req_body):
        self.calls.append(("fallback", route, dict(req_body)))
        return {"code": 0, "data": [{"shipment_sn": req_body["shipment_sn_arr"][0]}]}


class ShipmentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_normal_detail_response_when_not_param_error(self):
        client = FakeLingXingClient({"code": 0, "data": [{"shipment_sn": "SP260421012"}]})

        response = await fetch_shipment_detail_with_fallback(client, ["SP260421012"])

        self.assertEqual({"code": 0, "data": [{"shipment_sn": "SP260421012"}]}, response)
        self.assertEqual([("normal", ["SP260421012"])], client.calls)

    async def test_falls_back_to_shipment_sn_arr_for_param_error(self):
        client = FakeLingXingClient({"code": 102, "message": "参数错误"})

        response = await fetch_shipment_detail_with_fallback(client, ["SP260421012"])

        self.assertEqual({"code": 0, "data": [{"shipment_sn": "SP260421012"}]}, response)
        self.assertEqual(
            [
                ("normal", ["SP260421012"]),
                ("fallback", client.ROUTE_SHIPMENT_LIST_DETAIL, {"shipment_sn_arr": ["SP260421012"]}),
            ],
            client.calls,
        )


if __name__ == "__main__":
    unittest.main()
