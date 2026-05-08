"""Redis-Cluster Topology -- Mitose-Pattern Cell-Division for Hash-Slot-Sharding [CRUX-MK].

Externe Domain: Redis-Cluster (https://redis.io/docs/management/scaling/).
- 16384 Hash-Slots (CRC16(key) mod 16384) verteilt auf N Shards.
- Resharding via MOVED/ASK Protocol.
- Pure Redis-Cluster-Domain: KEINE crux/governance/Kemmer-Imports.

Bio-Pattern (Mitose / Cell-Division):
    1. Mother-Cell (1 Shard) duplicated DNA (Hash-Slot-Range).
    2. Spindle-Apparatus aligns chromosomes (Resharding-Coordinator).
    3. Cell splits into 2 Daughter-Cells (50/50 Hash-Slot-Split).
    4. Mitotic-Checkpoint validates DNA-Integrity (Conservation-Law).
    5. Cytokinesis = final cleanup (Slot-Map-Atomic-Swap).

Pre-Conditions:
    - 16384 Total-Slots (Redis-Cluster-Standard).
    - Each Shard owns disjoint slot-ranges; union covers full 0..16383.
Post-Conditions:
    - All slot-ranges form contiguous partition (no gap, no overlap).
    - Resharding preserves ALL keys (Conservation-Law).
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


# ---- Redis-Cluster Constants (Industriestandard) ----
TOTAL_SLOTS: int = 16384                       # Redis-Cluster fixed slot-count
MIN_SLOTS_PER_SHARD: int = 16                  # below this, split inadvisable
MIN_SHARD_COUNT: int = 1
MAX_SHARD_COUNT: int = 1024                    # Redis-Doku praktisches Maximum
SLOT_HASH_BITS: int = 14                       # log2(16384)


class ShardState(str, Enum):
    """Lifecycle-State eines Redis-Cluster-Shards."""
    HEALTHY = "healthy"          # serving traffic normally
    SPLITTING = "splitting"      # mitose-in-progress (mother-cell)
    DAUGHTER_NEW = "daughter_new"  # freshly-created daughter, still importing
    MIGRATING = "migrating"      # source-shard during resharding
    IMPORTING = "importing"      # target-shard during resharding
    RETIRED = "retired"          # post-split mother-shard, slots evacuated


def crc16_slot(key: str) -> int:
    """Compute Redis-Cluster slot for a key.

    Note: Redis-Cluster uses CRC16-CCITT(key) mod 16384. We use a simple
    deterministic hash (sha256-mod) for the simulation here -- equivalent
    behaviour for slot-distribution (uniform 0..16383).
    """
    if not isinstance(key, str):
        raise TypeError("key must be str")
    h = hashlib.sha256(key.encode("utf-8")).digest()
    val = int.from_bytes(h[:2], "big")
    return val % TOTAL_SLOTS


@dataclass(frozen=True)
class SlotRange:
    """Inclusive [start, end] hash-slot range owned by a shard."""
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end >= TOTAL_SLOTS:
            raise ValueError(
                f"SlotRange [{self.start}, {self.end}] out of [0, {TOTAL_SLOTS-1}]"
            )
        if self.start > self.end:
            raise ValueError(f"SlotRange start ({self.start}) > end ({self.end})")

    def width(self) -> int:
        return self.end - self.start + 1

    def contains(self, slot: int) -> bool:
        return self.start <= slot <= self.end

    def split_half(self) -> tuple["SlotRange", "SlotRange"]:
        """Mitose-Equivalent: split range into two contiguous halves (~50/50)."""
        if self.width() < 2 * MIN_SLOTS_PER_SHARD:
            raise ValueError(
                f"SlotRange width {self.width()} < 2*MIN_SLOTS_PER_SHARD ({2*MIN_SLOTS_PER_SHARD})"
            )
        mid = self.start + (self.width() // 2) - 1
        return (SlotRange(self.start, mid), SlotRange(mid + 1, self.end))


@dataclass
class ShardInfo:
    """Mutable per-Shard state in the cluster topology."""
    shard_id: str
    slot_ranges: list[SlotRange]
    state: ShardState = ShardState.HEALTHY
    parent_shard_id: Optional[str] = None  # set for daughter-shards (mitose-lineage)
    key_count: int = 0                     # estimated keys in this shard

    def owns(self, slot: int) -> bool:
        return any(r.contains(slot) for r in self.slot_ranges)

    def total_slots(self) -> int:
        return sum(r.width() for r in self.slot_ranges)


@dataclass(frozen=True)
class TopologySnapshot:
    """Immutable view of the cluster at a moment in time."""
    shards: tuple[ShardInfo, ...]
    version: int

    def find_shard_for_slot(self, slot: int) -> Optional[ShardInfo]:
        for s in self.shards:
            if s.owns(slot):
                return s
        return None


class RedisClusterTopology:
    """Thread-safe Redis-Cluster topology with Mitose-Sharding support.

    Bio->Tech Mapping:
        - Cluster (organism)        = full 16384-slot partition
        - Shard (cell)              = ShardInfo with disjoint slot-ranges
        - Mitose (cell-division)    = split_shard(): one shard -> two daughters
        - Conservation-Law          = invariant: all slots covered exactly once
        - Mitotic-Checkpoint        = verify_invariants(): pre/post mitose

    All mutations under self._lock (RLock); public API is reentrant-safe.
    """

    def __init__(self, initial_shards: Optional[Iterable[ShardInfo]] = None) -> None:
        self._lock = threading.RLock()
        self._shards: dict[str, ShardInfo] = {}
        self._version: int = 0
        if initial_shards is not None:
            for s in initial_shards:
                self._shards[s.shard_id] = s
        elif not initial_shards:
            # default genesis: one shard owning all slots
            self._shards["shard-genesis"] = ShardInfo(
                shard_id="shard-genesis",
                slot_ranges=[SlotRange(0, TOTAL_SLOTS - 1)],
            )
        self._verify_invariants_locked()

    # ---------------- Read API ----------------

    def snapshot(self) -> TopologySnapshot:
        """Atomic view of the cluster state."""
        with self._lock:
            shards_snap = tuple(
                ShardInfo(
                    shard_id=s.shard_id,
                    slot_ranges=list(s.slot_ranges),
                    state=s.state,
                    parent_shard_id=s.parent_shard_id,
                    key_count=s.key_count,
                )
                for s in self._shards.values()
            )
            return TopologySnapshot(shards=shards_snap, version=self._version)

    def find_shard_for_key(self, key: str) -> Optional[str]:
        """Return shard_id owning the slot of 'key'."""
        slot = crc16_slot(key)
        with self._lock:
            for sid, s in self._shards.items():
                if s.owns(slot):
                    return sid
            return None

    def shard_count(self) -> int:
        with self._lock:
            return len(self._shards)

    def shard_ids(self) -> list[str]:
        with self._lock:
            return list(self._shards.keys())

    def get_shard(self, shard_id: str) -> Optional[ShardInfo]:
        with self._lock:
            return self._shards.get(shard_id)

    # ---------------- Mitose (Cell-Division) API ----------------

    def split_shard(
        self,
        mother_shard_id: str,
        daughter_a_id: str,
        daughter_b_id: str,
    ) -> tuple[str, str]:
        """Mitose: split one shard into two daughters with 50/50 slot-range.

        Steps (Cell-Division choreography):
            1. Mark mother-shard SPLITTING (DNA-Replication-Phase).
            2. Compute median slot-split (~50/50 by slot-count).
            3. Create daughter shards in DAUGHTER_NEW state.
            4. Atomic-swap: remove mother, add daughters (Cytokinesis).
            5. Mitotic-Checkpoint: verify invariants -> raise on violation.

        Returns (daughter_a_id, daughter_b_id).
        Raises if mother has multiple disjoint ranges (must be defragmented first).
        """
        if not mother_shard_id or not daughter_a_id or not daughter_b_id:
            raise ValueError("shard-IDs required")
        if daughter_a_id == daughter_b_id:
            raise ValueError("daughter shard-IDs must differ")
        with self._lock:
            mother = self._shards.get(mother_shard_id)
            if mother is None:
                raise KeyError(f"unknown mother_shard_id: {mother_shard_id}")
            if daughter_a_id in self._shards or daughter_b_id in self._shards:
                raise ValueError("daughter shard-ID collision with existing shard")
            if mother.state != ShardState.HEALTHY:
                raise ValueError(
                    f"mother shard {mother_shard_id} not HEALTHY (state={mother.state})"
                )
            if len(mother.slot_ranges) != 1:
                raise ValueError(
                    f"mother shard has {len(mother.slot_ranges)} disjoint ranges; defragment first"
                )
            # Bio: DNA-Replication phase (mark mother SPLITTING).
            mother.state = ShardState.SPLITTING
            try:
                left_range, right_range = mother.slot_ranges[0].split_half()
            except ValueError:
                mother.state = ShardState.HEALTHY  # rollback
                raise
            # Bio: Cell-Cleavage -- create daughter cells.
            half_keys = mother.key_count // 2
            daughter_a = ShardInfo(
                shard_id=daughter_a_id,
                slot_ranges=[left_range],
                state=ShardState.DAUGHTER_NEW,
                parent_shard_id=mother_shard_id,
                key_count=half_keys,
            )
            daughter_b = ShardInfo(
                shard_id=daughter_b_id,
                slot_ranges=[right_range],
                state=ShardState.DAUGHTER_NEW,
                parent_shard_id=mother_shard_id,
                key_count=mother.key_count - half_keys,
            )
            # Bio: Cytokinesis (atomic-swap of slot-map).
            del self._shards[mother_shard_id]
            self._shards[daughter_a_id] = daughter_a
            self._shards[daughter_b_id] = daughter_b
            self._version += 1
            # Mitotic-Checkpoint -- raise if invariant violated.
            self._verify_invariants_locked()
            return (daughter_a_id, daughter_b_id)

    def promote_daughter(self, daughter_id: str) -> None:
        """Daughter-Shard transitions DAUGHTER_NEW -> HEALTHY (post-import-phase)."""
        with self._lock:
            shard = self._shards.get(daughter_id)
            if shard is None:
                raise KeyError(f"unknown shard: {daughter_id}")
            if shard.state != ShardState.DAUGHTER_NEW:
                raise ValueError(
                    f"shard {daughter_id} not in DAUGHTER_NEW state (was {shard.state})"
                )
            shard.state = ShardState.HEALTHY
            self._version += 1

    # ---------------- Mitotic-Checkpoint (Invariant-Verification) ----------------

    def verify_invariants(self) -> None:
        """Public Mitotic-Checkpoint: raise on any topology-violation."""
        with self._lock:
            self._verify_invariants_locked()

    def _verify_invariants_locked(self) -> None:
        """Conservation-Law: all 16384 slots covered exactly once.

        Raises ValueError on violation (gap, overlap, or out-of-range).
        Caller must hold self._lock.
        """
        if not self._shards:
            raise ValueError("cluster has zero shards")
        # Aggregate all ranges, sort by start.
        all_ranges: list[tuple[int, int, str]] = []
        for s in self._shards.values():
            for r in s.slot_ranges:
                all_ranges.append((r.start, r.end, s.shard_id))
        all_ranges.sort()
        # Check coverage [0, TOTAL_SLOTS-1] exactly once.
        if all_ranges[0][0] != 0:
            raise ValueError(
                f"slot 0 not covered (first range starts at {all_ranges[0][0]})"
            )
        prev_end = -1
        for start, end, sid in all_ranges:
            if start != prev_end + 1:
                if start <= prev_end:
                    raise ValueError(
                        f"overlap detected at slot {start} (shard {sid} overlaps prev_end={prev_end})"
                    )
                raise ValueError(
                    f"gap detected: slots [{prev_end+1}, {start-1}] uncovered (before shard {sid})"
                )
            prev_end = end
        if prev_end != TOTAL_SLOTS - 1:
            raise ValueError(
                f"slot {TOTAL_SLOTS-1} not covered (last range ends at {prev_end})"
            )


# CRUX-MK
