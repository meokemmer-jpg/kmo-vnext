# [CRUX-MK]
"""Graphity-Homeostasis-Pricing Implementation (Welle-44 Phase-37)."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RoyaltyState(str, Enum):
    NORMAL = "normal"
    MILD_DEVIATION = "mild_deviation"
    UNDER_ROYALTY = "under_royalty"  # author getting less than fair
    OVER_ROYALTY = "over_royalty"    # author getting too much (publisher loss)
    CRITICAL = "critical"


@dataclass(frozen=True)
class RoyaltySample:
    sample_id: str
    book_id: str
    author_id: str
    royalty_pct: float  # actual royalty paid (0.0-1.0)
    timestamp: float

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id must be non-empty")
        if not self.book_id or not self.author_id:
            raise ValueError("book_id + author_id must be non-empty")
        if not 0.0 <= self.royalty_pct <= 1.0:
            raise ValueError("royalty_pct must be in [0.0, 1.0]")


@dataclass(frozen=True)
class RoyaltyDecision:
    state: RoyaltyState
    book_id: str
    author_id: str
    current_royalty_pct: float
    setpoint_pct: float
    deviation_pct: float
    recommendation: str
    samples_evaluated: int
    timestamp: float


class GraphityHomeostasisPricing:
    """Royalty-Drift-Controller fuer Verlag.

    Pre:
      - setpoint in [0.0, 1.0] (e.g. 0.10 for 10% standard royalty)
      - history_window >= 1
    """

    def __init__(
        self,
        setpoint: float = 0.10,  # 10% standard royalty
        history_window: int = 5,
        mild_threshold_pct: float = 5.0,
        critical_threshold_pct: float = 15.0,
    ) -> None:
        if not 0.0 <= setpoint <= 1.0:
            raise ValueError("setpoint must be in [0.0, 1.0]")
        if history_window < 1:
            raise ValueError("history_window must be >= 1")
        if mild_threshold_pct >= critical_threshold_pct:
            raise ValueError("mild < critical required")
        self._setpoint = setpoint
        self._mild_pct = mild_threshold_pct
        self._critical_pct = critical_threshold_pct
        self._lock = threading.RLock()
        # Per-book history deques
        self._histories: dict[str, deque] = {}

    def record_sample(self, sample: RoyaltySample) -> RoyaltyDecision:
        with self._lock:
            if sample.book_id not in self._histories:
                self._histories[sample.book_id] = deque(maxlen=5)
            self._histories[sample.book_id].append(sample)
            current = sum(s.royalty_pct for s in self._histories[sample.book_id]) / len(self._histories[sample.book_id])
            deviation = abs(current - self._setpoint) * 100.0 / max(0.0001, self._setpoint)
            state = self._classify(current, deviation)
            recommendation = self._recommend(state, current)
            return RoyaltyDecision(
                state=state,
                book_id=sample.book_id,
                author_id=sample.author_id,
                current_royalty_pct=current,
                setpoint_pct=self._setpoint,
                deviation_pct=deviation,
                recommendation=recommendation,
                samples_evaluated=len(self._histories[sample.book_id]),
                timestamp=time.time(),
            )

    def _classify(self, current: float, deviation_pct: float) -> RoyaltyState:
        if deviation_pct >= self._critical_pct:
            return RoyaltyState.CRITICAL
        if deviation_pct >= self._mild_pct:
            return RoyaltyState.UNDER_ROYALTY if current < self._setpoint else RoyaltyState.OVER_ROYALTY
        if deviation_pct >= self._mild_pct / 2:
            return RoyaltyState.MILD_DEVIATION
        return RoyaltyState.NORMAL

    def _recommend(self, state: RoyaltyState, current: float) -> str:
        if state == RoyaltyState.NORMAL:
            return "ok"
        if state == RoyaltyState.MILD_DEVIATION:
            return "monitor"
        if state == RoyaltyState.UNDER_ROYALTY:
            return f"renegotiate_up: {current:.1%} -> {self._setpoint:.1%}"
        if state == RoyaltyState.OVER_ROYALTY:
            return f"renegotiate_down: {current:.1%} -> {self._setpoint:.1%}"
        return "critical_legal_review_required"

    def get_book_history(self, book_id: str) -> tuple[RoyaltySample, ...]:
        with self._lock:
            if book_id not in self._histories:
                return ()
            return tuple(self._histories[book_id])


# CRUX-MK
