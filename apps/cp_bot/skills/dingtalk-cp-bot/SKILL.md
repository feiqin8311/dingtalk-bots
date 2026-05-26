---
name: dingtalk-cp-bot
description: Maintain and operate the DingTalk CP logistics document bot project. Use when an AI agent needs to understand, modify, run, deploy, debug, or document this repository, including DingTalk Stream handling, LingXing shipment lookup, FBA PDF download, Aliyun OCR, SMB address-book loading, MySQL usage logging, Docker deployment, and OpenClaw DingTalk agent context.
---

# DingTalk CP Bot

## Purpose

Use this skill when working on the `dingtalk-cp-bot` repository. The project is a DingTalk enterprise robot for logistics document checking: users send `SP...` shipment numbers, the bot queries LingXing, downloads FBA PDFs, OCRs the first page, checks destination FC/address consistency, and replies in DingTalk.

The source code is the highest authority. Read current files before making claims.

## First Steps

1. Inspect `AGENTS.md` first. It points to external project memory under `/home/yida/Project/ai-memory/projects/dingtalk-cp-bot/`.
2. Read the smallest useful source set:
   - `README.md` for setup and current behavior.
   - `app.py` for startup.
   - `config.py` for environment variables.
   - `handler.py` for message flow and business logic.
   - `address_book_source.py` for local/SMB Excel loading.
   - `usage_state.py` for in-memory deduplication and shipment locks.
3. Never print or copy full secrets from `.env`, OpenClaw config, or auth files. Show only `SET`/`MISSING` or masked values.
4. If changing behavior, add or update focused tests under `tests/` and run verification before reporting success.

## Current Architecture

- `app.py`: starts DingTalk Stream client and registers `ShipmentQueryHandler`.
- `config.py`: loads `.env` and exposes DingTalk, LingXing, OCR, SMB, download, and DB settings.
- `handler.py`: parses DingTalk messages, queues jobs, queries LingXing, downloads PDFs, runs OCR, matches FC/address, replies, and logs usage.
- `address_book_source.py`: opens `files/全站点地址.xlsx` from a local path, `smb://...`, or Windows UNC path.
- `usage_state.py`: process-local message deduplication and shipment locks.
- `tests/`: unit tests for address-book source loading and runtime state.

Detailed project notes are in `references/project-brief.md`; read it when you need more than this quick overview.

## Data And State

The database is intentionally minimal. MySQL is only used to record who used the bot:

- Required table: `fact_bot_cp_call_log`
- Stored fields: `user_id`, `user_name`, `message_text`, plus `created_at`
- Message deduplication and shipment locks are in memory, not in MySQL.

Do not recreate removed state tables unless the user explicitly asks for cross-process or multi-instance locking.

## Address Book

The address book can be local or SMB-backed.

Preferred SMB shape:

```env
ADDRESS_BOOK_XLSX_PATH=smb://192.168.0.45/供应链管理/2 物流发货管理/17.单证数据表维护/全站点地址.xlsx
SMB_USERNAME=...
SMB_PASSWORD=...
SMB_PORT=445
SMB_TIMEOUT_SEC=30
SMB_CLIENT_NAME=dingtalk-cp-bot
```

The code also supports Windows UNC paths such as `\\host\share\path\file.xlsx`.

Do not expose the real SMB password in responses or generated docs.

## Common Workflows

### OpenClaw One-Shot Shipment Check

When the logistics OpenClaw agent receives one or more shipment numbers like `SP260421012`, run the one-shot checker instead of starting the long-running DingTalk Stream service:

```bash
cd /home/yida/Project/dingtalk-cp-bot
scripts/openclaw-run-cp-check.sh SP260421012 --user-id <sender_id> --user-name <sender_name>
```

Omit `--user-id` or `--user-name` if the connector metadata is unavailable. Reply with the command's user-facing result only. Do not expose `.env`, AppSecret, SMB password, token, database password, or full internal logs.

### Verify The Project

Use a container when the host Python lacks dependencies:

```bash
docker run --rm --network host -v "$PWD":/app -w /app python:3.11-slim-bookworm sh -lc \
  "pip install -q -r requirements.txt -i https://pypi.org/simple && \
   python -m unittest tests.test_address_book_source tests.test_usage_state -v && \
   python -m py_compile app.py config.py handler.py address_book_source.py usage_state.py"
```

For a quick local test that needs no external dependencies:

```bash
python3 -m unittest tests.test_usage_state -v
```

### Check SMB Address Book Access

Use `.env` values through `config`; do not echo secrets:

```bash
python - <<'PY'
import config
from address_book_source import open_address_book_workbook
result = open_address_book_workbook(
    path=config.ADDRESS_BOOK_XLSX_PATH,
    smb_host=config.SMB_HOST,
    smb_share=config.SMB_SHARE,
    smb_username=config.SMB_USERNAME,
    smb_password=config.SMB_PASSWORD,
    smb_port=config.SMB_PORT,
    smb_timeout_sec=config.SMB_TIMEOUT_SEC,
    smb_client_name=config.SMB_CLIENT_NAME,
)
try:
    print(result.workbook.sheetnames)
finally:
    result.close()
PY
```

### Check Database Usage Logging

Only verify `fact_bot_cp_call_log` unless the task asks otherwise:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name = 'fact_bot_cp_call_log';
```

## Editing Rules

- Keep changes scoped. `handler.py` is large; avoid broad refactors unless needed for the requested behavior.
- Preserve local-file address book compatibility when changing SMB logic.
- Preserve in-memory dedup/lock behavior unless the user asks for multi-instance support.
- Do not store PDFs, OCR text, or detailed match results in MySQL unless explicitly requested.
- Update `README.md`, `env.example`, Docker copy rules, and tests when adding files or config keys.
- Run `git diff --check` before finalizing code changes.

## OpenClaw Context

The machine may have OpenClaw and a DingTalk connector configured. Treat this as operational context, not as part of the bot service unless the user asks about OpenClaw.

Useful checks:

```bash
openclaw --version
openclaw agents list
openclaw channels list
systemctl --user status openclaw-gateway.service --no-pager
```

Mask app secrets and auth tokens in any output.
