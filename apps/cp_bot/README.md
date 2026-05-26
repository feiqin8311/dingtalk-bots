# Dingtalk-Cp-Bot

> Monorepo note: this app is maintained under `/home/yida/Project/dingtalk-bots`.
> Prefer running Docker from the monorepo root with `docker compose up -d --build`.
>
> 单仓库说明：本应用维护于 `/home/yida/Project/dingtalk-bots`。
> Docker 推荐从单仓库根目录执行 `docker compose up -d --build`。

钉钉企业机器人：接收发货单号（`SP...`），调用领星查询发货数据，下载 FBA PDF，OCR 识别后做目的地核对并回复结果。

## 功能概览

- 支持钉钉文本消息，一次可提交多个发货单号。
- 支持消息去重、发货单并发锁、任务队列、失败重试、下载目录自动清理。
- 核对逻辑：
  - 优先使用 OCR 识别出的 FC 与领星 `destination_fulfillment_center_id` 直匹配。
  - 对 `加拿大/日本/阿联酋`，支持 OCR 文本包含 FC 的兜底通过。
  - 对 `美国/德国/英国/澳洲`，当 FC 不匹配时走地址簿结构化地址核对。
- 处理链路异常会自动通知 `.env` 中 `DING_TECH_USER_IDS` 配置的技术人员。

## 当前目录结构

当前仓库实际文件如下：

```text
.
├── app.py
├── handler.py
├── config.py
├── address_book_source.py
├── env.example
├── requirements.txt
├── tests/
├── Dockerfile
├── docker-compose.yml
├── downloads/
└── README.md
```

说明：
- `files/全站点地址.xlsx` 为可选外部文件（用于地址簿核对），默认路径由 `ADDRESS_BOOK_XLSX_PATH` 指定。
- 本仓库当前未包含 `sql/mysql_state.sql`，请手动建表（下文提供 SQL）。

## 环境要求

- Python 3.11+
- MySQL 5.7+/8.0+
- 可访问：
  - 钉钉 Stream
  - 领星 OpenAPI
  - 阿里云 OCR
  - SMB 共享盘（当地址簿配置为 `smb://...` 时）
- 仓库内置 `api/` 兼容层，提供：
  - `DingTalkNotifier`
  - `AliyunOCRClient`
  - `LingXingClient`

## 快速开始（本地）

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 准备配置

```bash
cp env.example .env
```

至少填写：

- 钉钉：`DINGTALK_APP_KEY`、`DINGTALK_APP_SECRET`、`DINGTALK_ROBOT_CODE`
- 技术告警：`DING_TECH_USER_IDS`（支持英文逗号或分号分隔）
- 领星：`LINGXING_API_KEY`、`LINGXING_API_SECRET`
- OCR：`ALIBABA_CLOUD_ACCESS_KEY_ID`、`ALIBABA_CLOUD_ACCESS_KEY_SECRET`
- MySQL：`DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`
- `COMMON_DIR` 可选；如果存在，会优先加载其中的 `.env` 作为基础环境变量。

3. （可选）准备地址簿

- 默认路径：`files/全站点地址.xlsx`
- 用到的列：`收件人`、`目的港`
- sheet 名支持：
  - 美国
  - 德国
  - 英国
  - 澳洲（或 澳大利亚）

如果不挂载共享盘，也可以直接用 SMB 协议读取地址簿：

```env
ADDRESS_BOOK_XLSX_PATH=smb://192.168.0.45/供应链管理/2 物流发货管理/17.单证数据表维护/全站点地址.xlsx
SMB_USERNAME=Logistics
SMB_PASSWORD=your_password
SMB_PORT=445
SMB_TIMEOUT_SEC=30
SMB_CLIENT_NAME=dingtalk-cp-bot
```

`ADDRESS_BOOK_XLSX_PATH` 也支持 Windows UNC 形式，例如：

```text
\\192.168.0.45\供应链管理\2 物流发货管理\17.单证数据表维护\全站点地址.xlsx
```

4. 初始化 MySQL 数据库和表

代码要求项目统一调用日志数据库/表存在，用于记录谁使用过机器人和进入了哪个分支：

- 数据库：`dingtalk_bot`
- 表：`fact_dingtalk_bot_call_log`

推荐从单仓库根目录执行：

```bash
mysql < sql/dingtalk_bot_call_log.sql
```

或手动执行：

```sql
CREATE DATABASE IF NOT EXISTS dingtalk_bot DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE dingtalk_bot;

CREATE TABLE IF NOT EXISTS fact_dingtalk_bot_call_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '调用时间',
  bot_module VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '模块：logistics/cp/split',
  event_type VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '事件类型',
  request_id VARCHAR(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '请求ID',
  message_id VARCHAR(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '钉钉消息ID',
  user_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '钉钉用户ID',
  user_name VARCHAR(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户名称',
  ack_status VARCHAR(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '处理状态',
  shipment_sns TEXT COLLATE utf8mb4_unicode_ci COMMENT '发货单号列表',
  message_text TEXT COLLATE utf8mb4_unicode_ci COMMENT '用户消息或事件详情',
  PRIMARY KEY (id),
  KEY idx_module_created (bot_module, created_at),
  KEY idx_event_created (event_type, created_at),
  KEY idx_user_created (user_id, created_at),
  KEY idx_request_id (request_id),
  KEY idx_message_id (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='钉钉机器人项目统一调用日志';
```

5. 启动

```bash
python3 app.py
```

## Docker 启动

```bash
docker compose up -d --build
```

注意：

- `docker-compose.yml` 当前挂载 `downloads`、`files`；`${COMMON_DIR}` 是可选兼容挂载。
- 如果用本地地址簿文件，容器内要做地址簿匹配，需要挂载地址簿文件目录，或把 `ADDRESS_BOOK_XLSX_PATH` 指向容器内可读路径。
- 如果用 `smb://...` 地址簿路径，不需要挂载共享盘，但容器需要能访问 SMB 服务器的 `445` 端口，并需要配置 `SMB_USERNAME/SMB_PASSWORD`。

## 使用方式

在钉钉发送文本，例如：

```text
SP260204001
```

或：

```text
SP260204001 SP260204012
```

机器人会先回：

- `已接收，正在核对...`
- 或 `已接收，前面X人，请稍等...`

常见即时反馈：

- 重复消息：`重复消息已忽略，请勿重复提交。`
- 非文本：`Only text messages are supported.`
- 空消息：`Please send shipment numbers like SP260119001.`
- 未识别单号：`No shipment number found. Example: SP260119001`

## 核对规则（当前实现）

- 地址匹配阈值（代码常量）：
  - `ADDRESS_MATCH_PASS_SCORE = 82`
  - `ADDRESS_MATCH_MIN_GAP = 8`
- 支持结构化地址核对国家：`US / DE / UK / AU`
- `加拿大/日本/阿联酋` 走 OCR 文本包含 FC 的兜底策略。
- 地址簿每次核对时都会重新加载，Excel 更新后通常不需要重启服务。

## 异常通知（DING_TECH_USER_IDS）

- 当处理链路发生异常时，会向 `DING_TECH_USER_IDS` 中每个用户发送告警。
- 告警内容包含：
  - `request_id`
  - 异常阶段 `stage`
  - 异常类型与信息
  - 截断后的 traceback

## 日志与数据说明

- 启动日志会打印配置检查信息。
- 请求日志包含 `req=...`，用于串联整条链路。
- `fact_dingtalk_bot_call_log` 记录物流部统一入口路由事件和 CP 分支 `RECEIVED` 事件。
- 消息去重和发货单并发锁使用本机内存状态，不再写入 MySQL；进程重启后这些临时状态会清空。

## 常见问题

- `Missing DB config ...`
  - 检查 `.env` 中 `DB_HOST/DB_USER/DB_NAME`。
- `MySQL tables missing ...`
  - 先执行上面的建表 SQL。
- `地址簿不存在` / `加载地址簿失败` / `地址簿未加载到...`
  - 本地文件模式：检查 `ADDRESS_BOOK_XLSX_PATH` 文件路径。
  - SMB 模式：检查 `ADDRESS_BOOK_XLSX_PATH`、`SMB_USERNAME/SMB_PASSWORD`、共享盘权限和 `445` 端口连通性。
  - 两种模式都要检查 sheet 名、`收件人/目的港` 列。
- `OCR结果为空` / `OCR调用失败`
  - 检查 OCR 凭证与网络。
- `领星查询失败`
  - 检查领星 Key/Secret、Token 服务与网络连通性。
