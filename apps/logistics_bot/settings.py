from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = find_repo_root(APP_DIR)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.env import load_env_files


def _read_positive_int_env(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    parsed = int(raw)
    if parsed <= 0:
        raise RuntimeError(f"{key} must be > 0")
    return parsed


@dataclass(frozen=True)
class LogisticsBotConfig:
    client_id: str
    client_secret: str
    robot_code: str
    split_workspace: str
    stream_ws_ping_interval: int
    stream_ws_ping_timeout: int
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    db_connect_timeout_sec: int
    bot_call_log_table: str

    @property
    def workspace(self) -> str:
        return self.split_workspace


def load_config_from_env() -> LogisticsBotConfig:
    load_env_files(
        [
            ROOT_DIR / ".env",
            ROOT_DIR / "apps" / "logistics_bot" / ".env",
            ROOT_DIR / "apps" / "cp_bot" / ".env",
            ROOT_DIR / "apps" / "split_bot" / ".env",
            Path.cwd() / ".env",
        ]
    )
    client_id = (
        os.getenv("LOGISTICS_DING_CLIENT_ID")
        or os.getenv("DING_CLIENT_ID")
        or os.getenv("DINGTALK_APP_KEY")
        or os.getenv("CLIENT_ID")
        or ""
    ).strip()
    client_secret = (
        os.getenv("LOGISTICS_DING_CLIENT_SECRET")
        or os.getenv("DING_CLIENT_SECRET")
        or os.getenv("DINGTALK_APP_SECRET")
        or os.getenv("CLIENT_SECRET")
        or ""
    ).strip()
    robot_code = (
        os.getenv("LOGISTICS_DING_ROBOT_CODE")
        or os.getenv("DING_ROBOT_CODE")
        or os.getenv("DINGTALK_ROBOT_CODE")
        or os.getenv("ROBOT_CODE")
        or ""
    ).strip()
    workspace = os.getenv(
        "LOGISTICS_SPLIT_WORKSPACE",
        os.getenv("PDF_SPLIT_WORKSPACE", str(ROOT_DIR / "apps" / "split_bot" / ".bot-workspace")),
    )
    missing = [
        name
        for name, value in {
            "DING_CLIENT_ID/DINGTALK_APP_KEY": client_id,
            "DING_CLIENT_SECRET/DINGTALK_APP_SECRET": client_secret,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required DingTalk env vars: {', '.join(missing)}")
    return LogisticsBotConfig(
        client_id=client_id,
        client_secret=client_secret,
        robot_code=robot_code,
        split_workspace=workspace,
        stream_ws_ping_interval=_read_positive_int_env("DING_STREAM_WS_PING_INTERVAL", 30),
        stream_ws_ping_timeout=_read_positive_int_env("DING_STREAM_WS_PING_TIMEOUT", 120),
        db_host=os.getenv("DB_HOST", "").strip(),
        db_port=int((os.getenv("DB_PORT") or "3306").strip()),
        db_user=os.getenv("DB_USER", "").strip(),
        db_password=os.getenv("DB_PASSWORD", "").strip(),
        db_name=os.getenv("DB_NAME", "").strip(),
        db_connect_timeout_sec=int((os.getenv("DB_CONNECT_TIMEOUT_SEC") or "5").strip()),
        bot_call_log_table=(os.getenv("BOT_CALL_LOG_TABLE") or "fact_dingtalk_bot_call_log").strip(),
    )
