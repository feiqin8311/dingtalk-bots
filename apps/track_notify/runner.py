from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from dedup_store import TrackStateStore
from dingtalk_table import DingTalkNotableClient, TableRow
from excel_export import ReportItem, export_filename, format_shipped_at, write_report_xlsx
from gateway_client import LogisticsGatewayClient
from milestones import filter_new_milestones, milestone_label
from owners import notify_user_ids
from pingyi_client import PingyiClient, TrackShipment
from settings import TrackNotifyConfig


def _carrier_kind(carrier: str) -> str:
    text = carrier or ""
    if "龙舟" in text:
        return "longzhou"
    if "平谊" in text:
        return "pingyi"
    return "unknown"


def _item_to_dict(item: ReportItem) -> dict[str, Any]:
    return asdict(item)


def _item_from_dict(raw: dict[str, Any]) -> ReportItem:
    return ReportItem(
        shipment_key=str(raw.get("shipment_key") or ""),
        event_key=str(raw.get("event_key") or ""),
        message=str(raw.get("message") or ""),
        user_ids=list(raw.get("user_ids") or []),
        invoice_no=str(raw.get("invoice_no") or ""),
        brand=str(raw.get("brand") or ""),
        country=str(raw.get("country") or ""),
        fba_code=str(raw.get("fba_code") or ""),
        logistics_no=str(raw.get("logistics_no") or ""),
        carrier=str(raw.get("carrier") or ""),
        shipped_at=str(raw.get("shipped_at") or ""),
        eta_date=str(raw.get("eta_date") or ""),
        delivered_at=str(raw.get("delivered_at") or ""),
        owners=str(raw.get("owners") or ""),
        detail=str(raw.get("detail") or ""),
        event_keys=list(raw.get("event_keys") or []),
    )


def _checkpoint_bucket(store: TrackStateStore, bucket: list[ReportItem]) -> None:
    """查一行记一行：整表快照进 sqlite，进程被杀可恢复。"""
    store.sync_pending_items([_item_to_dict(it) for it in bucket])


def _row_base(row: TableRow) -> dict[str, str]:
    return {
        "invoice_no": row.invoice_no or "",
        "brand": row.brand or "",
        "country": row.country or "",
        "carrier": row.carrier or "",
        "shipped_at": format_shipped_at(row.shipped_at),
        "eta_date": format_shipped_at(row.eta_date),
        "delivered_at": format_shipped_at(row.delivered_at),
        "owners": row.owner_names or "",
    }


def _emit_events(
    *,
    row: TableRow,
    shipment: TrackShipment,
    shipment_key: str,
    display_code: str,
    kind: str,
    user_ids: list[str],
    store: TrackStateStore,
    bucket: list[ReportItem],
    logger: logging.Logger,
) -> int:
    """
    只收集指定业务节点；一单（FBA/物流编号）一行，详情内换行装本次新增节点。
    已推过的节点（notified_events）跳过；无新节点则不写 Excel。
    """
    is_pingyi = kind == "pingyi"
    fba = display_code if is_pingyi else ",".join(row.fba_codes)
    logistics = ",".join(row.logistics_nos) if is_pingyi else display_code

    matched = filter_new_milestones(shipment.events, kind=kind)
    new_pairs = [
        (mkey, event)
        for mkey, event in matched
        if not store.has_event(shipment_key, mkey)
    ]
    skipped = len(matched) - len(new_pairs)
    if skipped:
        logger.debug(
            "skip already notified shipment=%s kind=%s skipped=%s",
            shipment_key,
            kind,
            skipped,
        )
    if not new_pairs:
        logger.debug(
            "no new milestones shipment=%s kind=%s events=%s matched=%s",
            shipment_key,
            kind,
            len(shipment.events),
            len(matched),
        )
        return 0

    detail_parts: list[str] = []
    event_keys: list[str] = []
    for mkey, event in new_pairs:
        when = (event.occur_date or "").strip()
        if " " in when:
            when = when.split(" ", 1)[0]
        status = milestone_label(mkey)
        part = f"{when} {status}".strip() if when else status
        if part:
            detail_parts.append(part)
        event_keys.append(mkey)

    detail = "\n".join(detail_parts)
    message = f"{display_code} 节点{len(event_keys)}条"
    base = _row_base(row)
    bucket.append(
        ReportItem(
            shipment_key=shipment_key,
            event_key=event_keys[0],
            message=message,
            user_ids=list(user_ids),
            invoice_no=base["invoice_no"],
            brand=base["brand"],
            country=base["country"],
            fba_code=fba,
            logistics_no=logistics,
            carrier=base["carrier"],
            shipped_at=base["shipped_at"],
            eta_date=base["eta_date"],
            delivered_at=base["delivered_at"],
            owners=base["owners"],
            detail=detail,
            event_keys=event_keys,
        )
    )
    logger.info(
        "milestones shipment=%s kind=%s new=%s keys=%s",
        shipment_key,
        kind,
        len(event_keys),
        ",".join(event_keys),
    )
    return 1


def _missing_key_line(row: TableRow, *, kind: str) -> str:
    inv = (row.invoice_no or row.record_id or "").strip()
    if kind == "pingyi":
        return f"{inv} 无FBA编码，无法查询平谊轨迹".strip()
    return f"{inv} 无物流编号，无法查询龙舟轨迹".strip()


def _query_fail_line(row: TableRow, code: str, reason: str) -> str:
    inv = (row.invoice_no or "").strip()
    code = (code or "").strip()
    reason = (reason or "未知错误").strip()
    head = f"{inv} {code}".strip() if inv else code
    return f"{head} 查询失败：{reason}".strip()


def _no_track_line(row: TableRow, code: str) -> str:
    inv = (row.invoice_no or "").strip()
    code = (code or "").strip()
    head = f"{inv} {code}".strip() if inv else code
    return f"{head} 未查到轨迹".strip()


def _collect_once(
    *,
    shipment_key: str,
    event_key: str,
    message: str,
    user_ids: list[str],
    store: TrackStateStore,
    bucket: list[ReportItem],
    row: TableRow,
    fba_code: str = "",
    logistics_no: str = "",
    detail: str = "",
    logger: logging.Logger,
) -> int:
    """异常行写入 Excel（去重）；mark 在发送/落盘成功后。"""
    if store.has_event(shipment_key, event_key):
        logger.debug("skip already recorded %s | %s", shipment_key, event_key)
        return 0
    base = _row_base(row)
    bucket.append(
        ReportItem(
            shipment_key=shipment_key,
            event_key=event_key,
            message=message,
            user_ids=list(user_ids),
            invoice_no=base["invoice_no"],
            brand=base["brand"],
            country=base["country"],
            fba_code=fba_code,
            logistics_no=logistics_no,
            carrier=base["carrier"],
            shipped_at=base["shipped_at"],
            eta_date=base["eta_date"],
            delivered_at=base["delivered_at"],
            owners=base["owners"],
            detail=detail or message,
        )
    )
    return 1


def _report_missing_key(
    row: TableRow,
    *,
    kind: str,
    store: TrackStateStore,
    bucket: list[ReportItem],
    logger: logging.Logger,
) -> tuple[int, bool, list[str]]:
    line = _missing_key_line(row, kind=kind)
    # 问题数据只推柯鹏翔
    user_ids = notify_user_ids(row.owners, issue=True)
    event_key = "missing_fba" if kind == "pingyi" else "missing_logistics_no"
    logger.warning(
        "missing key kind=%s record=%s invoice=%s owners=%s => %s",
        kind,
        row.record_id,
        row.invoice_no,
        row.owner_names,
        line,
    )
    n = _collect_once(
        shipment_key=row.record_id,
        event_key=event_key,
        message=line,
        user_ids=user_ids,
        store=store,
        bucket=bucket,
        row=row,
        fba_code=",".join(row.fba_codes),
        logistics_no=",".join(row.logistics_nos),
        detail=line,
        logger=logger,
    )
    return n, True, [line]


def _process_pingyi_row(
    row: TableRow,
    *,
    client: PingyiClient,
    store: TrackStateStore,
    bucket: list[ReportItem],
    logger: logging.Logger,
) -> tuple[int, bool, list[str]]:
    codes = row.fba_codes
    if not codes:
        return _report_missing_key(
            row, kind="pingyi", store=store, bucket=bucket, logger=logger
        )

    # 完整 → 负责人+柯鹏翔；问题 → 仅柯鹏翔（无负责人映射也照常处理）
    ok_uids = notify_user_ids(row.owners, issue=False)
    issue_uids = notify_user_ids(row.owners, issue=True)

    logistics_joined = ",".join(row.logistics_nos)
    notified = 0
    query_ok = True
    issues: list[str] = []
    for code in codes:
        try:
            shipment = client.get_track(code)
        except Exception as exc:
            query_ok = False
            line = _query_fail_line(row, code, str(exc))
            issues.append(line)
            logger.exception("getTrack failed fba=%s: %s", code, exc)
            notified += _collect_once(
                shipment_key=code,
                event_key="query_error",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=code,
                logistics_no=logistics_joined,
                detail=line,
                logger=logger,
            )
            continue
        if shipment is None:
            line = _no_track_line(row, code)
            issues.append(line)
            logger.warning("no track fba=%s record=%s", code, row.record_id)
            notified += _collect_once(
                shipment_key=code,
                event_key="no_track",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=code,
                logistics_no=logistics_joined,
                detail=line,
                logger=logger,
            )
            continue
        logger.info(
            "track record=%s fba=%s tracking=%s status=%s events=%s",
            row.record_id,
            code,
            shipment.tracking_no,
            shipment.track_status_name or shipment.track_status,
            len(shipment.events),
        )
        notified += _emit_events(
            row=row,
            shipment=shipment,
            shipment_key=code,
            display_code=code,
            kind="pingyi",
            user_ids=ok_uids,
            store=store,
            bucket=bucket,
            logger=logger,
        )
    return notified, query_ok, issues


def _process_longzhou_row(
    row: TableRow,
    *,
    client: LogisticsGatewayClient | None,
    store: TrackStateStore,
    bucket: list[ReportItem],
    logger: logging.Logger,
) -> tuple[int, bool, list[str]]:
    if client is None:
        line = _query_fail_line(
            row, ",".join(row.logistics_nos) or row.invoice_no, "网关未配置"
        )
        logger.error(
            "skip longzhou record=%s: gateway not configured (LOGISTICS_GATEWAY_*)",
            row.record_id,
        )
        n = _collect_once(
            shipment_key=row.record_id,
            event_key="gateway_missing",
            message=line,
            user_ids=notify_user_ids(row.owners, issue=True),
            store=store,
            bucket=bucket,
            row=row,
            fba_code=",".join(row.fba_codes),
            logistics_no=",".join(row.logistics_nos),
            detail=line,
            logger=logger,
        )
        return n, False, [line]

    nos = row.logistics_nos
    if not nos:
        return _report_missing_key(
            row, kind="longzhou", store=store, bucket=bucket, logger=logger
        )

    ok_uids = notify_user_ids(row.owners, issue=False)
    issue_uids = notify_user_ids(row.owners, issue=True)

    brand = (row.brand or "").strip()
    fba_joined = ",".join(row.fba_codes)
    notified = 0
    query_ok = True
    issues: list[str] = []
    for logistics_no in nos:
        try:
            shipment = client.query_longzhou(logistics_no, brand=brand, platform="agl")
        except Exception as exc:
            query_ok = False
            line = _query_fail_line(row, logistics_no, str(exc))
            issues.append(line)
            logger.exception(
                "gateway longzhou failed logistics_no=%s brand=%s: %s",
                logistics_no,
                brand,
                exc,
            )
            notified += _collect_once(
                shipment_key=logistics_no,
                event_key="query_error",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=fba_joined,
                logistics_no=logistics_no,
                detail=line,
                logger=logger,
            )
            continue
        if shipment is None:
            line = _no_track_line(row, logistics_no)
            issues.append(line)
            logger.warning(
                "no track logistics_no=%s record=%s brand=%s",
                logistics_no,
                row.record_id,
                brand,
            )
            notified += _collect_once(
                shipment_key=logistics_no,
                event_key="no_track",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=fba_joined,
                logistics_no=logistics_no,
                detail=line,
                logger=logger,
            )
            continue
        logger.info(
            "track record=%s logistics_no=%s brand=%s events=%s latest=%s",
            row.record_id,
            logistics_no,
            brand,
            len(shipment.events),
            shipment.track_status_name,
        )
        notified += _emit_events(
            row=row,
            shipment=shipment,
            shipment_key=logistics_no,
            display_code=logistics_no,
            kind="longzhou",
            user_ids=ok_uids,
            store=store,
            bucket=bucket,
            logger=logger,
        )
    return notified, query_ok, issues


def _retry_longzhou_query_errors(
    bucket: list[ReportItem],
    rows: list[TableRow],
    *,
    gateway: LogisticsGatewayClient | None,
    store: TrackStateStore,
    logger: logging.Logger,
    pause_sec: float = 3.0,
) -> dict[str, int]:
    """
    本轮全部查完后：对龙舟 query_error 再串行重查 1 次（瞬时 AGL 失败）。
    成功则从 bucket 去掉 error，写入节点（若有）；仍失败则保留原问题行。
    """
    stats = {"gateway_retry": 0, "gateway_recovered": 0}
    if gateway is None:
        return stats

    by_no: dict[str, TableRow] = {}
    for row in rows:
        if _carrier_kind(row.carrier) != "longzhou":
            continue
        for no in row.logistics_nos:
            key = (no or "").strip()
            if key:
                by_no[key] = row

    targets: list[tuple[TableRow, str]] = []
    seen_no: set[str] = set()
    for it in bucket:
        if it.event_key != "query_error":
            continue
        no = (it.logistics_no or it.shipment_key or "").strip()
        if not no or no not in by_no or no in seen_no:
            continue
        seen_no.add(no)
        targets.append((by_no[no], no))

    if not targets:
        return stats

    logger.info(
        "longzhou retry pass count=%s pause=%ss (serial)",
        len(targets),
        pause_sec,
    )
    stats["gateway_retry"] = len(targets)

    for i, (row, logistics_no) in enumerate(targets):
        if i > 0 and pause_sec > 0:
            time.sleep(pause_sec)
        brand = (row.brand or "").strip()
        fba_joined = ",".join(row.fba_codes)
        ok_uids = notify_user_ids(row.owners, issue=False)
        issue_uids = notify_user_ids(row.owners, issue=True)
        try:
            shipment = gateway.query_longzhou(
                logistics_no, brand=brand, platform="agl"
            )
        except Exception as exc:
            logger.warning(
                "longzhou retry still failed logistics_no=%s brand=%s: %s",
                logistics_no,
                brand,
                exc,
            )
            continue

        # 去掉本单首次 query_error（无论成功有轨迹 / 确认无轨迹）
        bucket[:] = [
            it
            for it in bucket
            if not (
                it.event_key == "query_error" and it.shipment_key == logistics_no
            )
        ]
        stats["gateway_recovered"] += 1

        if shipment is None:
            line = _no_track_line(row, logistics_no)
            logger.info(
                "longzhou retry no track logistics_no=%s record=%s",
                logistics_no,
                row.record_id,
            )
            _collect_once(
                shipment_key=logistics_no,
                event_key="no_track",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=fba_joined,
                logistics_no=logistics_no,
                detail=line,
                logger=logger,
            )
            continue

        logger.info(
            "longzhou retry ok logistics_no=%s brand=%s events=%s latest=%s",
            logistics_no,
            brand,
            len(shipment.events),
            shipment.track_status_name,
        )
        _emit_events(
            row=row,
            shipment=shipment,
            shipment_key=logistics_no,
            display_code=logistics_no,
            kind="longzhou",
            user_ids=ok_uids,
            store=store,
            bucket=bucket,
            logger=logger,
        )
    return stats


def _process_row(
    row: TableRow,
    *,
    pingyi: PingyiClient | None,
    gateway: LogisticsGatewayClient | None,
    store: TrackStateStore,
    bucket: list[ReportItem],
    logger: logging.Logger,
) -> tuple[int, bool, list[str]]:
    if not row.record_id:
        return 0, False, []
    kind = _carrier_kind(row.carrier)
    if kind == "pingyi":
        if pingyi is None:
            line = _query_fail_line(
                row, ",".join(row.fba_codes) or row.invoice_no, "平谊客户端未配置"
            )
            logger.error("skip pingyi record=%s: pingyi client missing", row.record_id)
            return 0, False, [line]
        return _process_pingyi_row(
            row, client=pingyi, store=store, bucket=bucket, logger=logger
        )
    if kind == "longzhou":
        return _process_longzhou_row(
            row, client=gateway, store=store, bucket=bucket, logger=logger
        )
    logger.warning(
        "skip unknown carrier=%s record=%s invoice=%s",
        row.carrier,
        row.record_id,
        row.invoice_no,
    )
    return 0, False, []


def _deliver_excel_reports(
    items: list[ReportItem],
    *,
    config: TrackNotifyConfig,
    store: TrackStateStore,
    dry_run: bool,
    logger: logging.Logger,
) -> dict[str, int]:
    stats = {"excel_rows": len(items), "excel_files": 0, "excel_sent": 0, "excel_failed": 0}
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
            cleared_no: list[tuple[str, str]] = []
            for item in no_owner:
                for ek in item.keys_to_mark():
                    store.mark_event(item.shipment_key, ek, item.message)
                cleared_no.append((item.shipment_key, item.event_key))
            store.clear_pending_for(cleared_no)

    # 先写盘，再发钉钉：发送侧 import 失败时也要有 Excel 可查
    prepared: list[tuple[str, Path, list[ReportItem]]] = []
    for user_id, user_items in by_user.items():
        seen: set[tuple[str, str]] = set()
        unique: list[ReportItem] = []
        for it in user_items:
            k = (it.shipment_key, it.event_key)
            if k in seen:
                continue
            seen.add(k)
            unique.append(it)
        path = export_dir / export_filename(user_id=user_id, when=when)
        write_report_xlsx(unique, path)
        stats["excel_files"] += 1
        prepared.append((user_id, path, unique))

    notifier = None
    if not dry_run and config.send_excel:
        if not config.ding_client_id or not config.ding_client_secret or not config.ding_robot_code:
            logger.error("missing ding credentials/robot_code, cannot send excel")
        else:
            try:
                # cp_bot.api.config 依赖 apps/cp_bot 在 sys.path（独立子进程无 logistics 环境）
                cp_dir = str(ROOT_DIR / "apps" / "cp_bot")
                if cp_dir not in sys.path:
                    sys.path.insert(0, cp_dir)
                from api.dingtalk_client import DingTalkNotifier  # noqa: WPS433

                notifier = DingTalkNotifier(
                    app_key=config.ding_client_id,
                    app_secret=config.ding_client_secret,
                    robot_code=config.ding_robot_code,
                )
            except Exception:
                logger.exception("DingTalkNotifier import/init failed")

    for user_id, path, unique in prepared:
        if dry_run:
            logger.info("[dry-run] excel owner=%s path=%s rows=%s", user_id, path, len(unique))
            continue
        if not config.send_excel:
            logger.info(
                "[excel-only] owner=%s path=%s rows=%s (TRACK_SEND_EXCEL off)",
                user_id,
                path,
                len(unique),
            )
            cleared: list[tuple[str, str]] = []
            for item in unique:
                for ek in item.keys_to_mark():
                    store.mark_event(item.shipment_key, ek, item.message)
                cleared.append((item.shipment_key, item.event_key))
            store.clear_pending_for(cleared)
            continue
        if notifier is None:
            stats["excel_failed"] += 1
            logger.error("excel not sent owner=%s path=%s (notifier unavailable)", user_id, path)
            continue
        try:
            notifier.send_user_file(user_id, str(path))
            stats["excel_sent"] += 1
            logger.info("excel sent owner=%s path=%s rows=%s", user_id, path, len(unique))
            cleared = []
            for item in unique:
                for ek in item.keys_to_mark():
                    store.mark_event(item.shipment_key, ek, item.message)
                cleared.append((item.shipment_key, item.event_key))
            store.clear_pending_for(cleared)
        except Exception as exc:
            stats["excel_failed"] += 1
            logger.exception("excel send failed owner=%s: %s", user_id, exc)

    return stats


def run_once(config: TrackNotifyConfig, *, dry_run: bool = False) -> dict[str, int]:
    logger = logging.getLogger("track_notify")
    table = DingTalkNotableClient(
        config.ding_client_id,
        config.ding_client_secret,
        operator_union_id=config.operator_union_id,
    )
    pingyi: PingyiClient | None = None
    if config.pingyi_app_token and config.pingyi_app_key:
        pingyi = PingyiClient(
            config.pingyi_app_token,
            config.pingyi_app_key,
            base_url=config.pingyi_base_url,
        )
    gateway: LogisticsGatewayClient | None = None
    if config.gateway_base_url and config.gateway_api_key:
        gateway = LogisticsGatewayClient(
            config.gateway_base_url,
            config.gateway_api_key,
            timeout_sec=config.gateway_timeout_sec,
            max_concurrent=config.gateway_max_concurrent,
            min_interval_sec=config.gateway_min_interval_sec,
        )
    store = TrackStateStore(config.state_db_path)
    bucket: list[ReportItem] = []
    stats: dict[str, int] = {
        "candidates": 0,
        "processed": 0,
        "collected": 0,
        "missing_key": 0,
        "query_issues": 0,
        "gateway_retry": 0,
        "gateway_recovered": 0,
        "pending_resumed": 0,
        "excel_rows": 0,
        "excel_files": 0,
        "excel_sent": 0,
        "excel_failed": 0,
    }
    issue_lines: list[str] = []
    try:
        # 崩溃恢复：上次已查出未推送的行先落盘/推送，避免白跑
        if not dry_run:
            leftover = [_item_from_dict(r) for r in store.load_pending_items()]
            if leftover:
                logger.info(
                    "resume pending report items count=%s (checkpoint from prior run)",
                    len(leftover),
                )
                stats["pending_resumed"] = len(leftover)
                resume_deliver = _deliver_excel_reports(
                    leftover,
                    config=config,
                    store=store,
                    dry_run=False,
                    logger=logger,
                )
                for k, v in resume_deliver.items():
                    stats[k] = stats.get(k, 0) + v

        rows = table.iter_candidate_rows(
            config.dingtalk_doc_key,
            config.dingtalk_sheet_id,
            config.dingtalk_view_id,
            carrier_keywords=config.carrier_keywords,
            ship_year=config.ship_year,
        )
        stats["candidates"] = len(rows)
        # 每次都查：不按行级 checked 跳过；去重只在「指定节点已推送」层
        pending = list(rows)

        workers = max(1, min(config.query_workers, len(pending) or 1))
        logger.info(
            "candidates carriers=%s ship_year=%s count=%s pending=%s "
            "row_workers=%s gateway_concurrent=%s gateway_interval=%ss timeout=%ss",
            ",".join(config.carrier_keywords),
            config.ship_year,
            len(rows),
            len(pending),
            workers,
            config.gateway_max_concurrent,
            config.gateway_min_interval_sec,
            int(config.gateway_timeout_sec),
        )

        def _work(row: TableRow) -> tuple[TableRow, int, bool, list[str], list[ReportItem]]:
            local: list[ReportItem] = []
            collected, query_ok, issues = _process_row(
                row,
                pingyi=pingyi,
                gateway=gateway,
                store=store,
                bucket=local,
                logger=logger,
            )
            return row, collected, query_ok, issues, local

        # AGL ~80s/单；ThreadPool 并发，避免 45 条串行 1h+
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_work, row) for row in pending]
            for fut in as_completed(futures):
                row, collected, query_ok, issues, local = fut.result()
                kind = _carrier_kind(row.carrier)
                if kind == "pingyi" and not row.fba_codes:
                    stats["missing_key"] += 1
                elif kind == "longzhou" and not row.logistics_nos:
                    stats["missing_key"] += 1
                stats["processed"] += 1
                stats["collected"] += collected
                bucket.extend(local)
                if issues:
                    stats["query_issues"] += len(issues)
                    issue_lines.extend(issues)
                # 跑一个记一个（整表快照，含本行结果）
                if not dry_run:
                    _checkpoint_bucket(store, bucket)

        # 龙舟瞬时失败：全量结束后再串行重查 1 轮 query_error
        retry_stats = _retry_longzhou_query_errors(
            bucket,
            pending,
            gateway=gateway,
            store=store,
            logger=logger,
            pause_sec=3.0,
        )
        stats.update(retry_stats)
        # 重试后问题行可能变少，issue 摘要以 bucket 为准
        if retry_stats.get("gateway_recovered"):
            issue_lines = [
                it.detail or it.message
                for it in bucket
                if it.event_key
                in {"query_error", "no_track", "missing_fba", "missing_logistics_no", "gateway_missing"}
            ]
            stats["query_issues"] = len(issue_lines)
        if not dry_run:
            _checkpoint_bucket(store, bucket)

        deliver = _deliver_excel_reports(
            bucket,
            config=config,
            store=store,
            dry_run=dry_run,
            logger=logger,
        )
        stats.update(deliver)
        if issue_lines:
            logger.info(
                "issue summary (%s):\n%s",
                len(issue_lines),
                "\n".join(issue_lines),
            )
        logger.info("run done %s", stats)
        return stats
    finally:
        store.close()
