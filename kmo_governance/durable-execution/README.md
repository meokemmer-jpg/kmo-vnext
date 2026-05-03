# KMO Durable-Execution-State-Machine (P-KMO-A7)

Persistente Self-Built JSON-State-Machine fuer langlaufende 7-Phasen-Workflows.
Conservative-Pick gemaess Architekt-Empfehlung -- **kein** Temporal.io.

## Spec
SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30 §P-KMO-A7

## Files
- `kmo_durable_state_machine.py` -- `DurableStateMachine` Engine + `WorkflowRun` Dataclass.
- `event_types.py` -- `EventType` Enum + `Event` Dataclass + 5 Helfer-Konstruktoren
  (`make_routing_decision`, `make_df_status_change`, `make_stop_flag_transition`,
  `make_approval_state`, `make_state_transition`).
- `tests/test_durable_state_machine.py` -- pytest-Suite (15 Tests).

## API
```python
from kmo_durable_state_machine import DurableStateMachine
from event_types import EventType

sm = DurableStateMachine(state_root="branch-hub/workflow-state/")

# Start
run = sm.start_workflow("kmo-run-001", initial_state={"target": "df-86"})

# Phase-Transitions (haeufigster Pfad)
run = sm.transition_phase(
    "kmo-run-001", from_phase="init", to_phase="plan", state_patch={"plan_done": True}
)

# Domain-Events (4 KMO-Klassen)
sm.transition("kmo-run-001", EventType.ROUTING_DECISION, payload={
    "phase": "build", "chosen_target": "df-86",
    "candidates": ["df-86", "df-87"], "rationale": "lowest-load",
})

# Crash? Neuer Prozess, gleicher state_root:
sm2 = DurableStateMachine(state_root="branch-hub/workflow-state/")
recovered = sm2.recover("kmo-run-001")  # Latest snapshot + replay newer events

# Snapshot manuell (auto-snapshot alle N Events default 10)
sm.snapshot("kmo-run-001")

# History
events = sm.get_history("kmo-run-001")
```

## Storage-Layout
```
<state_root>/<workflow-id>/
  events.jsonl            # append-only event-log, ein Event pro Zeile
  snapshots/<seq>.json    # periodische State-Snapshots (Default alle 10 Events)
  state.lock/             # mkdir-Mutex fuer Concurrent-Transition-Safety
```

## Event-Klassen (4 KMO-Pflicht + 3 System)
- `ROUTING_DECISION`     -- Welche DF/Agent uebernimmt eine Phase
- `DF_STATUS_CHANGE`     -- Dark-Factory Status-Wechsel (IDLE/RUNNING/DONE/FAIL)
- `STOP_FLAG_TRANSITION` -- STOP.flag gesetzt/geloescht
- `APPROVAL_STATE`       -- Approval-Gate-Antwort (Gerdi/Martin/auto)
- `WORKFLOW_STARTED`     -- System: Workflow-Init
- `STATE_TRANSITION`     -- System: Phase-Wechsel + state-patch
- `SNAPSHOT_TAKEN`       -- System: Marker fuer Snapshot

## Crash-Recovery-Modell
1. Event-Log ist append-only mit fsync nach jedem Append.
2. Bei Restart: latest Snapshot laden -> Replay aller Events mit `seq > snapshot.seq`.
3. Materialisierte `WorkflowRun` enthaelt aktuelle `current_phase`, `state_data`, `sequence`.

## Concurrency
- Process-lokal: `threading.RLock`.
- Cross-Process: `state.lock/` als atomic-mkdir-Mutex mit Stale-Lock-TTL (Default 300s).
- Sequence-Nummern werden unter Lock vergeben -> keine Luecken, keine Duplikate.

## Tests
```
pytest tests/test_durable_state_machine.py -v
```
15 Tests: start/transition/duplicate-reject/seven-phase-happy-path,
crash-recovery (3 Varianten), event-sourcing-replay (2 Varianten),
snapshot/auto-snapshot, concurrent-race + stale-lock-claim, helper-constructors,
list_workflows, events.jsonl-Format-Validitaet.

## CRUX-Bindung
- **K_0:** Crash-Recovery + atomic-fsync verhindern Lost-Commits.
- **Q_0:** Immutable Event-Sourcing-Audit-Trail erfuellt §K12 Distillation-Resistenz.
- **I_min:** Strukturiertes 7-Phasen-Modell mit explizitem Lifecycle.
- **W_0:** Snapshot-amortisierte Replay-Kosten reduzieren Restart-OPEX.

## Pre-Action-Verification (CLAUDE.md §0 [PRE-ACTION-VERIFICATION-PFLICHT])
Caller-Verantwortung. State-Machine selbst greift nur auf das uebergebene
`state_root` zu (lokal). Bei `state_root` auf Drive-Sync-Path: aufrufende Schicht
muss env_tag + Backup-Status + Replication-Lag pruefen.

[CRUX-MK]
