from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime
from pathlib import Path

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
            for item in no_owner:
                for ek in item.keys_to_mark():
                    store.mark_event(item.shipment_key, ek, item.message)

    notifier = None
    if not dry_run and config.send_excel:
        if not config.ding_client_id or not config.ding_client_secret or not config.ding_robot_code:
            logger.error("missing ding credentials/robot_code, cannot send excel")
        else:
            from apps.cp_bot.api.dingtalk_client import DingTalkNotifier

            notifier = DingTalkNotifier(
                app_key=config.ding_client_id,
                app_secret=config.ding_client_secret,
                robot_code=config.ding_robot_code,
            )

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
        if dry_run:
            logger.info("[dry-run] excel owner=%s path=%s rows=%s", user_id, path, len(unique))
            continue
        # 暂时只落盘：写 Excel + 记状态，不推钉钉
        if not config.send_excel:
            logger.info(
                "[excel-only] owner=%s path=%s rows=%s (TRACK_SEND_EXCEL off)",
                user_id,
                path,
                len(unique),
            )
            for item in unique:
                for ek in item.keys_to_mark():
                    store.mark_event(item.shipment_key, ek, item.message)
            continue
        if notifier is None:
            stats["excel_failed"] += 1
            continue
        try:
            # 只发 Excel，不发文字说明
            notifier.send_user_file(user_id, str(path))
            stats["excel_sent"] += 1
            logger.info("excel sent owner=%s path=%s rows=%s", user_id, path, len(unique))
            for item in unique:
                for ek in item.keys_to_mark():
                    store.mark_event(item.shipment_key, ek, item.message)
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
        )
    store = TrackStateStore(config.state_db_path)
    bucket: list[ReportItem] = []
    stats: dict[str, int] = {
        "candidates": 0,
        "processed": 0,
        "collected": 0,
        "missing_key": 0,
        "query_issues": 0,
        "excel_rows": 0,
        "excel_files": 0,
        "excel_sent": 0,
        "excel_failed": 0,
    }
    issue_lines: list[str] = []
    try:
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
            "candidates carriers=%s ship_year=%s count=%s pending=%s workers=%s timeout=%ss",
            ",".join(config.carrier_keywords),
            config.ship_year,
            len(rows),
            len(pending),
            workers,
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
