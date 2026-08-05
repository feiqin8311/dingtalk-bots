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


@dataclass(frozen=True)
class TrackNotifyConfig:
    pingyi_base_url: str
    pingyi_app_token: str
    pingyi_app_key: str
    gateway_base_url: str
    gateway_api_key: str
    gateway_timeout_sec: float
    # 龙舟 AGL 网关并发（默认 1=串行，护网关）
    gateway_max_concurrent: int
    # 两次 AGL 请求启动间隔秒数（0=不额外间隔；串行时单票已 ~80s）
    gateway_min_interval_sec: float
    dingtalk_doc_key: str
    dingtalk_sheet_id: str
    dingtalk_view_id: str
    operator_union_id: str
    ding_client_id: str
    ding_client_secret: str
    ding_robot_code: str
    carrier_keywords: tuple[str, ...]
    ship_year: int | None
    state_dir: Path
    # 行级线程池：平谊可并行；龙舟在网关侧再闸门
    query_workers: int
    # 是否钉钉推送 Excel；False 时只落盘 exports/（暂时默认关）
    send_excel: bool

    @property
    def state_db_path(self) -> Path:
        return self.state_dir / "track_notify.sqlite3"

    @property
    def dedup_db_path(self) -> Path:
        return self.state_db_path

    # 兼容旧字段名
    @property
    def carrier_keyword(self) -> str:
        return self.carrier_keywords[0] if self.carrier_keywords else ""


def _parse_carrier_keywords() -> tuple[str, ...]:
    raw = (
        os.getenv("TRACK_CARRIER_KEYWORDS")
        or os.getenv("TRACK_CARRIER_KEYWORD")
        or "平谊,龙舟"
    ).strip()
    parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
    return tuple(parts) if parts else ("平谊", "龙舟")


def load_config_from_env() -> TrackNotifyConfig:
    load_env_files(
        [
            ROOT_DIR / ".env",
            ROOT_DIR / "apps" / "track_notify" / ".env",
            ROOT_DIR / "apps" / "logistics_bot" / ".env",
            ROOT_DIR / "apps" / "cp_bot" / ".env",
            Path.cwd() / ".env",
        ]
    )
    token = (os.getenv("PINGYI_APP_TOKEN") or "").strip()
    key = (os.getenv("PINGYI_APP_KEY") or "").strip()
    gateway_key = (
        os.getenv("LOGISTICS_GATEWAY_API_KEY")
        or os.getenv("GATEWAY_AUTH_TOKEN")
        or ""
    ).strip()
    if not token and not key and not gateway_key:
        raise RuntimeError(
            "Need PINGYI_APP_TOKEN/KEY and/or LOGISTICS_GATEWAY_API_KEY"
        )
    client_id = (
        os.getenv("LOGISTICS_DING_CLIENT_ID")
        or os.getenv("DING_CLIENT_ID")
        or os.getenv("DINGTALK_APP_KEY")
        or ""
    ).strip()
    client_secret = (
        os.getenv("LOGISTICS_DING_CLIENT_SECRET")
        or os.getenv("DING_CLIENT_SECRET")
        or os.getenv("DINGTALK_APP_SECRET")
        or ""
    ).strip()
    state_raw = (os.getenv("TRACK_NOTIFY_STATE_DIR") or str(APP_DIR / ".state")).strip()
    state_dir = Path(state_raw)
    if not state_dir.is_absolute():
        state_dir = ROOT_DIR / state_dir
    try:
        gateway_timeout = float((os.getenv("LOGISTICS_GATEWAY_TIMEOUT_SEC") or "240").strip())
    except ValueError:
        gateway_timeout = 240.0
    try:
        # 龙舟 AGL 默认串行，避免并行打挂浏览器/会话
        gateway_max_concurrent = int(
            (os.getenv("LOGISTICS_GATEWAY_MAX_CONCURRENT") or "1").strip()
        )
    except ValueError:
        gateway_max_concurrent = 1
    gateway_max_concurrent = max(1, min(8, gateway_max_concurrent))
    try:
        gateway_min_interval = float(
            (os.getenv("LOGISTICS_GATEWAY_MIN_INTERVAL_SEC") or "0").strip()
        )
    except ValueError:
        gateway_min_interval = 0.0
    gateway_min_interval = max(0.0, min(60.0, gateway_min_interval))
    try:
        # 行级并发主要利好平谊；龙舟仍受 gateway_max_concurrent 限制
        query_workers = int((os.getenv("TRACK_QUERY_WORKERS") or "4").strip())
    except ValueError:
        query_workers = 4
    query_workers = max(1, min(16, query_workers))
    ship_year_raw = (os.getenv("TRACK_SHIP_YEAR") or "2026").strip()
    if ship_year_raw in {"", "0", "*", "all", "ANY"}:
        ship_year: int | None = None
    else:
        try:
            ship_year = int(ship_year_raw)
        except ValueError:
            ship_year = 2026
    # 暂时默认不推钉钉，只生成 Excel；要推送设 TRACK_SEND_EXCEL=1
    send_raw = (os.getenv("TRACK_SEND_EXCEL") or "0").strip().lower()
    send_excel = send_raw in {"1", "true", "yes", "on", "y"}
    return TrackNotifyConfig(
        pingyi_base_url=(os.getenv("PINGYI_BASE_URL") or "http://hzpy.rtb56.com").strip(),
        pingyi_app_token=token,
        pingyi_app_key=key,
        gateway_base_url=(
            os.getenv("LOGISTICS_GATEWAY_BASE_URL")
            or "http://host.docker.internal:18743"
        ).strip(),
        gateway_api_key=gateway_key,
        gateway_timeout_sec=max(30.0, gateway_timeout),
        gateway_max_concurrent=gateway_max_concurrent,
        gateway_min_interval_sec=gateway_min_interval,
        dingtalk_doc_key=(
            os.getenv("TRACK_DINGTALK_DOC_KEY") or "R1zknDm0WRl1kQwrCZ9rmxxDJBQEx5rG"
        ).strip(),
        dingtalk_sheet_id=(os.getenv("TRACK_DINGTALK_SHEET_ID") or "0r21tyL").strip(),
        dingtalk_view_id=(os.getenv("TRACK_DINGTALK_VIEW_ID") or "6n38xji").strip(),
        operator_union_id=(
            os.getenv("TRACK_OPERATOR_UNION_ID") or "iiTcqTk5siSYoBBbKR7hRGiSQiEiE"
        ).strip(),
        ding_client_id=client_id,
        ding_client_secret=client_secret,
        ding_robot_code=(
            os.getenv("LOGISTICS_DING_ROBOT_CODE")
            or os.getenv("DING_ROBOT_CODE")
            or os.getenv("DINGTALK_ROBOT_CODE")
            or ""
        ).strip(),
        carrier_keywords=_parse_carrier_keywords(),
        ship_year=ship_year,
        state_dir=state_dir,
        query_workers=query_workers,
        send_excel=send_excel,
    )
