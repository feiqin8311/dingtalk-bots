# dingtalk-bots

物流部钉钉机器人单仓库。线上只跑**一个容器、一个钉钉 Stream 连接**：`apps/logistics_bot` 做统一入口，按用户选的菜单把消息分发给各业务分支。

## 业务分支

| 菜单 | 目录 | 做什么 | 详细说明 |
|------|------|--------|----------|
| 1. 发货单核对 | `apps/cp_bot` | 发货单号 → 领星查询 → FBA PDF OCR → 目的地核对 | [README](apps/cp_bot/README.md) |
| 2. 标签/PDF 拆分 | `apps/split_bot` | 按规则 Excel 拆分 PDF 并打包 | [README](apps/split_bot/README.md) |
| 3. 不分仓拼箱 | `apps/pinxiang_bot` | 发货单 → 拼箱结果 → Amazon 模板 / 装箱表回填 | [README](apps/pinxiang_bot/README.md) |
| 4. 分仓拼箱 | `apps/lcl_bot` | 分仓拼箱 + 运营转发 + 领星删单 | [README](apps/lcl_bot/README.md) |
| 5. FBA 箱唛清理 | `apps/fba_label_bot` | 去掉箱唛 PDF 上的公司名和发货地 | — |
| （定时） | `apps/track_notify` | 周一/周三 10:00 查轨迹并通知负责人；由入口进程以子进程拉起，挂掉自动重启 | [README](apps/track_notify/README.md) |

入口与路由说明见 [apps/logistics_bot/README.md](apps/logistics_bot/README.md)。

## 目录

```text
apps/          各业务分支（见上表）
shared/        跨应用基础设施
  stream_client.py     钉钉 Stream 长连接（断线重连、日志、任务管理）
  dingtalk_token.py    钉钉 access_token 进程级缓存（新版 API + 旧版 OAPI）
  call_log.py          MySQL 调用日志
  amazon_templates/    Amazon Manifest 模板（拼箱两个分支共用）
files/         从共享盘同步的业务 Excel（不入库），见 files/README.md
deploy/        发版脚本，见 deploy/README.md
sql/           建表 SQL
tests/         跨应用测试（路由、轨迹、分仓拼箱、共享模块）
```

## 配置

复制 `env.example` 为仓库根 `.env` 并填写。容器启动时先读各 `apps/*/.env`（仅补缺，兼容旧配置），最后读根 `.env`（优先）。

## 本地开发

```bash
uv venv -p 3.11 .venv
uv pip install -p .venv -r requirements.txt pytest
PYTHON=.venv/bin/python scripts/run_tests.sh
```

`scripts/run_tests.sh` 依次跑根目录和各 app 的测试。各 app 的测试必须在自己目录下跑：cp_bot 与 pinxiang_bot 都有顶层 `handler.py`，logistics_bot 与 track_notify 都有 `settings.py`，放进同一个 pytest 进程会导错模块。CI（`.github/workflows/tests.yml`）跑的是同一个脚本。

依赖在 `requirements.txt` 中全部锁定精确版本；升级时改版本号并跑完测试。

## 部署

```bash
./deploy/deploy.sh            # 只改代码：rsync + 重启，十几秒
./deploy/deploy.sh --rebuild  # 改了 requirements.txt：重建镜像
```

详见 [deploy/README.md](deploy/README.md)。旧的独立容器（`dingtalk-cp-bot`、`dingtalk-split-bot`）放在 compose 的 `legacy` profile 里，默认不启动。
