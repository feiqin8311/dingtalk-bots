# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""分仓拼箱配置（嵌入 monorepo apps/lcl_bot，路径相对本 app）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
# monorepo root = …/dingtalk-bots
MONOREPO_ROOT = PACKAGE_DIR.parent.parent

# 统一根 .env；app 级仅补缺
for candidate in (
    MONOREPO_ROOT / ".env",
    MONOREPO_ROOT / "apps" / "logistics_bot" / ".env",
    MONOREPO_ROOT / "apps" / "cp_bot" / ".env",
    PACKAGE_DIR / ".env",
    Path.cwd() / ".env",
):
    if candidate.is_file():
        load_dotenv(candidate, override=False)

# 兼容原 lcl 命名 + monorepo 钉钉变量
CLIENT_ID = (
    os.getenv("LCL_DING_CLIENT_ID")
    or os.getenv("CLIENT_ID")
    or os.getenv("DING_CLIENT_ID")
    or os.getenv("DINGTALK_APP_KEY")
    or os.getenv("LOGISTICS_DING_CLIENT_ID")
    or ""
).strip()
CLIENT_SECRET = (
    os.getenv("LCL_DING_CLIENT_SECRET")
    or os.getenv("CLIENT_SECRET")
    or os.getenv("DING_CLIENT_SECRET")
    or os.getenv("DINGTALK_APP_SECRET")
    or os.getenv("LOGISTICS_DING_CLIENT_SECRET")
    or ""
).strip()
AGENT_ID = os.getenv("AGENT_ID")
ROBOT_CODE = (
    os.getenv("LCL_DING_ROBOT_CODE")
    or os.getenv("ROBOT_CODE")
    or os.getenv("DING_ROBOT_CODE")
    or os.getenv("DINGTALK_ROBOT_CODE")
    or CLIENT_ID
    or ""
).strip()

_logistics_users_str = os.getenv("LCL_LOGISTICS_USERS") or os.getenv("LOGISTICS_USERS") or ""
LOGISTICS_USERS = [uid.strip() for uid in _logistics_users_str.split(",") if uid.strip()]

# 流程四运营与流程三共用：PINXIANG_OPS_USERS + pinxiang 默认名单（不再单独 LCL_OPERATION_USERS）
_pinxiang_dir = str(MONOREPO_ROOT / "apps" / "pinxiang_bot")
if _pinxiang_dir not in sys.path:
    sys.path.insert(0, _pinxiang_dir)
from pinxiang_config import OPS_USERS as OPS_USERS  # noqa: E402

# 兼容旧代码：纯 userId 列表
OPERATION_USERS = [u["user_id"] for u in OPS_USERS]

_technology_users_str = (
    os.getenv("LCL_TECHNOLOGY_USERS")
    or os.getenv("TECHNOLOGY_USERS")
    or os.getenv("DING_TECH_USER_IDS")
    or "17331048354297047"
)
TECHNOLOGY_USERS = [
    uid.strip() for uid in _technology_users_str.replace(";", ",").split(",") if uid.strip()
]

_other_users_str = os.getenv("LCL_OTHER_USERS") or os.getenv("OTHER_USERS") or ""
OTHER_USERS = [uid.strip() for uid in _other_users_str.split(",") if uid.strip()]

# 工作目录：默认本 app 下（compose 可挂载）
BASE_DIR = os.getenv("LCL_BASE_DIR", str(PACKAGE_DIR)).strip() or str(PACKAGE_DIR)
EXCEL_FILES_DIR = os.getenv("LCL_EXCEL_FILES_DIR", os.path.join(BASE_DIR, "Excel_Files"))
TEMPLATE_FILES_DIR = os.getenv(
    "LCL_TEMPLATE_FILES_DIR",
    os.path.join(BASE_DIR, "templates"),
)
AMAZON_TEMPLATE_SOURCE_FILE = os.path.join(
    TEMPLATE_FILES_DIR,
    "ManifestFileUpload_Template_IncludeCasePack_IncludeExpirationDate_IncludeMLC_MPL.xlsx",
)
AMAZON_TEMPLATE_SOURCE_FILE_V2 = os.path.join(
    TEMPLATE_FILES_DIR,
    "ManifestFileUpload_Template_IncludeCasePack_IncludeExpirationDate_IncludeMLC_MPL2.xlsx",
)

LINGXING_API_HOST = os.getenv("LINGXING_API_HOST", "http://121.41.4.126:3188")
LINGXING_API_KEY = os.getenv("LINGXING_API_KEY", "")
LINGXING_API_SECRET = os.getenv("LINGXING_API_SECRET", "")
LINGXING_TOKEN_URL = os.getenv("LINGXING_TOKEN_URL", "http://121.41.4.126:3721/token")
LINGXING_TOKEN_REQUEST_KEY = os.getenv("LINGXING_TOKEN_REQUEST_KEY", "") or LINGXING_API_KEY
LINGXING_SSL_VERIFY = os.getenv("LINGXING_SSL_VERIFY", "false").lower() == "true"

STATE_FILE_PATH = os.getenv(
    "LCL_STATE_FILE_PATH",
    os.path.join(BASE_DIR, "Workflow_State", "workflow_state.json"),
)

os.makedirs(EXCEL_FILES_DIR, exist_ok=True)
os.makedirs(TEMPLATE_FILES_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATE_FILE_PATH) or ".", exist_ok=True)

DINGTALK_API_BASE_URL = "https://api.dingtalk.com"
DINGTALK_OAPI_BASE_URL = "https://oapi.dingtalk.com"
DINGTALK_TOKEN_URL = f"{DINGTALK_API_BASE_URL}/v1.0/oauth2/accessToken"
DINGTALK_CORP_TOKEN_URL = f"{DINGTALK_OAPI_BASE_URL}/gettoken"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s | %(levelname)s | %(message)s")

PROJECT_ROOT = MONOREPO_ROOT
