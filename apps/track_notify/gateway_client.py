from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from pingyi_client import TrackEvent, TrackShipment

DEFAULT_GATEWAY_BASE = "http://host.docker.internal:18743"
_AGL_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def normalize_agl_time(raw: str) -> str:
    """AGL 时间 → YYYY-MM-DD；无日期则原样（可能是 —）。"""
    text = (raw or "").strip()
    if not text or text in {"—", "-", "–"}:
        return ""
    m = _AGL_DATE_RE.search(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 已是 2026-06-18 之类
    if re.match(r"\d{4}-\d{1,2}-\d{1,2}", text):
        return text.split(" ", 1)[0]
    return text.split(" ", 1)[0]


class LogisticsGatewayClient:
    """公网物流查询网关：龙舟 AGL 直查走 /api/fba/query。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_sec: float = 240,
    ) -> None:
        if not base_url:
            raise ValueError("gateway base_url required")
        if not api_key:
            raise ValueError("gateway api_key required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    def query_longzhou(
        self,
        logistics_no: str,
        *,
        brand: str = "",
        platform: str = "agl",
    ) -> TrackShipment | None:
        """
        文档：logistics_no 直查，不读钉钉表。
        body: logistics_no + brand + platform=agl；fba_code 可不传。
        """
        logistics_no = (logistics_no or "").strip()
        if not logistics_no:
            raise ValueError("logistics_no required")
        payload: dict[str, Any] = {
            "logistics_no": logistics_no,
            "platform": (platform or "agl").strip() or "agl",
            "include_order": False,
            "include_tracking": True,
        }
        brand = (brand or "").strip()
        if brand:
            payload["brand"] = brand

        body = self._post_json("/api/fba/query", payload)
        if not body.get("success"):
            err = body.get("error") or str(body)
            if any(x in str(err) for x in ("不存在", "未找到", "无轨迹", "no track")):
                return None
            raise RuntimeError(f"gateway fba/query failed: {err}")

        data = body.get("data") or {}
        if not isinstance(data, dict):
            return None
        track_block = data.get("物流查询结果")
        if not isinstance(track_block, dict):
            return None

        events: list[TrackEvent] = []
        for item in track_block.get("物流轨迹") or []:
            if not isinstance(item, dict):
                continue
            when = normalize_agl_time(str(item.get("时间") or ""))
            desc = str(item.get("内容") or "").strip()
            if not desc:
                continue
            events.append(
                TrackEvent(
                    occur_date=when,
                    location="",
                    description=desc,
                    track_code="",
                    track_status="",
                    track_status_name="",
                )
            )
        if not events:
            latest = track_block.get("最新轨迹")
            if isinstance(latest, dict):
                desc = str(latest.get("内容") or "").strip()
                if desc:
                    events.append(
                        TrackEvent(
                            occur_date=normalize_agl_time(str(latest.get("时间") or "")),
                            location="",
                            description=desc,
                            track_code="",
                            track_status="",
                            track_status_name="",
                        )
                    )
        if not events:
            return None

        # 轨迹列表可能是新→旧；通知前按时间字符串排序（空日期垫后）
        events.sort(key=lambda e: e.occur_date or "9999")
        query_val = str(track_block.get("查询值") or logistics_no).strip()
        return TrackShipment(
            reference_no=query_val,
            tracking_no=query_val,
            destination_country="",
            track_status="",
            track_status_name=str((track_block.get("最新轨迹") or {}).get("内容") or "").strip()
            if isinstance(track_block.get("最新轨迹"), dict)
            else "",
            events=events,
        )

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"gateway HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"gateway unavailable: {exc}") from exc
        if not text:
            return {}
        data = json.loads(text)
        if not isinstance(data, dict):
            raise RuntimeError(f"gateway unexpected response type: {type(data)}")
        return data
