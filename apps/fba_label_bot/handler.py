"""物流菜单 5：FBA 箱唛清理。上传 PDF（可多个）→ 删除公司名/发货信息 → 逐个回传。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple

import dingtalk_stream
import requests
from dingtalk_stream import AckMessage

from apps.split_bot.Bot.runtime import MessageDeduplicator, collect_download_codes, collect_file_names_by_download_code
from apps.split_bot.Utils.dingtalk_api import get_token, send_robot_private_file_message, send_robot_private_text_message

from .cleaner import clean_pdf_bytes, output_file_name


class FbaLabelBotHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, logger: Optional[logging.Logger] = None, config: Optional[object] = None):
        super().__init__()
        self.logger = logger or logging.getLogger(__name__)
        self.config = config
        self._deduplicator = MessageDeduplicator()
        self._job_semaphore = asyncio.Semaphore(1)

    async def process(self, callback: dingtalk_stream.CallbackMessage) -> Tuple[str, str]:
        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        user_id = incoming_message.sender_staff_id
        message_key = incoming_message.message_id or f"{user_id}:{incoming_message.create_at}"
        if self._deduplicator.seen(message_key):
            self.logger.info("fba label: skip duplicate message %s", message_key)
            return AckMessage.STATUS_OK, "OK"
        try:
            await self._handle_message(user_id, callback.data)
        except Exception as exc:
            self.logger.exception("fba label task failed")
            await self._send_text(user_id, f"箱唛处理失败：{exc}")
        return AckMessage.STATUS_OK, "OK"

    async def _handle_message(self, user_id: str, raw_payload: dict) -> None:
        download_codes = collect_download_codes(raw_payload)
        if not download_codes:
            await self._send_text(user_id, "请上传 FBA 箱唛 PDF，可一次发多个文件。")
            return
        file_names = collect_file_names_by_download_code(raw_payload)
        loop = asyncio.get_running_loop()
        # 钉钉多选文件时一般一条消息一个文件；同一用户的消息排队处理，避免并发占内存。
        async with self._job_semaphore:
            for index, code in enumerate(download_codes, start=1):
                file_name = file_names.get(code) or f"箱唛-{index}.pdf"
                try:
                    content = await loop.run_in_executor(None, self._download, code)
                    if content[:4] != b"%PDF" and Path(file_name).suffix.lower() != ".pdf":
                        await self._send_text(user_id, f"跳过：{file_name} 不是 PDF 文件。")
                        continue
                    result = await loop.run_in_executor(None, clean_pdf_bytes, content)
                    if result.content is None:
                        await self._send_text(user_id, f"未匹配到待删除的文字，原文件未改动：{file_name}")
                        continue
                    out_name = output_file_name(file_name)
                    await self._send_file(user_id, out_name, result.content)
                    self.logger.info("fba label cleaned user=%s file=%s pages=%s", user_id, file_name, result.pages)
                except Exception as exc:
                    self.logger.exception("fba label clean failed file=%s", file_name)
                    await self._send_text(user_id, f"处理失败：{file_name}：{exc}")

    def _download(self, download_code: str) -> bytes:
        download_url = self.get_image_download_url(download_code)
        if not download_url:
            raise RuntimeError("无法获取文件下载地址")
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(download_url, timeout=60)
        response.raise_for_status()
        return response.content

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
            None, self.dingtalk_client.upload_to_dingtalk, content, "file", file_name, "application/pdf"
        )
        if not media_id:
            raise RuntimeError("PDF 上传到钉钉失败")
        result = await loop.run_in_executor(
            None, send_robot_private_file_message, token, self.config, [user_id], media_id, file_name
        )
        if not result:
            raise RuntimeError("PDF 文件消息发送失败")
