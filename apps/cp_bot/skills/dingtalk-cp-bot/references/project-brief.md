# Project Brief

## Repository

`/home/yida/Project/dingtalk-cp-bot`

## Business Flow

1. A DingTalk user sends text containing one or more `SP...` shipment numbers.
2. `ShipmentQueryHandler.process()` validates the message, records a `RECEIVED` usage log, deduplicates the message in memory, acquires in-memory shipment locks, and queues the job.
3. Worker tasks query LingXing shipment detail.
4. For each shipment, the bot chooses exactly one FBA PDF when possible. If no FBA PDF exists but other files exist, it asks the user to pick a file.
5. The selected/downloaded PDF first page is rendered to PNG with PyMuPDF.
6. Aliyun OCR extracts text from the PNG.
7. The bot checks the OCR destination FC against LingXing `destination_fulfillment_center_id`.
8. If FC direct match fails:
   - Canada/Japan/UAE can pass when the OCR text contains the destination code.
   - US/Germany/UK/Australia use structured address fallback against the Excel address book.
9. The bot replies with a summary and per-shipment result.

## Important Files

- `app.py`: CLI entrypoint and DingTalk Stream client startup.
- `config.py`: `.env` loading and constants.
- `handler.py`: main runtime and business logic.
- `address_book_source.py`: local/SMB Excel source abstraction.
- `usage_state.py`: in-memory message dedup and shipment locks.
- `env.example`: non-secret configuration template.
- `Dockerfile` / `docker-compose.yml`: container deployment.
- `tests/test_address_book_source.py`: local/SMB loading unit tests.
- `tests/test_usage_state.py`: in-memory state tests.

## Required External Services

- DingTalk Stream robot credentials.
- LingXing OpenAPI credentials and token endpoint.
- Aliyun OCR credentials.
- MySQL for usage logging only.
- Optional SMB access for `全站点地址.xlsx`.
- External Common project referenced by `COMMON_DIR`; `handler.py` imports:
  - `api.DingTalkNotifier`
  - `api.aliyun_client.AliyunOCRClient`
  - `api.lingxing_client.LingXingClient`

## Database Contract

Only `fact_bot_cp_call_log` is required.

```sql
CREATE TABLE IF NOT EXISTS fact_bot_cp_call_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '调用时间',
  user_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '钉钉用户ID',
  user_name VARCHAR(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户名称',
  message_text TEXT COLLATE utf8mb4_unicode_ci COMMENT '用户发送的问题',
  PRIMARY KEY (id),
  KEY idx_user_id (user_id),
  KEY idx_created_at (created_at),
  KEY idx_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='CP机器人调用日志';
```

Removed/unused tables:

- `dim_bot_cp_message_dedup`
- `dim_bot_cp_shipment_lock`

Do not recreate them for normal maintenance.

## Runtime State

`usage_state.InMemoryRuntimeState` handles:

- message deduplication with TTL
- shipment locks with TTL

This is process-local. Restarting the process clears dedup/lock state. This is intentional for the low-volume single-instance deployment.

## Address Matching Notes

`handler.py` contains detailed parsing/scoring logic. Key constants:

- `ADDRESS_MATCH_PASS_SCORE = 82.0`
- `ADDRESS_MATCH_MIN_GAP = 8.0`
- `SUPPORTED_ADDRESS_COUNTRIES = {"US", "DE", "UK", "AU"}`

Address book workbook requirements:

- Sheets: `美国`, `德国`, `英国`, `澳洲` or `澳大利亚`
- Columns: `收件人`, `目的港`

## Configuration Safety

Never expose these values in responses or skill docs:

- DingTalk app secrets
- LingXing keys/secrets
- Aliyun access secrets
- MySQL password
- SMB password
- OpenClaw auth tokens

Use masked output such as `SET`, `MISSING`, or first few characters only.

## Useful Verification Commands

Run all unit tests and compile in a dependency-complete container:

```bash
docker run --rm --network host -v "$PWD":/app -w /app python:3.11-slim-bookworm sh -lc \
  "pip install -q -r requirements.txt -i https://pypi.org/simple && \
   python -m unittest tests.test_address_book_source tests.test_usage_state -v && \
   python -m py_compile app.py config.py handler.py address_book_source.py usage_state.py"
```

Build Docker image:

```bash
docker build --network host -t dingtalk-cp-bot:check .
```

Check whitespace:

```bash
git diff --check
```
