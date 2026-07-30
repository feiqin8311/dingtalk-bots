from __future__ import annotations

import logging
import re
import sys
import json
import threading
import urllib.request
import uuid
from pathlib import Path
from typing import Literal, Tuple

import dingtalk_stream
from dingtalk_stream import AckMessage

from settings import ROOT_DIR, LogisticsBotConfig

# branch selection must survive process restart (was pure memory → menu after upload)
_BRANCH_STATE_PATH = ROOT_DIR / "apps" / "logistics_bot" / ".state" / "selected_branch.json"
_VALID_BRANCHES = frozenset({"cp", "split", "pinxiang", "lcl"})


CP_APP_DIR = ROOT_DIR / "apps" / "cp_bot"
SPLIT_APP_DIR = ROOT_DIR / "apps" / "split_bot"
PINXIANG_APP_DIR = ROOT_DIR / "apps" / "pinxiang_bot"
LCL_APP_DIR = ROOT_DIR / "apps" / "lcl_bot"
# insert order: last wins for top-level `handler` → cp_bot must be last
for path in (str(SPLIT_APP_DIR), str(CP_APP_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from handler import ShipmentQueryHandler  # type: ignore  # noqa: E402
from Bot.handler import PdfSplitBotHandler  # type: ignore  # noqa: E402
from Bot.runtime import collect_download_codes  # type: ignore  # noqa: E402
from Utils.dingtalk_api import get_token, send_robot_private_text_message  # type: ignore  # noqa: E402
from shared.call_log import ProjectCallLogStore  # noqa: E402

# pinxiang / lcl isolated: absolute path load so they never shadow cp_bot.handler
import importlib.util

_pinxiang_spec = importlib.util.spec_from_file_location(
    "pinxiang_bot_handler",
    PINXIANG_APP_DIR / "handler.py",
)
assert _pinxiang_spec and _pinxiang_spec.loader
_pinxiang_module = importlib.util.module_from_spec(_pinxiang_spec)
sys.modules["pinxiang_bot_handler"] = _pinxiang_module
_pinxiang_spec.loader.exec_module(_pinxiang_module)
PinxiangBotHandler = _pinxiang_module.PinxiangBotHandler

if str(LCL_APP_DIR) not in sys.path:
    sys.path.insert(0, str(LCL_APP_DIR.parent))  # apps/ so `import lcl_bot` works
from lcl_bot.handlers import WorkflowBotHandler as LclBotHandler  # type: ignore  # noqa: E402


RouteName = Literal[
    "cp",
    "split",
    "pinxiang",
    "lcl",
    "help",
    "reset",
    "select_cp",
    "select_split",
    "select_pinxiang",
    "select_lcl",
]

HELP_TEXT = """物流部机器人

请选择要办理的业务：
1. 发货单核对
2. 标签/PDF 拆分
3. 不分仓拼箱
4. 分仓拼箱

回复【1】【2】【3】或【4】进入对应业务
回复【重置】➡️ 放弃本次并重新选择业务
"""

CP_SELECTED_TEXT = """已进入：1. 发货单核对

请发送发货单号，例如：
SP260204001

回复【重置】➡️ 放弃本次并重新选择业务
"""

SPLIT_SELECTED_TEXT = """已进入：2. 标签/PDF 拆分

请上传 PDF 文件和 Excel 规则文件。
拆分预览后，回复“确认”继续，或回复“取消”放弃。

回复【重置】➡️ 放弃本次并重新选择业务
"""

PINXIANG_SELECTED_TEXT = """已进入：3. 不分仓拼箱

物流：上传发货单 Excel → 审核拼箱结果 → 确认并选择运营转发。
运营：收到拼箱结果与 Amazon 模板后处理。

回复【重置】➡️ 放弃本次并重新选择业务
"""

LCL_SELECTED_TEXT = """已进入：4. 分仓拼箱

物流：上传含「发货单详情」的 Excel → 审核拼箱结果 → 确认转发给运营。
运营：下载拼箱结果与 Amazon 模板；可回【模板2】；上传包装信息表后机器人回填。
后续可按提示处理领星删单等步骤。

回复【重置】➡️ 放弃本次并重新选择业务
"""

RESET_TEXT = """已重置当前选择。

请选择要办理的业务：
1. 发货单核对
2. 标签/PDF 拆分
3. 不分仓拼箱
4. 分仓拼箱

回复【重置】➡️ 放弃本次并重新选择业务
"""


class LogisticsRouter(dingtalk_stream.ChatbotHandler):
    def __init__(self, *, logger: logging.Logger, config: LogisticsBotConfig):
        super().__init__()
        self.logger = logger
        self.config = config
        self.cp_handler = ShipmentQueryHandler(logger=logger)
        self.split_handler = PdfSplitBotHandler(logger=logger, config=config)
        self.pinxiang_handler = PinxiangBotHandler(logger=logger, config=config)
        self.lcl_handler = LclBotHandler(logger=logger, config_obj=config)
        self._branch_lock = threading.Lock()
        self._selected_branch_by_user: dict[str, RouteName] = self._load_branch_state()
        self._call_log = self._build_call_log_store()

    async def process(self, callback: dingtalk_stream.CallbackMessage) -> Tuple[str, str]:
        if getattr(self.split_handler, "dingtalk_client", None) is None:
            self.split_handler.dingtalk_client = self.dingtalk_client
        if getattr(self.cp_handler, "dingtalk_client", None) is None:
            self.cp_handler.dingtalk_client = self.dingtalk_client
        if getattr(self.pinxiang_handler, "dingtalk_client", None) is None:
            self.pinxiang_handler.dingtalk_client = self.dingtalk_client
        if getattr(self.lcl_handler, "dingtalk_client", None) is None:
            self.lcl_handler.dingtalk_client = self.dingtalk_client
        user_id = self._extract_user_id(callback.data)
        route = self._route(callback.data, user_id=user_id)
        self.logger.info("logistics router selected route=%s", route)
        self._log_route_event(callback.data, route=route, user_id=user_id)
        if route == "reset":
            self._reset_user(user_id)
            await self._send_text(callback.data, RESET_TEXT)
            return AckMessage.STATUS_OK, "RESET"
        if route == "select_cp":
            self._set_branch(user_id, "cp")
            await self._send_text(callback.data, CP_SELECTED_TEXT)
            return AckMessage.STATUS_OK, "SELECT_CP"
        if route == "select_split":
            self._set_branch(user_id, "split")
            await self._send_text(callback.data, SPLIT_SELECTED_TEXT)
            return AckMessage.STATUS_OK, "SELECT_SPLIT"
        if route == "select_pinxiang":
            self._set_branch(user_id, "pinxiang")
            await self._send_text(callback.data, PINXIANG_SELECTED_TEXT)
            return AckMessage.STATUS_OK, "SELECT_PINXIANG"
        if route == "select_lcl":
            self._set_branch(user_id, "lcl")
            await self._send_text(callback.data, LCL_SELECTED_TEXT)
            return AckMessage.STATUS_OK, "SELECT_LCL"
        if route == "cp":
            return await self.cp_handler.process(callback)
        if route == "split":
            return await self.split_handler.process(callback)
        if route == "pinxiang":
            return await self.pinxiang_handler.process(callback)
        if route == "lcl":
            return await self.lcl_handler.process(callback)
        await self._send_text(callback.data, HELP_TEXT)
        return AckMessage.STATUS_OK, "HELP"

    def _set_branch(self, user_id: str, branch: RouteName) -> None:
        if not user_id or branch not in _VALID_BRANCHES:
            return
        with self._branch_lock:
            self._selected_branch_by_user[user_id] = branch
            self._save_branch_state_unlocked()

    def _load_branch_state(self) -> dict[str, RouteName]:
        path = _BRANCH_STATE_PATH
        try:
            if not path.is_file():
                return {}
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            out: dict[str, RouteName] = {}
            for uid, branch in raw.items():
                if uid and branch in _VALID_BRANCHES:
                    out[str(uid)] = branch  # type: ignore[assignment]
            return out
        except Exception as exc:
            self.logger.warning("load branch state failed: %s", exc)
            return {}

    def _save_branch_state_unlocked(self) -> None:
        path = _BRANCH_STATE_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._selected_branch_by_user, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception as exc:
            self.logger.warning("save branch state failed: %s", exc)

    def _build_call_log_store(self) -> ProjectCallLogStore | None:
        missing = [
            name
            for name, value in {
                "DB_HOST": getattr(self.config, "db_host", ""),
                "DB_USER": getattr(self.config, "db_user", ""),
                "DB_NAME": getattr(self.config, "db_name", ""),
            }.items()
            if not str(value).strip()
        ]
        if missing:
            self.logger.warning("logistics call log disabled: missing %s", ", ".join(missing))
            return None
        return ProjectCallLogStore(
            host=getattr(self.config, "db_host"),
            port=getattr(self.config, "db_port", 3306),
            user=getattr(self.config, "db_user"),
            password=getattr(self.config, "db_password", ""),
            database=getattr(self.config, "db_name"),
            table=getattr(self.config, "bot_call_log_table", "fact_dingtalk_bot_call_log"),
            connect_timeout_sec=getattr(self.config, "db_connect_timeout_sec", 5),
        )

    def _log_route_event(self, payload: dict, *, route: RouteName, user_id: str) -> None:
        if self._call_log is None:
            return
        if route in {"reset", "select_cp", "select_split", "select_pinxiang", "select_lcl", "help"}:
            return
        text = self._extract_text(payload)
        normalized = self._normalize_command(text)
        if route in {"split", "pinxiang", "lcl"} and normalized in {
            "确认",
            "确认拆分",
            "确认拼箱",
            "confirm",
            "取消",
            "取消拆分",
            "取消拼箱",
            "cancel",
            "模板2",
            "template2",
        }:
            return
        try:
            self._call_log.log_event(
                bot_module="logistics",
                event_type=f"ROUTE_{str(route).upper()}",
                request_id=str(payload.get("messageId") or payload.get("msgId") or uuid.uuid4().hex[:12]),
                message_id=str(payload.get("messageId") or payload.get("msgId") or "") or None,
                user_id=user_id or None,
                user_name=self._extract_user_name(payload),
                message_text=self._extract_text(payload) or f"[{route}]",
            )
        except Exception as exc:
            self.logger.warning("logistics route call log failed: %s", exc)

    def _route(self, payload: dict, *, user_id: str) -> RouteName:
        text = self._extract_text(payload)
        normalized = self._normalize_command(text)
        if normalized in {"重置", "重新开始", "reset"}:
            return "reset"
        # 拼箱进行中（选运营 1/2、确认、运营上传）优先于全局菜单，
        # 否则回复「1. 柯鹏翔」会被误判为「1. 发货单核对」
        if user_id and getattr(self.pinxiang_handler, "has_pending", lambda _u: False)(user_id):
            return "pinxiang"
        selected = self._selected_branch_by_user.get(user_id or "")
        if selected == "pinxiang":
            return "pinxiang"
        if selected == "lcl":
            return "lcl"
        if self._is_menu_choice(normalized, "1"):
            return "select_cp"
        if self._is_menu_choice(normalized, "2"):
            return "select_split"
        if self._is_menu_choice(normalized, "3"):
            return "select_pinxiang"
        if self._is_menu_choice(normalized, "4"):
            return "select_lcl"
        if selected in {"cp", "split"}:
            if collect_download_codes(payload):
                return "split"
            if normalized in {"确认", "确认拆分", "confirm", "取消", "取消拆分", "cancel"}:
                return "split"
            return selected
        return "help"

    @staticmethod
    def _normalize_command(text: str) -> str:
        return re.sub(r"\s+", "", (text or "").strip()).lower()

    @staticmethod
    def _is_menu_choice(normalized: str, choice: str) -> bool:
        if normalized == choice:
            return True
        return (
            normalized.startswith(f"{choice}.")
            or normalized.startswith(f"{choice}、")
            or normalized.startswith(f"{choice},")
        )

    @staticmethod
    def _looks_like_split_command(text: str) -> bool:
        return bool(re.search(r"(拆分|标签拆分|pdf\s*split|split)", text, flags=re.IGNORECASE))

    @staticmethod
    def _looks_like_cp_command(text: str) -> bool:
        if re.search(r"\bSP[0-9A-Za-z]+\b", text, flags=re.IGNORECASE):
            return True
        if re.match(r"^\s*(?:选择文件|选文件|pick)\s+SP[0-9A-Za-z]+\s+\d+\s*$", text, flags=re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _extract_text(payload: dict) -> str:
        candidates = _walk_text_values(payload)
        if candidates:
            return "\n".join(item for item in candidates if item).strip()
        try:
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(payload)
        except Exception:
            incoming_message = None
        if incoming_message is not None:
            for attr in ("text", "content", "text_content"):
                value = getattr(incoming_message, attr, None)
                if isinstance(value, str):
                    candidates.append(value)
                elif isinstance(value, dict):
                    candidates.extend(str(v) for v in value.values() if v)
                elif value is not None:
                    for nested_attr in ("content", "text"):
                        nested = getattr(value, nested_attr, None)
                        if nested:
                            candidates.append(str(nested))
        candidates.extend(_walk_text_values(payload))
        return "\n".join(item for item in candidates if item).strip()

    async def _send_text(self, payload: dict, message: str) -> None:
        if self._send_session_text(payload, message):
            return
        user_id = self._extract_user_id(payload)
        if not user_id:
            self.logger.warning("cannot send text: missing sender user id")
            return
        if not self.config.robot_code:
            self.logger.warning("cannot send private text: missing robot_code")
            return
        token = await get_token(self.config)
        if not token:
            self.logger.warning("cannot send text: missing DingTalk access token")
            return
        send_robot_private_text_message(token, self.config, [user_id], message)

    def _send_session_text(self, payload: dict, message: str) -> bool:
        webhook = self._extract_session_webhook(payload)
        if not webhook:
            return False
        data = json.dumps({"msgtype": "text", "text": {"content": message}}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(webhook, data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10):
                return True
        except Exception as exc:
            self.logger.warning("session webhook send failed: %s", exc)
            return False

    def _reset_user(self, user_id: str) -> None:
        if not user_id:
            return
        prev = self._selected_branch_by_user.get(user_id)
        with self._branch_lock:
            self._selected_branch_by_user.pop(user_id, None)
            self._save_branch_state_unlocked()
        self.split_handler._pending_uploads.pop(user_id, None)
        self.split_handler._pending_confirmations.pop(user_id, None)
        clear = getattr(self.pinxiang_handler, "clear_user", None)
        if callable(clear):
            clear(user_id)
        # lcl 全局单工作流：从分仓分支重置时清状态
        if prev == "lcl":
            try:
                sm = getattr(self.lcl_handler, "state_manager", None)
                if sm is not None and hasattr(sm, "reset"):
                    sm.reset()
            except Exception as exc:
                self.logger.warning("lcl state reset failed: %s", exc)

    @staticmethod
    def _extract_user_id(payload: dict) -> str:
        try:
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(payload)
            value = getattr(incoming_message, "sender_staff_id", None)
            if value:
                return str(value)
        except Exception:
            pass
        for key in ("senderStaffId", "sender_staff_id", "senderId", "sender_id"):
            value = payload.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _extract_user_name(payload: dict) -> str | None:
        for key in ("senderNick", "sender_nick", "userName", "user_name"):
            value = payload.get(key)
            if value:
                return str(value)
        try:
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(payload)
            value = getattr(incoming_message, "sender_nick", None)
            if value:
                return str(value)
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_session_webhook(payload: dict) -> str:
        for key in ("sessionWebhook", "session_webhook"):
            value = payload.get(key)
            if value:
                return str(value)
        try:
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(payload)
            value = getattr(incoming_message, "session_webhook", None)
            if value:
                return str(value)
        except Exception:
            pass
        return ""


def _walk_text_values(value) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"content", "text", "text_content"} and isinstance(nested, str) and nested.strip():
                found.append(nested.strip())
            else:
                found.extend(_walk_text_values(nested))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_text_values(item))
    return found
