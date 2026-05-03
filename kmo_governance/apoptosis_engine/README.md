# KMO Apoptosis-Engine [CRUX-MK]

KMO-vNext Welle-9α Phase-1 Modul 2.2: Programmierter Cell-Tod.

## Bio-Aequivalent

**Caspase-Kaskade.** Initiator-Caspase 8/9 erhaelt Apoptose-Signale, aktiviert
Effector-Caspase 3/7, die Substrate cleavt → kontrollierte Cell-Fragmentierung
OHNE Entzuendung.

- **Bcl-2-Familie:** Anti-Apoptose-Modulatoren (BCL-2, BCL-XL). Hier: `Bcl2Modulator`.
- **Cytochrome-c-Release:** Pre-Death-Snapshot aus Mitochondrien. Hier: `CytochromeCSnapshotter`.

## Architektur

```
ApoptosisEngine (Multi-Signal-Trigger)
   ├── signal(cell_id, hotel_id, trigger, intensity)
   │     └── score = Σ w_i * intensity_i
   │     └── eff_threshold = threshold + log1p(n_active_protections)
   │     └── if score >= eff_threshold: cascade()
   │
   ├── 3-Stage-Cascade (synchron, atomic):
   │     1. INITIAL_CHECK  -> validate
   │     2. EFFECTOR_CASCADE -> snapshot vor Cleanup
   │     3. CLEANUP -> APOPTOSED
   │
   └── Bcl2Modulator (Anti-Apoptose-Lock)
         ├── protect_pending_decision(cell_id, hotel_id, decision_id, ttl_sec) -> token
         └── release_protection(token)

   CytochromeCSnapshotter (atomic-write JSON)
         ├── snapshot(cell_id, hotel_id, reason, score, state, signals) -> Path
         ├── list_for_hotel(hotel_id)
         └── purge_hotel(hotel_id)  # GDPR cascade
```

## Trigger-Types + Default-Weights

| TriggerType | Bio-Aequivalent | Weight |
|-------------|------------------|--------|
| STATE_KORRUPTION | DNA-Damage | 1.0 |
| STOP_FLAG | Death-Receptor (Fas/TNF) | 1000 (immediate) |
| MAX_RETRIES | ER-Stress | 0.5 |
| QUOTA_EXHAUSTED | Glucose-Deprivation | 1.0 |
| HEALTH_CHECK_FAILED | Mitochondrial-Damage | 1.0 |

## Math

```
score(cell)  = Σ w_i * intensity_i
eff_threshold = threshold + log1p(n_active_protections)
P(apoptose)  = sigmoid(score - eff_threshold)
triggered    = score >= eff_threshold
```

## Public API

```python
from kmo_governance.apoptosis_engine import (
    ApoptosisEngine, TriggerType, Bcl2Modulator,
)

engine = ApoptosisEngine()
engine.register_state_provider(lambda cid, hid: get_cell_state(cid, hid))

# Signal a state-corruption event
engine.signal("saga-run-1", "apaleo-eu-hotel-001",
              TriggerType.STATE_KORRUPTION, intensity=1.0)

# Protect a critical decision
bcl2 = Bcl2Modulator()
token = bcl2.protect_pending_decision("saga-run-1", "apaleo-eu-hotel-001",
                                      "approval-pending", ttl_sec=300)
# ... critical work ...
bcl2.release_protection(token)
```

## Integration mit cell_boundary

`CellBoundaryManager.on_quota_exhausted` callback wird in Phase-1.2.4
(Saga-Engine-Integration) zu `engine.signal(..., TriggerType.QUOTA_EXHAUSTED, ...)`
verdrahtet.

## CRUX + LC

- **K11 Cascade-Containment:** Apoptose isoliert pro `(cell_id, hotel_id)`. Kein Spillover.
- **K12 Distillation-Resistenz:** Snapshots enthalten signal-history mit Provenance.
- **K13 Pre-Action-Verification:** Snapshot wird VOR Effector-Cascade geschrieben.
- **K14 Human-Override-Decay:** Bcl-2-Protection als 1-Funktions-Override.
- **K15 Entropy-Budget:** ~470 LoC + 14 Tests = 33.6 LoC/Test.
- **K16 Concurrent-Spawn-Mutex:** RLock im Engine + Modulator.
- **LC1-LC5:** State extern (File-Snapshots), idempotent Cascade, RLock-Isolation.

## Tests

```bash
cd /Users/make/Projects/dark-factories/kmo
python3 -m pytest kmo_governance/apoptosis_engine/tests/ -v
# 14/14 passing (7 Pflicht-Spec + 7 Edge-Cases)
```

## Status

- v0.1.0 (2026-05-01): 14/14 Tests passing.
- pending Cross-LLM-Code-Review (Welle-9α-Pentagon).

[CRUX-MK]
