#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DingTalk notifier helpers (enterprise robot + group robot).

Encapsulates:
- Single chat by userId (enterprise internal robot)
- Group webhook notifications (with optional signature)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Optional

from . import config


_TOKEN_CACHE: Dict[tuple, Dict[str, Any]] = {}
_COMMAND_QUEUE: Dict[str, list[Dict[str, Any]]] = {}
_COMMAND_LOCK = threading.Lock()


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"请求失败: {exc.code} {exc.reason}. {detail}") from exc
    if not body:
        return {}
    return json.loads(body)


def _post_raw(url: str, data: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=data, method="POST")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"请求失败: {exc.code} {exc.reason}. {detail}") from exc
    if not body:
        return {}
    return json.loads(body)


def _build_multipart_formdata(field_name: str, file_path: str) -> tuple[str, bytes]:
    boundary = uuid.uuid4().hex
    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        file_data = f.read()

    lines = []
    lines.append(f"--{boundary}\r\n".encode("utf-8"))
    lines.append(
        (
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    lines.append(file_data)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(lines)


def _guess_file_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".doc", ".docx"}:
        return "doc"
    if ext in {".xls", ".xlsx", ".xlsm"}:
        return "xls"
    if ext in {".ppt", ".pptx"}:
        return "ppt"
    if ext == ".pdf":
        return "pdf"
    if ext in {".zip", ".rar", ".7z"}:
        return "zip"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}:
        return "image"
    if ext in {".txt", ".log"}:
        return "txt"
    return "file"


def _sign_webhook_url(webhook_url: str, secret: str) -> str:
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    parsed = urllib.parse.urlparse(webhook_url)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    params.update({"timestamp": timestamp, "sign": sign})
    new_query = urllib.parse.urlencode(params)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


class DingTalkNotifier:
    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        robot_code: Optional[str] = None,
        api_base_url: Optional[str] = None,
        group_webhook: Optional[str] = None,
        group_secret: Optional[str] = None,
    ) -> None:
        self.app_key = app_key or config.DINGTALK_APP_KEY
        self.app_secret = app_secret or config.DINGTALK_APP_SECRET
        self.robot_code = robot_code or config.DINGTALK_ROBOT_CODE
        self.api_base_url = api_base_url or config.DINGTALK_API_BASE_URL
        self.group_webhook = group_webhook or config.DINGTALK_GROUP_WEBHOOK
        self.group_secret = group_secret or config.DINGTALK_GROUP_SECRET

    def get_access_token(self) -> str:
        cache_key = (self.app_key, self.app_secret, self.api_base_url)
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and time.time() < cached.get("expires_at", 0) - 60:
            return cached["access_token"]

        if not self.app_key or not self.app_secret:
            raise RuntimeError("缺少 appKey/appSecret，无法获取 accessToken。")

        token_url = f"{self.api_base_url}/v1.0/oauth2/accessToken"
        payload = {"appKey": self.app_key, "appSecret": self.app_secret}
        result = _post_json(token_url, payload)
        token = result.get("accessToken") or result.get("access_token")
        if not token:
            raise RuntimeError(f"获取 accessToken 失败: {result}")
        expires_in = result.get("expireIn") or result.get("expires_in") or 7200
        _TOKEN_CACHE[cache_key] = {
            "access_token": token,
            "expires_at": time.time() + int(expires_in),
        }
        return token

    def get_download_url(self, download_code: str, robot_code: Optional[str] = None) -> str:
        if not download_code:
            raise ValueError("缺少 downloadCode。")
        token = self.get_access_token()
        url = f"{self.api_base_url}/v1.0/robot/messageFiles/download"
        payload = {"downloadCode": download_code}
        resolved_robot_code = robot_code or self.robot_code
        if resolved_robot_code:
            payload["robotCode"] = resolved_robot_code
        headers = {"x-acs-dingtalk-access-token": token}
        try:
            result = _post_json(url, payload, headers=headers)
        except RuntimeError as exc:
            if "invalidParameter.robotCode.downloadCode" in str(exc) and "robotCode" in payload:
                result = _post_json(url, {"downloadCode": download_code}, headers=headers)
            else:
                raise
        download_url = result.get("downloadUrl") or result.get("download_url")
        if not download_url:
            raise RuntimeError(f"获取下载链接失败: {result}")
        return download_url

    def download_file(self, download_url: str, dest_path: str) -> str:
        if not download_url:
            raise ValueError("缺少下载链接。")
        req = urllib.request.Request(download_url, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(dest_path, "wb") as handle:
            handle.write(data)
        return dest_path

    def download_file_by_code(
        self,
        download_code: str,
        dest_path: str,
        robot_code: Optional[str] = None,
    ) -> str:
        download_url = self.get_download_url(download_code, robot_code=robot_code)
        return self.download_file(download_url, dest_path)

    def send_user_text(self, user_id: str, text: str, robot_code: Optional[str] = None) -> Dict[str, Any]:
        robot_code = robot_code or self.robot_code
        if not robot_code:
            raise RuntimeError("缺少 ROBOT_CODE，无法发送单聊消息。")
        token = self.get_access_token()
        url = f"{self.api_base_url}/v1.0/robot/oToMessages/batchSend"
        payload = {
            "robotCode": robot_code,
            "userIds": [user_id],
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": text}, ensure_ascii=False),
        }
        headers = {"x-acs-dingtalk-access-token": token}
        return _post_json(url, payload, headers=headers)

    def send_user_file(self, user_id: str, file_path: str, robot_code: Optional[str] = None) -> Dict[str, Any]:
        robot_code = robot_code or self.robot_code
        if not robot_code:
            raise RuntimeError("缺少 ROBOT_CODE，无法发送单聊消息。")
        token = self.get_access_token()
        media_id = self._upload_message_file(file_path, token)
        filename = os.path.basename(file_path)
        url = f"{self.api_base_url}/v1.0/robot/oToMessages/batchSend"
        payload = {
            "robotCode": robot_code,
            "userIds": [user_id],
            "msgKey": "sampleFile",
            "msgParam": json.dumps(
                {
                    "mediaId": media_id,
                    "fileName": filename,
                    "fileType": _guess_file_type(file_path),
                },
                ensure_ascii=False,
            ),
        }
        headers = {"x-acs-dingtalk-access-token": token}
        return _post_json(url, payload, headers=headers)

    def send_group_text(
        self,
        text: str,
        webhook_url: Optional[str] = None,
        at_mobiles: Optional[list[str]] = None,
        at_all: bool = False,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        webhook_url = webhook_url or self.group_webhook
        if not webhook_url:
            raise RuntimeError("缺少群机器人 webhook。")
        secret = secret if secret is not None else self.group_secret
        if secret:
            webhook_url = _sign_webhook_url(webhook_url, secret)
        payload: Dict[str, Any] = {"msgtype": "text", "text": {"content": text}}
        if at_mobiles or at_all:
            payload["at"] = {"atMobiles": at_mobiles or [], "isAtAll": bool(at_all)}
        return _post_json(webhook_url, payload)

    def _upload_message_file(self, file_path: str, token: str) -> str:
        url = f"{self.api_base_url}/v1.0/robot/messageFiles/upload"
        boundary, body = _build_multipart_formdata("media", file_path)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x-acs-dingtalk-access-token": token,
        }
        try:
            result = _post_raw(url, body, headers)
            media_id = result.get("media_id") or result.get("mediaId")
            if not media_id:
                raise RuntimeError(f"上传文件失败: {result}")
            return media_id
        except Exception:
            return self._upload_media_legacy(file_path, token)

    def _upload_media_legacy(self, file_path: str, token: str) -> str:
        query = urllib.parse.urlencode({"access_token": token, "type": "file"})
        url = f"https://oapi.dingtalk.com/media/upload?{query}"
        boundary, body = _build_multipart_formdata("media", file_path)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        result = _post_raw(url, body, headers)
        media_id = result.get("media_id") or result.get("mediaId")
        if not media_id:
            raise RuntimeError(f"上传媒体失败: {result}")
        return media_id


_DEFAULT_NOTIFIER = DingTalkNotifier()


def send_user_text(
    user_id: str,
    text: str,
    *,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    robot_code: Optional[str] = None,
) -> Dict[str, Any]:
    notifier = DingTalkNotifier(app_key=app_key, app_secret=app_secret, robot_code=robot_code)
    return notifier.send_user_text(user_id, text, robot_code=robot_code)


def send_user_file(
    user_id: str,
    file_path: str,
    *,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    robot_code: Optional[str] = None,
) -> Dict[str, Any]:
    notifier = DingTalkNotifier(app_key=app_key, app_secret=app_secret, robot_code=robot_code)
    return notifier.send_user_file(user_id, file_path, robot_code=robot_code)


def send_group_text(
    text: str,
    *,
    webhook_url: Optional[str] = None,
    at_mobiles: Optional[list[str]] = None,
    at_all: bool = False,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    return _DEFAULT_NOTIFIER.send_group_text(
        text,
        webhook_url=webhook_url,
        at_mobiles=at_mobiles,
        at_all=at_all,
        secret=secret,
    )


def download_file_by_code(
    download_code: str,
    dest_path: str,
    *,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    robot_code: Optional[str] = None,
) -> str:
    notifier = DingTalkNotifier(app_key=app_key, app_secret=app_secret, robot_code=robot_code)
    return notifier.download_file_by_code(download_code, dest_path, robot_code=robot_code)


def extract_callback_text(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates: list[str] = []
    direct = [
        payload.get("content"),
        (payload.get("text") or {}).get("content") if isinstance(payload.get("text"), dict) else None,
        payload.get("msg"),
        payload.get("message"),
    ]
    for item in direct:
        if isinstance(item, str) and item.strip():
            candidates.append(item.strip())
    data = payload.get("data")
    if isinstance(data, dict):
        nested = [
            data.get("content"),
            (data.get("text") or {}).get("content") if isinstance(data.get("text"), dict) else None,
            (data.get("message") or {}).get("text") if isinstance(data.get("message"), dict) else None,
        ]
        for item in nested:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())
    msg_param = payload.get("msgParam") or payload.get("msg_param")
    if isinstance(msg_param, str) and msg_param.strip():
        try:
            parsed = json.loads(msg_param)
            if isinstance(parsed, dict):
                msg_text = parsed.get("content") or parsed.get("text")
                if isinstance(msg_text, str) and msg_text.strip():
                    candidates.append(msg_text.strip())
        except Exception:
            candidates.append(msg_param.strip())
    return candidates[0] if candidates else ""


def extract_callback_user_id(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    direct_keys = [
        "user_id",
        "userId",
        "senderId",
        "senderUserId",
        "senderStaffId",
        "staffId",
        "fromUserId",
    ]
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        for key in direct_keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def record_command(
    command_key: str,
    *,
    user_id: str = "",
    content: str = "",
    raw_payload: Optional[Dict[str, Any]] = None,
) -> int:
    key = (command_key or "").strip()
    if not key:
        return 0
    row = {
        "id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
        "command_key": key,
        "user_id": (user_id or "").strip(),
        "content": (content or "").strip(),
        "raw_payload": raw_payload if isinstance(raw_payload, dict) else None,
        "created_ts": float(time.time()),
    }
    with _COMMAND_LOCK:
        queue = _COMMAND_QUEUE.setdefault(key, [])
        queue.append(row)
        # keep a bounded in-memory queue
        if len(queue) > 500:
            del queue[:-500]
    return 1


def record_command_from_callback(
    payload: Dict[str, Any],
    *,
    command_key: str = "xiyou_login",
    keywords: Optional[list[str]] = None,
) -> bool:
    text = extract_callback_text(payload)
    if not text:
        return False
    user_id = extract_callback_user_id(payload)
    key_list = [str(item).strip().lower() for item in (keywords or ["已登录"]) if str(item).strip()]
    lowered = text.lower()
    if key_list and not any(item in lowered for item in key_list):
        return False
    record_command(
        command_key=command_key,
        user_id=user_id,
        content=text,
        raw_payload=payload if isinstance(payload, dict) else None,
    )
    return True


def consume_command(
    command_key: str,
    *,
    keywords: Optional[list[str]] = None,
    since_ts: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    key = (command_key or "").strip()
    if not key:
        return None
    key_list = [str(item).strip().lower() for item in (keywords or ["已登录"]) if str(item).strip()]
    since_value = float(since_ts) if since_ts else None
    with _COMMAND_LOCK:
        queue = _COMMAND_QUEUE.get(key, [])
        if not queue:
            return None
        for idx, row in enumerate(queue):
            created_ts = float(row.get("created_ts") or 0.0)
            if since_value and created_ts < since_value:
                continue
            content = str(row.get("content") or "").strip().lower()
            if key_list and not any(item in content for item in key_list):
                continue
            matched = queue.pop(idx)
            return {
                "id": matched.get("id"),
                "command_key": matched.get("command_key"),
                "user_id": matched.get("user_id"),
                "content": matched.get("content"),
                "created_ts": matched.get("created_ts"),
            }
    return None


__all__ = [
    "DingTalkNotifier",
    "send_user_text",
    "send_user_file",
    "send_group_text",
    "download_file_by_code",
    "extract_callback_text",
    "extract_callback_user_id",
    "record_command",
    "record_command_from_callback",
    "consume_command",
]
