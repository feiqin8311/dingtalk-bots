"""Persistence for active and queued non-warehouse packing jobs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PendingLogistics:
    packing_result_path: Path
    merge_dir: Path
    shipment_path: Path
    stage: str  # confirm | select_ops
    updated_at: float
    logistics_channel: str = ""
    store_name: str = ""
    country: str = ""
    amazon_template_path: Optional[Path] = None


@dataclass
class PendingOpsJob:
    logistics_user_id: str
    logistics_name_hint: str
    packing_result_path: Path
    merge_dir: Path
    shipment_path: Path
    updated_at: float
    logistics_channel: str = ""
    store_name: str = ""
    country: str = ""
    amazon_template_path: Optional[Path] = None


def load_pending_state(path: Path, logistics_ttl: int, ops_ttl: int):
    if not path.is_file():
        return {}, {}, {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}, {}, {}
    logistics_cutoff = time.time() - logistics_ttl
    ops_cutoff = time.time() - ops_ttl
    logistics: dict[str, PendingLogistics] = {}
    for uid, item in (raw.get("logistics") or {}).items():
        if not uid or not isinstance(item, dict):
            continue
        pending = _logistics_from_dict(item)
        if pending is None or pending.updated_at < logistics_cutoff:
            continue
        if not pending.packing_result_path.is_file() or not pending.shipment_path.is_file():
            continue
        logistics[str(uid)] = pending
    ops: dict[str, PendingOpsJob] = {}
    for uid, item in (raw.get("ops") or {}).items():
        if not uid or not isinstance(item, dict):
            continue
        job = _ops_from_dict(item)
        if job is None or job.updated_at < ops_cutoff:
            continue
        if not job.packing_result_path.is_file():
            continue
        # shipment 可与 packing 同文件（运营自助）；缺失则用 packing 兜底
        if not job.shipment_path.is_file():
            job.shipment_path = job.packing_result_path
        ops[str(uid)] = job
    ops_queue: dict[str, list[PendingOpsJob]] = {}
    for uid, items in (raw.get("ops_queue") or {}).items():
        if not uid or not isinstance(items, list):
            continue
        kept: list[PendingOpsJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            job = _ops_from_dict(item)
            if job is None or job.updated_at < ops_cutoff:
                continue
            if not job.packing_result_path.is_file():
                continue
            if not job.shipment_path.is_file():
                job.shipment_path = job.packing_result_path
            kept.append(job)
        if kept:
            ops_queue[str(uid)] = kept
    return logistics, ops, ops_queue


def save_pending_state(path: Path, logistics, ops, ops_queue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "logistics": {
            uid: {
                "packing_result_path": str(p.packing_result_path),
                "merge_dir": str(p.merge_dir),
                "shipment_path": str(p.shipment_path),
                "stage": p.stage,
                "updated_at": p.updated_at,
                "logistics_channel": p.logistics_channel,
                "store_name": p.store_name,
                "country": p.country,
                "amazon_template_path": str(p.amazon_template_path)
                if p.amazon_template_path
                else "",
            }
            for uid, p in logistics.items()
        },
        "ops": {
            uid: {
                "logistics_user_id": j.logistics_user_id,
                "logistics_name_hint": j.logistics_name_hint,
                "packing_result_path": str(j.packing_result_path),
                "merge_dir": str(j.merge_dir),
                "shipment_path": str(j.shipment_path),
                "updated_at": j.updated_at,
                "logistics_channel": j.logistics_channel,
                "store_name": j.store_name,
                "country": j.country,
                "amazon_template_path": str(j.amazon_template_path)
                if j.amazon_template_path
                else "",
            }
            for uid, j in ops.items()
        },
        "ops_queue": {
            uid: [
                {
                    "logistics_user_id": j.logistics_user_id,
                    "logistics_name_hint": j.logistics_name_hint,
                    "packing_result_path": str(j.packing_result_path),
                    "merge_dir": str(j.merge_dir),
                    "shipment_path": str(j.shipment_path),
                    "updated_at": j.updated_at,
                    "logistics_channel": j.logistics_channel,
                    "store_name": j.store_name,
                    "country": j.country,
                    "amazon_template_path": str(j.amazon_template_path)
                    if j.amazon_template_path
                    else "",
                }
                for j in jobs
            ]
            for uid, jobs in ops_queue.items()
        },
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


def _logistics_from_dict(item: dict) -> Optional[PendingLogistics]:
    try:
        stage = str(item.get("stage") or "confirm")
        if stage not in {"confirm", "select_ops"}:
            stage = "confirm"
        tpl = str(item.get("amazon_template_path") or "").strip()
        return PendingLogistics(
            packing_result_path=Path(str(item["packing_result_path"])),
            merge_dir=Path(str(item["merge_dir"])),
            shipment_path=Path(str(item["shipment_path"])),
            stage=stage,
            updated_at=float(item.get("updated_at") or 0),
            logistics_channel=str(item.get("logistics_channel") or ""),
            store_name=str(item.get("store_name") or ""),
            country=str(item.get("country") or ""),
            amazon_template_path=Path(tpl) if tpl else None,
        )
    except Exception:
        return None

def _ops_from_dict(item: dict) -> Optional[PendingOpsJob]:
    try:
        tpl = str(item.get("amazon_template_path") or "").strip()
        return PendingOpsJob(
            logistics_user_id=str(item.get("logistics_user_id") or ""),
            logistics_name_hint=str(item.get("logistics_name_hint") or ""),
            packing_result_path=Path(str(item["packing_result_path"])),
            merge_dir=Path(str(item["merge_dir"])),
            shipment_path=Path(str(item["shipment_path"])),
            updated_at=float(item.get("updated_at") or 0),
            logistics_channel=str(item.get("logistics_channel") or ""),
            store_name=str(item.get("store_name") or ""),
            country=str(item.get("country") or ""),
            amazon_template_path=Path(tpl) if tpl else None,
        )
    except Exception:
        return None
