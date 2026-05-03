---
type: pipeline-flows
version: 0.3.0
crux-mk: true
datum: 2026-04-30
source: test_pre3_e2e_full_pipeline.py + SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30
---

# KMO Pipeline Flows [CRUX-MK]

End-to-End-Sequenzen + Failure-Modes der 6-Patch-Pipeline. Jeder Flow ist 1:1
gegen einen pytest-Test in `tests/test_pre3_e2e_full_pipeline.py` validiert.

Querverweise:
- [01-ARCHITECTURE.md](01-ARCHITECTURE.md) -- Komponenten-Hierarchie
- [03-API-REFERENCE.md](03-API-REFERENCE.md) -- Module-API

---

## 1. Happy-Path E2E (T1)

**Test:** `test_pre3_t1_happy_path_all_6_patches`
**Erwartung:** Alle 7 Saga-Phasen DONE, Outbox-Consumer empfaengt 1 Event.

```mermaid
sequenceDiagram
    autonumber
    participant CTRL as Control-Plane
    participant DCF as A5 DataClassFilter
    participant LM as A1 LeaseManager
    participant AG as A4 ApprovalGate
    participant DSM as A7 DurableStateMachine
    participant SE as A2 SagaEngine
    participant OBP as A3 OutboxProducer
    participant OBC as A3 OutboxConsumer

    Note over CTRL: action_id="happy-001"<br/>prompt="HeyLou test booking action"

    CTRL->>DCF: pre_routing_check(prompt, "claude-opus")
    DCF->>DCF: classify_input -> PUBLIC
    DCF-->>CTRL: RoutingDecision(allowed=True, PUBLIC)

    CTRL->>LM: acquire(DF, "happy-001", holder)
    LM->>LM: respect_stop_flag (none)
    LM->>LM: INSERT OR IGNORE -> UNIQUE OK
    LM-->>CTRL: lease_token (UUID)

    CTRL->>AG: simulated approval_ok=True

    CTRL->>DSM: start_workflow("wf-happy-001")
    DSM->>DSM: append WORKFLOW_STARTED
    DSM-->>CTRL: WorkflowRun(status=RUNNING)

    CTRL->>DSM: transition_phase("init"->"approved")
    DSM->>DSM: append STATE_TRANSITION
    DSM-->>CTRL: WorkflowRun(current_phase="approved")

    CTRL->>SE: register_kmo_phases(7 phases)
    CTRL->>SE: execute("saga-happy-001", initial_input)

    loop 7 KMO-Phasen
        SE->>SE: do_func(input, ctx)
        SE->>SE: exit_criteria check
        SE->>SE: atomic_write_state (tempfile + os.replace)
    end

    SE-->>CTRL: SagaResult(DONE, phases_done=7)

    CTRL->>OBP: publish("kmo-pipeline", payload)
    OBP->>OBP: _next_seq via SQLite
    OBP->>OBP: atomic_write_json
    OBP-->>CTRL: EventEnvelope(seq=1)

    CTRL->>LM: release(lease_token)
    LM-->>CTRL: True

    Note over OBC: Spaeter (Cross-Machine via Drive-Sync)

    OBC->>OBC: subscribe(["kmo-pipeline"], handler)
    OBC->>OBC: poll_and_process()
    OBC->>OBC: _is_processed (No)
    OBC->>OBC: handler(event) -> success
    OBC->>OBC: acknowledge -> ack-file
    OBC-->>CTRL: ConsumerStats(processed=1)
```

**Dauer typisch:** ~50ms (alle 6 Patches in tmp_path-Test). Production-Latenz mit
Drive-Sync-Delay: 2-30s je nach Outbox-Polling-Intervall.

---

## 2. Failure-Mode: SECRET-Block (T2)

**Test:** `test_pre3_t2_data_class_filter_blocks_secret`
**Erwartung:** Pipeline stoppt nach DataClassFilter, kein Lease, kein Saga.

```mermaid
sequenceDiagram
    autonumber
    participant CTRL as Control-Plane
    participant DCF as A5 DataClassFilter
    participant LM as A1 LeaseManager

    Note over CTRL: prompt="API_KEY=sk-1234567890abcdef..."

    CTRL->>DCF: pre_routing_check(prompt, target)
    DCF->>DCF: _detect_secret_patterns
    DCF->>DCF: regex match "api_key" -> SECRET
    DCF->>DCF: is_provider_allowed(SECRET, "claude-opus")
    Note right of DCF: max_data_class=CONFIDENTIAL (3)<br/>SECRET=4 > 3 -> BLOCK
    DCF->>DCF: _append_audit (JSONL)
    DCF-->>CTRL: RoutingDecision(allowed=False,<br/>SECRET, "Mismatch...")

    CTRL->>CTRL: blocked_by="data_class_filter"

    Note over LM: KEIN acquire() -- Pipeline gestoppt

    Note over CTRL: result.lease_token=None<br/>K_0 geschuetzt: kein API-Key-Leak
```

**Audit-Trail:** Jeder Block wird in
`branch-hub/audit/kmo-routing-decisions.jsonl` appended mit
`{"decision":"BLOCK","data_class":"SECRET","detected_patterns":["api_key"]}`.

---

## 3. Failure-Mode: Lease-Conflict (T3)

**Test:** `test_pre3_t3_lease_conflict_blocks_second_pipeline`
**Erwartung:** Zweite Pipeline auf gleicher Resource bekommt `lease_token=None`.

```mermaid
sequenceDiagram
    autonumber
    participant P1 as Pipeline 1
    participant LM as A1 LeaseManager
    participant DB as SQLite-WAL
    participant P2 as Pipeline 2

    P1->>LM: acquire(DF, "shared-resource", holder="first")
    LM->>DB: INSERT INTO leases (..., resource_id="shared-resource")
    DB-->>LM: rowcount=1 (OK)
    LM-->>P1: lease_token_1

    Note over P1: Pipeline 1 arbeitet (haelt Lease)

    P2->>LM: acquire(DF, "shared-resource", holder="second")
    LM->>LM: respect_stop_flag (none)
    LM->>DB: INSERT OR IGNORE INTO leases
    Note right of DB: UNIQUE-Constraint<br/>(resource_type, resource_id)<br/>conflict -> IGNORE
    DB-->>LM: rowcount=0
    LM->>LM: force_release_stale (no stale)
    LM->>DB: retry INSERT OR IGNORE -> still conflict
    LM-->>P2: None

    Note over P2: blocked_by="lease_conflict"<br/>P2 wartet oder gibt auf

    P1->>LM: release(lease_token_1)
    LM->>DB: DELETE FROM leases WHERE lease_id=?
    DB-->>LM: rowcount=1
    LM-->>P1: True

    Note over P1,P2: Jetzt koennte P2 erfolgreich acquiren
```

**Stale-Lease-Recovery:** Wenn P1 crasht ohne release, expires_at < now wird vom
naechsten `acquire()` automatisch via `force_release_stale()` bereinigt. TTL-Default
300s.

---

## 4. Failure-Mode: Saga-Phase-Fail + Compensate (T4)

**Test:** `test_pre3_t4_saga_phase_fail_compensate_lease_released`
**Erwartung:** Phase-3 failt, Phase-2 + Phase-1 werden in Reverse-Order undo'd,
Lease wird in `finally` released.

```mermaid
stateDiagram-v2
    [*] --> P1_Pending
    P1_Pending --> P1_Running: do_func(p1)
    P1_Running --> P1_Done: success
    P1_Done --> P2_Running: do_func(p2)
    P2_Running --> P2_Done: success
    P2_Done --> P3_Running: do_func(p3)
    P3_Running --> P3_Failed: RuntimeError("intentional fail")
    P3_Failed --> Compensating: _compensate()

    state Compensating {
        [*] --> Undo_P2: reverse-chain
        Undo_P2 --> Undo_P1: idempotent
        Undo_P1 --> [*]
    }

    Compensating --> Compensated: all undone
    Compensated --> [*]: SagaResult(COMPENSATED,<br/>phases_done=2,<br/>phases_undone=2)

    note right of P3_Failed
        Phase-3 NIE in undo-chain
        (war NIE DONE).
        Nur P2 und P1 undo.
    end note

    note left of Compensated
        Lease wird im finally:
        gelassen released.
        is_locked() -> None
    end note
```

**Reverse-Chain-Regel:** Nur Phasen mit `status == DONE` werden undo'd. RUNNING/FAILED
werden uebersprungen. Bei Undo-Exception: Status `UNDO_FAILED`, Saga endet
`PARTIAL_COMPENSATION` (Audit-Trail im State).

**Lease-Release-Garantie:** `finally` block in Pipeline-Code (siehe
`_run_full_pipeline`) ruft `release(token)` auch nach Saga-Fail. Test verifiziert
`assert pipeline["lease"].is_locked(...) is None`.

---

## 5. Failure-Mode: Crash-Recovery (T5)

**Test:** `test_pre3_t5_crash_recovery_durable_state_resume`
**Erwartung:** Neue StateMachine-Instanz auf gleichem `state_root` recovert
vollstaendige History.

```mermaid
sequenceDiagram
    autonumber
    participant P1 as Process 1
    participant DSM1 as DurableStateMachine #1
    participant FS as Filesystem<br/>state_root/wf-crash/
    participant DSM2 as DurableStateMachine #2<br/>(neuer Process)
    participant P2 as Process 2

    P1->>DSM1: start_workflow("wf-crash", {"step":0})
    DSM1->>FS: append events.jsonl<br/>WORKFLOW_STARTED seq=1
    DSM1->>FS: fsync
    DSM1-->>P1: WorkflowRun(seq=1)

    P1->>DSM1: transition_phase("init"->"step1", {step:1})
    DSM1->>FS: acquire mkdir-mutex state.lock/
    DSM1->>FS: append STATE_TRANSITION seq=2
    DSM1->>FS: fsync
    DSM1->>FS: release state.lock/
    DSM1-->>P1: WorkflowRun(seq=2, phase="step1")

    P1->>DSM1: transition_phase("step1"->"step2", {step:2})
    DSM1->>FS: append STATE_TRANSITION seq=3
    DSM1-->>P1: WorkflowRun(seq=3, phase="step2")

    Note over P1,DSM1: !!! CRASH !!! Process 1 stirbt

    Note over DSM2: Neuer Process startet

    P2->>DSM2: __init__(state_root)
    DSM2->>FS: state_root/.mkdir(exist_ok=True)
    P2->>DSM2: get_history("wf-crash")
    DSM2->>FS: read events.jsonl
    FS-->>DSM2: 3 events (seq 1,2,3)
    DSM2->>DSM2: parse + sort by sequence
    DSM2-->>P2: [Event_1, Event_2, Event_3]

    P2->>DSM2: recover("wf-crash")
    DSM2->>FS: latest_snapshot? None
    DSM2->>DSM2: WorkflowRun(phase="init", PENDING)
    loop replay events
        DSM2->>DSM2: _apply_event(run, event)
    end
    DSM2-->>P2: WorkflowRun(seq=3, phase="step2",<br/>state_data={step:2})

    Note over P2,DSM2: Workflow vollstaendig recovert<br/>Kein Datenverlust
```

**Snapshot-Strategie:** Default alle 10 Events. Snapshot-Pfad
`state_root/<wf-id>/snapshots/<seq:010d>.json`. Replay nur Events mit
`seq > snapshot.sequence`.

**Konkurrenz-Schutz:** `_acquire_fs_lock()` via `mkdir(exist_ok=False)`. Bei
`FileExistsError` Stale-Check via `mtime > 300s` -> claim. Sonst
`ConcurrentTransitionError`.

---

## 6. Outbox-Idempotency-Flow

**Test:** Implizit in T1 + T5; explizit `test_outbox.py::test_idempotency`.
**Erwartung:** Gleiches Event (gleiche `event_id`) wird zweimal publiziert,
aber nur einmal verarbeitet.

```mermaid
sequenceDiagram
    autonumber
    participant Mac as Mac (Producer)
    participant Drive as branch-hub/outbox/<br/>(Drive-Sync)
    participant Win as Windows (Consumer)
    participant DB as Consumer-SQLite<br/>processed_events

    Mac->>Mac: publish("topic", payload, event_id="fixed-id-1")
    Mac->>Mac: _next_seq -> 1
    Mac->>Drive: atomic_write mac-topic-00000001.json
    Note right of Drive: Drive-Sync repliziert nach Win

    Mac->>Mac: publish("topic", payload, event_id="fixed-id-1")
    Note right of Mac: Race: gleiche event_id<br/>aber neue seq=2 (Producer-side)
    Mac->>Drive: atomic_write mac-topic-00000002.json

    Win->>Win: subscribe(["topic"], handler)
    Win->>Win: poll_and_process()
    Win->>Drive: glob *.json -> 2 files
    Win->>Win: parse mac-topic-00000001.json
    Win->>DB: SELECT WHERE event_id="fixed-id-1" AND last_error IS NULL
    DB-->>Win: None (not processed)
    Win->>Win: handler(event_1) success
    Win->>DB: INSERT processed_events (event_id, success)
    Win->>Drive: write ack-file
    Note over Win: stats.processed=1

    Win->>Win: parse mac-topic-00000002.json
    Win->>DB: SELECT WHERE event_id="fixed-id-1"
    DB-->>Win: row (already processed)
    Win->>Win: skip
    Note over Win: stats.skipped_idempotent=1

    Note over Mac,Win: Result: 2 publishes, 1 process
```

**Retry-Logik bei Handler-Fail:**
```
attempt 1: handler raises -> retry_count=1, last_error="..."
attempt 2: same event polled -> _is_processed=False (last_error NOT NULL)
attempt 3: retry_count=2
attempt 4: retry_count=3 -> move_to_dlq() -> dlq-file
```

DLQ-File enthaelt vollstaendigen Envelope + reason + retry_count fuer
manuelle Re-Inspection.

---

## 7. Cross-Reference: Test-Mapping

| Test | Validiert | Pipeline-Pfad |
|---|---|---|
| `test_pre3_t1_happy_path_all_6_patches` | Happy-Path E2E | [§1](#1-happy-path-e2e-t1) |
| `test_pre3_t2_data_class_filter_blocks_secret` | A5 SECRET-Block | [§2](#2-failure-mode-secret-block-t2) |
| `test_pre3_t3_lease_conflict_blocks_second_pipeline` | A1 UNIQUE-Conflict | [§3](#3-failure-mode-lease-conflict-t3) |
| `test_pre3_t4_saga_phase_fail_compensate_lease_released` | A2 Compensate + Lease-Release | [§4](#4-failure-mode-saga-phase-fail--compensate-t4) |
| `test_pre3_t5_crash_recovery_durable_state_resume` | A7 Replay nach Crash | [§5](#5-failure-mode-crash-recovery-t5) |
| Implicit T1+T5 | A3 Outbox-Idempotency | [§6](#6-outbox-idempotency-flow) |

**Reproduzierbarkeit:**
```bash
cd /Users/make/Projects/dark-factories/kmo
pytest tests/test_pre3_e2e_full_pipeline.py -v
# Erwartung: 5 passed
```

---

## 8. Saga-Phase-Reihenfolge (KMO-7-Phasen)

Aus `phase_registry.py`:

```mermaid
graph LR
    P1[1. Plan] --> P2[2. Spec]
    P2 --> P3[3. Wargame<br/>exit: verdict>=CONDITIONAL]
    P3 --> P4[4. Build]
    P4 --> P5[5. Test<br/>exit: tests_passed]
    P5 --> P6[6. DEV-Demo]
    P6 --> P7[7. Approval/Gerdi<br/>exit: approved]
    P7 --> DONE([SagaStatus.DONE])

    P3 -.fail.-> COMP[Compensate]
    P5 -.fail.-> COMP
    P7 -.fail.-> COMP
    COMP --> COMPED([COMPENSATED])

    classDef phase fill:#fff9c4,stroke:#f57f17
    classDef gate fill:#ffccbc,stroke:#bf360c
    classDef done fill:#c8e6c9,stroke:#2e7d32
    class P1,P2,P4,P6 phase
    class P3,P5,P7 gate
    class DONE,COMPED done
```

**Exit-Criteria-Gates** (3 Gates in 7 Phasen):
- **Wargame (P3):** `verdict in {CONDITIONAL, SIM-HARDENED, 2OF3-HARDENED, HARDENED}`
- **Test (P5):** `tests_passed == True`
- **Approval (P7):** `approved == True`

Bei Gate-Fail: Compensate-Chain via `_compensate()`, alle vorherigen DONE-Phasen
werden in Reverse-Order undo'd.

[CRUX-MK]
