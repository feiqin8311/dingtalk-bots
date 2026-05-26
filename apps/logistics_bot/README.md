# Logistics Bot / 物流部机器人

Unified DingTalk Stream bot for Logistics department workflows.

物流部统一钉钉 Stream 机器人。

## Branches / 分支

- CP shipment check: send `SP...` shipment numbers.
- PDF/label split: upload PDF + Excel, or send `标签拆分` / `拆分`.

- CP 发货单核对：发送 `SP...` 发货单号。
- PDF/标签拆分：上传 PDF + Excel，或发送 `标签拆分` / `拆分`。

## Routing / 路由

Users can choose a branch first:

```text
1. 发货单核对
2. 标签/PDF 拆分
```

Routing:

1. Reply `1` -> enter CP shipment check branch.
2. Reply `2` -> enter PDF/label split branch.
3. Attachment upload -> split branch.
4. `确认` / `取消` -> split branch confirmation flow.
5. Text containing `SP...` -> CP branch.
6. Reply `重置` -> clear branch selection and restart from the menu.
7. Other text -> help menu.

## Run / 启动

From monorepo root:

```bash
python apps/logistics_bot/main.py
```

Docker:

```bash
docker compose up -d --build dingtalk-logistics-bot
```
