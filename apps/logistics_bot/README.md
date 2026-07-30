# Logistics Bot / 物流部机器人

Unified DingTalk Stream bot for Logistics department workflows.

物流部统一钉钉 Stream 机器人。

## Branches / 分支

- CP shipment check: send `SP...` shipment numbers.
- PDF/label split: upload PDF + Excel, or send `标签拆分` / `拆分`.
- No-FC-split packing (不分仓拼箱): menu `3` → `apps/pinxiang_bot`.
- FC-split packing (分仓拼箱 / LCL): menu `4` → `apps/lcl_bot` (from dingtalk-lcl-bot).

- CP 发货单核对：发送 `SP...` 发货单号。
- PDF/标签拆分：上传 PDF + Excel。
- 不分仓拼箱：菜单 `3`。
- 分仓拼箱：菜单 `4`（原 lcl-bot）。

## Routing / 路由

```text
1. 发货单核对
2. 标签/PDF 拆分
3. 不分仓拼箱
4. 分仓拼箱
```

1. Reply `1` → CP  
2. Reply `2` → split  
3. Reply `3` → pinxiang  
4. Reply `4` → lcl  
5. Branch selected: messages stay on that branch  
6. Reply `重置` → clear branch (+ lcl workflow if leaving 4)

## Run / 启动

From monorepo root:

```bash
python apps/logistics_bot/main.py
```

Docker:

```bash
docker compose up -d --build dingtalk-logistics-bot
```
