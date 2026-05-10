# [CRUX-MK]
"""Cape-Familien-Dedup Implementation (Welle-46 Phase-39)."""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FamilienDecisionDedupResult:
    is_duplicate: bool
    family_member_id: str
    decision_topic: str
    decision_hash: str
    ttl_remaining_s: float
    first_seen_at: Optional[float]

    def __post_init__(self) -> None:
        if not self.family_member_id:
            raise ValueError("family_member_id must be non-empty")
        if not self.decision_topic:
            raise ValueError("decision_topic must be non-empty")


class CapeFamilienDedup:
    """Familien-Decision-Repetition-Avoidance.

    Pre:
      - ttl_s > 0 (default 86400 = 1 day Familien-Decision-Cycle)
    """

    def __init__(self, ttl_s: float = 86400.0, max_active: int = 1000) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        if max_active < 1:
            raise ValueError("max_active >= 1")
        self._ttl = ttl_s
        self._max_active = max_active
        self._lock = threading.RLock()
        self._seen: dict[tuple[str, str, str], float] = {}

    def check_and_register(
        self,
        family_member_id: str,
        decision_topic: str,
        decision_payload: bytes,
    ) -> FamilienDecisionDedupResult:
        if not family_member_id or not decision_topic:
            raise ValueError("family_member_id + decision_topic non-empty")
        if not isinstance(decision_payload, bytes):
            raise TypeError("decision_payload must be bytes")
        decision_hash = hashlib.sha256(decision_payload).hexdigest()
        key = (family_member_id, decision_topic, decision_hash)
        now = time.monotonic()
        with self._lock:
            self._sweep_expired(now)
            if key in self._seen:
                first_seen = self._seen[key]
                return FamilienDecisionDedupResult(
                    is_duplicate=True,
                    family_member_id=family_member_id,
                    decision_topic=decision_topic,
                    decision_hash=decision_hash,
                    ttl_remaining_s=max(0.0, self._ttl - (now - first_seen)),
                    first_seen_at=first_seen,
                )
            if len(self._seen) >= self._max_active:
                # LRU evict
                oldest = min(self._seen, key=lambda k: self._seen[k])
                del self._seen[oldest]
            self._seen[key] = now
            return FamilienDecisionDedupResult(
                is_duplicate=False,
                family_member_id=family_member_id,
                decision_topic=decision_topic,
                decision_hash=decision_hash,
                ttl_remaining_s=self._ttl,
                first_seen_at=now,
            )

    def _sweep_expired(self, now: float) -> None:
        expired = [k for k, ts in self._seen.items() if (now - ts) > self._ttl]
        for k in expired:
            del self._seen[k]

    def active_count(self) -> int:
        with self._lock:
            self._sweep_expired(time.monotonic())
            return len(self._seen)


# CRUX-MK
