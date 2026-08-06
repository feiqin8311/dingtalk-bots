from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "http://hzpy.rtb56.com"
PUBLIC_SERVICE_PATH = "/webservice/PublicService.asmx/ServiceInterfaceUTF8"
# 并发查轨迹时偶发 >30s；默认 60 + 超时重试，避免误报 query_error
DEFAULT_TIMEOUT_SEC = 60.0
DEFAULT_RETRIES = 2


@dataclass(frozen=True)
class TrackEvent:
    occur_date: str
    location: str
    description: str
    track_code: str
    track_status: str
    track_status_name: str

    @property
    def dedup_key(self) -> str:
        return f"{self.occur_date}|{self.track_code}|{self.description}"


@dataclass(frozen=True)
class TrackShipment:
    reference_no: str
    tracking_no: str
    destination_country: str
    track_status: str
    track_status_name: str
    events: list[TrackEvent]

    def format_notify_line(self, event: TrackEvent, fba_code: str = "") -> str:
        # 文档：FBA编码 + 时间 + 状态
        # 例：FBA19FYM2YQK 2026-06-18 船只从始发港离港
        code = (fba_code or self.reference_no or self.tracking_no).strip()
        when = (event.occur_date or "").strip()
        if " " in when:
            when = when.split(" ", 1)[0]
        status = (event.description or "").strip()
        return f"{code} {when} {status}".strip()


class PingyiClient:
    """软通宝/平谊 PublicService（ServiceInterfaceUTF8）。"""

    def __init__(
        self,
        app_token: str,
        app_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        if not app_token or not app_key:
            raise ValueError("pingyi appToken/appKey required")
        self.app_token = app_token
        self.app_key = app_key
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = max(5.0, float(timeout_sec))
        self.retries = max(0, int(retries))

    def call(self, service_method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = urllib.parse.urlencode(
            {
                "appToken": self.app_token,
                "appKey": self.app_key,
                "serviceMethod": service_method,
                "paramsJson": json.dumps(params or {}, ensure_ascii=False),
            }
        ).encode("utf-8")
        url = f"{self.base_url}{PUBLIC_SERVICE_PATH}"
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        attempts = self.retries + 1
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"pingyi HTTP {exc.code}: {detail}") from exc
            except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as exc:
                last_exc = exc
                # URLError.reason 可能是 timeout；瞬时网络也重试
                if attempt + 1 >= attempts:
                    raise
                time.sleep(min(2.0 * (attempt + 1), 5.0))
        else:
            assert last_exc is not None
            raise last_exc
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError(f"pingyi unexpected response type: {type(data)}")
        return data

    def get_track(self, number: str) -> TrackShipment | None:
        """用跟踪号或 FBA 参考号查轨迹。"""
        number = (number or "").strip()
        if not number:
            raise ValueError("tracking/reference number required")
        result = self.call("getTrack", {"tracking_number": number})
        if not result.get("success"):
            msg = result.get("cnmessage") or result.get("enmessage") or str(result)
            if "不存在" in str(msg):
                return None
            raise RuntimeError(f"getTrack failed: {msg}")
        rows = result.get("data") or []
        if not rows:
            return None
        row = rows[0]
        events = [
            TrackEvent(
                occur_date=str(item.get("track_occur_date") or "").strip(),
                location=str(item.get("track_location") or "").strip(),
                description=str(item.get("track_description") or "").strip(),
                track_code=str(item.get("track_code") or "").strip(),
                track_status=str(item.get("track_status") or "").strip(),
                track_status_name=str(
                    item.get("track_status_cnname") or item.get("track_status_name") or ""
                ).strip(),
            )
            for item in (row.get("details") or [])
        ]
        # API 返回 details 新→旧；通知时按时间正序更直观
        events.sort(key=lambda e: e.occur_date)
        return TrackShipment(
            reference_no=str(row.get("shipper_hawbcode") or "").strip(),
            tracking_no=str(row.get("server_hawbcode") or "").strip(),
            destination_country=str(row.get("destination_country") or "").strip(),
            track_status=str(row.get("track_status") or "").strip(),
            track_status_name=str(row.get("track_status_name") or "").strip(),
            events=events,
        )

    def get_tracking_number(self, reference_no: str) -> dict[str, Any] | None:
        reference_no = (reference_no or "").strip()
        if not reference_no:
            raise ValueError("reference_no required")
        result = self.call("getTrackingNumber", {"reference_no": reference_no})
        if not result.get("success"):
            msg = result.get("cnmessage") or result.get("enmessage") or str(result)
            if "不能为空" in str(msg):
                raise RuntimeError(f"getTrackingNumber failed: {msg}")
            return None
        data = result.get("data")
        return data if isinstance(data, dict) else None

    def get_shipping_methods(self) -> list[dict[str, Any]]:
        result = self.call("getShippingMethod", {})
        if result.get("success") == 0 and "data" not in result:
            msg = result.get("cnmessage") or result.get("enmessage") or str(result)
            raise RuntimeError(f"getShippingMethod failed: {msg}")
        data = result.get("data") or []
        return data if isinstance(data, list) else []
