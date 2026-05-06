# [CRUX-MK]
"""Adaptive Throttle (Welle-18 Phase-12.1)."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ThrottleAction(str, Enum):
    HOLD = "hold"
    INCREASE = "increase"
    DECREASE = "decrease"


@dataclass(frozen=True)
class ThrottleMetric:
    """Sample of latency + error rate."""

    latency_ms: float
    error_rate: float
    timestamp: float

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if not 0.0 <= self.error_rate <= 1.0:
            raise ValueError("error_rate must be in [0.0, 1.0]")


@dataclass(frozen=True)
class ThrottleDecision:
    """Throttle decision with new rate."""

    action: ThrottleAction
    new_rate: float
    reason: str
    timestamp: float


class AdaptiveThrottle:
    """PID-like adaptive rate-limiter.

    Pre: base_rate > 0, target_latency_ms > 0, error_threshold in [0, 1]
    Post: thread-safe; rate adjusts based on latency+error signals
    """

    def __init__(
        self,
        base_rate: float = 100.0,
        min_rate: float = 1.0,
        max_rate: float = 1000.0,
        target_latency_ms: float = 100.0,
        error_threshold: float = 0.05,
        increase_factor: float = 1.1,
        decrease_factor: float = 0.5,
        window_size: int = 50,
    ) -> None:
        if base_rate <= 0:
            raise ValueError("base_rate must be > 0")
        if min_rate <= 0:
            raise ValueError("min_rate must be > 0")
        if max_rate < base_rate:
            raise ValueError("max_rate must be >= base_rate")
        if target_latency_ms <= 0:
            raise ValueError("target_latency_ms must be > 0")
        if not 0.0 <= error_threshold <= 1.0:
            raise ValueError("error_threshold must be in [0.0, 1.0]")
        if increase_factor <= 1.0:
            raise ValueError("increase_factor must be > 1.0")
        if not 0.0 < decrease_factor < 1.0:
            raise ValueError("decrease_factor must be in (0.0, 1.0)")
        if window_size <= 0:
            raise ValueError("window_size must be > 0")

        self.base_rate = base_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.target_latency_ms = target_latency_ms
        self.error_threshold = error_threshold
        self.increase_factor = increase_factor
        self.decrease_factor = decrease_factor
        self._current_rate = float(base_rate)
        self._metrics: deque[ThrottleMetric] = deque(maxlen=window_size)
        self._decisions: list[ThrottleDecision] = []
        self._lock = threading.RLock()

    @property
    def current_rate(self) -> float:
        with self._lock:
            return self._current_rate

    def record_metric(self, latency_ms: float, error_rate: float) -> None:
        m = ThrottleMetric(
            latency_ms=latency_ms,
            error_rate=error_rate,
            timestamp=time.time(),
        )
        with self._lock:
            self._metrics.append(m)

    def adjust(self) -> ThrottleDecision:
        """Compute new rate based on metric-window."""
        with self._lock:
            if not self._metrics:
                decision = ThrottleDecision(
                    action=ThrottleAction.HOLD,
                    new_rate=self._current_rate,
                    reason="no metrics",
                    timestamp=time.time(),
                )
                self._decisions.append(decision)
                return decision

            avg_latency = sum(m.latency_ms for m in self._metrics) / len(self._metrics)
            avg_error = sum(m.error_rate for m in self._metrics) / len(self._metrics)

            # Decision logic
            old_rate = self._current_rate
            if avg_error > self.error_threshold:
                # High error rate -> decrease aggressive
                self._current_rate = max(
                    self.min_rate, self._current_rate * self.decrease_factor
                )
                action = ThrottleAction.DECREASE
                reason = f"error_rate {avg_error:.3f} > {self.error_threshold}"
            elif avg_latency > self.target_latency_ms:
                # High latency -> decrease moderate
                self._current_rate = max(
                    self.min_rate,
                    self._current_rate * (1 - (1 - self.decrease_factor) * 0.5),
                )
                action = ThrottleAction.DECREASE
                reason = f"latency {avg_latency:.1f}ms > {self.target_latency_ms}ms"
            elif avg_latency < self.target_latency_ms * 0.5 and avg_error < self.error_threshold * 0.5:
                # Low pressure -> increase
                self._current_rate = min(
                    self.max_rate, self._current_rate * self.increase_factor
                )
                action = ThrottleAction.INCREASE
                reason = f"latency {avg_latency:.1f}ms low, error {avg_error:.3f} low"
            else:
                action = ThrottleAction.HOLD
                reason = f"in target band (latency={avg_latency:.1f}ms, error={avg_error:.3f})"

            decision = ThrottleDecision(
                action=action,
                new_rate=self._current_rate,
                reason=reason,
                timestamp=time.time(),
            )
            self._decisions.append(decision)
            return decision

    def reset(self) -> None:
        """Reset to base_rate + clear metrics + clear decisions."""
        with self._lock:
            self._current_rate = self.base_rate
            self._metrics.clear()
            self._decisions.clear()

    def get_decisions(self) -> list[ThrottleDecision]:
        with self._lock:
            return list(self._decisions)

    def metric_count(self) -> int:
        with self._lock:
            return len(self._metrics)


# CRUX-MK
