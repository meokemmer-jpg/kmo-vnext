# KMO Wound-Healing [CRUX-MK]

KMO-vNext Welle-9α Phase-1 Modul 2.3: 4-Phase Recovery-Lifecycle nach Saga-FAILED.

## Bio-Aequivalent

**Wound-Healing-Process.** Statt direkter Saga-Compensation (= sofortiger Tod
+ Reverse-Undo) eine strukturierte Recovery durchlaufen:

| Phase | Bio-Analogie | Software-Aktion |
|-------|--------------|------------------|
| HEMOSTASIS | Blutgerinnung | Circuit-Break, Failure-Containment |
| INFLAMMATION | Macrophage-Cleanup | Garbage-Collection, State-Reset |
| PROLIFERATION | Tissue-Neubildung | Auto-Restart, State-Reconstruction |
| REMODELING | Narben-Umbau | Gradual Re-Optimization, Schema-Migration |
| HEALED | Heil | terminal-success |
| ABORTED | Tod | terminal-failure |

## State-Machine (DAG)

```
NOT_STARTED -> HEMOSTASIS -> INFLAMMATION -> PROLIFERATION -> REMODELING -> HEALED
              ↘          ↘             ↘                 ↘             ↘
                          ABORTED  (jederzeit terminal)
```

## Public API

```python
from kmo_governance.wound_healing import WoundHealingLifecycle, HealingPhase

healing = WoundHealingLifecycle(
    saga_run_id="saga-run-1",
    hotel_id="apaleo-eu-hotel-001",
    cleanup_callback=lambda ctx: free_locks(ctx.saga_run_id),
    restart_callback=lambda ctx: rerun_saga(ctx.saga_run_id),
    optimize_callback=lambda ctx: schema_migrate_v2(ctx.saga_run_id),
)
healing.start_hemostasis(failure_reason="phase-3-timeout")
healing.transition_to_inflammation()
healing.transition_to_proliferation()
healing.transition_to_remodeling()
healing.complete()

# MTTR snapshot
print(healing.metrics.snapshot())
```

## Integration mit Saga-Engine

Phase-1.2.4 (Task-4) wired Saga-on-failure-Handler:

```python
def saga_on_failure(saga_run, failure_reason):
    healing = WoundHealingLifecycle(
        saga_run_id=saga_run.run_id,
        hotel_id=saga_run.hotel_id,
        cleanup_callback=lambda ctx: saga._compensate(saga_run),
        restart_callback=lambda ctx: saga.resume(saga_run.run_id),
    )
    healing.start_hemostasis(failure_reason)
    # ... gradual phase transitions ...
```

## CRUX + LC

- **K11 Cascade-Containment:** Hemostasis isoliert Failure pro saga_run.
- **K13 Pre-Action-Verification:** Phase-Transitionen DAG-validiert.
- **K15 Entropy-Budget:** ~400 LoC + 10 Tests = 40 LoC/Test.
- **LC1 Graceful-Degradation:** alle Callbacks optional (None = no-op).
- **LC4 Failure-Isolation:** Callback-Exceptions nicht durchgereicht (state-machine bleibt advancing).

## Tests

```bash
cd /Users/make/Projects/dark-factories/kmo
python3 -m pytest kmo_governance/wound_healing/tests/ -v
# 10/10 passing (7 Pflicht + 3 Edge-Cases)
```

[CRUX-MK]
