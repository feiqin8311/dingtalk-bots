# Logistics Bot / 物流部机器人

Unified DingTalk Stream bot for Logistics department workflows.

物流部统一钉钉 Stream 机器人。

## Branches / 分支

- CP shipment check: send `SP...` shipment numbers.
- PDF/label split: upload PDF + Excel, or send `标签拆分` / `拆分`.
- No-FC-split packing (不分仓拼箱): upload shipment Excel → packing result → confirm → Amazon template.

- CP 发货单核对：发送 `SP...` 发货单号。
- PDF/标签拆分：上传 PDF + Excel，或发送 `标签拆分` / `拆分`。
- 不分仓拼箱：上传发货单 → 拼箱结果 → 确认并选择运营转发 → 运营上传装箱表 → 机器人填写回传。

## Routing / 路由

Users can choose a branch first:

```text
1. 发货单核对
2. 标签/PDF 拆分
3. 不分仓拼箱
```

Routing:

1. Reply `1` -> enter CP shipment check branch.
2. Reply `2` -> enter PDF/label split branch.
3. Reply `3` -> enter 不分仓拼箱 branch.
4. When branch selected: messages stay on that branch (attachments / 确认 / 取消 included for pinxiang).
5. On split branch: attachment / 确认 / 取消 -> split handler.
6. Reply `重置` -> clear branch selection and restart from the menu.
7. Other text (no branch) -> help menu.

## Run / 启动

From monorepo root:

```bash
python apps/logistics_bot/main.py
```

Docker:

```bash
docker compose up -d --build dingtalk-logistics-bot
```
