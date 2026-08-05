from __future__ import annotations

# unionId -> userId（推送 batchSend 用 userId）
UNION_TO_USERID: dict[str, str] = {
    "iiTcqTk5siSYoBBbKR7hRGiSQiEiE": "17331048354297047",  # 柯鹏翔
    "iiCcejLysla6iiFFOiPD53DFwiEiE": "17409662804279906",  # 乔丹丹
    "UQrqqgBXryxyFbP7kGAfdAiEiE": "114101644921239955",  # 刘育园/芋圆
    "ugU9bS9NAwNmXpdpFdfaiPwiEiE": "17585060291709805",  # 戴思怡
}

# 总览接收人：完整数据 + 问题数据都推
KEPENGXIANG_USER_ID = "17331048354297047"

# 物流通知名单（userId）——只收完整节点数据，不收问题行
LOGISTICS_NOTIFY_USER_IDS: tuple[str, ...] = (
    "17409662804279906",  # 乔丹丹
    "114101644921239955",  # 刘育园
    "17585060291709805",  # 戴思怡
)

# userId -> 中文名（Excel 文件名用）
USERID_TO_NAME: dict[str, str] = {
    "17331048354297047": "柯鹏翔",
    "17409662804279906": "乔丹丹",
    "114101644921239955": "刘育园",
    "17585060291709805": "戴思怡",
}


def display_name(user_id: str) -> str:
    uid = (user_id or "").strip()
    if not uid or uid == "no_owner":
        return "无负责人"
    return USERID_TO_NAME.get(uid, uid)


def owner_user_ids(owners: list[dict[str, str]]) -> list[str]:
    ids: list[str] = []
    for owner in owners:
        union_id = (owner.get("unionId") or "").strip()
        user_id = UNION_TO_USERID.get(union_id, "")
        if user_id and user_id not in ids:
            ids.append(user_id)
    return ids


def notify_user_ids(owners: list[dict[str, str]], *, issue: bool) -> list[str]:
    """
    推送对象：
    - 问题数据（缺号/无轨迹/查询失败）：只给柯鹏翔
    - 完整节点数据：表内负责人 + 柯鹏翔（全量汇总）
    """
    if issue:
        return [KEPENGXIANG_USER_ID]
    ids = owner_user_ids(owners)
    if KEPENGXIANG_USER_ID not in ids:
        ids.append(KEPENGXIANG_USER_ID)
    return ids
