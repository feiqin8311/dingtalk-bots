"""LingXing shipment query helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def is_param_error(response: Dict[str, Any]) -> bool:
    code = response.get("code") or response.get("Code") or response.get("status")
    msg = response.get("message") or response.get("msg") or response.get("Message") or ""
    return str(code) == "102" or "参数错误" in str(msg)


async def fetch_shipment_detail_with_fallback(client: Any, shipment_sns: List[str]) -> Dict[str, Any]:
    response = await client.fetch_shipment_list_detail(shipment_sns)
    if not is_param_error(response):
        return response
    return await client._request(  # type: ignore[attr-defined]
        client.ROUTE_SHIPMENT_LIST_DETAIL,
        req_body={"shipment_sn_arr": shipment_sns},
    )
