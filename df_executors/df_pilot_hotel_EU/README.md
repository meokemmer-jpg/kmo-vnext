# KMO HeyLou-Pilot Hotel-EU [CRUX-MK]

Welle-9α Phase-1.2.5 Pilot. Single-Hotel Cell-Layer Integration.

## Pilot-Hotel

**EU-Apaleo (Architekt-Empfehlung).** GDPR-Stringenz + niedrigerem Risk wegen
EU-Datenschutz-Mandat als Pilot-Stage 1.

## Architektur (Cell-Layer-Stack zusammen-orchestriert)

```
PilotHotelOrchestrator (1 Hotel-ID, 1 BoundaryAuditLog, 1 ApoptosisEngine, 1 SagaEngine)
   ├── begin_saga_run(run_id) -> CellBoundaryManager + QuotaEnforcer
   │     ├── CellBoundary (cell_id=run_id, hotel_id=pilot.hotel_id, quota)
   │     ├── on_quota_exhausted -> ApoptosisEngine.signal(QUOTA_EXHAUSTED)
   │     └── QuotaEnforcer (charges + audit-log per hotel)
   │
   ├── execute_saga(run_id, input) -> SagaResult
   │     ├── Saga registriert Cell-Layer-Hooks via:
   │     │     - set_cell_quotas(quota)
   │     │     - register_apoptosis_handler(_on_quota_exhausted)
   │     │     - enable_wound_healing(_healing_factory)
   │     └── Beim Saga-FAILED: WoundHealingLifecycle gestartet (Hemostasis ->...->HEALED)
   │
   └── purge_hotel() -> GDPR cascade-delete (audit-events + apoptose-snapshots)
```

## Pre-Production-Tests (PRE-3 / PRE-4 / PRE-5)

Spec §Phase-1.2.5 Pflicht-Tests:

| Test-Klasse | Was wird verifiziert | Tests |
|-------------|----------------------|-------|
| **PRE-3 E2E** | Full booking-pipeline through Cell-Layer | 2 |
| **PRE-4 Shared-Path** | GDPR cascade + Multi-Tenancy isolation | 2 |
| **PRE-5 Stress** | 100/200-thread concurrent quota-consume | 2 |
| Edge | Constructor-validation | 1 |
| **Total** | | **7** |

## Setup + Tests

```bash
cd /Users/make/Projects/dark-factories/kmo
python3 -m pytest df_executors/df_pilot_hotel_EU/tests/ -v
# 7/7 passing
```

## Public API

```python
from df_executors.df_pilot_hotel_EU import PilotHotelOrchestrator
from kmo_governance.cell_boundary import CellQuota

pilot = PilotHotelOrchestrator(
    hotel_id="apaleo-eu-pilot-001",
    state_dir="/var/kmo/pilot/state",
    quota=CellQuota(llm_token_budget=50_000, cpu_seconds=300),
)

# Register saga phases (existing API)
pilot.saga.register_phase("p1", "Phase1", do_fn, undo_fn)
pilot.saga.register_phase("p2", "Phase2", do_fn2, undo_fn2)

# Execute through Cell-Layer
result = pilot.execute_saga("booking-run-1", {"booking_id": "bk-1"})

# Forensics
cell = pilot.get_cell_state("booking-run-1")     # consumed_tokens, is_apoptosed, ...
apop = pilot.get_apoptose_state("booking-run-1") # cascade_stage, snapshot_path, signals
heal = pilot.get_healing("booking-run-1")        # phase, MTTR-metrics

# GDPR cascade
pilot.purge_hotel()  # deletes audit-events + apoptose-snapshots for this pilot
```

## CRUX-Konformitaet

- **K_0:** geschuetzt durch Cell-Quota-Caps + Wound-Healing (kein Datenverlust durch Crashes)
- **Q_0:** epistemische Integritaet via Audit-Trail mit Provenance-Hashes
- **K11 Cascade-Containment:** Cell + Apoptose isolieren Failure pro saga_run
- **K13 Pre-Action-Verification:** Hotel-ID-Scoping + Quota-Check vor jeder Aktion
- **K14 Override-Decay:** purge_hotel als 1-Funktions-GDPR-Override
- **K15 Entropy-Budget:** ~270 LoC + 7 Tests = 38.6 LoC/Test
- **LC1-LC5:** Alle Cell-Layer-Modules sind dependent-isolation-conform

## Welle-7-Pre-Production-Status

- **PRE-3 E2E:** ✅ 2 Tests passing
- **PRE-4 Shared-Path:** ✅ 2 Tests passing
- **PRE-5 Stress:** ✅ 2 Tests passing (100-threads + 200-threads-overflow)
- **Demo-Materialien fuer Martin-Freigabe:** in WELLE-9-ALPHA-PHASE-1-PROGRESS.md

## Status

- v0.1.0 Skeleton (2026-05-02): 7/7 Tests passing
- pending Cross-LLM-Wargame Welle-9α-Final-Mess (Task 6)
- pending Echte HeyLou-Hotel-Anbindung (Mo 4-6 Real-Implementation laut Spec)

[CRUX-MK]
