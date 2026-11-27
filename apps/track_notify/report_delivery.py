"""Write per-owner Excel reports and mark events after delivery."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from .dedup_store import CST, TrackStateStore
from .excel_export import ReportItem, export_filename, filter_report_item, write_report_xlsx
from .settings import TrackNotifyConfig

def _mark_and_clear_items(store: TrackStateStore, items: list[ReportItem]) -> None:
    cleared: list[tuple[str, str]] = []
    for item in items:
        for ek in item.keys_to_mark():
            store.mark_event(item.shipment_key, ek, item.message)
        cleared.append((item.shipment_key, item.event_key))
    store.clear_pending_for(cleared)


def _deliver_excel_reports(
    items: list[ReportItem],
    *,
    config: TrackNotifyConfig,
    store: TrackStateStore,
    dry_run: bool,
    logger: logging.Logger,
) -> dict[str, int]:
    stats = {
        "excel_rows": len(items),
        "excel_files": 0,
        "excel_sent": 0,
        "excel_failed": 0,
        "excel_mark_deferred": 0,
    }
    if not items:
        return stats

    by_user: dict[str, list[ReportItem]] = defaultdict(list)
    no_owner: list[ReportItem] = []
    for item in items:
        if item.user_ids:
            for uid in item.user_ids:
                by_user[uid].append(item)
        else:
            no_owner.append(item)

    export_dir = config.state_dir / "exports"
    when = datetime.now()

    if no_owner:
        path = export_dir / export_filename(user_id="no_owner", when=when)
        write_report_xlsx(no_owner, path)
        stats["excel_files"] += 1
        logger.warning("excel for no-owner rows path=%s rows=%s", path, len(no_owner))
        if not dry_run:
            _mark_and_clear_items(store, no_owner)

    # 先写盘，再发钉钉：发送侧 import 失败时也要有 Excel 可查
    # 有日期则只留日期行；全无日期节点不入任何人 Excel（问题行仍给柯鹏翔）
    prepared: list[tuple[str, Path, list[ReportItem]]] = []
    # 实际写入某人 Excel 的行 → mark 时只要求这些收件人发送成功
    delivered_recipients: dict[tuple[str, str], set[str]] = defaultdict(set)
    for user_id, user_items in by_user.items():
        seen: set[tuple[str, str]] = set()
        unique: list[ReportItem] = []
        for it in user_items:
            k = (it.shipment_key, it.event_key)
            if k in seen:
                continue
            seen.add(k)
            view = filter_report_item(it)
            if view is None:
                logger.info(
                    "omit undated-only detail user=%s shipment=%s",
                    user_id,
                    it.shipment_key,
                )
                continue
            unique.append(view)
            delivered_recipients[k].add(user_id)
        if not unique:
            logger.info("excel skip empty after date-filter owner=%s", user_id)
            continue
        path = export_dir / export_filename(user_id=user_id, when=when)
        write_report_xlsx(unique, path)
        stats["excel_files"] += 1
        prepared.append((user_id, path, unique))

    if dry_run:
        for user_id, path, unique in prepared:
            logger.info("[dry-run] excel owner=%s path=%s rows=%s", user_id, path, len(unique))
        return stats

    if not config.send_excel:
        for user_id, path, unique in prepared:
            logger.info(
                "[excel-only] owner=%s path=%s rows=%s (TRACK_SEND_EXCEL off)",
                user_id,
                path,
                len(unique),
            )
        # 落盘成功 + 全员被滤掉的无日期节点一并 mark，避免下周再冒出来
        markable = [it for it in items if it.user_ids]
        if markable:
            _mark_and_clear_items(store, markable)
        return stats

    notifier = None
    if not config.ding_client_id or not config.ding_client_secret or not config.ding_robot_code:
        logger.error("missing ding credentials/robot_code, cannot send excel")
    else:
        try:
            from apps.cp_bot.api.dingtalk_client import DingTalkNotifier  # noqa: WPS433

            notifier = DingTalkNotifier(
                app_key=config.ding_client_id,
                app_secret=config.ding_client_secret,
                robot_code=config.ding_robot_code,
            )
        except Exception:
            logger.exception("DingTalkNotifier import/init failed")

    # 先发完全部收件人，再按 item 统一 mark：实际收件人失败则该行不 mark，下次可重推
    success_users: set[str] = set()
    for user_id, path, unique in prepared:
        if notifier is None:
            stats["excel_failed"] += 1
            logger.error("excel not sent owner=%s path=%s (notifier unavailable)", user_id, path)
            continue
        try:
            notifier.send_user_file(user_id, str(path))
            success_users.add(user_id)
            stats["excel_sent"] += 1
            logger.info("excel sent owner=%s path=%s rows=%s", user_id, path, len(unique))
        except Exception as exc:
            stats["excel_failed"] += 1
            logger.exception("excel send failed owner=%s: %s", user_id, exc)

    by_key: dict[tuple[str, str], ReportItem] = {}
    for item in items:
        if not item.user_ids:
            continue
        by_key[(item.shipment_key, item.event_key)] = item

    to_mark: list[ReportItem] = []
    for key, item in by_key.items():
        needed = delivered_recipients.get(key, set())
        if not needed:
            # 全员因「无日期」被滤掉且无总览收件人写入 — 仍 mark，避免卡死
            to_mark.append(item)
            continue
        if needed.issubset(success_users):
            to_mark.append(item)
        else:
            stats["excel_mark_deferred"] += 1
            logger.warning(
                "defer mark shipment=%s event=%s missing_recipients=%s",
                item.shipment_key,
                item.event_key,
                sorted(needed - success_users),
            )
    if to_mark:
        _mark_and_clear_items(store, to_mark)

    return stats
