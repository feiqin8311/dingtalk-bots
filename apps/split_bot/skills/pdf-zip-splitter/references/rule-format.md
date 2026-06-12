# dingtalk-split-bot Reference

## Text Rule Table Format

Use a UTF-8 text table with 3 columns per row for the local splitter:

```text
公司名<TAB>编号/备注<TAB>页数范围
宁波德韵工具有限公司	900913	1-50
宁波德韵工具有限公司	919019	159-169
余姚嘉城工具工贸有限公司	911212	67-75
```

Supported page formats:
- `170`
- `1-50`
- `1-2,5,7-9`

Behavior:
- Merge multiple rows from the same company into one PDF
- Deduplicate repeated pages within a company
- Treat page numbers as 1-based
- Package generated PDFs into one ZIP

Output names:
- Supplier `仓库发`: `<source-stem>-仓库发.pdf`
- Other suppliers: `<source-stem>-<supplier>-一式两份.pdf`
- ZIP: `<source-stem>.zip`

## Excel Workbook Modes

The DingTalk bot uses the first worksheet.

Auto-detect mode:
- Use when there is no third column with non-empty data values.
- Interpret column A as `供应商` and column B as `SKU` by position.
- Match each SKU against extracted PDF page text as a whole token.
- Assign unmatched pages to `仓库发` unless a row has supplier but blank SKU; then that supplier becomes the unmatched-pages supplier.
- Send preview and require confirmation before splitting.

Explicit page mode:
- Use when a third column exists and at least one data row has a value in that column.
- Interpret column A as supplier, column B as SKU/reference, column C as `拆分页面`.
- Skip PDF text SKU matching.
- Split immediately without confirmation preview.

Important edge case:
- A header or third column with all empty data cells must stay in auto-detect mode.

## Runtime State

- Upload pairing, pending confirmations, deduplication, and token caches are process-local.
- Restarting the bot clears pending uploads and confirmations.
- `PdfSplitBotHandler` serializes split jobs with `asyncio.Semaphore(1)`.
- `run_split_job` removes the temporary job root after the ZIP bytes are read.

## DingTalk Operations

Required environment variables:
- `DING_CLIENT_ID`
- `DING_CLIENT_SECRET`
- `DING_ROBOT_CODE`
- `PDF_SPLIT_WORKSPACE`
- `DING_STREAM_WS_PING_INTERVAL`
- `DING_STREAM_WS_PING_TIMEOUT`

Server deployment known from project memory:
- Host: `121.41.4.126`
- Project path: `/yida/dingtalk-split-bot`
- Compose file: `/yida/dingtalk-split-bot/docker-compose.yml`
- Container: `dingtalk-split-bot`
- SSH key: `/home/yida/.ssh/id_ed25519_yida_ops`

Before changing production, verify current memory and source state. After confirmed deployment changes, validate container status, logs, or the relevant endpoint.

## Source And Memory

Project memory:
- gbrain MCP project memory for `dingtalk-bots` and `dingtalk-split-bot`

Read targeted memory files as needed:
- `architecture.md` for runtime flow
- `business-logic.md` for workbook and confirmation behavior
- `operations.md` for local, Docker, and server notes
- `data-model.md` for runtime state shapes
- `api-map.md` for DingTalk API usage

When memory conflicts with code, trust code and update memory or record uncertainty.
