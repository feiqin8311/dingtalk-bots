# dingtalk-bots

Monorepo for the DingTalk bots in this workspace.

## Layout

- `apps/logistics_bot/` — unified Logistics department DingTalk bot
- `apps/cp_bot/` — shipment query / OCR / address-check bot
- `apps/split_bot/` — PDF + Excel split-and-package bot
- `shared/` — common utilities to be extracted gradually
- `tests/` — cross-app or shared tests

## Current migration policy

- Keep both bots runnable independently.
- Default deployment is the unified Logistics bot; legacy standalone bots are behind the `legacy` compose profile.
- Prefer extracting shared infrastructure first (logging, env loading, DingTalk helpers, dedup, workspace helpers).
- Keep business logic isolated per bot.

## Run

Each app keeps its own entrypoint during migration:

- `python apps/logistics_bot/main.py`
- `python apps/cp_bot/app.py`
- `python apps/split_bot/main.py`

The Logistics bot menu is:

```text
1. 发货单核对
2. 标签/PDF 拆分
```

Reply `重置` to clear the current branch selection and start again.

## Database

The project-level call log database/table is shared by all departments, routers, and bot branches:

```text
DB_NAME=dingtalk_bot
BOT_CALL_LOG_TABLE=fact_dingtalk_bot_call_log
```

Create it with:

```bash
mysql < sql/dingtalk_bot_call_log.sql
```

## Docker

Build and run both services:

```bash
docker compose up -d --build
```

By default this starts only `dingtalk-logistics-bot`. To run old standalone services too:

```bash
docker compose --profile legacy up -d --build
```

Or run a single app entrypoint directly:

- `bash apps/logistics_bot/run.sh`
- `bash apps/cp_bot/run.sh`
- `bash apps/split_bot/run.sh`
