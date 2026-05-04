# [CRUX-MK]
"""Observability-Layer SKELETON (Welle-10 Phase-6.1).

Klassen:
  - Counter: monoton steigender Counter (events, errors)
  - Gauge: aktueller Wert (active_connections, memory_mb)
  - Histogram: Bucket-Verteilung (latencies)
  - MetricsRegistry: zentrale Aggregation
  - Span: Tracing-Span (start/end + tags + child-spans)
  - Tracer: Span-Stack-Tracking (per-Thread)
  - HealthCheckRegistry: Per-Modul-Health-Status (UP/DEGRADED/DOWN)

Prometheus-kompatibles Export-Format via to_prometheus().
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class HealthStatus(Enum):
    """Health-Status pro Komponente."""

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
class Counter:
    """Monoton steigender Counter mit thread-safety.

    Pre: name non-empty.
    Post: inc() ist race-safe, never decreases.
    """

    def __init__(self, name: str, labels: Optional[dict[str, str]] = None) -> None:
        if not name:
            raise ValueError("name required")
        self.name = name
        self.labels = labels or {}
        self._value = 0
        self._lock = threading.Lock()

    def inc(self, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("counter inc amount must be >= 0 (use Gauge for decreases)")
        with self._lock:
            self._value += amount

    def get(self) -> int:
        with self._lock:
            return self._value

    def to_prometheus(self) -> str:
        labels_str = ""
        if self.labels:
            labels_str = "{" + ",".join(f'{k}="{v}"' for k, v in self.labels.items()) + "}"
        return f"{self.name}{labels_str} {self._value}"


class Gauge:
    """Bidirectional gauge (kann fallen + steigen)."""

    def __init__(self, name: str, labels: Optional[dict[str, str]] = None) -> None:
        if not name:
            raise ValueError("name required")
        self.name = name
        self.labels = labels or {}
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = float(value)

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += float(amount)

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= float(amount)

    def get(self) -> float:
        with self._lock:
            return self._value


class Histogram:
    """Bucket-Verteilung (default: 0.001/0.01/0.1/1/10 sec buckets)."""

    DEFAULT_BUCKETS = (0.001, 0.01, 0.1, 1.0, 10.0)

    def __init__(
        self,
        name: str,
        buckets: Optional[tuple] = None,
    ) -> None:
        if not name:
            raise ValueError("name required")
        self.name = name
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._counts = {b: 0 for b in self.buckets}
        self._counts[float("inf")] = 0
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for b in self.buckets:
                if value <= b:
                    self._counts[b] += 1
            self._counts[float("inf")] += 1

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "count": self._count,
                "sum": self._sum,
                "buckets": dict(self._counts),
                "mean": self._sum / self._count if self._count > 0 else 0.0,
            }


class MetricsRegistry:
    """Zentrale Aggregation aller Metrics."""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, labels: Optional[dict] = None) -> Counter:
        with self._lock:
            key = f"{name}:{sorted((labels or {}).items())}"
            if key not in self._counters:
                self._counters[key] = Counter(name, labels)
            return self._counters[key]

    def gauge(self, name: str, labels: Optional[dict] = None) -> Gauge:
        with self._lock:
            key = f"{name}:{sorted((labels or {}).items())}"
            if key not in self._gauges:
                self._gauges[key] = Gauge(name, labels)
            return self._gauges[key]

    def histogram(self, name: str, buckets: Optional[tuple] = None) -> Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, buckets)
            return self._histograms[name]

    def to_prometheus(self) -> str:
        lines = []
        with self._lock:
            for c in self._counters.values():
                lines.append(c.to_prometheus())
            for g in self._gauges.values():
                lines.append(f"{g.name} {g.get()}")
            for h in self._histograms.values():
                stats = h.get_stats()
                lines.append(f"{h.name}_count {stats['count']}")
                lines.append(f"{h.name}_sum {stats['sum']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------
@dataclass
class Span:
    """Tracing-Span (start/end + parent + children)."""

    name: str
    trace_id: str
    span_id: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    parent_id: Optional[str] = None
    tags: dict[str, str] = field(default_factory=dict)
    children: list = field(default_factory=list)

    def end(self) -> None:
        if self.end_time is None:
            self.end_time = time.time()

    def duration(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return self.end_time - self.start_time

    def add_tag(self, key: str, value: str) -> None:
        self.tags[key] = value


class Tracer:
    """Per-Thread Span-Stack mit Tree-Aggregation."""

    _COUNTER = 0
    _COUNTER_LOCK = threading.Lock()

    def __init__(self) -> None:
        self._local = threading.local()
        self._completed_spans: list[Span] = []
        self._lock = threading.Lock()

    def _next_id(self) -> str:
        with Tracer._COUNTER_LOCK:
            Tracer._COUNTER += 1
            return f"span-{Tracer._COUNTER}"

    def _stack(self) -> list:
        if not hasattr(self._local, "stack"):
            self._local.stack = []
        return self._local.stack

    def start_span(
        self,
        name: str,
        trace_id: Optional[str] = None,
    ) -> Span:
        stack = self._stack()
        parent = stack[-1] if stack else None
        tid = trace_id or (parent.trace_id if parent else self._next_id())
        span = Span(
            name=name,
            trace_id=tid,
            span_id=self._next_id(),
            parent_id=parent.span_id if parent else None,
        )
        if parent is not None:
            parent.children.append(span)
        stack.append(span)
        return span

    def end_current_span(self) -> Optional[Span]:
        stack = self._stack()
        if not stack:
            return None
        span = stack.pop()
        span.end()
        with self._lock:
            self._completed_spans.append(span)
        return span

    def get_completed_spans(self) -> list[Span]:
        with self._lock:
            return list(self._completed_spans)


# ---------------------------------------------------------------------------
# Health-Checks
# ---------------------------------------------------------------------------
class HealthCheckRegistry:
    """Per-Modul-Health-Status mit Aggregation."""

    def __init__(self) -> None:
        self._checks: dict[str, Callable[[], HealthStatus]] = {}
        self._lock = threading.Lock()

    def register(self, name: str, check_fn: Callable[[], HealthStatus]) -> None:
        if not callable(check_fn):
            raise TypeError("check_fn must be callable")
        with self._lock:
            self._checks[name] = check_fn

    def run_all(self) -> dict[str, HealthStatus]:
        with self._lock:
            checks = dict(self._checks)
        results = {}
        for name, fn in checks.items():
            try:
                results[name] = fn()
            except Exception:
                results[name] = HealthStatus.DOWN
        return results

    def aggregate(self) -> HealthStatus:
        """Aggregation: any DOWN -> DOWN, any DEGRADED (no DOWN) -> DEGRADED, else UP."""
        results = self.run_all()
        statuses = list(results.values())
        if not statuses:
            return HealthStatus.UP
        if HealthStatus.DOWN in statuses:
            return HealthStatus.DOWN
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.UP


# CRUX-MK
