from __future__ import annotations

import asyncio
import logging
import sys
import time
import zipfile
from dataclasses import dataclass, field
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import dingtalk_stream
import requests
from dingtalk_stream import AckMessage

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent.parent
SPLIT_DIR = ROOT_DIR / "apps" / "split_bot"
for path in (str(APP_DIR), str(ROOT_DIR), str(SPLIT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import config as pinxiang_config  # noqa: E402
from amazon_packaging import fill_amazon_packaging_file, is_amazon_packaging_workbook  # noqa: E402
from packing import process_shipment_file, write_packing_workbook  # noqa: E402
from product_info_source import load_product_specs  # noqa: E402
from runtime import (  # noqa: E402
    MessageDeduplicator,
    collect_download_codes,
    collect_file_names_by_download_code,
)
from Utils.dingtalk_api import (  # noqa: E402
    get_token,
    send_robot_private_file_message,
    send_robot_private_text_message,
)


class MessageFormatError(ValueError):
    pass


@dataclass
class DownloadedFile:
    path: Path
    file_name: str
    content_type: str


@dataclass
class PendingLogistics:
    """物流侧：已出拼箱结果，待确认 / 选运营。"""

    packing_result_path: Path
    merge_dir: Path
    shipment_path: Path
    stage: str  # confirm | select_ops
    updated_at: float


@dataclass
class PendingOpsJob:
    """运营侧：已收到拼箱，待上传亚马逊装箱表。"""

    logistics_user_id: str
    logistics_name_hint: str
    packing_result_path: Path
    merge_dir: Path
    shipment_path: Path
    updated_at: float


class PinxiangBotHandler(dingtalk_stream.ChatbotHandler):
    """不分仓拼箱：发货单→拼箱结果→物流选运营转发→运营上传装箱表→回填。"""

    def __init__(self, logger: Optional[logging.Logger] = None, config: Optional[object] = None):
        super().__init__()
        self.logger = logger or logging.getLogger(__name__)
        self.config = config
        self.workspace = Path(
            getattr(config, "pinxiang_workspace", None)
            or getattr(config, "workspace", None)
            or pinxiang_config.WORKSPACE
        )
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._deduplicator = MessageDeduplicator()
        self._job_semaphore = asyncio.Semaphore(1)
        self._pending_logistics: dict[str, PendingLogistics] = {}
        self._pending_ops: dict[str, PendingOpsJob] = {}
        self._pending_ttl_seconds = int(
            getattr(config, "pinxiang_pending_ttl_sec", pinxiang_config.PENDING_TTL_SEC)
        )
        self.ops_users = list(pinxiang_config.OPS_USERS)

    async def process(self, callback: dingtalk_stream.CallbackMessage) -> Tuple[str, str]:
        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        user_id = str(incoming_message.sender_staff_id or "")
        message_key = incoming_message.message_id or f"{user_id}:{incoming_message.create_at}"
        self.logger.info("pinxiang received message: user_id=%s message_id=%s", user_id, incoming_message.message_id)
        if self._deduplicator.seen(message_key):
            self.logger.info("pinxiang skip duplicate: %s", message_key)
            return AckMessage.STATUS_OK, "OK"
        try:
            async with self._job_semaphore:
                await self._handle_message(incoming_message, user_id, callback.data)
        except (FileNotFoundError, MessageFormatError, ValueError) as exc:
            await self._send_text(user_id, str(exc))
        except Exception as exc:
            self.logger.exception("pinxiang task failed")
            await self._send_text(user_id, f"不分仓拼箱失败：{exc}")
        return AckMessage.STATUS_OK, "OK"

    async def _handle_message(self, incoming_message, user_id: str, raw_payload: dict) -> None:
        message_text = self._extract_message_text(incoming_message, raw_payload)
        self._cleanup_pending()

        has_files = bool(collect_download_codes(raw_payload))

        # 运营上传装箱表
        if has_files and user_id in self._pending_ops:
            await self._handle_ops_amazon_upload(incoming_message, user_id, raw_payload)
            return

        # 物流选运营 / 确认 / 取消（纯文本）
        if not has_files:
            if await self._handle_text_commands(user_id, message_text):
                return
            if user_id in self._pending_ops:
                raise MessageFormatError(
                    "请上传亚马逊「包装箱包装信息」Excel（.xlsx）。\n回复【取消】可放弃当前任务。"
                )
            raise MessageFormatError(
                "请上传发货单 Excel（.xlsx）。\n"
                "拼箱结果出来后：回复【确认】并选择运营转发；运营上传装箱表后机器人填写回传。"
            )

        # 物流上传发货单（若该用户同时是运营且有待办，优先当装箱表）
        download_codes = collect_download_codes(raw_payload)
        file_names = collect_file_names_by_download_code(raw_payload)
        downloaded = await asyncio.get_running_loop().run_in_executor(
            None,
            self._download_excel,
            download_codes,
            incoming_message.message_id,
            file_names,
        )
        if downloaded is None:
            raise MessageFormatError("未识别到 Excel（.xlsx），请重试。")

        if is_amazon_packaging_workbook(downloaded.path):
            # 运营误走物流分支：若有待办则填表
            if user_id in self._pending_ops:
                await self._fill_and_reply_amazon(user_id, downloaded)
                return
            raise MessageFormatError(
                "这是亚马逊装箱表。请先由物流完成拼箱并转发任务后，再由运营上传此文件。"
            )

        await self._handle_shipment_upload(user_id, downloaded, incoming_message)

    async def _handle_shipment_upload(self, user_id: str, shipment: DownloadedFile, incoming_message) -> None:
        await self._send_text(user_id, "已收到发货单，正在计算拼箱，请稍等…")
        job_dir = self.workspace / str(incoming_message.message_id or time.time_ns())
        job_dir.mkdir(parents=True, exist_ok=True)

        product_specs = await asyncio.get_running_loop().run_in_executor(
            None, self._load_product_specs_safe
        )
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(process_shipment_file, shipment.path, product_specs=product_specs),
        )
        packing_name = f"拼箱结果-{Path(shipment.file_name).stem}.xlsx"
        packing_path = job_dir / packing_name
        await asyncio.get_running_loop().run_in_executor(
            None, partial(write_packing_workbook, result, packing_path)
        )

        shipment_copy = job_dir / shipment.file_name
        if shipment.path.resolve() != shipment_copy.resolve():
            shipment_copy.write_bytes(shipment.path.read_bytes())
        else:
            shipment_copy = shipment.path

        self._pending_logistics[user_id] = PendingLogistics(
            packing_result_path=packing_path,
            merge_dir=job_dir,
            shipment_path=shipment_copy,
            stage="confirm",
            updated_at=time.time(),
        )

        await self._send_file(
            user_id,
            packing_name,
            packing_path.read_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        warn_text = ""
        if result.warnings:
            warn_text = "\n⚠️ " + "；".join(result.warnings[:5])
        if not result.rows:
            warn_text += "\n（本票无非整箱行，拼箱结果表为空。）"
        await self._send_text(
            user_id,
            "拼箱结果已发送。"
            f"{warn_text}\n\n"
            "请审核：\n"
            "回复【确认】➡️ 选择运营并转发\n"
            "回复【取消】➡️ 放弃本次任务",
        )

    async def _handle_text_commands(self, user_id: str, message_text: str) -> bool:
        normalized = _normalize(message_text)
        if not normalized:
            return False

        if normalized in {"取消", "cancel", "取消拼箱"}:
            self._pending_logistics.pop(user_id, None)
            if user_id in self._pending_ops:
                self._pending_ops.pop(user_id, None)
            await self._send_text(user_id, "已取消本次拼箱任务。")
            return True

        pending = self._pending_logistics.get(user_id)

        # 选择运营
        if pending and pending.stage == "select_ops":
            ops = self._match_ops_choice(normalized)
            if ops is None:
                await self._send_text(user_id, self._ops_menu_text(prefix="请选择运营人员：\n"))
                return True
            await self._forward_to_ops(user_id, pending, ops)
            return True

        # 确认 → 进入选运营
        if normalized in {"确认", "confirm", "确认拼箱"}:
            if pending is None:
                raise MessageFormatError("当前没有待确认的拼箱任务，请先上传发货单。")
            if not pending.packing_result_path.is_file():
                raise MessageFormatError("拼箱结果文件丢失，请重新上传发货单。")
            pending.stage = "select_ops"
            pending.updated_at = time.time()
            await self._send_text(user_id, self._ops_menu_text(prefix="已确认拼箱结果。\n请选择要转发的运营：\n"))
            return True

        return False

    async def _forward_to_ops(self, logistics_user_id: str, pending: PendingLogistics, ops: dict) -> None:
        ops_id = ops["user_id"]
        ops_name = ops["name"]
        packing_path = pending.packing_result_path
        packing_bytes = packing_path.read_bytes()
        packing_name = packing_path.name

        # 发给运营：说明 + 拼箱结果
        await self._send_text(
            ops_id,
            f"【不分仓拼箱】物流已审核通过，请处理。\n"
            f"来源物流用户：{logistics_user_id}\n"
            f"请下载拼箱结果核对后，上传亚马逊「包装箱包装信息」Excel，"
            f"机器人将自动填写并回传。",
        )
        await self._send_file(
            ops_id,
            packing_name,
            packing_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        self._pending_ops[ops_id] = PendingOpsJob(
            logistics_user_id=logistics_user_id,
            logistics_name_hint=logistics_user_id,
            packing_result_path=packing_path,
            merge_dir=pending.merge_dir,
            shipment_path=pending.shipment_path,
            updated_at=time.time(),
        )
        self._pending_logistics.pop(logistics_user_id, None)

        await self._send_text(
            logistics_user_id,
            f"已转发给运营【{ops_name}】。\n等待运营上传亚马逊装箱表并由机器人填写回传。",
        )
        self.logger.info(
            "pinxiang forwarded to ops=%s(%s) from logistics=%s",
            ops_name,
            ops_id,
            logistics_user_id,
        )

    async def _handle_ops_amazon_upload(self, incoming_message, user_id: str, raw_payload: dict) -> None:
        download_codes = collect_download_codes(raw_payload)
        file_names = collect_file_names_by_download_code(raw_payload)
        downloaded = await asyncio.get_running_loop().run_in_executor(
            None,
            self._download_excel,
            download_codes,
            incoming_message.message_id,
            file_names,
        )
        if downloaded is None:
            raise MessageFormatError("未识别到 Excel 文件。")
        if not is_amazon_packaging_workbook(downloaded.path):
            raise MessageFormatError(
                "请上传含「包装箱包装信息」工作表的亚马逊装箱 Excel（不是发货单、也不是 Manifest 模版）。"
            )
        await self._fill_and_reply_amazon(user_id, downloaded)

    async def _fill_and_reply_amazon(self, ops_user_id: str, amazon_file: DownloadedFile) -> None:
        job = self._pending_ops.get(ops_user_id)
        if job is None:
            raise MessageFormatError("当前没有待处理的拼箱任务。")

        await self._send_text(ops_user_id, "已收到装箱表，正在按拼箱结果填写，请稍等…")

        packing_result = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                process_shipment_file,
                job.shipment_path,
                product_specs=self._load_product_specs_safe(),
            ),
        )
        # 拼箱结果表只含改箱行；填亚马逊时用 rows（与业务样例一致）
        rows = packing_result.rows
        if not rows:
            raise MessageFormatError("拼箱结果无改箱行，无法填写装箱表。")

        out_name = f"已填写-{amazon_file.file_name}"
        if not out_name.lower().endswith(".xlsx"):
            out_name += ".xlsx"
        out_path = job.merge_dir / out_name

        await asyncio.get_running_loop().run_in_executor(
            None,
            partial(fill_amazon_packaging_file, amazon_file.path, rows, out_path),
        )

        await self._send_file(
            ops_user_id,
            out_name,
            out_path.read_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        await self._send_text(ops_user_id, "装箱表已填写完成，请查收。")

        # 抄送物流
        try:
            await self._send_file(
                job.logistics_user_id,
                out_name,
                out_path.read_bytes(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            await self._send_text(
                job.logistics_user_id,
                f"运营已完成装箱表填写（文件已抄送）。任务结束。",
            )
        except Exception:
            self.logger.exception("copy filled amazon file to logistics failed")

        self._pending_ops.pop(ops_user_id, None)

    def _ops_menu_text(self, *, prefix: str = "") -> str:
        lines = [prefix.rstrip(), ""]
        for i, ops in enumerate(self.ops_users, start=1):
            lines.append(f"{i}. {ops['name']}")
        lines.append("")
        lines.append("回复序号或姓名选择；回复【取消】放弃。")
        return "\n".join(lines).strip()

    def _match_ops_choice(self, normalized: str) -> Optional[dict]:
        # 1 / 1. / 1、
        for i, ops in enumerate(self.ops_users, start=1):
            if normalized == str(i) or normalized.startswith(f"{i}.") or normalized.startswith(f"{i}、"):
                return ops
            name = _normalize(ops["name"])
            if name and (normalized == name or name in normalized or normalized in name):
                return ops
            if normalized == ops["user_id"]:
                return ops
        return None

    def _download_excel(
        self,
        download_codes: list[str],
        message_id: str,
        file_names: Optional[dict[str, str]] = None,
    ) -> Optional[DownloadedFile]:
        job_dir = self.workspace / str(message_id) / "downloads"
        job_dir.mkdir(parents=True, exist_ok=True)
        file_names = file_names or {}
        for index, code in enumerate(download_codes, start=1):
            download_url = self.get_image_download_url(code)
            if not download_url:
                continue
            response = requests.get(download_url, timeout=120)
            response.raise_for_status()
            file_name = file_names.get(code) or _infer_filename(response.headers, f"file-{index}.xlsx")
            suffix = Path(file_name).suffix.lower()
            file_path = job_dir / file_name
            file_path.write_bytes(response.content)
            downloaded = DownloadedFile(file_path, file_name, response.headers.get("Content-Type", ""))
            if suffix in {".xlsx", ".xlsm"} or _looks_like_xlsx(response.content):
                return downloaded
            if suffix == ".xls":
                raise MessageFormatError("暂不支持 .xls，请另存为 .xlsx 后重试。")
        return None

    def _cleanup_pending(self) -> None:
        cutoff = time.time() - self._pending_ttl_seconds
        self._pending_logistics = {
            k: v for k, v in self._pending_logistics.items() if v.updated_at >= cutoff
        }
        self._pending_ops = {k: v for k, v in self._pending_ops.items() if v.updated_at >= cutoff}

    def clear_user(self, user_id: str) -> None:
        self._pending_logistics.pop(user_id, None)
        self._pending_ops.pop(user_id, None)

    def has_pending(self, user_id: str) -> bool:
        """供 logistics 路由：有进行中任务则强制进 pinxiang，无需再回菜单 3。"""
        if not user_id:
            return False
        return user_id in self._pending_logistics or user_id in self._pending_ops

    def _load_product_specs_safe(self) -> dict:
        path = (pinxiang_config.PRODUCT_INFO_PATH or "").strip()
        if not path:
            return {}
        if not path.lower().startswith("smb://") and not path.startswith("\\\\") and not path.startswith("//"):
            if not Path(path).is_file():
                self.logger.warning("product info file missing, fallback to shipment pack fields: %s", path)
                return {}
        try:
            return load_product_specs(
                path,
                smb_username=pinxiang_config.SMB_USERNAME,
                smb_password=pinxiang_config.SMB_PASSWORD,
                smb_port=pinxiang_config.SMB_PORT,
                smb_timeout_sec=pinxiang_config.SMB_TIMEOUT_SEC,
                smb_client_name=pinxiang_config.SMB_CLIENT_NAME,
            )
        except Exception as exc:
            self.logger.warning("load product info failed, fallback to shipment pack fields: %s", exc)
            return {}

    async def _send_text(self, user_id: str, message: str) -> None:
        if not user_id:
            self.logger.warning("pinxiang cannot send text: missing user id")
            return
        token = await get_token(self.config)
        if token:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, send_robot_private_text_message, token, self.config, [user_id], message
            )

    async def _send_file(
        self,
        user_id: str,
        file_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        token = await get_token(self.config)
        if not token:
            raise RuntimeError("无法获取钉钉 access token")
        loop = asyncio.get_running_loop()
        media_id = await loop.run_in_executor(
            None,
            self.dingtalk_client.upload_to_dingtalk,
            content,
            "file",
            file_name,
            content_type,
        )
        if not media_id:
            raise RuntimeError("文件上传到钉钉失败")
        result = await loop.run_in_executor(
            None,
            send_robot_private_file_message,
            token,
            self.config,
            [user_id],
            media_id,
            file_name,
        )
        if not result:
            raise RuntimeError("文件消息发送失败")

    def _extract_message_text(self, incoming_message, raw_payload: dict) -> str:
        try:
            return "\n".join(self.extract_text_from_incoming_message(incoming_message) or []).strip()
        except Exception:
            pass
        content = raw_payload.get("text", {}).get("content")
        if isinstance(content, str):
            return content.strip()
        return ""


def _normalize(text: str) -> str:
    return (text or "").strip().lower().replace(" ", "").replace("\u3000", "")


def _infer_filename(headers, fallback_name: str) -> str:
    content_disposition = headers.get("Content-Disposition", "")
    if "filename=" in content_disposition:
        raw = content_disposition.split("filename=", 1)[1].strip().strip('"')
        return Path(urlparse(raw).path).name or fallback_name
    return fallback_name


def _looks_like_xlsx(content: bytes) -> bool:
    if not content.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "xl/workbook.xml" in names
