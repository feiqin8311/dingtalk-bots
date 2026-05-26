# PDF ZIP Bot

> Monorepo note: this app is maintained under `/home/yida/Project/dingtalk-bots`.
> Prefer running Docker from the monorepo root with `docker compose up -d --build`.
>
> 单仓库说明：本应用维护于 `/home/yida/Project/dingtalk-bots`。
> Docker 推荐从单仓库根目录执行 `docker compose up -d --build`。

This project implements the planned first stage: a reusable PDF split-and-package core plus a DingTalk stream bot entrypoint modeled after your existing `Dingtalk-Gpt-Bot2` layout.

## Rule format

Provide UTF-8 text with three columns per row:

```text
公司名<TAB>编号/备注<TAB>页数范围
宁波德韵工具有限公司	900913	1-50
宁波德韵工具有限公司	919019	159-169
余姚嘉城工具工贸有限公司	911212	67-75
```

- Column 1: company folder name
- Column 2: metadata only in v1
- Column 3: page range (`1-50`, `170`, `1-2,5`)

Rows for the same company are merged into one output PDF named `公司名-一式两份.pdf`.

## CLI

```bash
python -m pdf_zip_bot.cli FBA15LNH9GT5-1776059871368.pdf rules.txt --output-dir output
```

The command generates:

- `output/<公司名>/<公司名>-一式两份.pdf`
- `output/<源文件名>-split-results.zip`

## DingTalk stream bot

```bash
cp env.example .env
python main.py
```

Robot message format:

- Upload one source PDF
- Upload one Excel rule file in `.xlsx` format

The bot can accept them in the same message or in two separate messages from the same user. Pending uploads are paired automatically within 10 minutes.

Excel rules use the first worksheet and must include these columns:

- `供应商`
- `SKU`

Other columns such as `物流商单号`、`国家`、`发货量` may remain in the workbook and are ignored for matching.

Two workbook modes are supported:

- Auto-detect mode: if there is no `拆分页面` column, the bot searches the PDF text by `SKU`, then assigns unmatched pages to `仓库发`
- Explicit page mode: if a `拆分页面` column exists, the whole workbook is treated as explicit page ranges and the bot does not search the PDF by `SKU`

Once both files are available, the bot scans the PDF text for each SKU and replies with a preview table in DingTalk:

```text
供应商	SKU	页数
宁波德韵工具有限公司	900913	1-10
宁波德韵工具有限公司	900913	12
宁波德韵工具有限公司	900913	15-20
```

At this stage the bot only replies with the detected page ranges. It does not generate the split ZIP yet.

After the preview is sent, the bot waits for your reply:

- reply `确认` to continue splitting and send the ZIP
- reply `取消` to abandon the current task

If only one file has arrived so far, the bot stores it temporarily and replies with a prompt to continue uploading the missing file type:

- only PDF: `请继续上传 Excel 规则文件（.xlsx）`
- only Excel: `请继续上传 PDF 文件`

## Docker Deploy

1. Copy `env.example` to `.env` and fill in the real DingTalk credentials
2. Build and start the bot:

```bash
docker compose up -d --build
```

The Docker image installs Python packages from the Tsinghua PyPI mirror to reduce timeout issues on China mainland servers.

3. Check logs:

```bash
docker compose logs -f
```

4. Stop the bot:

```bash
docker compose down
```

The container mounts `.bot-workspace` for temporary job files and uses the values from `.env`.
