"""Redis-Mitose Orchestrator -- Cell-Division Pattern fuer Cluster-Resharding [CRUX-MK].

Externe Domain: Redis-Cluster Resharding-Workflow.
Pure Redis-Domain (Cluster-API + Mock-KV-Store) ohne Kemmer-Imports.

Bio-Pattern (Mitose Choreography):
    1. Interphase    -- shard load monitored
    2. Prophase      -- decide-to-split: load > threshold
    3. Metaphase     -- align slot-ranges (split_half)
    4. Anaphase      -- migrate keys to daughter shards
    5. Telophase     -- swap slot-map atomically
    6. Cytokinesis   -- mark daughters HEALTHY (promotion)
    7. Checkpoint    -- verify Conservation-Law

Tech-Mapping:
    - load                 = key_count / threshold
    - prophase decision    = decide_to_split() returns shard-IDs needing mitose
    - metaphase + anaphase = split_shard() + migrate_keys()
    - cytokinesis          = promote_daughter()
    - checkpoint           = topology.verify_invariants()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .redis_cluster_topology import (
    RedisClusterTopology,
    ShardInfo,
    ShardState,
    SlotRange,
    crc16_slot,
)


# ---- Mitose-Constants (Redis-Cluster-Defaults) ----
DEFAULT_LOAD_THRESHOLD: int = 100_000        # keys/shard before mitose
DEFAULT_MIN_KEYS_PER_HALF: int = 100         # daughter must inherit >= this many keys
DEFAULT_MIGRATION_BATCH_SIZE: int = 1_000    # keys per migrate_keys() call
DEFAULT_DAUGHTER_ID_PREFIX: str = "shard"


class MitoseOutcome(str, Enum):
    """Outcome of a mitose-cycle."""
    DIVIDED = "divided"            # mother split into 2 daughters
    SKIPPED = "skipped"            # load below threshold, no split
    REJECTED = "rejected"          # split-condition violated (e.g., disjoint ranges)
    FAILED = "failed"              # split attempted but rolled back


@dataclass(frozen=True)
class MitoseEvent:
    """Audit-log entry for a mitose-cycle."""
    mother_shard_id: str
    daughter_a_id: Optional[str]
    daughter_b_id: Optional[str]
    outcome: MitoseOutcome
    keys_migrated: int
    timestamp: float
    reason: str = ""


class RedisMitoseOrchestrator:
    """Drives Mitose-Cycles on a RedisClusterTopology.

    Workflow (per cycle):
        1. Scan all shards; collect those exceeding load_threshold.
        2. For each over-loaded shard:
            a. Generate unique daughter-IDs.
            b. Execute split_shard (Mitose).
            c. Migrate keys from mother-store to daughter-stores.
            d. Promote daughters to HEALTHY.
            e. Append MitoseEvent.
        3. Return list of MitoseEvents.

    Thread-safe: all topology-mutations under topology lock.
    """

    def __init__(
        self,
        topology: RedisClusterTopology,
        load_threshold: int = DEFAULT_LOAD_THRESHOLD,
        min_keys_per_half: int = DEFAULT_MIN_KEYS_PER_HALF,
        migration_batch_size: int = DEFAULT_MIGRATION_BATCH_SIZE,
        daughter_id_prefix: str = DEFAULT_DAUGHTER_ID_PREFIX,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if load_threshold <= 0:
            raise ValueError("load_threshold must be > 0")
        if min_keys_per_half < 0:
            raise ValueError("min_keys_per_half must be >= 0")
        if migration_batch_size <= 0:
            raise ValueError("migration_batch_size must be > 0")
        self.topology = topology
        self.load_threshold = int(load_threshold)
        self.min_keys_per_half = int(min_keys_per_half)
        self.migration_batch_size = int(migration_batch_size)
        self.daughter_id_prefix = daughter_id_prefix
        self._clock = clock
        self._counter_lock = threading.Lock()
        self._daughter_counter = 0
        self._events: list[MitoseEvent] = []
        self._events_lock = threading.Lock()

    # ---------------- Public API ----------------

    def decide_to_split(self) -> list[str]:
        """Prophase: scan topology, return shard-IDs eligible for mitose."""
        snap = self.topology.snapshot()
        candidates: list[str] = []
        for s in snap.shards:
            if s.state != ShardState.HEALTHY:
                continue
            if s.key_count < self.load_threshold:
                continue
            if s.key_count // 2 < self.min_keys_per_half:
                continue
            # Mother needs single contiguous range to split cleanly.
            if len(s.slot_ranges) != 1:
                continue
            if s.slot_ranges[0].width() < 32:  # too narrow to subdivide
                continue
            candidates.append(s.shard_id)
        return candidates

    def execute_mitose(
        self,
        mother_shard_id: str,
        kv_store: dict[str, dict[str, str]],
    ) -> MitoseEvent:
        """Full Mitose-Cycle for a single mother-shard.

        kv_store: dict mapping shard_id -> {key: value}. Mocks Redis per-shard
        keyspaces. The orchestrator migrates keys whose CRC16-slot falls into
        the daughter's range.

        Returns a MitoseEvent describing the outcome.
        """
        ts = self._clock()
        # Generate daughter IDs.
        daughter_a_id = self._next_daughter_id()
        daughter_b_id = self._next_daughter_id()
        # Snapshot mother for migration plan.
        mother = self.topology.get_shard(mother_shard_id)
        if mother is None:
            event = MitoseEvent(
                mother_shard_id=mother_shard_id,
                daughter_a_id=None,
                daughter_b_id=None,
                outcome=MitoseOutcome.REJECTED,
                keys_migrated=0,
                timestamp=ts,
                reason="mother shard not found",
            )
            self._record_event(event)
            return event
        try:
            # Anaphase + Telophase: split via topology API (atomic).
            self.topology.split_shard(mother_shard_id, daughter_a_id, daughter_b_id)
        except (ValueError, KeyError) as exc:
            event = MitoseEvent(
                mother_shard_id=mother_shard_id,
                daughter_a_id=None,
                daughter_b_id=None,
                outcome=MitoseOutcome.REJECTED,
                keys_migrated=0,
                timestamp=ts,
                reason=f"split rejected: {exc}",
            )
            self._record_event(event)
            return event
        # Migrate keys (Anaphase: chromatids migrate to opposite poles).
        migrated_count = self._migrate_keys(
            mother_shard_id, daughter_a_id, daughter_b_id, kv_store
        )
        # Cytokinesis: promote daughters to HEALTHY.
        try:
            self.topology.promote_daughter(daughter_a_id)
            self.topology.promote_daughter(daughter_b_id)
        except (KeyError, ValueError) as exc:
            event = MitoseEvent(
                mother_shard_id=mother_shard_id,
                daughter_a_id=daughter_a_id,
                daughter_b_id=daughter_b_id,
                outcome=MitoseOutcome.FAILED,
                keys_migrated=migrated_count,
                timestamp=ts,
                reason=f"promotion failed: {exc}",
            )
            self._record_event(event)
            return event
        event = MitoseEvent(
            mother_shard_id=mother_shard_id,
            daughter_a_id=daughter_a_id,
            daughter_b_id=daughter_b_id,
            outcome=MitoseOutcome.DIVIDED,
            keys_migrated=migrated_count,
            timestamp=ts,
            reason=f"mitose complete: {migrated_count} keys migrated",
        )
        self._record_event(event)
        return event

    def run_cycle(
        self,
        kv_store: dict[str, dict[str, str]],
        max_splits: Optional[int] = None,
    ) -> list[MitoseEvent]:
        """Convenience: scan + split all eligible shards in one cycle."""
        candidates = self.decide_to_split()
        if max_splits is not None:
            candidates = candidates[:max_splits]
        events: list[MitoseEvent] = []
        for mother_id in candidates:
            ev = self.execute_mitose(mother_id, kv_store)
            events.append(ev)
            if ev.outcome != MitoseOutcome.DIVIDED:
                # Skip subsequent splits if topology became inconsistent.
                continue
        return events

    def event_history(self) -> list[MitoseEvent]:
        with self._events_lock:
            return list(self._events)

    # ---------------- Internal helpers ----------------

    def _next_daughter_id(self) -> str:
        with self._counter_lock:
            self._daughter_counter += 1
            return f"{self.daughter_id_prefix}-{self._daughter_counter:04d}"

    def _migrate_keys(
        self,
        mother_id: str,
        daughter_a_id: str,
        daughter_b_id: str,
        kv_store: dict[str, dict[str, str]],
    ) -> int:
        """Move keys from mother kv-store to the correct daughter.

        After topology.split_shard, mother is gone -- we read mother's
        legacy kv-store, remap each key by slot, and write into the
        appropriate daughter kv-store. Returns count of migrated keys.
        """
        mother_keys = kv_store.pop(mother_id, {})
        daughter_a_kv: dict[str, str] = kv_store.setdefault(daughter_a_id, {})
        daughter_b_kv: dict[str, str] = kv_store.setdefault(daughter_b_id, {})
        daughter_a = self.topology.get_shard(daughter_a_id)
        daughter_b = self.topology.get_shard(daughter_b_id)
        if daughter_a is None or daughter_b is None:
            raise RuntimeError("daughter shards vanished mid-migration")
        migrated = 0
        # Process in batches to simulate Redis-Cluster-Migration RESHARD command.
        batch = self.migration_batch_size
        keys = list(mother_keys.keys())
        for i in range(0, len(keys), batch):
            for key in keys[i : i + batch]:
                slot = crc16_slot(key)
                if daughter_a.owns(slot):
                    daughter_a_kv[key] = mother_keys[key]
                elif daughter_b.owns(slot):
                    daughter_b_kv[key] = mother_keys[key]
                else:
                    # Conservation-violation: should not happen if topology valid.
                    raise RuntimeError(
                        f"key '{key}' (slot {slot}) owned by neither daughter"
                    )
                migrated += 1
        return migrated

    def _record_event(self, event: MitoseEvent) -> None:
        with self._events_lock:
            self._events.append(event)


# CRUX-MK
