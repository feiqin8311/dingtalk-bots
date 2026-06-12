#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Config loader for DingTalk CP Bot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


ROOT_DIR = _find_repo_root(Path(__file__).resolve().parent)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

from shared.env import load_env_files

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_env_files([ENV_PATH])
load_dotenv(ENV_PATH, override=False)
load_dotenv(ENV_PATH, override=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s | %(levelname)s | %(message)s")

# DingTalk credentials (Stream + robot send)
DINGTALK_APP_KEY = os.getenv("DINGTALK_APP_KEY") or os.getenv("CLIENT_ID") or os.getenv("DING_CLIENT_ID") or ""
DINGTALK_APP_SECRET = (
    os.getenv("DINGTALK_APP_SECRET") or os.getenv("CLIENT_SECRET") or os.getenv("DING_CLIENT_SECRET") or ""
)
DINGTALK_ROBOT_CODE = os.getenv("DINGTALK_ROBOT_CODE") or os.getenv("ROBOT_CODE") or ""
DING_TECH_USER_IDS = [
    item.strip()
    for item in (
        os.getenv("DING_TECH_USER_IDS", "")
        .replace(";", ",")
        .split(",")
    )
    if item.strip()
]

CLIENT_ID = os.getenv("CLIENT_ID") or os.getenv("DING_CLIENT_ID") or DINGTALK_APP_KEY
CLIENT_SECRET = os.getenv("CLIENT_SECRET") or os.getenv("DING_CLIENT_SECRET") or DINGTALK_APP_SECRET

# LingXing OpenAPI configuration
LINGXING_API_HOST = os.getenv("LINGXING_API_HOST", "http://121.41.4.126:3188")
LINGXING_API_KEY = os.getenv("LINGXING_API_KEY", "")
LINGXING_API_SECRET = os.getenv("LINGXING_API_SECRET", "")
LINGXING_TOKEN_URL = os.getenv("LINGXING_TOKEN_URL", "http://121.41.4.126:3721/token")
LINGXING_TOKEN_REQUEST_KEY = os.getenv("LINGXING_TOKEN_REQUEST_KEY", "") or LINGXING_API_KEY
LINGXING_SSL_VERIFY = os.getenv("LINGXING_SSL_VERIFY", "false").lower() == "true"

# Local storage
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR") or str(BASE_DIR / "downloads")
ADDRESS_BOOK_XLSX_PATH = os.getenv("ADDRESS_BOOK_XLSX_PATH") or str(BASE_DIR / "files" / "全站点地址.xlsx")
SMB_USERNAME = os.getenv("SMB_USERNAME", "")
SMB_PASSWORD = os.getenv("SMB_PASSWORD", "")
SMB_HOST = os.getenv("SMB_HOST", "")
SMB_SHARE = os.getenv("SMB_SHARE", "")
SMB_PORT = int((os.getenv("SMB_PORT") or "445").strip())
SMB_TIMEOUT_SEC = int((os.getenv("SMB_TIMEOUT_SEC") or "30").strip())
SMB_CLIENT_NAME = os.getenv("SMB_CLIENT_NAME", "dingtalk-cp-bot")

# Concurrency and reliability
MAX_CONCURRENT_REQUESTS = 3
MESSAGE_DEDUP_TTL_SEC = 600
SHIPMENT_LOCK_TTL_SEC = 1800
DOWNLOAD_CONCURRENCY = 3
OCR_CONCURRENCY = 2
RESOURCE_WAIT_TIMEOUT_SEC = 120
JOB_QUEUE_MAX_SIZE = 200

# Retry strategy
API_RETRY_TIMES = 3
API_RETRY_BASE_DELAY_SEC = 1.0
API_RETRY_MAX_DELAY_SEC = 6.0

# DB state store (dedup + shipment locks)
DB_HOST = (os.getenv("DB_HOST") or "").strip()
DB_PORT = int((os.getenv("DB_PORT") or "3306").strip())
DB_USER = (os.getenv("DB_USER") or "").strip()
DB_PASSWORD = (os.getenv("DB_PASSWORD") or "").strip()
DB_NAME = (os.getenv("DB_NAME") or "").strip()
DB_CONNECT_TIMEOUT_SEC = int((os.getenv("DB_CONNECT_TIMEOUT_SEC") or "5").strip())
BOT_CALL_LOG_TABLE = (os.getenv("BOT_CALL_LOG_TABLE") or "fact_dingtalk_bot_call_log").strip()

# File cleanup
DOWNLOAD_RETENTION_DAYS = 7
DOWNLOAD_CLEANUP_INTERVAL_SEC = 300
