# Track Notify / 主动查询物流状态并回传

## 规则（业务文档）

1. **调度**：周一、周三 **07:00**（Asia/Shanghai）；若启动时已过点且当日未成功跑过会补跑
2. **筛选**：`2025New！`  
   - **发货时间** 年份 = 2026（列值为毫秒时间戳，如 `1779033600000`）  
   - 货代含「平谊」或「龙舟」或「美通」或「堡森」  
   - 预计船期 ≤ 今天  
   - 实际送仓时间为空  
3. **查询**  
   - **平谊**：读 **FBA编码** → 软通宝 `getTrack`  
   - **龙舟**：读 **物流编号** + **品牌** → 物流网关  
     `POST /api/fba/query`（`logistics_no` + `brand` + `platform=agl`）  
   - **堡森**：读 **FBA编码** → 物流网关  
     `POST /api/fba/query`（`fba_code` + `platform=baosen` + `include_tracking=true`）  
     网关对钉钉表取该 FBA 的物流编号再查堡森；不直传物流编号。表缺物流编号 → 报「缺少物流编号」  
   - **美通**：读 **物流编号** → `GET /v1/track/aafOrderTrack/getTrackInfo`  
4. **匹配节点（只推这些）**  
   - **龙舟**：`出发地 中国宁波` / `已到达卸货港` / `已提柜` / `货物已送达 FC 场地`  
   - **堡森**：`预计离港` / `已离港` / `预计到港` / `已到达`（港名不写死） / `卡车发出` / `派送成功`。预计≠已发生。  
   - **平谊**：`船只从始发港离港`（KC）/ `船只到达目的港`（DG）/ `货件已被完整配送至亚马逊仓库`（SC）  
   - **美通**：按「出运渠道」分套。**卡航**：`仓库监装出库` / `预配班列` / `抵达清关地` / `预计送仓` / `实际送仓`。**海运/海派**：`仓库监装出库` / `预配船期` / `离港`（已于） / `到港`（已于，不含预计） / `交付`（UPS/DHL/FEDEX/DPD 不写死）。  
   - 一次命中多个节点 → 同一 Excel 行「物流详情」里换行都列出  
5. **通知**  
   - a. **新增指定节点** + **异常行**（无 FBA / 未查到 / 查询失败）写入 Excel；轨迹有查到但无新节点 → 不推  

   - b. 节点级去重（sqlite `notified_events`：有日期的节点只推一次；无日期单独记 `:undated`，补上日期后再推一次给物流。周一已推「已到达卸货港」，周三无新节点不推；出现「已提柜」再推）  
   - c. **每次仍全量查询候选行**（不再整行 skip）  
   - c2. **龙舟/堡森网关瞬时失败**：本轮结束后对 `query_error` **再串行重查 1 轮**（票间 pause 3s）；仍失败才进问题表  
    - c3. **查一行记一行**：结果写入 sqlite `pending_report_items`（只落盘不发）；下次 `--once` 同日把 checkpoint 并入 bucket 后继续全量查，**全部查完后才统一发一次 Excel**；跨日丢弃 pending
    - d. **按接收人生成 Excel**  
      - **完整节点**：表内负责人 + **柯鹏翔**（柯鹏翔收全量完整数据）  
      - **无日期节点**（如单独「已到达卸货港」无 `YYYY-MM-DD`）：**不推物流人员**；若同行有日期行，所有人只保留有日期的（例：`2026-08-13 出发地 中国宁波`）；全无日期时**柯鹏翔仍收**  
      - **问题数据**（缺号/无轨迹/查询失败）：**只推柯鹏翔**，不推物流人员  
   - e. `TRACK_SEND_EXCEL=0` 只落盘，`1` 私聊只发文件  
    - f. 文件目录：`TRACK_NOTIFY_STATE_DIR/exports/`；文件名含时分秒（`*_轨迹回传_YYYYMMDD_HHMMSS.xlsx`），同日多次跑不会互相覆盖


## 手动跑一轮

```bash
# 仓库根目录
python3 apps/track_notify/main.py --once --dry-run
python3 apps/track_notify/main.py --once
```

平谊单号调试：

```bash
python3 apps/track_notify/main.py FBA19JTBN929 --dry-run
```

## 调度

挂在 `apps/logistics_bot/main.py` 后台线程，Mon/Wed 07:00。

## 配置

见 `env.example`。

| 变量 | 用途 |
|------|------|
| `PINGYI_*` | 平谊 API |
| `MEITONG_USERNAME` / `MEITONG_PASSWORD` | 美通 oauth 账号 |
| `MEITONG_BASE_URL` | 默认 `https://www.szaaf.com` |
| `MEITONG_TIMEOUT_SEC` | 美通单次超时，默认 `30` |
| `MEITONG_RETRIES` | 超时/5xx 重试次数，默认 `2` |
| `PINGYI_TIMEOUT_SEC` | 平谊单次超时，默认 `60` |
| `PINGYI_RETRIES` | 超时/网络失败重试次数，默认 `2`（共 3 次） |
| `LOGISTICS_GATEWAY_BASE_URL` / `LOGISTICS_GATEWAY_API_KEY` | 龙舟/堡森网关 |
| `LOGISTICS_GATEWAY_TIMEOUT_SEC` | 单次 AGL 超时，默认 `240`（实测 ~80s） |
| `TRACK_QUERY_WORKERS` | 行级线程池，默认 `4`（主要加速平谊） |
| `LOGISTICS_GATEWAY_MAX_CONCURRENT` | 龙舟 AGL 网关并发，**默认 `1` 串行**，护网关 |
| `LOGISTICS_GATEWAY_MIN_INTERVAL_SEC` | AGL 两次请求最小间隔秒，默认 `0` |
| `TRACK_SEND_EXCEL` | 是否钉钉推送，默认 `0` 只落盘 `exports/`；`1` 推送给负责人 |
| `TRACK_CARRIER_KEYWORDS` | 默认 `平谊,龙舟,美通,堡森` |
| `TRACK_SHIP_YEAR` | 发货时间年份，默认 `2026`；`all` 不限 |
| `TRACK_NOTIFY_STATE_DIR` | sqlite 状态目录 |
