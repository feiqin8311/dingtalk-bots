"""Process-wide, thread-safe DingTalk access-token cache.

One router process hosts several bots that share the same app key; before this
each kept its own cache (some unlocked, one ignoring ``expireIn``), so tokens
were fetched repeatedly and could race under concurrent threads.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Tuple

DEFAULT_API_BASE_URL = "https://api.dingtalk.com"
DEFAULT_OAPI_BASE_URL = "https://oapi.dingtalk.com"
# refresh this long before DingTalk's stated expiry
REFRESH_MARGIN_SEC = 300
_DEFAULT_EXPIRES_IN = 7200
_TIMEOUT_SEC = 20

_cache: Dict[Tuple[str, ...], Tuple[str, float]] = {}
_lock = threading.Lock()


def _http_json(request: urllib.request.Request) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DingTalk token request failed: {exc.code} {exc.reason}. {detail}") from exc
    return json.loads(body) if body else {}


def _fetch_api_token(api_base_url: str, app_key: str, app_secret: str) -> Tuple[str, int]:
    """New-style token (``x-acs-dingtalk-access-token``) from /v1.0/oauth2/accessToken."""
    payload = json.dumps({"appKey": app_key, "appSecret": app_secret}).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base_url.rstrip('/')}/v1.0/oauth2/accessToken",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    data = _http_json(request)
    token = data.get("accessToken") or data.get("access_token")
    if not token:
        raise RuntimeError(f"DingTalk accessToken missing in response: {data}")
    return token, int(data.get("expireIn") or data.get("expires_in") or _DEFAULT_EXPIRES_IN)


def _fetch_corp_token(oapi_base_url: str, app_key: str, app_secret: str) -> Tuple[str, int]:
    """Legacy OAPI token (``?access_token=``) from /gettoken, used by topapi calls."""
    query = urllib.parse.urlencode({"appkey": app_key, "appsecret": app_secret})
    data = _http_json(urllib.request.Request(f"{oapi_base_url.rstrip('/')}/gettoken?{query}"))
    if data.get("errcode") not in (0, None):
        raise RuntimeError(f"DingTalk gettoken failed: {data.get('errmsg')}")
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"DingTalk access_token missing in response: {data}")
    return token, int(data.get("expires_in") or _DEFAULT_EXPIRES_IN)


def _cached(
    key: Tuple[str, ...],
    fetch: Callable[[], Tuple[str, int]],
    force_refresh: bool,
) -> str:
    # Held across the fetch on purpose: concurrent callers wait for one request
    # instead of all hitting the token endpoint at once.
    with _lock:
        hit = _cache.get(key)
        if hit and not force_refresh and time.time() < hit[1]:
            return hit[0]
        token, expires_in = fetch()
        _cache[key] = (token, time.time() + max(60, expires_in - REFRESH_MARGIN_SEC))
        return token


def get_access_token(
    app_key: str,
    app_secret: str,
    *,
    api_base_url: str = DEFAULT_API_BASE_URL,
    force_refresh: bool = False,
) -> str:
    if not app_key or not app_secret:
        raise RuntimeError("缺少 appKey/appSecret，无法获取 accessToken。")
    return _cached(
        ("api", api_base_url, app_key, app_secret),
        lambda: _fetch_api_token(api_base_url, app_key, app_secret),
        force_refresh,
    )


def get_corp_access_token(
    app_key: str,
    app_secret: str,
    *,
    oapi_base_url: str = DEFAULT_OAPI_BASE_URL,
    force_refresh: bool = False,
) -> str:
    if not app_key or not app_secret:
        raise RuntimeError("缺少 appKey/appSecret，无法获取 access_token。")
    return _cached(
        ("corp", oapi_base_url, app_key, app_secret),
        lambda: _fetch_corp_token(oapi_base_url, app_key, app_secret),
        force_refresh,
    )


def clear_cache() -> None:
    """For tests."""
    with _lock:
        _cache.clear()
