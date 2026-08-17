from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pingyi_client import TrackEvent, TrackShipment


DEFAULT_BASE_URL = "https://www.szaaf.com"
TOKEN_PATH = "/v1/user/oauth/token"
TRACK_PATH = "/v1/track/aafOrderTrack/getTrackInfo"
# 文档公开的应用凭证；账号用 MEITONG_USERNAME / MEITONG_PASSWORD
DEFAULT_CLIENT_ID = "aaf"
DEFAULT_CLIENT_SECRET = "aaf88888888"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_RETRIES = 2
_NO_ORDER_MARKERS = ("无此订单", "不存在")


class MeitongClient:
    """美通 V1.0：oauth/token + getTrackInfo（orderNo=物流编号）。"""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        if not username or not password:
            raise ValueError("meitong username/password required")
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = max(5.0, float(timeout_sec))
        self.retries = max(0, int(retries))
        self._lock = threading.Lock()
        self._token = ""
        self._token_expire_at = 0.0

    def get_track(self, order_no: str) -> TrackShipment | None:
        order_no = (order_no or "").strip()
        if not order_no:
            raise ValueError("order_no required")
        body = self._get_track_body(order_no, allow_refresh=True)
        if not body.get("success") or int(body.get("code") or 0) != 200:
            msg = str(body.get("message") or body)
            if any(m in msg for m in _NO_ORDER_MARKERS):
                return None
            raise RuntimeError(f"getTrackInfo failed: {msg}")
        rows = body.get("data") or []
        if not isinstance(rows, list) or not rows:
            return None
        events = [
            TrackEvent(
                occur_date=str(item.get("eventTime") or "").strip(),
                location=str(item.get("location") or "").strip(),
                description=str(item.get("content") or "").strip(),
                track_code=str(item.get("eventTimeType") or "").strip(),
                track_status="",
                track_status_name="",
            )
            for item in rows
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]
        if not events:
            return None
        events.sort(key=lambda e: e.occur_date or "9999")
        latest = events[-1].description
        return TrackShipment(
            reference_no=order_no,
            tracking_no=order_no,
            destination_country="",
            track_status="",
            track_status_name=latest,
            events=events,
        )

    def _get_track_body(self, order_no: str, *, allow_refresh: bool) -> dict[str, Any]:
        url = (
            f"{self.base_url}{TRACK_PATH}?"
            + urllib.parse.urlencode({"orderNo": order_no})
        )
        token = self._ensure_token()
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            raw = self._urlopen(req)
        except RuntimeError as exc:
            if allow_refresh and "HTTP 401" in str(exc):
                self._invalidate_token()
                return self._get_track_body(order_no, allow_refresh=False)
            raise
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError(f"meitong unexpected response type: {type(data)}")
        return data

    def _ensure_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_expire_at - 60:
                return self._token
            body = urllib.parse.urlencode(
                {
                    "grant_type": "password",
                    "client_id": DEFAULT_CLIENT_ID,
                    "client_secret": DEFAULT_CLIENT_SECRET,
                    "username": self.username,
                    "password": self.password,
                    "login_type": "api_key",
                    "user_type": "1",
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}{TOKEN_PATH}",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            raw = self._urlopen(req)
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise RuntimeError(f"meitong token unexpected type: {type(data)}")
            token = str(data.get("access_token") or "").strip()
            if not token or int(data.get("code") or 0) != 200:
                raise RuntimeError(
                    f"meitong oauth failed: {data.get('message') or data}"
                )
            self._token = token
            expires = float(data.get("expires_in") or 3600)
            self._token_expire_at = time.time() + max(60.0, expires)
            return token

    def _invalidate_token(self) -> None:
        with self._lock:
            self._token = ""
            self._token_expire_at = 0.0

    def _urlopen(self, req: urllib.request.Request) -> str:
        attempts = self.retries + 1
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code == 401:
                    raise RuntimeError(f"meitong HTTP 401: {detail}") from exc
                if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    last_exc = RuntimeError(f"meitong HTTP {exc.code}: {detail}")
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
                    continue
                raise RuntimeError(f"meitong HTTP {exc.code}: {detail}") from exc
            except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    raise RuntimeError(f"meitong request failed: {exc}") from exc
                time.sleep(min(2.0 * (attempt + 1), 5.0))
        assert last_exc is not None
        raise RuntimeError(f"meitong request failed: {last_exc}") from last_exc
