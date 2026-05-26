#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lightweight runtime state for DingTalk CP Bot."""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple


def normalize_shipment_sns(shipment_sns: List[str]) -> List[str]:
    return sorted({str(sn).strip().upper() for sn in shipment_sns if str(sn).strip()})


class InMemoryRuntimeState:
    """Process-local deduplication and shipment locks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._message_expires_at: Dict[str, float] = {}
        self._shipment_locks: Dict[str, Tuple[str, float]] = {}

    def _cleanup_expired_locked(self, now_ts: float) -> None:
        for message_id, expires_at in list(self._message_expires_at.items()):
            if expires_at <= now_ts:
                self._message_expires_at.pop(message_id, None)
        for shipment_sn, (_, expires_at) in list(self._shipment_locks.items()):
            if expires_at <= now_ts:
                self._shipment_locks.pop(shipment_sn, None)

    def register_message(self, message_id: str, ttl_sec: int) -> bool:
        now_ts = time.time()
        key = str(message_id or "").strip()
        if not key:
            return True
        with self._lock:
            self._cleanup_expired_locked(now_ts)
            expires_at = self._message_expires_at.get(key)
            if expires_at and expires_at > now_ts:
                return False
            self._message_expires_at[key] = now_ts + ttl_sec
            return True

    def acquire_shipment_locks(
        self,
        shipment_sns: List[str],
        holder_id: str,
        ttl_sec: int,
    ) -> Tuple[bool, Optional[str]]:
        keys = normalize_shipment_sns(shipment_sns)
        if not keys:
            return True, None
        now_ts = time.time()
        holder = str(holder_id or "").strip()
        with self._lock:
            self._cleanup_expired_locked(now_ts)
            for key in keys:
                existing = self._shipment_locks.get(key)
                if existing and existing[0] != holder and existing[1] > now_ts:
                    return False, key
            expires_at = now_ts + ttl_sec
            for key in keys:
                self._shipment_locks[key] = (holder, expires_at)
            return True, None

    def release_shipment_locks(self, shipment_sns: List[str], holder_id: str) -> None:
        keys = normalize_shipment_sns(shipment_sns)
        holder = str(holder_id or "").strip()
        if not keys:
            return
        with self._lock:
            for key in keys:
                existing = self._shipment_locks.get(key)
                if existing and existing[0] == holder:
                    self._shipment_locks.pop(key, None)
