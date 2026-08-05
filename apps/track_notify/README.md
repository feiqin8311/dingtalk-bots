# Track Notify / 主动查询物流状态并回传

## 规则（业务文档）

1. **调度**：周一、周三 **00:00**（Asia/Shanghai）
2. **筛选**：`2025New！`  
   - **发货时间** 年份 = 2026（列值为毫秒时间戳，如 `1779033600000`）  
   - 货代含「平谊」或「龙舟」  
   - 预计船期 ≤ 今天  
   - 实际送仓时间为空  
3. **查询**  
   - **平谊**：读 **FBA编码** → 软通宝 `getTrack`  
   - **龙舟**：读 **物流编号** + **品牌** → 物流网关  
     `POST /api/fba/query`（`logistics_no` + `brand` + `platform=agl`）  
4. **匹配节点（只推这些）**  
   - **龙舟**：`出发地 中国宁波` / `已到达卸货港` / `已提柜` / `货物已送达 FC 场地`  
   - **平谊**：`船只从始发港离港`（KC）/ `船只到达目的港`（DG）/ `货件已被完整配送至亚马逊仓库`（SC）  
   - 一次命中多个节点 → 同一 Excel 行「物流详情」里换行都列出  
5. **通知**  
   - a. **新增指定节点** + **异常行**（无 FBA / 未查到 / 查询失败）写入 Excel；轨迹有查到但无新节点 → 不推  

   - b. 节点级去重（sqlite `notified_events`：周一已推「已到达卸货港」，周三无新节点不推；出现「已提柜」再推）  
   - c. **每次仍全量查询候选行**（不再整行 skip）  
   - d. **按接收人生成 Excel**  
     - **完整节点**：表内负责人 + **柯鹏翔**（柯鹏翔收全量完整数据）  
     - **问题数据**（缺号/无轨迹/查询失败）：**只推柯鹏翔**，不推物流人员  
   - e. `TRACK_SEND_EXCEL=0` 只落盘，`1` 私聊只发文件  
   - f. 文件目录：`TRACK_NOTIFY_STATE_DIR/exports/`  


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

挂在 `apps/logistics_bot/main.py` 后台线程，Mon/Wed 00:00。

## 配置

见 `env.example`。

| 变量 | 用途 |
|------|------|
| `PINGYI_*` | 平谊 API |
| `LOGISTICS_GATEWAY_BASE_URL` / `LOGISTICS_GATEWAY_API_KEY` | 龙舟网关 |
| `LOGISTICS_GATEWAY_TIMEOUT_SEC` | 单次 AGL 超时，默认 `240`（实测 ~80s） |
| `TRACK_QUERY_WORKERS` | 行级并发，默认 `4`（~45 龙舟 ×80s /4 ≈ 15min） |
| `TRACK_SEND_EXCEL` | 是否钉钉推送，默认 `0` 只落盘 `exports/`；`1` 推送给负责人 |
| `TRACK_CARRIER_KEYWORDS` | 默认 `平谊,龙舟` |
| `TRACK_SHIP_YEAR` | 发货时间年份，默认 `2026`；`all` 不限 |
| `TRACK_NOTIFY_STATE_DIR` | sqlite 状态目录 |
