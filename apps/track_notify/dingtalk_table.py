from __future__ import annotations

import json
import logging
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any


CST = timezone(timedelta(hours=8))
_log = logging.getLogger("track_notify")

# 瞬态网络/SSL：重试后仍失败再抛
_RETRYABLE = (
    TimeoutError,
    socket.timeout,
    ssl.SSLError,
    ConnectionError,
    urllib.error.URLError,
)


@dataclass
class TableRow:
    record_id: str
    invoice_no: str
    brand: str
    country: str
    carrier: str
    fba_codes: list[str]
    logistics_nos: list[str]
    eta_date: date | None
    delivered_at: date | None
    shipped_at: date | None = None  # 发货时间：钉钉毫秒时间戳 → date
    owners: list[dict[str, str]] = field(default_factory=list)
    channel: str = ""
    site: str = ""

    @property
    def owner_names(self) -> str:
        return ",".join(o.get("name") or o.get("unionId") or "" for o in self.owners)


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or "").strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("name") or item.get("unionId") or item.get("id") or ""))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p).strip()
    return str(value).strip()


def _split_codes(raw: Any) -> list[str]:
    text = _field_text(raw)
    if not text:
        return []
    out: list[str] = []
    for line in text.replace(",", "\n").replace("，", "\n").replace(";", "\n").splitlines():
        code = line.strip()
        if code and code not in out:
            out.append(code)
    return out


def _ts_to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
        if n > 10_000_000_000:
            n //= 1000
        return datetime.fromtimestamp(n, tz=CST).date()
    except (TypeError, ValueError, OSError):
        return None


def _owners(value: Any) -> list[dict[str, str]]:
    if not value:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        union_id = str(item.get("unionId") or item.get("unionid") or "").strip()
        name = str(item.get("name") or "").strip()
        if union_id or name:
            result.append({"unionId": union_id, "name": name})
    return result


class DingTalkNotableClient:
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        *,
        operator_union_id: str,
        api_base_url: str = "https://api.dingtalk.com",
        timeout_sec: float = 60,
        max_retries: int = 4,
    ) -> None:
        if not app_key or not app_secret:
            raise ValueError("dingtalk app key/secret required")
        if not operator_union_id:
            raise ValueError("operator_union_id required")
        self.app_key = app_key
        self.app_secret = app_secret
        self.operator_union_id = operator_union_id
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.max_retries = max(1, max_retries)
        self._token: str | None = None
        self._token_expire_at = 0.0

    def get_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire_at - 60:
            return self._token
        url = f"{self.api_base_url}/v1.0/oauth2/accessToken"
        payload = {"appKey": self.app_key, "appSecret": self.app_secret}
        data = self._request("POST", url, payload, auth=False)
        token = data.get("accessToken") or data.get("access_token")
        if not token:
            raise RuntimeError(f"get accessToken failed: {data}")
        self._token = token
        self._token_expire_at = now + float(data.get("expireIn") or data.get("expires_in") or 7200)
        return token

    def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["x-acs-dingtalk-access-token"] = self.get_access_token()
        raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_exc: BaseException | None = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(url, data=raw, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                if not text:
                    return {}
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise RuntimeError(f"unexpected response: {type(data)}")
                return data
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                # 5xx / 429 可重试；4xx 直接失败
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    sleep_sec = min(30.0, 2.0 ** attempt)
                    _log.warning(
                        "dingtalk HTTP %s retry %s/%s sleep=%.0fs: %s",
                        exc.code,
                        attempt,
                        self.max_retries,
                        sleep_sec,
                        detail[:200],
                    )
                    time.sleep(sleep_sec)
                    last_exc = exc
                    continue
                raise RuntimeError(f"dingtalk HTTP {exc.code}: {detail}") from exc
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                sleep_sec = min(30.0, 2.0 ** attempt)
                _log.warning(
                    "dingtalk network retry %s/%s sleep=%.0fs: %s",
                    attempt,
                    self.max_retries,
                    sleep_sec,
                    exc,
                )
                time.sleep(sleep_sec)
        raise RuntimeError(f"dingtalk request failed after {self.max_retries} tries: {last_exc}") from last_exc

    def list_all_records(self, doc_key: str, sheet_id: str, view_id: str = "") -> list[dict[str, Any]]:
        op = urllib.parse.quote(self.operator_union_id)
        url = f"{self.api_base_url}/v1.0/notable/bases/{doc_key}/sheets/{sheet_id}/records/list?operatorId={op}"
        records: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            body: dict[str, Any] = {"maxResults": 100}
            if view_id:
                body["viewId"] = view_id
            if next_token:
                body["nextToken"] = next_token
            data = self._request("POST", url, body)
            batch = data.get("records") or data.get("value") or []
            records.extend(batch)
            next_token = data.get("nextToken") or data.get("next_token")
            if not next_token or not batch:
                break
        return records

    def iter_candidate_rows(
        self,
        doc_key: str,
        sheet_id: str,
        view_id: str = "",
        *,
        carrier_keyword: str = "",
        carrier_keywords: tuple[str, ...] | list[str] | None = None,
        ship_year: int | None = 2026,
        today: date | None = None,
    ) -> list[TableRow]:
        """
        筛选：
        - 发货时间年份 = ship_year（列「发货时间」为毫秒时间戳 int；None 表示不限年）
        - 预计船期≤今天 且 实际送仓时间为空
        - 货代命中 keywords 任一
        """
        today = today or datetime.now(tz=CST).date()
        if carrier_keywords is None:
            keywords = (carrier_keyword,) if carrier_keyword else ("平谊", "龙舟", "美通")
        else:
            keywords = tuple(k for k in carrier_keywords if k)
            if not keywords and carrier_keyword:
                keywords = (carrier_keyword,)
        rows: list[TableRow] = []
        for raw in self.list_all_records(doc_key, sheet_id, view_id):
            fields = raw.get("fields") or {}
            carrier = _field_text(fields.get("货代公司"))
            if keywords and not any(k in carrier for k in keywords):
                continue
            # 发货时间：API 为毫秒时间戳，如 1779033600000 → 2026-05-18
            shipped = _ts_to_date(fields.get("发货时间"))
            if ship_year is not None:
                if shipped is None or shipped.year != ship_year:
                    continue
            eta = _ts_to_date(fields.get("预计船期"))
            delivered = _ts_to_date(fields.get("实际送仓时间"))
            if delivered is not None:
                continue
            if eta is None or eta > today:
                continue
            rows.append(
                TableRow(
                    record_id=str(raw.get("id") or ""),
                    invoice_no=_field_text(fields.get("发票号")),
                    brand=_field_text(fields.get("品牌")),
                    country=_field_text(fields.get("国家")),
                    carrier=carrier,
                    fba_codes=_split_codes(fields.get("FBA编码")),
                    logistics_nos=_split_codes(fields.get("物流编号")),
                    eta_date=eta,
                    delivered_at=delivered,
                    shipped_at=shipped,
                    owners=_owners(fields.get("负责人")),
                    channel=_field_text(fields.get("出运渠道")),
                    site=_field_text(fields.get("站点")),
                )
            )
        return rows
