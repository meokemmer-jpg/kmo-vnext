"""Redis-Cluster Mitose-Sharding -- Cell-Division Pattern fuer Hash-Slot-Resharding [CRUX-MK].

Domain-Mapping (Bio -> Tech, echt extern):
- Mother-Cell                 -> Original Redis-Shard (single contiguous slot-range)
- DNA-Replication             -> Hash-Slot-Range Duplication
- Spindle-Apparatus           -> Resharding-Coordinator (Mitose-Orchestrator)
- Daughter-Cells              -> Daughter-Shards (50/50 Hash-Slot-Split)
- Mitotic-Checkpoint          -> Conservation-Law Validator
- Cytokinesis                 -> Final Topology-Atomic-Swap

Externer Domain: Redis-Cluster (https://redis.io/docs/management/scaling/).
Hash-Slots: 16384 (Redis-Standard, CRC16(key) mod 16384).
Resharding: classic MOVED/ASK redirection-protocol equivalent.

Welle-30-Iter-2 echt-extern Anti-Cargo-Cult-Validation:
- KEINE crux/governance Imports
- KEINE Kemmer-spezifischen Konstanten
- Pure Redis-Cluster-Domain mit Bio-Pattern-Inspiration

K11 Cascade-Containment: Mitose-Failure isoliert; topology-rollback bei Mitotic-Checkpoint-Fail.
K13 Pre-Action-Verification: invariant-check before AND after each split.
"""

from .redis_cluster_topology import (
    MAX_SHARD_COUNT,
    MIN_SHARD_COUNT,
    MIN_SLOTS_PER_SHARD,
    RedisClusterTopology,
    ShardInfo,
    ShardState,
    SlotRange,
    TOTAL_SLOTS,
    TopologySnapshot,
    crc16_slot,
)
from .redis_mitose_orchestrator import (
    DEFAULT_LOAD_THRESHOLD,
    DEFAULT_MIGRATION_BATCH_SIZE,
    DEFAULT_MIN_KEYS_PER_HALF,
    MitoseEvent,
    MitoseOutcome,
    RedisMitoseOrchestrator,
)
from .redis_resharding_validator import (
    ConservationViolation,
    RedisReshardingValidator,
    ValidationFinding,
    ValidationReport,
)

__all__ = [
    # topology
    "RedisClusterTopology",
    "ShardInfo",
    "ShardState",
    "SlotRange",
    "TopologySnapshot",
    "crc16_slot",
    "TOTAL_SLOTS",
    "MIN_SLOTS_PER_SHARD",
    "MIN_SHARD_COUNT",
    "MAX_SHARD_COUNT",
    # orchestrator
    "RedisMitoseOrchestrator",
    "MitoseEvent",
    "MitoseOutcome",
    "DEFAULT_LOAD_THRESHOLD",
    "DEFAULT_MIN_KEYS_PER_HALF",
    "DEFAULT_MIGRATION_BATCH_SIZE",
    # validator
    "RedisReshardingValidator",
    "ConservationViolation",
    "ValidationFinding",
    "ValidationReport",
]

# CRUX-MK
