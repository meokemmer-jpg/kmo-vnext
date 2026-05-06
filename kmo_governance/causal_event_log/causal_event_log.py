# [CRUX-MK]
"""Causal Event Log (Welle-16 Phase-11.1).

Vector-Clock-Pattern fuer causal-ordering ueber distributed Nodes.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional


class VectorClock:
    """Lamport-Vector-Clock per node.

    Pre: node_id non-empty.
    Post: thread-safe; tick() increments local; merge() takes max per-component.
    """

    def __init__(self, node_id: str) -> None:
        if not node_id:
            raise ValueError("node_id required")
        self.node_id = node_id
        self._clock: dict[str, int] = {node_id: 0}
        self._lock = threading.RLock()

    def tick(self) -> dict[str, int]:
        """Increment local clock. Returns snapshot."""
        with self._lock:
            self._clock[self.node_id] += 1
            return dict(self._clock)

    def merge(self, other_clock: dict[str, int]) -> dict[str, int]:
        """Merge other clock (max per-component) + tick local. Returns snapshot."""
        with self._lock:
            for node, value in other_clock.items():
                self._clock[node] = max(self._clock.get(node, 0), value)
            self._clock[self.node_id] += 1
            return dict(self._clock)

    def get_snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._clock)

    @staticmethod
    def compare(a: dict[str, int], b: dict[str, int]) -> str:
        """Compare two clocks. Returns 'before' / 'after' / 'concurrent' / 'equal'."""
        keys = set(a) | set(b)
        a_lt = False
        b_lt = False
        for k in keys:
            av = a.get(k, 0)
            bv = b.get(k, 0)
            if av < bv:
                a_lt = True
            elif av > bv:
                b_lt = True
        if not a_lt and not b_lt:
            return "equal"
        if a_lt and not b_lt:
            return "before"  # a happens-before b
        if b_lt and not a_lt:
            return "after"
        return "concurrent"


@dataclass(frozen=True)
class CausalEvent:
    """Event with vector-clock for causal-ordering."""

    event_id: str
    node_id: str
    payload: tuple  # tuple of (k, v) pairs
    clock_snapshot: tuple  # tuple of (node, value) pairs (frozen-dict equivalent)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id required")
        if not self.node_id:
            raise ValueError("node_id required")

    def get_clock(self) -> dict:
        return dict(self.clock_snapshot)

    def get_payload(self) -> dict:
        return dict(self.payload)


class CausalEventLog:
    """Append-only log with causal-order tracking.

    Pre: node_id non-empty.
    Post: thread-safe; events ordered by vector-clock.
    """

    def __init__(self, node_id: str) -> None:
        if not node_id:
            raise ValueError("node_id required")
        self.node_id = node_id
        self.clock = VectorClock(node_id)
        self._events: list[CausalEvent] = []
        self._counter: int = 0
        self._lock = threading.RLock()

    def _next_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"{self.node_id}-{self._counter}"

    def append_local(self, payload: dict) -> CausalEvent:
        """Local event: tick + record."""
        clock = self.clock.tick()
        event = CausalEvent(
            event_id=self._next_id(),
            node_id=self.node_id,
            payload=tuple(sorted(payload.items())),
            clock_snapshot=tuple(sorted(clock.items())),
        )
        with self._lock:
            self._events.append(event)
        return event

    def receive_remote(
        self, remote_clock: dict[str, int], payload: dict, remote_node_id: str
    ) -> CausalEvent:
        """Receive event from remote node: merge clock + record."""
        clock = self.clock.merge(remote_clock)
        event = CausalEvent(
            event_id=self._next_id(),
            node_id=remote_node_id,
            payload=tuple(sorted(payload.items())),
            clock_snapshot=tuple(sorted(clock.items())),
        )
        with self._lock:
            self._events.append(event)
        return event

    def get_events(self) -> list[CausalEvent]:
        with self._lock:
            return list(self._events)

    def get_causal_order(self) -> list[CausalEvent]:
        """Returns events sorted by vector-clock (best-effort linearization)."""
        with self._lock:
            return sorted(
                self._events,
                key=lambda e: sum(v for _, v in e.clock_snapshot),
            )


# CRUX-MK
