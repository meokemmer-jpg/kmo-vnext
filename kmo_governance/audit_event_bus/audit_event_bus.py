# [CRUX-MK]
"""Audit-Event-Bus (Welle-14 Phase-9.1).

Lymphatic-System-Pattern: peripher gesammelte Wahrnehmungs-Events zentral aggregiert
mit Retention-Policy (TTL + Max-Size).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class AuditEventLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class AuditEvent:
    """Immutable Audit-Event.

    Pre: source non-empty, level valid, payload is dict.
    Post: event_id is unique (timestamp + source + counter).
    """

    event_id: str
    source: str
    level: AuditEventLevel
    payload: tuple  # tuple of (key, value) pairs (frozen-dict equivalent)
    timestamp: float

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id required")
        if not self.source:
            raise ValueError("source required")
        if not isinstance(self.level, AuditEventLevel):
            raise TypeError("level must be AuditEventLevel")

    def get_payload_dict(self) -> dict:
        return dict(self.payload)


@dataclass(frozen=True)
class AuditQuery:
    """Frozen-Query-Spec fuer event-search."""

    start_ts: Optional[float] = None
    end_ts: Optional[float] = None
    levels: tuple = ()  # tuple of AuditEventLevel
    sources: tuple = ()
    payload_contains: tuple = ()  # tuple of (key, value) pairs

    def matches(self, event: AuditEvent) -> bool:
        if self.start_ts is not None and event.timestamp < self.start_ts:
            return False
        if self.end_ts is not None and event.timestamp > self.end_ts:
            return False
        if self.levels and event.level not in self.levels:
            return False
        if self.sources and event.source not in self.sources:
            return False
        if self.payload_contains:
            payload = event.get_payload_dict()
            for k, v in self.payload_contains:
                if payload.get(k) != v:
                    return False
        return True


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention spec: TTL + max_size."""

    ttl_s: float = 3600.0  # 1 hour default
    max_size: int = 10000

    def __post_init__(self) -> None:
        if self.ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        if self.max_size <= 0:
            raise ValueError("max_size must be > 0")


class AuditEventBus:
    """Central event-bus mit retention + pub/sub.

    Pre: retention is RetentionPolicy.
    Post: thread-safe; events older than ttl_s removed via prune_expired();
          deque max_size enforced via maxlen.
    """

    def __init__(self, retention: Optional[RetentionPolicy] = None) -> None:
        self.retention = retention or RetentionPolicy()
        self._events: deque[AuditEvent] = deque(maxlen=self.retention.max_size)
        self._subscribers: dict[str, Callable[[AuditEvent], None]] = {}
        self._counter: int = 0
        self._lock = threading.RLock()

    def _next_event_id(self, source: str) -> str:
        with self._lock:
            self._counter += 1
            return f"{source}-{int(time.time() * 1000)}-{self._counter}"

    def publish(
        self,
        source: str,
        level: AuditEventLevel,
        payload: dict,
    ) -> AuditEvent:
        """Publish event. Auto-generated event_id + timestamp."""
        if not source:
            raise ValueError("source required")
        event = AuditEvent(
            event_id=self._next_event_id(source),
            source=source,
            level=level,
            payload=tuple(sorted(payload.items())),
            timestamp=time.time(),
        )
        with self._lock:
            self._events.append(event)
            subscribers = list(self._subscribers.values())
        # Notify outside lock to avoid deadlock
        for cb in subscribers:
            try:
                cb(event)
            except Exception:
                pass  # subscriber-failure isolated
        return event

    def subscribe(
        self,
        subscription_id: str,
        callback: Callable[[AuditEvent], None],
    ) -> None:
        if not subscription_id:
            raise ValueError("subscription_id required")
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            self._subscribers[subscription_id] = callback

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            self._subscribers.pop(subscription_id, None)

    def query(self, q: AuditQuery) -> list[AuditEvent]:
        with self._lock:
            return [e for e in self._events if q.matches(e)]

    def count(self) -> int:
        with self._lock:
            return len(self._events)

    def prune_expired(self) -> int:
        """Remove events older than retention.ttl_s. Returns count removed."""
        cutoff = time.time() - self.retention.ttl_s
        with self._lock:
            initial = len(self._events)
            self._events = deque(
                (e for e in self._events if e.timestamp >= cutoff),
                maxlen=self.retention.max_size,
            )
            return initial - len(self._events)


# CRUX-MK
