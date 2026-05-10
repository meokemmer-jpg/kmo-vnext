from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable


DEFAULT_TTL_SECONDS = 604800
DEFAULT_MAX_ENTRIES = 10000


@dataclass(frozen=True)
class ManuscriptDedupResult:
    author_id: str
    manuscript_topic: str
    payload_hash: str
    key: str
    duplicate: bool
    registered_at: float
    expires_at: float


@dataclass(frozen=True)
class _Entry:
    registered_at: float
    expires_at: float


class GraphityDedupEngine:
    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")

        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._time_fn = time_fn or time.time
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def check_and_register(
        self,
        author_id: str,
        topic: str,
        payload: bytes,
    ) -> ManuscriptDedupResult:
        self._validate(author_id, topic, payload)

        now = self._time_fn()
        payload_hash = hashlib.sha256(payload).hexdigest()
        key = self._make_key(author_id, topic, payload_hash)

        with self._lock:
            self._sweep_expired(now)

            existing = self._entries.get(key)
            if existing is not None:
                self._entries.move_to_end(key)
                return ManuscriptDedupResult(
                    author_id=author_id,
                    manuscript_topic=topic,
                    payload_hash=payload_hash,
                    key=key,
                    duplicate=True,
                    registered_at=existing.registered_at,
                    expires_at=existing.expires_at,
                )

            entry = _Entry(registered_at=now, expires_at=now + self.ttl_seconds)
            self._entries[key] = entry
            self._evict_lru()

            return ManuscriptDedupResult(
                author_id=author_id,
                manuscript_topic=topic,
                payload_hash=payload_hash,
                key=key,
                duplicate=False,
                registered_at=entry.registered_at,
                expires_at=entry.expires_at,
            )

    def _sweep_expired(self, now: float | None = None) -> int:
        current = self._time_fn() if now is None else now
        removed = 0

        with self._lock:
            expired_keys = [
                key for key, entry in self._entries.items() if entry.expires_at <= current
            ]
            for key in expired_keys:
                del self._entries[key]
                removed += 1

        return removed

    def active_count(self) -> int:
        with self._lock:
            self._sweep_expired()
            return len(self._entries)

    def _evict_lru(self) -> None:
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    @staticmethod
    def _make_key(author_id: str, manuscript_topic: str, payload_hash: str) -> str:
        source = "\x1f".join((author_id, manuscript_topic, payload_hash))
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate(author_id: str, topic: str, payload: bytes) -> None:
        if isinstance(payload, str):
            raise TypeError("payload must be bytes, not str")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes-like")
        if not isinstance(author_id, str):
            raise TypeError("author_id must be str")
        if not isinstance(topic, str):
            raise TypeError("topic must be str")
        if not author_id.strip():
            raise ValueError("author_id must not be empty")
        if not topic.strip():
            raise ValueError("topic must not be empty")
        if len(payload) == 0:
            raise ValueError("payload must not be empty")
