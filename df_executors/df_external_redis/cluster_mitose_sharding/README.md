# Redis-Cluster Mitose-Sharding [CRUX-MK]

Welle-30-Iter-2 W-30R-2: Echte fremde Domain (Redis-Cluster Hash-Slot-Sharding).
Mitose-Pattern (Cell-Division) adaptiert auf Cluster-Resharding.

## Domain-Mapping (Bio -> Tech, echt extern)

| Biologie (Mitose / Cell-Division)       | Tech (Redis-Cluster Sharding)                    |
|-----------------------------------------|--------------------------------------------------|
| Mother-Cell                              | Original Redis-Shard (single contiguous slot-range) |
| DNA-Replication                          | Hash-Slot-Range Duplication                       |
| Spindle-Apparatus                        | Resharding-Coordinator (Mitose-Orchestrator)      |
| Daughter-Cells                           | Daughter-Shards (50/50 Hash-Slot-Split)           |
| Mitotic-Checkpoint                       | Conservation-Law Validator                        |
| Cytokinesis                              | Topology-Atomic-Swap + Daughter-Promotion         |
| Anaphase (Chromatid-Migration)           | Key-Migration (mother-store -> daughter-stores)    |

Pattern-Reuse: Mitose ist konzeptionelle Inspiration; Implementation nutzt klassisches
Hash-Slot-Splitting (16384 slots, CRC16 mod-equivalent), keine Bio-Library.

## Module-Aufbau

| Datei                              | Verantwortung                                                  |
|------------------------------------|----------------------------------------------------------------|
| `redis_cluster_topology.py`        | ShardInfo + SlotRange + Conservation-Law Invariants            |
| `redis_mitose_orchestrator.py`     | Mitose-Cycle: decide_to_split + execute_mitose + key-migration |
| `redis_resharding_validator.py`    | Mitotic-Checkpoint: Conservation-Law (lost/duplicated/wrong-shard) |
| `tests/test_redis_mitose.py`       | 16 Tests inkl. 3 echter Threading-Tests                         |

## Anwendung

```python
from df_executors.df_external_redis.cluster_mitose_sharding import (
    RedisClusterTopology,
    RedisMitoseOrchestrator,
    RedisReshardingValidator,
)

# 1. Genesis topology: single shard owns all 16384 slots.
topo = RedisClusterTopology()
topo.get_shard("shard-genesis").key_count = 5000  # simulate load

# 2. Orchestrator decides + executes mitose.
orch = RedisMitoseOrchestrator(topo, load_threshold=1000)
kv_store = {"shard-genesis": {f"key-{i}": f"v-{i}" for i in range(5000)}}
pre_keys = set(kv_store["shard-genesis"].keys())

events = orch.run_cycle(kv_store)
# events[0].outcome == MitoseOutcome.DIVIDED
# kv_store now contains "shard-0001" + "shard-0002" with ~50/50 split

# 3. Conservation-Law validation (Mitotic-Checkpoint).
validator = RedisReshardingValidator(topo)
report = validator.validate(pre_keys=pre_keys, post_kv_store=kv_store)
assert report.passed   # 0 keys lost, 0 duplicated, full slot-coverage
```

## Architecture-Note

**Externer Domain-Score**: 5/5

Begruendung:
1. **Redis-Cluster** ist canonical externer Tech-Stack (https://redis.io/docs/management/scaling/), kein Kemmer-Bezug.
2. **16384 Hash-Slots** und **CRC16(key) mod 16384** sind Redis-Cluster-Spec-konform.
3. **MOVED/ASK Resharding-Protokoll** ist Industriestandard fuer Distributed-KV-Stores (vgl. Cassandra Token-Ranges, DynamoDB Partitions).
4. **Mitose (Cell-Division)** liefert nur konzeptionelle Inspiration; Code nutzt klassische Slot-Range-Bisektion + atomic-swap, kein biologisches Modell.
5. **KEINE Imports** aus `crux/`, `kmo_governance/`, `infrastructure/`, oder Kemmer-Konstanten. Pure Redis-Domain.

Vergleich zu W-30R-1 (NGINX Quorum-Consensus):
- W-30R-1: Bacterial-Quorum-Sensing -> 3-of-5 Threshold-Voting (NGINX-Cluster-Config)
- W-30R-2: Mitose -> Cell-Division-Sharding (Redis-Cluster-Slots)
- Beide: Bio-Pattern-Reuse als architektonische Inspiration; Tech-Implementation Industriestandard.

## Test-Coverage

| Test-Klasse                                      | Tests | Threading | Race-Condition |
|--------------------------------------------------|-------|-----------|----------------|
| Topology / SlotRange (Math + Invariants)         |   4   | -         | -              |
| Orchestrator (decide + execute + run_cycle)      |   5   | -         | -              |
| Validator (Conservation-Law: lost / dup / coverage) |   3   | -         | -              |
| Threading / Race-Conditions                       |   3   | YES       | YES            |
| End-to-End (2-Generation Mitose)                  |   1   | -         | -              |
| **Total**                                         | **16**| **3 echt**| **3 echt**     |

Echte `threading.Thread`-Tests:
1. `test_concurrent_topology_reads_during_split` -- 50 Reader-Threads + 1 Splitter; alle Snapshots Conservation-Law-konform
2. `test_concurrent_split_attempts_idempotent_on_duplicate_ids` -- 20 Threads attempt gleiche daughter-IDs; exakt 1 gewinnt
3. `test_concurrent_key_lookups_during_resharding` -- 30 Threads `find_shard_for_key` waehrend Mitose; 100% Coverage erhalten

## Conservation-Law (Mitotic-Checkpoint)

Pflicht-Invariants nach jeder Mitose:
- **NoLoss**: jeder pre-mitose key existiert in genau einem daughter (`KEY_LOST` ausgeschlossen)
- **NoDuplicate**: kein key in 2+ daughters (`KEY_DUPLICATED` ausgeschlossen)
- **CorrectPlacement**: key in shard liegt nur dort, wenn dessen slot-range den CRC16-slot enthaelt
- **FullCoverage**: union aller slot-ranges == [0, 16383] (kein gap, kein overlap)

`RedisReshardingValidator.validate()` prueft alle 4 in einem Pass.

## CRUX-Bindung

- **Q_0** (epistemische Integritaet): Echte externe Generalisations-Validation (Redis-Cluster != Kemmer-Domain).
- **W_0** (Pattern-Reuse): Mitose-Konzept aus Bio-Wissenschaft als architektonische Inspiration; KEIN Code-Reuse von W-30R-1 (NGINX Quorum-Sensing) oder kmo_governance.
- **K11 Cascade-Containment**: Mitose-Failure (Conservation-Law-Violation) raised vor Cytokinesis -> Topology bleibt vorherigem Zustand isoliert.
- **K13 Pre-Action-Verification**: invariant-check vor jedem split (mother HEALTHY, single contiguous range, width >= 2*MIN_SLOTS_PER_SHARD).

## rho-Schaetzung Redis-Domain

- **Real-World-Anwendung**: jedes Multi-Tenant Redis-Cluster-Deployment (zehntausende EUR Engineering-Hours/Jahr fuer Resharding-Automation; vgl. Twemproxy, Codis, KeyDB-Cluster).
- **Kemmer-Spezifisch**: 0 EUR direkter Anwendungs-Wert (rein Anti-Cargo-Cult-Validation der Welle-30-These "Externalitaet ist nicht Illusion").
- **Indirekt**: Validation des Bio-Pattern-Reuse-Ansatzes auf 2. Domain (nach NGINX); falls W-30R-3 ebenfalls erfolgreich -> Welle-30-Aggregat-Verdict gilt empirisch widerlegt (Bio-Pattern-Generalisation ist machbar mit Disziplin).

## Welle-30-Iter-2 Bilanz (post W-30R-2)

| Domain         | Score | Bio-Pattern              | Status        |
|----------------|-------|--------------------------|---------------|
| W-30R-1 NGINX  |  5/5  | Bacterial-Quorum-Sensing | done          |
| W-30R-2 Redis  |  5/5  | Mitose / Cell-Division   | done          |
| W-30R-3 ?      |  ?/5  | ?                         | pending       |

# CRUX-MK
