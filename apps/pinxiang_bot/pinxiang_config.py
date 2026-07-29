#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pinxiang_bot 独立配置（仅读本 app / monorepo 的 env，不依赖 dingtalk-lcl-bot）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start.parent


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = _find_repo_root(APP_DIR)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from shared.env import load_env_files  # noqa: E402

load_env_files(
    [
        ROOT_DIR / ".env",
        ROOT_DIR / "apps" / "logistics_bot" / ".env",
        APP_DIR / ".env",
        Path.cwd() / ".env",
    ]
)

WORKSPACE = os.getenv(
    "PINXIANG_WORKSPACE",
    str(APP_DIR / ".bot-workspace"),
)

DEFAULT_PRODUCT_INFO = ROOT_DIR / "files" / "产品信息单证专用.xlsx"
PRODUCT_INFO_PATH = (
    os.getenv("PINXIANG_PRODUCT_INFO_PATH") or str(DEFAULT_PRODUCT_INFO)
).strip()

SMB_USERNAME = os.getenv("SMB_USERNAME", os.getenv("PINXIANG_SMB_USERNAME", "")).strip()
SMB_PASSWORD = os.getenv("SMB_PASSWORD", os.getenv("PINXIANG_SMB_PASSWORD", ""))
SMB_PORT = int((os.getenv("SMB_PORT") or os.getenv("PINXIANG_SMB_PORT") or "445").strip())
SMB_TIMEOUT_SEC = int((os.getenv("SMB_TIMEOUT_SEC") or "30").strip())
SMB_CLIENT_NAME = os.getenv("SMB_CLIENT_NAME", "dingtalk-pinxiang-bot").strip()

PENDING_TTL_SEC = int((os.getenv("PINXIANG_PENDING_TTL_SEC") or "600").strip())

# 运营人员（物流确认后选择转发对象）
# 可用 env 覆盖：PINXIANG_OPS_USERS=袁皓冉:id1,陈潇潇:id2
# 默认运营；可用 PINXIANG_OPS_USERS 覆盖
_DEFAULT_OPS = (
    ("袁皓冉", "17839075860894598"),
    ("陈潇潇", "17403614178121993"),
)


def _load_ops_users() -> list[dict[str, str]]:
    raw = os.getenv("PINXIANG_OPS_USERS", "").strip()
    if not raw:
        return [{"name": n, "user_id": u} for n, u in _DEFAULT_OPS]
    users: list[dict[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, uid = part.split(":", 1)
        else:
            name, uid = part, part
        users.append({"name": name.strip(), "user_id": uid.strip()})
    return users or [{"name": n, "user_id": u} for n, u in _DEFAULT_OPS]


OPS_USERS = _load_ops_users()
