# [CRUX-MK]
"""Time-Sync-Skew tracker (Welle-15 Phase-10.1).

Zirkadianer-Rhythmus-Synchronisations-Pattern. Tracked Clock-Skew zwischen
verteilten KMO-Modulen (z.B. PC1+Mac+Hotel-PMS). Drift-Detection bei
Threshold-Breach.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SkewSample:
    """Single skew-measurement."""

    clock_id: str
    timestamp: float
    offset_ms: float

    def __post_init__(self) -> None:
        if not self.clock_id:
            raise ValueError("clock_id required")


@dataclass(frozen=True)
class SkewEvent:
    """Drift-Event when threshold breached."""

    clock_id: str
    delta_ms: float
    threshold_ms: float
    breach_type: str  # "above" or "below"
    timestamp: float


class TimeSyncTracker:
    """Tracks clock-skew samples per clock_id with sliding-window.

    Pre: window_size > 0
    Post: thread-safe; median + percentile computable
    """

    def __init__(self, window_size: int = 100) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be > 0")
        self.window_size = int(window_size)
        self._samples: dict[str, deque[SkewSample]] = {}
        self._lock = threading.RLock()

    def register_clock(self, clock_id: str) -> None:
        if not clock_id:
            raise ValueError("clock_id required")
        with self._lock:
            if clock_id not in self._samples:
                self._samples[clock_id] = deque(maxlen=self.window_size)

    def sample_skew(self, clock_id: str, offset_ms: float) -> SkewSample:
        sample = SkewSample(
            clock_id=clock_id,
            timestamp=time.time(),
            offset_ms=float(offset_ms),
        )
        with self._lock:
            if clock_id not in self._samples:
                self._samples[clock_id] = deque(maxlen=self.window_size)
            self._samples[clock_id].append(sample)
        return sample

    def get_skew(self, clock_id: str) -> Optional[float]:
        """Most recent offset_ms for clock_id."""
        with self._lock:
            samples = self._samples.get(clock_id)
            if not samples:
                return None
            return samples[-1].offset_ms

    def median_skew(self, clock_id: str) -> Optional[float]:
        """Median offset_ms over window."""
        with self._lock:
            samples = self._samples.get(clock_id)
            if not samples:
                return None
            sorted_offsets = sorted(s.offset_ms for s in samples)
            n = len(sorted_offsets)
            mid = n // 2
            if n % 2 == 1:
                return sorted_offsets[mid]
            return (sorted_offsets[mid - 1] + sorted_offsets[mid]) / 2.0

    def sample_count(self, clock_id: str) -> int:
        with self._lock:
            samples = self._samples.get(clock_id)
            return len(samples) if samples else 0

    def all_clocks(self) -> list[str]:
        with self._lock:
            return list(self._samples.keys())


class DriftDetector:
    """Detects drift above threshold per clock.

    Pre: threshold_ms > 0.
    Post: thread-safe; emit SkewEvent when breach detected.
    """

    def __init__(
        self,
        threshold_ms: float = 100.0,
        tracker: Optional[TimeSyncTracker] = None,
    ) -> None:
        if threshold_ms <= 0:
            raise ValueError("threshold_ms must be > 0")
        self.threshold_ms = float(threshold_ms)
        self.tracker = tracker or TimeSyncTracker()
        self._events: list[SkewEvent] = []
        self._lock = threading.RLock()

    def detect_drift(self, clock_id: str) -> Optional[SkewEvent]:
        """Check current skew against threshold; emit event on breach."""
        skew = self.tracker.get_skew(clock_id)
        if skew is None:
            return None
        if abs(skew) > self.threshold_ms:
            event = SkewEvent(
                clock_id=clock_id,
                delta_ms=skew,
                threshold_ms=self.threshold_ms,
                breach_type="above" if skew > 0 else "below",
                timestamp=time.time(),
            )
            with self._lock:
                self._events.append(event)
            return event
        return None

    def get_events(self) -> list[SkewEvent]:
        with self._lock:
            return list(self._events)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


# CRUX-MK
