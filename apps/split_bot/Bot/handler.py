from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import dingtalk_stream
import requests
from dingtalk_stream import AckMessage

from pdf_zip_bot import build_rules_from_workbook, format_rule_preview_markdown, workbook_uses_explicit_pages
from pdf_zip_bot.rules import SplitRule
from pdf_zip_bot.messages import MessageFormatError
from Bot.runtime import (
    MessageDeduplicator,
    collect_download_codes,
    collect_file_names_by_download_code,
    run_split_job,
)
from Utils.dingtalk_api import get_token, send_robot_private_file_message, send_robot_private_text_message


@dataclass
class DownloadedFile:
    path: Path
    file_name: str
    content_type: str


@dataclass
class DownloadedAttachments:
    source_pdf: Optional[DownloadedFile] = None
    rule_workbook: Optional[DownloadedFile] = None


@dataclass
class PendingUpload:
    attachments: DownloadedAttachments
    updated_at: float


@dataclass
class PendingConfirmation:
    source_pdf: DownloadedFile
    rules: list[SplitRule]
    updated_at: float


class PdfSplitBotHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, logger: Optional[logging.Logger] = None, config: Optional[object] = None):
        super().__init__()
        self.logger = logger or logging.getLogger(__name__)
        self.config = config
        self.workspace = Path(getattr(config, "workspace", Path(tempfile.gettempdir()) / "pdf-zip-bot-jobs"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._deduplicator = MessageDeduplicator()
        self._job_semaphore = asyncio.Semaphore(1)
        self._pending_uploads: dict[str, PendingUpload] = {}
        self._pending_confirmations: dict[str, PendingConfirmation] = {}
        self._pending_ttl_seconds = 600

    async def process(self, callback: dingtalk_stream.CallbackMessage) -> Tuple[str, str]:
        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        user_id = incoming_message.sender_staff_id
        message_key = incoming_message.message_id or f"{user_id}:{incoming_message.create_at}"
        self.logger.info("received message: user_id=%s message_id=%s", user_id, incoming_message.message_id)
        if self._deduplicator.seen(message_key):
            self.logger.info("skip duplicate message: %s", message_key)
            return AckMessage.STATUS_OK, "OK"
        try:
            async with self._job_semaphore:
                await self._handle_message(incoming_message, user_id, callback.data)
        except (FileNotFoundError, MessageFormatError) as exc:
            await self._send_text(user_id, str(exc))
        except Exception as exc:
            self.logger.exception("pdf split task failed")
            await self._send_text(user_id, f"PDF 拆分失败：{exc}")
        return AckMessage.STATUS_OK, "OK"

    async def _handle_message(self, incoming_message, user_id: str, raw_payload: dict) -> None:
        message_text = self._extract_message_text(incoming_message, raw_payload)
        if not collect_download_codes(raw_payload):
            self.logger.info("handling text-only message: user_id=%s text=%s", user_id, message_text)
            if await self._handle_confirmation_message(incoming_message, user_id, message_text):
                return
            raise MessageFormatError("请上传 PDF 文件或 Excel 规则文件（.xlsx）")

        download_codes = collect_download_codes(raw_payload)
        file_names = collect_file_names_by_download_code(raw_payload)

        self._cleanup_pending_uploads()
        self._cleanup_pending_confirmations()
        attachments = await asyncio.get_running_loop().run_in_executor(
            None, self._download_message_files, download_codes, incoming_message.message_id, file_names
        )
        self.logger.info(
            "downloaded attachments: user_id=%s pdf=%s excel=%s",
            user_id,
            bool(attachments.source_pdf),
            bool(attachments.rule_workbook),
        )
        combined = self._merge_with_pending_uploads(user_id, attachments)
        if combined.source_pdf is None and combined.rule_workbook is None:
            raise FileNotFoundError("请上传 PDF 文件或 Excel 规则文件（.xlsx）")
        if combined.source_pdf is None:
            self._pending_uploads[user_id] = PendingUpload(combined, time.time())
            self.logger.info("stored pending excel awaiting pdf: user_id=%s", user_id)
            raise FileNotFoundError("已收到 Excel 规则文件，请继续上传 PDF 文件")
        if combined.rule_workbook is None:
            self._pending_uploads[user_id] = PendingUpload(combined, time.time())
            self.logger.info("stored pending pdf awaiting excel: user_id=%s", user_id)
            raise FileNotFoundError("已收到 PDF 文件，请继续上传 Excel 规则文件（.xlsx）")

        self._pending_uploads.pop(user_id, None)
        pdf_file_name = getattr(combined.source_pdf, "file_name", None) or combined.source_pdf.path.name
        workbook_file_name = getattr(combined.rule_workbook, "file_name", None) or combined.rule_workbook.path.name
        self.logger.info(
            "building preview: user_id=%s pdf=%s excel=%s",
            user_id,
            pdf_file_name,
            workbook_file_name,
        )
        await self._send_text(user_id, "已收到任务，开始读取 PDF 和 Excel 规则，请稍等。")
        workbook_bytes = combined.rule_workbook.path.read_bytes()
        rules = await asyncio.get_running_loop().run_in_executor(
            None,
            build_rules_from_workbook,
            workbook_bytes,
            combined.source_pdf.path,
        )
        explicit_pages = await asyncio.get_running_loop().run_in_executor(
            None,
            workbook_uses_explicit_pages,
            workbook_bytes,
        )
        if explicit_pages:
            self.logger.info("explicit page mode detected, skipping confirmation: user_id=%s", user_id)
            await self._send_text(user_id, "检测到 Excel 已提供拆分页面，开始直接拆分并生成 ZIP，请稍等。")
            archive = await run_split_job(
                combined.source_pdf.path,
                rules,
                self.workspace / incoming_message.message_id,
            )
            await self._send_file(user_id, archive.file_name, archive.content_bytes)
            self.logger.info("split completed and zip sent: user_id=%s zip=%s", user_id, archive.file_name)
            await self._send_text(user_id, "拆分完成，ZIP 已发送。")
            return

        self._pending_confirmations[user_id] = PendingConfirmation(
            source_pdf=combined.source_pdf,
            rules=deepcopy(rules),
            updated_at=time.time(),
        )
        self.logger.info("preview ready, waiting for confirmation: user_id=%s rule_count=%s", user_id, len(rules))
        preview_message = format_rule_preview_markdown(rules)
        await self._reply_markdown("SKU 页数预览", preview_message, incoming_message)
        await self._send_text(user_id, "请回复“确认”继续拆分，或回复“取消”放弃本次任务。")

    def _download_message_files(
        self,
        download_codes: list[str],
        message_id: str,
        file_names: Optional[dict[str, str]] = None,
    ) -> DownloadedAttachments:
        job_dir = self.workspace / message_id / "downloads"
        job_dir.mkdir(parents=True, exist_ok=True)
        source_pdf: Optional[DownloadedFile] = None
        rule_workbook: Optional[DownloadedFile] = None
        file_names = file_names or {}
        for index, code in enumerate(download_codes, start=1):
            download_url = self.get_image_download_url(code)
            if not download_url:
                continue
            response = requests.get(download_url, timeout=60)
            response.raise_for_status()
            file_name = file_names.get(code) or _infer_filename(response.headers, f"attachment-{index}")
            suffix = Path(file_name).suffix.lower()
            file_path = job_dir / file_name
            file_path.write_bytes(response.content)
            downloaded = DownloadedFile(file_path, file_name, response.headers.get("Content-Type", ""))
            if source_pdf is None and (suffix == ".pdf" or response.content[:4] == b"%PDF"):
                if suffix != ".pdf":
                    pdf_path = file_path.with_suffix(".pdf")
                    file_path.rename(pdf_path)
                    downloaded = DownloadedFile(pdf_path, pdf_path.name, downloaded.content_type)
                source_pdf = downloaded
                continue
            if rule_workbook is None and _is_excel_file(downloaded, response.content):
                rule_workbook = downloaded

        return DownloadedAttachments(source_pdf=source_pdf, rule_workbook=rule_workbook)

    def _merge_with_pending_uploads(self, user_id: str, attachments: DownloadedAttachments) -> DownloadedAttachments:
        pending = self._pending_uploads.get(user_id)
        if pending is None:
            return attachments
        return DownloadedAttachments(
            source_pdf=attachments.source_pdf or pending.attachments.source_pdf,
            rule_workbook=attachments.rule_workbook or pending.attachments.rule_workbook,
        )

    def _cleanup_pending_uploads(self) -> None:
        cutoff = time.time() - self._pending_ttl_seconds
        self._pending_uploads = {
            user_id: pending
            for user_id, pending in self._pending_uploads.items()
            if pending.updated_at >= cutoff
        }

    def _cleanup_pending_confirmations(self) -> None:
        cutoff = time.time() - self._pending_ttl_seconds
        self._pending_confirmations = {
            user_id: pending
            for user_id, pending in self._pending_confirmations.items()
            if pending.updated_at >= cutoff
        }

    async def _send_text(self, user_id: str, message: str) -> None:
        token = await get_token(self.config)
        if token:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, send_robot_private_text_message, token, self.config, [user_id], message)

    async def _send_file(self, user_id: str, file_name: str, content: bytes) -> None:
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
            "application/zip",
        )
        if not media_id:
            raise RuntimeError("ZIP 上传到钉钉失败")
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
            raise RuntimeError("ZIP 文件消息发送失败")

    async def _reply_markdown(self, title: str, text: str, incoming_message) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.reply_markdown, title, text, incoming_message)

    def _extract_message_text(self, incoming_message, raw_payload: dict) -> str:
        try:
            return "\n".join(self.extract_text_from_incoming_message(incoming_message) or []).strip()
        except Exception:
            pass
        content = raw_payload.get("text", {}).get("content")
        if isinstance(content, str):
            return content.strip()
        return ""

    async def _handle_confirmation_message(self, incoming_message, user_id: str, message_text: str) -> bool:
        normalized = (message_text or "").strip()
        if not normalized:
            return False

        if normalized in {"确认", "确认拆分", "confirm"}:
            pending = self._pending_confirmations.pop(user_id, None)
            if pending is None:
                raise MessageFormatError("当前没有待确认的任务，请先上传 PDF 和 Excel 规则文件。")
            self.logger.info("confirmation received, starting split: user_id=%s source_pdf=%s", user_id, pending.source_pdf.file_name)
            await self._send_text(user_id, "已确认，开始拆分并生成 ZIP，请稍等。")
            archive = await run_split_job(
                pending.source_pdf.path,
                pending.rules,
                self.workspace / incoming_message.message_id,
            )
            await self._send_file(user_id, archive.file_name, archive.content_bytes)
            self.logger.info("split completed and zip sent: user_id=%s zip=%s", user_id, archive.file_name)
            await self._send_text(user_id, "拆分完成，ZIP 已发送。")
            return True

        if normalized in {"取消", "取消拆分", "cancel"}:
            self._pending_confirmations.pop(user_id, None)
            self._pending_uploads.pop(user_id, None)
            self.logger.info("task canceled: user_id=%s", user_id)
            await self._send_text(user_id, "已取消本次任务。")
            return True

        return False

def _infer_filename(headers, fallback_name: str) -> str:
    content_disposition = headers.get("Content-Disposition", "")
    if "filename=" in content_disposition:
        raw = content_disposition.split("filename=", 1)[1].strip().strip('"')
        return Path(urlparse(raw).path).name or fallback_name
    content_type = headers.get("Content-Type", "")
    if "pdf" in content_type.lower():
        return f"{fallback_name}.pdf"
    return fallback_name


def _is_excel_file(downloaded: DownloadedFile, content: bytes) -> bool:
    suffix = downloaded.path.suffix.lower()
    if suffix == ".xlsx":
        return True
    content_type = downloaded.content_type.lower()
    if "spreadsheetml" in content_type or "excel" in content_type:
        return True
    return _looks_like_xlsx(content)


def _looks_like_xlsx(content: bytes) -> bool:
    if not content.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "xl/workbook.xml" in names
