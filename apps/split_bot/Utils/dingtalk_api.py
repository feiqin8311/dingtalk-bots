from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Tuple

from alibabacloud_dingtalk.robot_1_0.client import Client as DingTalkRobotClient
from alibabacloud_dingtalk.robot_1_0 import models as robot_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
from shared.dingtalk_token import get_access_token as shared_get_access_token

LOGGER = logging.getLogger(__name__)


def _build_openapi_config() -> open_api_models.Config:
    config = open_api_models.Config()
    config.protocol = "https"
    config.region_id = "central"
    return config


async def get_token(config=None) -> Optional[str]:
    if config is None:
        return None
    return await asyncio.to_thread(
        shared_get_access_token,
        config.client_id,
        config.client_secret,
        api_base_url=getattr(config, "dingtalk_api_base_url", "https://api.dingtalk.com"),
    )


def get_token_sync(config=None) -> Optional[str]:
    if config is None:
        return None
    return shared_get_access_token(
        config.client_id,
        config.client_secret,
        api_base_url=getattr(config, "dingtalk_api_base_url", "https://api.dingtalk.com"),
    )


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
