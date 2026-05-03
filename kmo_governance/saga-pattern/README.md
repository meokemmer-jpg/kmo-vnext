# KMO Saga-Engine (P-KMO-A2)

Saga-Pattern Engine fuer KMO-Dark-Factory mit do/undo pro Phase, Reverse-Chain Compensation und Crash-Recovery via persistente State-Machine.

## Spec
SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30 §P-KMO-A2

## Files
- `kmo_saga_engine.py` — `SagaEngine`, `SagaPhase`, `SagaRun`, `SagaResult` Dataclasses + Engine-Logic
- `phase_registry.py` — KMO-7-Phasen-Pipeline (Plan/Spec/Wargame/Build/Test/DEV-Demo/Approval-Gerdi) mit do/undo Stubs + Exit-Criteria
- `tests/test_saga_engine.py` — Pytest-Suite

## Phasen
1. Plan -> 2. Spec -> 3. Wargame -> 4. Build -> 5. Test -> 6. DEV-Demo -> 7. Approval/Gerdi

## API
```python
from kmo_saga_engine import SagaEngine
from phase_registry import register_kmo_phases

engine = SagaEngine(state_dir="branch-hub/workflow-state/")
register_kmo_phases(engine)
result = engine.execute(saga_run_id="kmo-run-001", initial_input={...})
# Crash? Resume:
result = engine.resume(saga_run_id="kmo-run-001")
status = engine.get_status("kmo-run-001")
```

## Verhalten
- **Happy-Path:** Alle 7 Phasen DONE -> SagaStatus.DONE
- **Phase-Fail:** Phase-N fail -> reverse-chain undo: Phase-(N-1), ..., Phase-1 -> SagaStatus.COMPENSATED
- **Undo-Fail:** SagaStatus.PARTIAL_COMPENSATION (Audit-Trail im State)
- **Crash:** RUNNING-Phase bei resume() -> FAILED -> Compensation
- **Exit-Criteria:** Phase-Output blockiert -> Compensation

## State-Persistenz
- Atomic-Write: tempfile + os.replace + fsync
- Pfad: `<state_dir>/<saga-run-id>-state.json`
- Schema: SagaRun mit phases[], current_phase_idx, overall_status, timestamps

## Tests
```
pytest tests/test_saga_engine.py -v
```
9 Tests: happy-path, fail-undo-chain, partial-compensation, crash-recovery, exit-criteria, duplicate-phase, unknown-resume, idempotent-resume, atomic-write.

## CRUX-Bindung
- **K_0:** Reverse-Chain Compensation verhindert Substanzverzehr durch partielle Commits
- **Q_0:** Exit-Criteria-Gate plus Audit-Trail in State
- **I_min:** Strukturierte 7-Phasen-Pipeline mit explizitem Lifecycle
- **W_0:** Crash-Recovery vermeidet Re-Run-Kosten

[CRUX-MK]
