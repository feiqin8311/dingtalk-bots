import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from openpyxl import Workbook
from pypdf import PdfWriter

from Bot.handler import PendingConfirmation, PendingUpload, PdfSplitBotHandler
from Bot.runtime import MessageDeduplicator, collect_download_codes, collect_file_names_by_download_code, run_split_job
from pdf_zip_bot import parse_rules_table


class DownloadCodeCollectionTests(unittest.TestCase):
    def test_collects_codes_from_rich_text_items(self):
        payload = {
            'msgtype': 'richText',
            'content': {
                'richText': [
                    {'text': '/pdfsplit'},
                    {'downloadCode': 'CODE-A'},
                    {'downloadCode': 'CODE-B'},
                ]
            },
        }

        self.assertEqual(collect_download_codes(payload), ['CODE-A', 'CODE-B'])

    def test_collects_codes_from_file_message_extensions(self):
        payload = {
            'msgtype': 'file',
            'content': {'downloadCode': 'FILE-CODE'},
            'attachments': [{'downloadCode': 'ATTACH-1'}],
        }

        self.assertEqual(collect_download_codes(payload), ['FILE-CODE', 'ATTACH-1'])

    def test_collects_original_file_names_by_download_code(self):
        payload = {
            'content': {'downloadCode': 'FILE-CODE', 'fileName': 'source.pdf'},
            'attachments': [
                {'downloadCode': 'ATTACH-1', 'fileName': 'rules.xlsx'},
                {'downloadCode': 'ATTACH-2', 'fileName': 'other.txt'},
            ],
        }

        self.assertEqual(
            collect_file_names_by_download_code(payload),
            {
                'FILE-CODE': 'source.pdf',
                'ATTACH-1': 'rules.xlsx',
                'ATTACH-2': 'other.txt',
            },
        )


class MessageDeduplicatorTests(unittest.TestCase):
    def test_marks_duplicate_messages_within_ttl(self):
        dedupe = MessageDeduplicator(ttl_seconds=60)

        self.assertFalse(dedupe.seen('message-1'))
        self.assertTrue(dedupe.seen('message-1'))


class SplitJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_split_job_returns_archive_bytes_and_cleans_entire_job_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_pdf = tmp_path / 'source.pdf'
            self._make_pdf(source_pdf, 6)
            rules = parse_rules_table('宁波德韵工具有限公司\t900913\t1-2\n')
            job_root = tmp_path / 'job-1'

            archive = await run_split_job(source_pdf, rules, job_root)

            self.assertFalse(job_root.exists())
            self.assertTrue(archive.file_name.endswith('.zip'))
            self.assertTrue(archive.content_bytes.startswith(b'PK'))

    def _make_pdf(self, path: Path, pages: int) -> None:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        with path.open('wb') as fh:
            writer.write(fh)


class AttachmentDownloadTests(unittest.TestCase):
    def test_downloads_pdf_and_excel_attachments_from_same_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / 'workspace'
            handler = PdfSplitBotHandler(config=SimpleNamespace(workspace=str(workspace)))
            pdf_bytes = self._make_pdf_bytes(2)
            workbook_bytes = self._make_workbook_bytes()

            with patch.object(
                handler,
                'get_image_download_url',
                side_effect=lambda code: f'https://example.test/{code}',
            ), patch(
                'Bot.handler.requests.get',
                side_effect=[
                    self._response('source.pdf', 'application/pdf', pdf_bytes),
                    self._response(
                        'rules.xlsx',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        workbook_bytes,
                    ),
                ],
            ):
                downloaded = handler._download_message_files(['PDF-CODE', 'XLSX-CODE'], 'message-1')

            self.assertEqual(downloaded.source_pdf.file_name, 'source.pdf')
            self.assertEqual(downloaded.rule_workbook.file_name, 'rules.xlsx')
            self.assertTrue(downloaded.source_pdf.path.exists())
            self.assertTrue(downloaded.rule_workbook.path.exists())

    def test_downloads_only_pdf_when_only_pdf_is_uploaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / 'workspace'
            handler = PdfSplitBotHandler(config=SimpleNamespace(workspace=str(workspace)))
            pdf_bytes = self._make_pdf_bytes(2)

            with patch.object(
                handler,
                'get_image_download_url',
                side_effect=lambda code: f'https://example.test/{code}',
            ), patch(
                'Bot.handler.requests.get',
                side_effect=[self._response('source.pdf', 'application/pdf', pdf_bytes)],
            ):
                downloaded = handler._download_message_files(['PDF-CODE'], 'message-1')

            self.assertEqual(downloaded.source_pdf.file_name, 'source.pdf')
            self.assertIsNone(downloaded.rule_workbook)

    def test_downloads_only_excel_when_only_excel_is_uploaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / 'workspace'
            handler = PdfSplitBotHandler(config=SimpleNamespace(workspace=str(workspace)))
            workbook_bytes = self._make_workbook_bytes()

            with patch.object(
                handler,
                'get_image_download_url',
                side_effect=lambda code: f'https://example.test/{code}',
            ), patch(
                'Bot.handler.requests.get',
                side_effect=[
                    self._response(
                        'rules.xlsx',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        workbook_bytes,
                    ),
                ],
            ):
                downloaded = handler._download_message_files(['XLSX-CODE'], 'message-1')

            self.assertIsNone(downloaded.source_pdf)
            self.assertEqual(downloaded.rule_workbook.file_name, 'rules.xlsx')

    def test_detects_excel_from_zip_content_when_headers_are_generic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / 'workspace'
            handler = PdfSplitBotHandler(config=SimpleNamespace(workspace=str(workspace)))
            workbook_bytes = self._make_workbook_bytes()

            with patch.object(
                handler,
                'get_image_download_url',
                side_effect=lambda code: f'https://example.test/{code}',
            ), patch(
                'Bot.handler.requests.get',
                side_effect=[
                    self._response(
                        'attachment-1',
                        'application/octet-stream',
                        workbook_bytes,
                    ),
                ],
            ):
                downloaded = handler._download_message_files(['XLSX-CODE'], 'message-1')

            self.assertIsNone(downloaded.source_pdf)
            self.assertEqual(downloaded.rule_workbook.file_name, 'attachment-1')

    def test_prefers_original_filename_from_payload_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / 'workspace'
            handler = PdfSplitBotHandler(config=SimpleNamespace(workspace=str(workspace)))
            pdf_bytes = self._make_pdf_bytes(2)
            file_names = {'PDF-CODE': 'FBA19BGSCLB4-1776058268239.pdf'}

            with patch.object(
                handler,
                'get_image_download_url',
                side_effect=lambda code: f'https://example.test/{code}',
            ), patch(
                'Bot.handler.requests.get',
                side_effect=[self._response('attachment-1', 'application/pdf', pdf_bytes)],
            ):
                downloaded = handler._download_message_files(['PDF-CODE'], 'message-1', file_names)

            self.assertEqual(downloaded.source_pdf.file_name, 'FBA19BGSCLB4-1776058268239.pdf')

    def _make_pdf_bytes(self, pages: int) -> bytes:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        with tempfile.NamedTemporaryFile(suffix='.pdf') as fh:
            writer.write(fh)
            fh.flush()
            fh.seek(0)
            return fh.read()

    def _make_workbook_bytes(self) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['物流商单号', '供应商', 'SKU', '国家', '发货量'])
        sheet.append(['26LT119', '宁波德韵工具有限公司', '900913', '德国', 1000])
        with tempfile.NamedTemporaryFile(suffix='.xlsx') as fh:
            workbook.save(fh.name)
            fh.seek(0)
            return fh.read()

    def _response(self, file_name: str, content_type: str, content: bytes):
        class Response:
            def __init__(self):
                self.headers = {
                    'Content-Disposition': f'attachment; filename="{file_name}"',
                    'Content-Type': content_type,
                }
                self.content = content

            def raise_for_status(self):
                return None

        return Response()


class HandlerReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_message_replies_preview_table_before_any_zip_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = PdfSplitBotHandler(config=SimpleNamespace(workspace=str(Path(tmpdir) / 'workspace')))
            incoming_message = SimpleNamespace(message_id='message-1')
            attachments = SimpleNamespace(
                source_pdf=SimpleNamespace(path=Path('/tmp/source.pdf')),
                rule_workbook=SimpleNamespace(path=Path('/tmp/rules.xlsx')),
            )
            preview_message = (
                '| 供应商 | SKU | 页数 |\n'
                '| --- | --- | --- |\n'
                '| 宁波德韵工具有限公司 | 900913 | 1-10 |\n'
                '| 宁波德韵工具有限公司 | 900913 | 12 |'
            )

            with patch.object(handler, '_send_text', new=AsyncMock()) as send_text, \
                patch.object(handler, '_reply_markdown', new=AsyncMock()) as reply_markdown, \
                patch.object(handler, '_download_message_files', return_value=attachments), \
                patch('Bot.handler.build_rules_from_workbook', return_value=[]), \
                patch('Bot.handler.workbook_uses_explicit_pages', return_value=False), \
                patch('Bot.handler.format_rule_preview_markdown', return_value=preview_message), \
                patch.object(Path, 'read_bytes', side_effect=[b'workbook-bytes']):
                await handler._handle_message(incoming_message, 'user-1', {'attachments': [{'downloadCode': 'PDF'}]})

            send_text.assert_any_await('user-1', '已收到任务，开始读取 PDF 和 Excel 规则，请稍等。')
            reply_markdown.assert_awaited_once_with('SKU 页数预览', preview_message, incoming_message)
            send_text.assert_any_await('user-1', '请回复“确认”继续拆分，或回复“取消”放弃本次任务。')

    async def test_handle_message_skips_confirmation_when_explicit_pages_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = PdfSplitBotHandler(config=SimpleNamespace(workspace=str(Path(tmpdir) / 'workspace')))
            incoming_message = SimpleNamespace(message_id='message-1')
            workbook_path = SimpleNamespace(read_bytes=lambda: b'workbook-bytes')
            attachments = SimpleNamespace(
                source_pdf=SimpleNamespace(path=Path('/tmp/source.pdf'), file_name='source.pdf'),
                rule_workbook=SimpleNamespace(path=workbook_path, file_name='rules.xlsx'),
            )
            archive = SimpleNamespace(file_name='source.zip', content_bytes=b'PK\x03\x04')

            with patch.object(handler, '_send_text', new=AsyncMock()) as send_text, \
                patch.object(handler, '_reply_markdown', new=AsyncMock()) as reply_markdown, \
                patch.object(handler, '_send_file', new=AsyncMock()) as send_file, \
                patch.object(handler, '_download_message_files', return_value=attachments), \
                patch('Bot.handler.build_rules_from_workbook', return_value=[]), \
                patch('Bot.handler.workbook_uses_explicit_pages', return_value=True), \
                patch('Bot.handler.run_split_job', new=AsyncMock(return_value=archive)):
                await handler._handle_message(incoming_message, 'user-1', {'attachments': [{'downloadCode': 'PDF'}]})

            reply_markdown.assert_not_called()
            send_text.assert_any_await('user-1', '检测到 Excel 已提供拆分页面，开始直接拆分并生成 ZIP，请稍等。')
            send_file.assert_awaited_once_with('user-1', 'source.zip', b'PK\x03\x04')
            send_text.assert_any_await('user-1', '拆分完成，ZIP 已发送。')
            self.assertNotIn('user-1', handler._pending_confirmations)

    async def test_handle_message_does_not_send_start_message_before_attachment_validation(self):
        handler = PdfSplitBotHandler(config=SimpleNamespace(workspace='/tmp/workspace'))
        incoming_message = SimpleNamespace(message_id='message-1')

        with patch.object(handler, '_send_text', new=AsyncMock()) as send_text, \
            patch.object(handler, '_download_message_files', return_value=SimpleNamespace(source_pdf=None, rule_workbook=None)):
            with self.assertRaises(FileNotFoundError):
                await handler._handle_message(incoming_message, 'user-1', {'attachments': [{'downloadCode': 'PDF'}]})

        send_text.assert_not_called()

    async def test_process_treats_missing_attachment_prompt_as_non_failure(self):
        logger = SimpleNamespace(info=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None)
        handler = PdfSplitBotHandler(logger=logger, config=SimpleNamespace(workspace='/tmp/workspace'))
        callback = SimpleNamespace(
            data={
                'senderStaffId': 'user-1',
                'messageId': 'message-1',
                'createAt': 1,
            }
        )

        with patch('Bot.handler.dingtalk_stream.ChatbotMessage.from_dict', return_value=SimpleNamespace(
            sender_staff_id='user-1',
            message_id='message-1',
            create_at=1,
        )), patch.object(handler, '_handle_message', side_effect=FileNotFoundError('请继续上传 Excel 规则文件')), \
            patch.object(handler, '_send_text', new=AsyncMock()) as send_text:
            status, message = await handler.process(callback)

        self.assertEqual(message, 'OK')
        send_text.assert_awaited_once_with('user-1', '请继续上传 Excel 规则文件')

    async def test_handle_message_stores_pdf_then_waits_for_excel(self):
        handler = PdfSplitBotHandler(config=SimpleNamespace(workspace='/tmp/workspace'))
        incoming_message = SimpleNamespace(message_id='message-1')
        pdf_only = SimpleNamespace(source_pdf=SimpleNamespace(path=Path('/tmp/source.pdf')), rule_workbook=None)

        with patch.object(handler, '_download_message_files', return_value=pdf_only):
            with self.assertRaises(FileNotFoundError) as ctx:
                await handler._handle_message(incoming_message, 'user-1', {'attachments': [{'downloadCode': 'PDF'}]})

        self.assertIn('已收到 PDF 文件', str(ctx.exception))
        self.assertIn('user-1', handler._pending_uploads)

    async def test_handle_message_uses_pending_pdf_when_excel_arrives_later(self):
        handler = PdfSplitBotHandler(config=SimpleNamespace(workspace='/tmp/workspace'))
        incoming_message = SimpleNamespace(message_id='message-2')
        handler._pending_uploads['user-1'] = PendingUpload(
            attachments=SimpleNamespace(source_pdf=SimpleNamespace(path=Path('/tmp/source.pdf')), rule_workbook=None),
            updated_at=time.time(),
        )
        excel_only = SimpleNamespace(source_pdf=None, rule_workbook=SimpleNamespace(path=Path('/tmp/rules.xlsx')))
        preview_message = '供应商\tSKU\t页数\n宁波德韵工具有限公司\t900913\t1-10'

        with patch.object(handler, '_download_message_files', return_value=excel_only), \
            patch.object(handler, '_send_text', new=AsyncMock()) as send_text, \
            patch.object(handler, '_reply_markdown', new=AsyncMock()) as reply_markdown, \
            patch('Bot.handler.build_rules_from_workbook', return_value=[]), \
            patch('Bot.handler.workbook_uses_explicit_pages', return_value=False), \
            patch('Bot.handler.format_rule_preview_markdown', return_value=preview_message), \
            patch.object(Path, 'read_bytes', side_effect=[b'workbook-bytes']):
            await handler._handle_message(incoming_message, 'user-1', {'attachments': [{'downloadCode': 'XLSX'}]})

        self.assertNotIn('user-1', handler._pending_uploads)
        send_text.assert_any_await('user-1', '已收到任务，开始读取 PDF 和 Excel 规则，请稍等。')
        reply_markdown.assert_awaited_once_with('SKU 页数预览', preview_message, incoming_message)

    async def test_confirmation_message_runs_split_and_sends_zip(self):
        handler = PdfSplitBotHandler(config=SimpleNamespace(workspace='/tmp/workspace'))
        incoming_message = SimpleNamespace(message_id='confirm-1')
        handler._pending_confirmations['user-1'] = PendingConfirmation(
            source_pdf=SimpleNamespace(path=Path('/tmp/source.pdf'), file_name='source.pdf'),
            rules=[],
            updated_at=time.time(),
        )
        archive = SimpleNamespace(file_name='result.zip', content_bytes=b'PK\x03\x04')

        with patch.object(handler, '_send_text', new=AsyncMock()) as send_text, \
            patch.object(handler, '_send_file', new=AsyncMock()) as send_file, \
            patch('Bot.handler.run_split_job', new=AsyncMock(return_value=archive)):
            await handler._handle_message(incoming_message, 'user-1', {'text': {'content': '确认'}})

        send_text.assert_any_await('user-1', '已确认，开始拆分并生成 ZIP，请稍等。')
        send_file.assert_awaited_once_with('user-1', 'result.zip', b'PK\x03\x04')
        send_text.assert_any_await('user-1', '拆分完成，ZIP 已发送。')
        self.assertNotIn('user-1', handler._pending_confirmations)

    async def test_cancel_message_clears_pending_state(self):
        handler = PdfSplitBotHandler(config=SimpleNamespace(workspace='/tmp/workspace'))
        incoming_message = SimpleNamespace(message_id='cancel-1')
        handler._pending_confirmations['user-1'] = PendingConfirmation(
            source_pdf=SimpleNamespace(path=Path('/tmp/source.pdf')),
            rules=[],
            updated_at=time.time(),
        )
        handler._pending_uploads['user-1'] = PendingUpload(
            attachments=SimpleNamespace(source_pdf=SimpleNamespace(path=Path('/tmp/source.pdf')), rule_workbook=None),
            updated_at=time.time(),
        )

        with patch.object(handler, '_send_text', new=AsyncMock()) as send_text:
            await handler._handle_message(incoming_message, 'user-1', {'text': {'content': '取消'}})

        send_text.assert_awaited_once_with('user-1', '已取消本次任务。')
        self.assertNotIn('user-1', handler._pending_confirmations)
        self.assertNotIn('user-1', handler._pending_uploads)


if __name__ == '__main__':
    unittest.main()
