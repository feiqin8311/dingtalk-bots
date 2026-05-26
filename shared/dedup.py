from __future__ import annotations

import time


class MessageDeduplicator:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._seen_at: dict[str, float] = {}

    def seen(self, message_key: str) -> bool:
        now = time.time()
        expired_before = now - self.ttl_seconds
        self._seen_at = {
            key: timestamp for key, timestamp in self._seen_at.items() if timestamp >= expired_before
        }
        if message_key in self._seen_at:
            return True
        self._seen_at[message_key] = now
        return False

