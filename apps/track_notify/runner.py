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

from dedup_store import CST, TrackStateStore
from dingtalk_table import DingTalkNotableClient, TableRow
from excel_export import (
    ReportItem,
    export_filename,
    filter_report_item_for_user,
    format_shipped_at,
    write_report_xlsx,
)
from gateway_client import LogisticsGatewayClient
from milestones import (
    event_has_date,
    filter_new_milestones,
    milestone_label,
    notify_event_key,
)
from meitong_client import MeitongClient
from owners import KEPENGXIANG_USER_ID, notify_user_ids
from pingyi_client import PingyiClient, TrackShipment
from settings import TrackNotifyConfig


def _carrier_kind(carrier: str) -> str:
    text = carrier or ""
    if "龙舟" in text:
        return "longzhou"
    if "堡森" in text:
        return "baosen"
    if "平谊" in text:
        return "pingyi"
    if "美通" in text:
        return "meitong"
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


_TRANSIENT_ISSUE_KEYS = frozenset({"query_error", "no_track"})


def _drop_transient_issues(bucket: list[ReportItem], shipment_key: str) -> int:
    """同单成功查到后，去掉 checkpoint/本轮残留的瞬时失败行，避免误进问题表。"""
    key = (shipment_key or "").strip()
    if not key:
        return 0
    before = len(bucket)
    bucket[:] = [
        it
        for it in bucket
        if not (it.shipment_key == key and it.event_key in _TRANSIENT_ISSUE_KEYS)
    ]
    return before - len(bucket)


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

    matched = filter_new_milestones(
        shipment.events, kind=kind, channel=row.channel
    )
    new_pairs: list[tuple[str, TrackEvent, str]] = []
    for mkey, event in matched:
        dated = event_has_date(event)
        nkey = notify_event_key(mkey, dated)
        if store.has_event(shipment_key, nkey):
            continue
        # 无日期：若 dated key 已在（含历史「一次记死」），不再刷无日期行
        if not dated and store.has_event(shipment_key, mkey):
            continue
        new_pairs.append((mkey, event, nkey))
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
    for mkey, event, nkey in new_pairs:
        when = (event.occur_date or "").strip()
        if " " in when:
            when = when.split(" ", 1)[0]
        status = milestone_label(mkey)
        part = f"{when} {status}".strip() if when else status
        if part:
            detail_parts.append(part)
        event_keys.append(nkey)

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
    if kind == "baosen":
        return f"{inv} 无FBA编码，无法查询堡森轨迹".strip()
    if kind == "meitong":
        return f"{inv} 无物流编号，无法查询美通轨迹".strip()
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
    event_key = "missing_fba" if kind in {"pingyi", "baosen"} else "missing_logistics_no"
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
        dropped = _drop_transient_issues(bucket, code)
        if dropped:
            logger.info(
                "drop stale pingyi issues fba=%s count=%s (query recovered)",
                code,
                dropped,
            )
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
        dropped = _drop_transient_issues(bucket, logistics_no)
        if dropped:
            logger.info(
                "drop stale longzhou issues logistics_no=%s count=%s (query recovered)",
                logistics_no,
                dropped,
            )
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


def _process_baosen_row(
    row: TableRow,
    *,
    client: LogisticsGatewayClient | None,
    store: TrackStateStore,
    bucket: list[ReportItem],
    logger: logging.Logger,
) -> tuple[int, bool, list[str]]:
    if client is None:
        line = _query_fail_line(
            row, ",".join(row.fba_codes) or row.invoice_no, "网关未配置"
        )
        logger.error(
            "skip baosen record=%s: gateway not configured (LOGISTICS_GATEWAY_*)",
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

    codes = row.fba_codes
    if not codes:
        return _report_missing_key(
            row, kind="baosen", store=store, bucket=bucket, logger=logger
        )

    ok_uids = notify_user_ids(row.owners, issue=False)
    issue_uids = notify_user_ids(row.owners, issue=True)
    logistics_joined = ",".join(row.logistics_nos)
    notified = 0
    query_ok = True
    issues: list[str] = []
    for code in codes:
        try:
            shipment = client.query_fba(code, platform="baosen")
        except Exception as exc:
            query_ok = False
            line = _query_fail_line(row, code, str(exc))
            issues.append(line)
            logger.exception("gateway baosen failed fba=%s: %s", code, exc)
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
        dropped = _drop_transient_issues(bucket, code)
        if dropped:
            logger.info(
                "drop stale baosen issues fba=%s count=%s (query recovered)",
                code,
                dropped,
            )
        logger.info(
            "track record=%s fba=%s events=%s latest=%s",
            row.record_id,
            code,
            len(shipment.events),
            shipment.track_status_name,
        )
        notified += _emit_events(
            row=row,
            shipment=shipment,
            shipment_key=code,
            display_code=code,
            kind="baosen",
            user_ids=ok_uids,
            store=store,
            bucket=bucket,
            logger=logger,
        )
    return notified, query_ok, issues


def _retry_baosen_query_errors(
    bucket: list[ReportItem],
    rows: list[TableRow],
    *,
    gateway: LogisticsGatewayClient | None,
    store: TrackStateStore,
    logger: logging.Logger,
    pause_sec: float = 3.0,
) -> dict[str, int]:
    """堡森 FBA 网关瞬时失败：全量结束后再串行重查 1 轮。"""
    stats = {"baosen_retry": 0, "baosen_recovered": 0}
    if gateway is None or not bucket:
        return stats

    by_fba: dict[str, TableRow] = {}
    for row in rows:
        if _carrier_kind(row.carrier) != "baosen":
            continue
        for code in row.fba_codes:
            key = (code or "").strip()
            if key:
                by_fba[key] = row

    targets: list[tuple[TableRow, str]] = []
    seen: set[str] = set()
    for it in bucket:
        if it.event_key != "query_error":
            continue
        code = (it.fba_code or it.shipment_key or "").strip()
        if not code or code not in by_fba or code in seen:
            continue
        seen.add(code)
        targets.append((by_fba[code], code))

    if not targets:
        return stats

    logger.info("baosen retry pass count=%s pause=%ss (serial)", len(targets), pause_sec)
    stats["baosen_retry"] = len(targets)

    for i, (row, code) in enumerate(targets):
        if i > 0 and pause_sec > 0:
            time.sleep(pause_sec)
        ok_uids = notify_user_ids(row.owners, issue=False)
        issue_uids = notify_user_ids(row.owners, issue=True)
        logistics_joined = ",".join(row.logistics_nos)
        try:
            shipment = gateway.query_fba(code, platform="baosen")
        except Exception as exc:
            logger.warning("baosen retry still failed fba=%s: %s", code, exc)
            continue

        bucket[:] = [
            it
            for it in bucket
            if not (it.event_key == "query_error" and it.shipment_key == code)
        ]
        stats["baosen_recovered"] += 1

        if shipment is None:
            line = _no_track_line(row, code)
            logger.info("baosen retry no track fba=%s record=%s", code, row.record_id)
            _collect_once(
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
            "baosen retry ok fba=%s events=%s latest=%s",
            code,
            len(shipment.events),
            shipment.track_status_name,
        )
        _emit_events(
            row=row,
            shipment=shipment,
            shipment_key=code,
            display_code=code,
            kind="baosen",
            user_ids=ok_uids,
            store=store,
            bucket=bucket,
            logger=logger,
        )
    return stats


def _process_meitong_row(
    row: TableRow,
    *,
    client: MeitongClient,
    store: TrackStateStore,
    bucket: list[ReportItem],
    logger: logging.Logger,
) -> tuple[int, bool, list[str]]:
    nos = row.logistics_nos
    if not nos:
        return _report_missing_key(
            row, kind="meitong", store=store, bucket=bucket, logger=logger
        )

    ok_uids = notify_user_ids(row.owners, issue=False)
    issue_uids = notify_user_ids(row.owners, issue=True)
    fba_joined = ",".join(row.fba_codes)
    notified = 0
    query_ok = True
    issues: list[str] = []
    for order_no in nos:
        try:
            shipment = client.get_track(order_no)
        except Exception as exc:
            query_ok = False
            line = _query_fail_line(row, order_no, str(exc))
            issues.append(line)
            logger.exception("meitong getTrackInfo failed order_no=%s: %s", order_no, exc)
            notified += _collect_once(
                shipment_key=order_no,
                event_key="query_error",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=fba_joined,
                logistics_no=order_no,
                detail=line,
                logger=logger,
            )
            continue
        if shipment is None:
            line = _no_track_line(row, order_no)
            issues.append(line)
            logger.warning("no track meitong order_no=%s record=%s", order_no, row.record_id)
            notified += _collect_once(
                shipment_key=order_no,
                event_key="no_track",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=fba_joined,
                logistics_no=order_no,
                detail=line,
                logger=logger,
            )
            continue
        dropped = _drop_transient_issues(bucket, order_no)
        if dropped:
            logger.info(
                "drop stale meitong issues order_no=%s count=%s (query recovered)",
                order_no,
                dropped,
            )
        logger.info(
            "track record=%s meitong=%s events=%s latest=%s",
            row.record_id,
            order_no,
            len(shipment.events),
            shipment.track_status_name,
        )
        notified += _emit_events(
            row=row,
            shipment=shipment,
            shipment_key=order_no,
            display_code=order_no,
            kind="meitong",
            user_ids=ok_uids,
            store=store,
            bucket=bucket,
            logger=logger,
        )
    return notified, query_ok, issues


def _retry_meitong_query_errors(
    bucket: list[ReportItem],
    rows: list[TableRow],
    *,
    meitong: MeitongClient | None,
    store: TrackStateStore,
    logger: logging.Logger,
    pause_sec: float = 1.0,
) -> dict[str, int]:
    stats = {"meitong_retry": 0, "meitong_recovered": 0}
    if meitong is None or not bucket:
        return stats

    by_no: dict[str, TableRow] = {}
    for row in rows:
        if _carrier_kind(row.carrier) != "meitong":
            continue
        for no in row.logistics_nos:
            key = (no or "").strip()
            if key:
                by_no[key] = row

    targets: list[tuple[TableRow, str]] = []
    seen: set[str] = set()
    for it in bucket:
        if it.event_key != "query_error":
            continue
        no = (it.logistics_no or it.shipment_key or "").strip()
        if not no or no not in by_no or no in seen:
            continue
        seen.add(no)
        targets.append((by_no[no], no))

    if not targets:
        return stats

    logger.info("meitong retry pass count=%s pause=%ss (serial)", len(targets), pause_sec)
    stats["meitong_retry"] = len(targets)

    for i, (row, order_no) in enumerate(targets):
        if i > 0 and pause_sec > 0:
            time.sleep(pause_sec)
        ok_uids = notify_user_ids(row.owners, issue=False)
        issue_uids = notify_user_ids(row.owners, issue=True)
        fba_joined = ",".join(row.fba_codes)
        try:
            shipment = meitong.get_track(order_no)
        except Exception as exc:
            logger.warning("meitong retry still failed order_no=%s: %s", order_no, exc)
            continue

        bucket[:] = [
            it
            for it in bucket
            if not (it.event_key == "query_error" and it.shipment_key == order_no)
        ]
        stats["meitong_recovered"] += 1

        if shipment is None:
            line = _no_track_line(row, order_no)
            logger.info("meitong retry no track order_no=%s record=%s", order_no, row.record_id)
            _collect_once(
                shipment_key=order_no,
                event_key="no_track",
                message=line,
                user_ids=issue_uids,
                store=store,
                bucket=bucket,
                row=row,
                fba_code=fba_joined,
                logistics_no=order_no,
                detail=line,
                logger=logger,
            )
            continue

        logger.info(
            "meitong retry ok order_no=%s events=%s latest=%s",
            order_no,
            len(shipment.events),
            shipment.track_status_name,
        )
        _emit_events(
            row=row,
            shipment=shipment,
            shipment_key=order_no,
            display_code=order_no,
            kind="meitong",
            user_ids=ok_uids,
            store=store,
            bucket=bucket,
            logger=logger,
        )
    return stats


def _retry_pingyi_query_errors(
    bucket: list[ReportItem],
    rows: list[TableRow],
    *,
    pingyi: PingyiClient | None,
    store: TrackStateStore,
    logger: logging.Logger,
    pause_sec: float = 1.0,
) -> dict[str, int]:
    """
    平谊瞬时超时：全量结束后对 query_error 再串行重查 1 轮。
    成功则去掉 query_error 并写节点；仍失败则保留问题行。
    """
    stats = {"pingyi_retry": 0, "pingyi_recovered": 0}
    if pingyi is None or not bucket:
        return stats

    by_fba: dict[str, TableRow] = {}
    for row in rows:
        if _carrier_kind(row.carrier) != "pingyi":
            continue
        for code in row.fba_codes:
            key = (code or "").strip()
            if key:
                by_fba[key] = row

    targets: list[tuple[TableRow, str]] = []
    seen: set[str] = set()
    for it in bucket:
        if it.event_key != "query_error":
            continue
        code = (it.fba_code or it.shipment_key or "").strip()
        if not code or code not in by_fba or code in seen:
            continue
        seen.add(code)
        targets.append((by_fba[code], code))

    if not targets:
        return stats

    logger.info(
        "pingyi retry pass count=%s pause=%ss (serial)",
        len(targets),
        pause_sec,
    )
    stats["pingyi_retry"] = len(targets)

    for i, (row, code) in enumerate(targets):
        if i > 0 and pause_sec > 0:
            time.sleep(pause_sec)
        ok_uids = notify_user_ids(row.owners, issue=False)
        issue_uids = notify_user_ids(row.owners, issue=True)
        logistics_joined = ",".join(row.logistics_nos)
        try:
            shipment = pingyi.get_track(code)
        except Exception as exc:
            logger.warning("pingyi retry still failed fba=%s: %s", code, exc)
            continue

        bucket[:] = [
            it
            for it in bucket
            if not (it.event_key == "query_error" and it.shipment_key == code)
        ]
        stats["pingyi_recovered"] += 1

        if shipment is None:
            line = _no_track_line(row, code)
            logger.info("pingyi retry no track fba=%s record=%s", code, row.record_id)
            _collect_once(
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
            "pingyi retry ok fba=%s events=%s status=%s",
            code,
            len(shipment.events),
            shipment.track_status_name or shipment.track_status,
        )
        _emit_events(
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
    return stats


def _process_row(
    row: TableRow,
    *,
    pingyi: PingyiClient | None,
    gateway: LogisticsGatewayClient | None,
    meitong: MeitongClient | None,
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
    if kind == "baosen":
        return _process_baosen_row(
            row, client=gateway, store=store, bucket=bucket, logger=logger
        )
    if kind == "meitong":
        if meitong is None:
            line = _query_fail_line(
                row, ",".join(row.logistics_nos) or row.invoice_no, "美通客户端未配置"
            )
            logger.error("skip meitong record=%s: meitong client missing", row.record_id)
            return 0, False, [line]
        return _process_meitong_row(
            row, client=meitong, store=store, bucket=bucket, logger=logger
        )
    logger.warning(
        "skip unknown carrier=%s record=%s invoice=%s",
        row.carrier,
        row.record_id,
        row.invoice_no,
    )
    return 0, False, []


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
    # 有日期则所有人只留日期行；全无日期不入物流人员 Excel，柯鹏翔仍收
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
            view = filter_report_item_for_user(
                it, user_id, full_detail_user_id=KEPENGXIANG_USER_ID
            )
            if view is None:
                logger.info(
                    "omit undated-only detail for logistics user=%s shipment=%s",
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
        # mark 原始 item；物流侧滤掉的无日期节点仍随柯鹏翔落盘一并 mark
        markable = [
            it
            for it in items
            if it.user_ids and (it.shipment_key, it.event_key) in delivered_recipients
        ]
        if markable:
            _mark_and_clear_items(store, markable)
        return stats

    notifier = None
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
            timeout_sec=config.pingyi_timeout_sec,
            retries=config.pingyi_retries,
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
    meitong: MeitongClient | None = None
    if config.meitong_username and config.meitong_password:
        meitong = MeitongClient(
            config.meitong_username,
            config.meitong_password,
            base_url=config.meitong_base_url,
            timeout_sec=config.meitong_timeout_sec,
            retries=config.meitong_retries,
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
        "pingyi_retry": 0,
        "pingyi_recovered": 0,
        "meitong_retry": 0,
        "meitong_recovered": 0,
        "pending_resumed": 0,
        "excel_rows": 0,
        "excel_files": 0,
        "excel_sent": 0,
        "excel_failed": 0,
    }
    issue_lines: list[str] = []
    try:
        # pending 只做同日崩溃恢复入库，不提前发；全量查完后统一发一次
        if not dry_run:
            today_ymd = datetime.now(tz=CST).strftime("%Y-%m-%d")
            discarded = store.discard_pending_if_stale(today_ymd)
            if discarded:
                logger.info(
                    "discard stale pending count=%s (not same day as %s); full re-query",
                    discarded,
                    today_ymd,
                )
            drop_pairs: list[tuple[str, str]] = []
            for raw in store.load_pending_items():
                item = _item_from_dict(raw)
                keys = item.keys_to_mark()
                if keys and all(store.has_event(item.shipment_key, ek) for ek in keys):
                    drop_pairs.append((item.shipment_key, item.event_key))
                    continue
                bucket.append(item)
            if drop_pairs:
                store.clear_pending_for(drop_pairs)
                logger.info("drop already-notified pending count=%s", len(drop_pairs))
            if bucket:
                stats["pending_resumed"] = len(bucket)
                logger.info(
                    "seed bucket from same-day checkpoint count=%s (send only after full query)",
                    len(bucket),
                )

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
        # 本轮新查出的结果按 key 覆盖 checkpoint 旧项，避免重复行
        seen_keys: set[tuple[str, str]] = {
            (it.shipment_key, it.event_key) for it in bucket if it.shipment_key and it.event_key
        }

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
                meitong=meitong,
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
                if kind in {"pingyi", "baosen"} and not row.fba_codes:
                    stats["missing_key"] += 1
                elif kind in {"longzhou", "meitong"} and not row.logistics_nos:
                    stats["missing_key"] += 1
                stats["processed"] += 1
                stats["collected"] += collected
                for it in local:
                    k = (it.shipment_key, it.event_key)
                    if k in seen_keys:
                        # 新结果覆盖 checkpoint 同 key 项
                        bucket[:] = [
                            x
                            for x in bucket
                            if (x.shipment_key, x.event_key) != k
                        ]
                    else:
                        seen_keys.add(k)
                    bucket.append(it)
                if issues:
                    stats["query_issues"] += len(issues)
                    issue_lines.extend(issues)
                # 只落盘，不发送
                if not dry_run:
                    _checkpoint_bucket(store, bucket)

        # 瞬时失败：全量结束后再串行重查 1 轮 query_error（龙舟 / 平谊）
        retry_stats = _retry_longzhou_query_errors(
            bucket,
            pending,
            gateway=gateway,
            store=store,
            logger=logger,
            pause_sec=3.0,
        )
        stats.update(retry_stats)
        baosen_retry = _retry_baosen_query_errors(
            bucket,
            pending,
            gateway=gateway,
            store=store,
            logger=logger,
            pause_sec=3.0,
        )
        stats.update(baosen_retry)
        py_retry = _retry_pingyi_query_errors(
            bucket,
            pending,
            pingyi=pingyi,
            store=store,
            logger=logger,
            pause_sec=1.0,
        )
        stats.update(py_retry)
        mt_retry = _retry_meitong_query_errors(
            bucket,
            pending,
            meitong=meitong,
            store=store,
            logger=logger,
            pause_sec=1.0,
        )
        stats.update(mt_retry)
        # 重试后问题行可能变少，issue 摘要以 bucket 为准
        if (
            retry_stats.get("gateway_recovered")
            or py_retry.get("pingyi_recovered")
            or mt_retry.get("meitong_recovered")
        ):
            issue_lines = [
                it.detail or it.message
                for it in bucket
                if it.event_key
                in {"query_error", "no_track", "missing_fba", "missing_logistics_no", "gateway_missing"}
            ]
            stats["query_issues"] = len(issue_lines)
        if not dry_run:
            _checkpoint_bucket(store, bucket)

        # 过滤本轮查询过程中已 mark 的（理论上不应有）；再统一发送一次
        final_items: list[ReportItem] = []
        for it in bucket:
            keys = it.keys_to_mark()
            if keys and all(store.has_event(it.shipment_key, ek) for ek in keys):
                continue
            final_items.append(it)

        logger.info(
            "query complete candidates=%s processed=%s bucket=%s final_send=%s",
            stats["candidates"],
            stats["processed"],
            len(bucket),
            len(final_items),
        )
        deliver = _deliver_excel_reports(
            final_items,
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
