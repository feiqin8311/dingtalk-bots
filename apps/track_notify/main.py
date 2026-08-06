#!/usr/bin/env python
from __future__ import annotations

import argparse
import fcntl
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "shared").is_dir():
            return path
    return start


ROOT_DIR = _find_repo_root(Path(__file__).resolve().parent)
APP_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import os

from dedup_store import TrackStateStore
from milestones import match_milestone
from pingyi_client import PingyiClient
from runner import run_once
from settings import load_config_from_env
from shared.logging import setup_logger


def _acquire_once_lock(state_dir: Path):
    """同一 state_dir 同时只允许一个 --once；失败返回 None。"""
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "run_once.lock"
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} at={datetime.now(tz=CST).isoformat()}\n")
    fh.flush()
    return fh

CST = timezone(timedelta(hours=8))
# Mon=0 ... Sun=6；周一、周三 00:00（AGL 慢，夜里慢慢查）
SCHEDULE_WEEKDAYS = frozenset({0, 2})
SCHEDULE_HOUR = 0
SCHEDULE_MINUTE = 0


def query_numbers(numbers: list[str], *, dry_run: bool) -> int:
    logger = setup_logger("%(asctime)s %(name)s %(levelname)-8s %(message)s", "INFO")
    config = load_config_from_env()
    client = PingyiClient(
        config.pingyi_app_token,
        config.pingyi_app_key,
        base_url=config.pingyi_base_url,
    )
    store = TrackStateStore(config.state_db_path)
    notified = 0
    try:
        for number in numbers:
            number = number.strip()
            if not number:
                continue
            shipment = client.get_track(number)
            if shipment is None:
                logger.warning("no track for %s", number)
                continue
            shipment_key = shipment.reference_no or shipment.tracking_no or number
            logger.info(
                "track %s -> %s status=%s events=%s",
                shipment_key,
                shipment.tracking_no,
                shipment.track_status_name or shipment.track_status,
                len(shipment.events),
            )
            for event in shipment.events:
                mkey = match_milestone(event, "pingyi")
                if not mkey:
                    continue
                line = shipment.format_notify_line(event, fba_code=number)
                if dry_run:
                    already = store.has_event(number, mkey)
                    logger.info(
                        "[dry-run]%s %s (%s)",
                        " skip" if already else "",
                        line,
                        mkey,
                    )
                    continue
                if store.mark_event(number, mkey, line):
                    logger.info("NEW %s (%s)", line, mkey)
                    notified += 1
    finally:
        store.close()
    return notified


def _next_run_at(now: datetime | None = None) -> datetime:
    now = now or datetime.now(tz=CST)
    candidate = now.replace(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, second=0, microsecond=0)
    for offset in range(0, 8):
        day = candidate + timedelta(days=offset)
        if day.weekday() not in SCHEDULE_WEEKDAYS:
            continue
        if day > now:
            return day
    return candidate + timedelta(days=7)


def run_daemon(*, dry_run: bool = False) -> None:
    logger = setup_logger("%(asctime)s %(name)s %(levelname)-8s %(message)s", "INFO")
    logger.info(
        "track_notify daemon started; schedule Mon/Wed %02d:%02d Asia/Shanghai dry_run=%s",
        SCHEDULE_HOUR,
        SCHEDULE_MINUTE,
        dry_run,
    )
    while True:
        target = _next_run_at()
        sleep_sec = max(1.0, (target - datetime.now(tz=CST)).total_seconds())
        logger.info("next run at %s (sleep %.0fs)", target.isoformat(timespec="seconds"), sleep_sec)
        # wake periodically so container stop is responsive
        deadline = time.monotonic() + sleep_sec
        while time.monotonic() < deadline:
            time.sleep(min(60.0, deadline - time.monotonic()))
        try:
            config = load_config_from_env()
            stats = run_once(config, dry_run=dry_run)
            logger.info("scheduled run done %s", stats)
        except Exception:
            logger.exception("scheduled run failed")
        # avoid double-fire if clock jumps backward within the same minute
        time.sleep(61)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Track notify: Mon/Wed job or manual FBA query"
    )
    parser.add_argument(
        "numbers",
        nargs="*",
        help="optional manual FBA/tracking numbers",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="read dingtalk table, query tracks, emit new milestone nodes to excel",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="stay running; run on Mon/Wed 00:00 Asia/Shanghai",
    )
    parser.add_argument("--dry-run", action="store_true", help="do not write state or notify")
    args = parser.parse_args(argv)

    if args.daemon:
        run_daemon(dry_run=args.dry_run)
        return 0

    if args.once:
        logger = setup_logger("%(asctime)s %(name)s %(levelname)-8s %(message)s", "INFO")
        config = load_config_from_env()
        lock_fh = None if args.dry_run else _acquire_once_lock(config.state_dir)
        if not args.dry_run and lock_fh is None:
            logger.error("another --once is already running (lock %s)", config.state_dir / "run_once.lock")
            return 2
        try:
            stats = run_once(config, dry_run=args.dry_run)
            print(stats)
            return 0
        finally:
            if lock_fh is not None:
                try:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                finally:
                    lock_fh.close()

    if not args.numbers:
        parser.error("provide --daemon, --once, or at least one FBA/tracking number")
    query_numbers(args.numbers, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
