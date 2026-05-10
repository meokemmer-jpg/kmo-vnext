# [CRUX-MK]
"""DF-Health-Monitor-Homeostasis Implementation (Welle-49 Phase-42, 9. Domain META)."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DFHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass(frozen=True)
class DFHealthSample:
    sample_id: str
    df_id: str
    lambda_per_day: float
    error_rate: float          # [0.0, 1.0]
    retry_overhead_pct: float  # [0.0, 1.0+] retry/total ratio
    p95_latency_ms: float
    timestamp: float

    def __post_init__(self) -> None:
        if not self.sample_id or not self.df_id:
            raise ValueError("sample_id + df_id non-empty")
        if self.lambda_per_day < 0:
            raise ValueError("lambda_per_day >= 0")
        if not 0.0 <= self.error_rate <= 1.0:
            raise ValueError("error_rate in [0.0, 1.0]")
        if self.retry_overhead_pct < 0:
            raise ValueError("retry_overhead_pct >= 0")
        if self.p95_latency_ms < 0:
            raise ValueError("p95_latency_ms >= 0")


@dataclass(frozen=True)
class DFHealthDecision:
    state: DFHealthState
    df_id: str
    health_score: float
    setpoint: float
    deviation_pct: float
    recommended_action: str  # "ok", "monitor", "reduce_frequency", "pause", "hard_stop"
    samples_evaluated: int
    timestamp: float


class DFHealthMonitorHomeostasis:
    """Self-Monitoring fuer Dark-Factories.

    Score-Formel:
        health_score = lambda * (1 - error_rate) - retry_overhead_pct

    Ein DF mit lambda=1/day, error_rate=0.05, retry=0.02 -> 0.93.
    Ein DF mit lambda=1/day, error_rate=0.50, retry=0.30 -> 0.20 (CRITICAL).

    Pre:
      - setpoint > 0
      - history_window >= 1
    """

    def __init__(
        self,
        setpoint: float = 0.85,  # 85% effective lambda is healthy
        history_window: int = 5,
        degraded_threshold_pct: float = 10.0,
        unhealthy_threshold_pct: float = 25.0,
        critical_threshold_pct: float = 50.0,
    ) -> None:
        if setpoint <= 0:
            raise ValueError("setpoint must be > 0")
        if history_window < 1:
            raise ValueError("history_window >= 1")
        if not (degraded_threshold_pct < unhealthy_threshold_pct < critical_threshold_pct):
            raise ValueError("degraded < unhealthy < critical required")
        self._setpoint = setpoint
        self._history_window = history_window
        self._degraded_pct = degraded_threshold_pct
        self._unhealthy_pct = unhealthy_threshold_pct
        self._critical_pct = critical_threshold_pct
        self._lock = threading.RLock()
        self._histories: dict[str, deque] = {}

    def _compute_health_score(self, sample: DFHealthSample) -> float:
        return sample.lambda_per_day * (1.0 - sample.error_rate) - sample.retry_overhead_pct

    def record_sample(self, sample: DFHealthSample) -> DFHealthDecision:
        with self._lock:
            if sample.df_id not in self._histories:
                self._histories[sample.df_id] = deque(maxlen=self._history_window)
            self._histories[sample.df_id].append(sample)
            scores = [self._compute_health_score(s) for s in self._histories[sample.df_id]]
            avg_score = sum(scores) / len(scores)
            deviation = abs(avg_score - self._setpoint) * 100.0 / max(0.001, self._setpoint)
            state = self._classify(avg_score, deviation)
            action = self._recommend_action(state)
            return DFHealthDecision(
                state=state,
                df_id=sample.df_id,
                health_score=avg_score,
                setpoint=self._setpoint,
                deviation_pct=deviation,
                recommended_action=action,
                samples_evaluated=len(self._histories[sample.df_id]),
                timestamp=time.time(),
            )

    def _classify(self, score: float, deviation_pct: float) -> DFHealthState:
        if score < self._setpoint and deviation_pct >= self._critical_pct:
            return DFHealthState.CRITICAL
        if score < self._setpoint and deviation_pct >= self._unhealthy_pct:
            return DFHealthState.UNHEALTHY
        if deviation_pct >= self._degraded_pct:
            return DFHealthState.DEGRADED
        return DFHealthState.HEALTHY

    def _recommend_action(self, state: DFHealthState) -> str:
        return {
            DFHealthState.HEALTHY: "ok",
            DFHealthState.DEGRADED: "monitor",
            DFHealthState.UNHEALTHY: "reduce_frequency",
            DFHealthState.CRITICAL: "pause_or_hard_stop",
        }[state]

    def get_df_history(self, df_id: str) -> tuple[DFHealthSample, ...]:
        with self._lock:
            if df_id not in self._histories:
                return ()
            return tuple(self._histories[df_id])

    def list_critical_dfs(self) -> tuple[str, ...]:
        """Return df_ids whose latest sample classifies as CRITICAL."""
        result = []
        with self._lock:
            for df_id, hist in self._histories.items():
                if not hist:
                    continue
                scores = [self._compute_health_score(s) for s in hist]
                avg = sum(scores) / len(scores)
                deviation = abs(avg - self._setpoint) * 100.0 / max(0.001, self._setpoint)
                if avg < self._setpoint and deviation >= self._critical_pct:
                    result.append(df_id)
        return tuple(sorted(result))


# CRUX-MK
