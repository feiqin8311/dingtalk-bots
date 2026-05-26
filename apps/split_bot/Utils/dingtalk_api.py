from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional, Tuple

from alibabacloud_dingtalk.oauth2_1_0.client import Client as DingTalkOauthClient
from alibabacloud_dingtalk.oauth2_1_0 import models as oauth_models
from alibabacloud_dingtalk.robot_1_0.client import Client as DingTalkRobotClient
from alibabacloud_dingtalk.robot_1_0 import models as robot_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

LOGGER = logging.getLogger(__name__)


def _build_openapi_config() -> open_api_models.Config:
    config = open_api_models.Config()
    config.protocol = "https"
    config.region_id = "central"
    return config


def _fetch_token_sync(config) -> Tuple[Optional[str], int]:
    client = DingTalkOauthClient(_build_openapi_config())
    request = oauth_models.GetAccessTokenRequest(
        app_key=config.client_id,
        app_secret=config.client_secret,
    )
    response = client.get_access_token(request)
    token = getattr(response.body, "access_token", None)
    expire_in = getattr(response.body, "expires_in", None) or getattr(response.body, "expire_in", 7200)
    return token, int(expire_in) if expire_in else 7200


async def get_token(config=None) -> Optional[str]:
    if not hasattr(get_token, "_token_cache"):
        get_token._token_cache = {"token": None, "expire": 0}
    now = time.time()
    if get_token._token_cache["token"] and now < get_token._token_cache["expire"]:
        return get_token._token_cache["token"]
    if config is None:
        return None
    loop = asyncio.get_running_loop()
    token, expire_in = await loop.run_in_executor(None, _fetch_token_sync, config)
    if token:
        get_token._token_cache["token"] = token
        get_token._token_cache["expire"] = now + max(expire_in - 200, 60)
    return token


def get_token_sync(config=None) -> Optional[str]:
    if not hasattr(get_token_sync, "_token_cache"):
        get_token_sync._token_cache = {"token": None, "expire": 0}
    now = time.time()
    if get_token_sync._token_cache["token"] and now < get_token_sync._token_cache["expire"]:
        return get_token_sync._token_cache["token"]
    if config is None:
        return None
    token, expire_in = _fetch_token_sync(config)
    if token:
        get_token_sync._token_cache["token"] = token
        get_token_sync._token_cache["expire"] = now + max(expire_in - 200, 60)
    return token


def _send_oto(access_token: str, config, user_ids: list[str], msg_key: str, msg_param: dict) -> Optional[object]:
    client = DingTalkRobotClient(_build_openapi_config())
    headers = robot_models.BatchSendOTOHeaders()
    headers.x_acs_dingtalk_access_token = access_token
    request = robot_models.BatchSendOTORequest(
        robot_code=config.robot_code,
        user_ids=user_ids,
        msg_key=msg_key,
        msg_param=json.dumps(msg_param, ensure_ascii=False),
    )
    try:
        return client.batch_send_otowith_options(request, headers, util_models.RuntimeOptions())
    except Exception as exc:  # pragma: no cover - depends on remote API
        LOGGER.exception("send oto failed for msg_key=%s", msg_key)
        return None


def send_robot_private_text_message(access_token: str, config, user_ids: list[str], message: str) -> Optional[object]:
    return _send_oto(access_token, config, user_ids, "sampleText", {"content": message})


def send_robot_private_file_message(
    access_token: str,
    config,
    user_ids: list[str],
    media_id: str,
    file_name: str,
) -> Optional[object]:
    return _send_oto(access_token, config, user_ids, "sampleFile", {"mediaId": media_id, "fileName": file_name})
