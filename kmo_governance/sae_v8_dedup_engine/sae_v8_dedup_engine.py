# [CRUX-MK]
"""SAE-v8 Dedup-Engine Implementation (Welle-42 Phase-35).

DEMO-only (per L34): Pattern-Lift, kein Real-Wiring zu sae_v8/core/trinity.py.
Welle-50+ Real-Wiring per SAE-v8-WIRING-PLAN.md.
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SlotVoteDedupResult:
    """Dedup-Pruefung-Result fuer Slot-Vote-Submission.

    Pre:
      - slot_id non-empty
      - agent_class non-empty
      - vote_hash non-empty
    """
    is_duplicate: bool
    slot_id: str
    agent_class: str
    vote_hash: str
    ttl_remaining_s: float
    first_seen_at: Optional[float]
    timestamp: float

    def __post_init__(self) -> None:
        if not self.slot_id:
            raise ValueError("slot_id must be non-empty")
        if not self.agent_class:
            raise ValueError("agent_class must be non-empty")
        if not self.vote_hash:
            raise ValueError("vote_hash must be non-empty")
        if self.ttl_remaining_s < 0:
            raise ValueError("ttl_remaining_s must be >= 0")


class SAEv8DedupEngine:
    """B-Cell-Memory-Match fuer SAE-v8 Slot-Vote-Submissions.

    Pre:
      - ttl_s > 0 (default 5s, Trinity-Voting-Window kurz)
      - max_active_keys >= 1
    """

    def __init__(
        self,
        ttl_s: float = 5.0,
        max_active_keys: int = 10000,
    ) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be > 0")
        if max_active_keys < 1:
            raise ValueError("max_active_keys must be >= 1")
        self._ttl = ttl_s
        self._max_keys = max_active_keys
        self._lock = threading.RLock()
        # Key: (slot_id, agent_class, vote_hash) -> first_seen_monotonic
        self._seen: dict[tuple[str, str, str], float] = {}

    def check_and_register(
        self,
        slot_id: str,
        agent_class: str,
        vote_payload: bytes,
    ) -> SlotVoteDedupResult:
        """Check duplicate + register (atomic CAS).

        Pre:
          - all fields non-empty
          - vote_payload bytes (will be SHA256-hashed)

        Post:
          - if duplicate: is_duplicate=True, registered=NOT updated
          - if new: is_duplicate=False, registered=now
        """
        if not slot_id or not agent_class:
            raise ValueError("slot_id + agent_class must be non-empty")
        if not isinstance(vote_payload, bytes):
            raise TypeError("vote_payload must be bytes")
        vote_hash = hashlib.sha256(vote_payload).hexdigest()
        key = (slot_id, agent_class, vote_hash)
        now = time.monotonic()
        with self._lock:
            self._sweep_expired(now)
            if key in self._seen:
                first_seen = self._seen[key]
                ttl_remaining = max(0.0, self._ttl - (now - first_seen))
                return SlotVoteDedupResult(
                    is_duplicate=True,
                    slot_id=slot_id,
                    agent_class=agent_class,
                    vote_hash=vote_hash,
                    ttl_remaining_s=ttl_remaining,
                    first_seen_at=first_seen,
                    timestamp=time.time(),
                )
            # New submission
            if len(self._seen) >= self._max_keys:
                self._evict_oldest()
            self._seen[key] = now
            return SlotVoteDedupResult(
                is_duplicate=False,
                slot_id=slot_id,
                agent_class=agent_class,
                vote_hash=vote_hash,
                ttl_remaining_s=self._ttl,
                first_seen_at=now,
                timestamp=time.time(),
            )

    def _sweep_expired(self, now: float) -> None:
        expired_keys = [
            k for k, first_seen in self._seen.items()
            if (now - first_seen) > self._ttl
        ]
        for k in expired_keys:
            del self._seen[k]

    def _evict_oldest(self) -> None:
        """LRU-evict oldest entry (caller must hold self._lock)."""
        if not self._seen:
            return
        oldest_key = min(self._seen, key=lambda k: self._seen[k])
        del self._seen[oldest_key]

    def active_keys_count(self) -> int:
        with self._lock:
            self._sweep_expired(time.monotonic())
            return len(self._seen)


# CRUX-MK
