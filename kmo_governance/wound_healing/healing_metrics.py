"""KMO Wound-Healing Metrics [CRUX-MK].

MTTR-Tracking pro Phase + Total. Aggregations fuer SLO-Reporting.

Bio-Aequivalent: Heilungs-Verlauf-Telemetrie. Hier: MTTR (Mean-Time-To-Recovery).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable


@dataclass
class HealingMetrics:
    """Thread-safe metrics aggregator. Records phase durations + total MTTR."""

    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._phase_durations: dict[object, list[float]] = defaultdict(list)
        self._total_mttrs: list[float] = []

    def record_phase_duration(self, phase: object, duration_sec: float) -> None:
        if duration_sec < 0:
            return
        with self._lock:
            self._phase_durations[phase].append(float(duration_sec))

    def record_total_mttr(self, total_sec: float) -> None:
        if total_sec < 0:
            return
        with self._lock:
            self._total_mttrs.append(float(total_sec))

    def avg_phase_duration(self, phase: object) -> float:
        with self._lock:
            ds = self._phase_durations.get(phase, [])
            return sum(ds) / len(ds) if ds else 0.0

    def avg_total_mttr(self) -> float:
        with self._lock:
            return sum(self._total_mttrs) / len(self._total_mttrs) if self._total_mttrs else 0.0

    def total_count(self) -> int:
        with self._lock:
            return len(self._total_mttrs)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_count": len(self._total_mttrs),
                "avg_total_mttr_sec": self.avg_total_mttr(),
                "avg_phase_duration_sec": {
                    str(p): (sum(ds) / len(ds) if ds else 0.0)
                    for p, ds in self._phase_durations.items()
                },
            }


# CRUX-MK
