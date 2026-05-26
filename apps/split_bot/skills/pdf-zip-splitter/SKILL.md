---
name: pdf-zip-splitter
description: Maintain and operate the dingtalk-split-bot project and its reusable PDF split-to-ZIP core. Use when working on the DingTalk PDF splitting robot, Excel/SKU page detection, explicit page-range splitting, generated ZIP behavior, DingTalk Stream bot handling, local CLI usage, tests, Docker deployment, or when the user provides a PDF plus split rules and wants company/supplier PDFs packaged as a ZIP.
---

# dingtalk-split-bot PDF ZIP Splitter

## Overview

Use this skill for two related surfaces:

- Maintain the `dingtalk-split-bot` repository: a DingTalk Stream robot that receives one PDF and one Excel workbook, previews or executes supplier-based PDF splitting, then sends a ZIP back through DingTalk.
- Run the bundled local splitter for one PDF plus a 3-column rule table.

Source code is authoritative. Read `/home/yida/Project/dingtalk-split-bot/AGENTS.md` and the project memory before meaningful maintenance work.

## Repository Workflow

1. Read `/home/yida/Project/ai-memory/AGENTS.md`.
2. Read `/home/yida/Project/ai-memory/projects/dingtalk-split-bot/index.md`.
3. Read only the relevant memory files, usually `architecture.md`, `business-logic.md`, `operations.md`, `data-model.md`, or `api-map.md`.
4. Inspect the implementing source files before changing behavior.
5. Keep changes scoped and update project memory after meaningful behavior or operations changes.

## Main Code Paths

- `main.py`: `.env` loading, DingTalk credentials, resilient Stream client startup.
- `Bot/handler.py`: message handling, attachment download, upload pairing, preview/confirmation, ZIP sending.
- `Bot/runtime.py`: message deduplication, payload file-code extraction, temporary split job cleanup.
- `Utils/dingtalk_api.py`: DingTalk OAuth token cache and robot one-to-one text/file messages.
- `pdf_zip_bot/rules.py`: text rule parsing, Excel workbook modes, SKU matching, preview formatting.
- `pdf_zip_bot/processor.py`: page-range expansion, supplier grouping, split PDF and ZIP writing.
- `pdf_zip_bot/cli.py`: local CLI around the PDF split core.

## Business Rules

- The DingTalk bot expects one PDF and one `.xlsx` workbook from the same user. Files may arrive together or separately within 10 minutes.
- Auto-detect workbook mode uses column A as `供应商` and column B as `SKU`. It extracts PDF text per page and matches SKU as a whole token, not a substring.
- Explicit page mode is enabled only when a third column exists and at least one data row has a non-empty third-column value. Then the bot reads page ranges directly and skips confirmation.
- If a workbook row has supplier but no SKU in auto-detect mode, that supplier becomes the unmatched-pages supplier. The default unmatched supplier is `仓库发`.
- Auto-detect mode sends a Markdown preview and waits for `确认`, `确认拆分`, or `confirm`; `取消`, `取消拆分`, or `cancel` abandons the task.
- Output groups rows by supplier/company. `仓库发` files are named `<source-stem>-仓库发.pdf`; other suppliers use `<source-stem>-<supplier>-一式两份.pdf`; the archive is `<source-stem>.zip`.

## Local Split Workflow

1. Confirm the source PDF path and save the rule table as a UTF-8 text file.
2. Read `references/rule-format.md` if rule format, workbook behavior, validation, or deployment details matter.
3. Run `scripts/pdf_split_zip.py <source_pdf> <rules_file> --output-dir <dir>`.
4. Return the generated ZIP path and summarize the produced PDFs.
5. For DingTalk integration work, reuse `pdf_zip_bot` core functions instead of duplicating split logic.

## Rule Handling

- Expect exactly 3 columns per row: company name, reference code, page range.
- Accept tabs or runs of 2 or more spaces between columns.
- Treat page numbers as 1-based.
- Reject invalid rows with clear line-numbered errors.
- Merge same-company rows in input order and deduplicate repeated pages within that company.

## Commands And Validation

Local split:

```bash
python skills/pdf-zip-splitter/scripts/pdf_split_zip.py source.pdf rules.txt --output-dir output
```

Run all tests:

```bash
python -m pytest
```

If `pytest` is unavailable, use:

```bash
python -m unittest discover -s tests -v
```

Run the bot locally:

```bash
cp env.example .env
python main.py
```

Docker:

```bash
docker compose up -d --build
docker compose logs -f
```

Never expose `.env`, access tokens, app secrets, robot codes, download URLs, or user file content in memory or user-facing replies.

## Resources

- `scripts/pdf_split_zip.py`: thin executable wrapper around the repo's `pdf_zip_bot` core.
- `references/rule-format.md`: detailed rule formats, workbook modes, maintenance notes, validation, and deployment reminders.
