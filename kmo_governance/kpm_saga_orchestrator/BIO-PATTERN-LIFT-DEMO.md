# Bio-Pattern-Lift Demo: kpm_saga_orchestrator [CRUX-MK]

**Welle-27 Phase-20 KMO-vNext Bio-Pattern-Lift.**
**Quelle:** `kmo_governance/saga_step_orchestrator` (Welle-9, DAG-basiert).
**Bio-Aequivalent:** Mitose-Phasen-Sequencing (5 strikt geordnete Phasen + Cytokinesis-Reverse-on-Failure).

## Pattern-Mapping

| Hotel (saga_step_orchestrator) | Trading (kpm_saga_orchestrator) | Mitose-Phase (Biologie) |
|---|---|---|
| `SagaStep.depends_on` (DAG-Edges) | `SagaPhase`-Enum (linear 5-Phase) | Cell-Cycle-Checkpoints (G1->S->G2->M) |
| `step.phase` ALLOCATE/EXECUTE/CONFIRM (custom strings) | `SagaPhase.VALIDATE` | Prophase (Cell-Prep, Chromatin-Condensation) |
| - | `SagaPhase.RESERVE` | Metaphase (Alignment am Spindelaequator) |
| `step.forward_fn` | `SagaPhase.EXECUTE` (handler_fn) | Anaphase (Chromosomen-Separation) |
| - | `SagaPhase.CONFIRM` | Telophase (Nuclear-Envelope-Reform) |
| - | `SagaPhase.SETTLE` | Cytokinesis (Cell-Division-Final) |
| `compensate_fn` | compensator-Registry (`register_compensator`) | Apoptose-Reverse / Cytokinesis-Cancel |
| `topological_sort()` | sequentielle Steps-Liste | Cell-Cycle-Checkpoint-Order |
| `SagaStepResult.status=FAILED` | `SagaState.FAILED` | Apoptosis-Trigger |
| `compensate(failed_id)` reverse-DAG | auto-Compensation reverse-completed | Cytokinesis-Reverse / Cell-Cycle-Arrest |
| `SagaStepGraph` (DAG-Validation) | implicit linear State-Machine | Cell-Cycle-Linear-Order |
| `RetryPolicy` | (nicht uebernommen — Trading verlangt fail-fast) | (nicht-anwendbar) |
| `CycleDetectedError` | (nicht-anwendbar — kein DAG) | (Cell-Cycle ist DAG-frei) |
| - | `SagaState.COMPENSATING` (cancel_in_progress) | Cell-Cycle-Arrest (G2/M-Checkpoint) |
| `SagaStepResult` | `SagaOutcome` (aggregierte Saga-View) | Cell-Cycle-Final-Outcome |
| - | `compensation_log` (tuple-of-(step,phase,status)) | Apoptosis-Audit (Caspase-Cascade-Log) |

## Domain-Adjustments (Trading vs Hotel)

### Linear 5-Phase-State-Machine statt DAG-Topology

**Begruendung:** Multi-Leg-Order ist inhaerent sequentiell:
- VALIDATE muss vor RESERVE (Margin-Pre-Check vor Capital-Lock)
- RESERVE muss vor EXECUTE (Capital muss reserviert sein vor Order-Submission)
- EXECUTE muss vor CONFIRM (Order am Markt vor Broker-Ack-Erwartung)
- CONFIRM muss vor SETTLE (Fill bestaetigt vor Position-Buchung)

DAG-Flexibilitaet (parallele Branches via `depends_on`) wird NICHT benoetigt.
Wenn ein Multi-Leg-Trade 3 Legs hat, sind das 3 SAGAS (1 pro Leg) oder 1 Saga
mit 3 Steps die ALLE 5 Phasen durchlaufen — beides linear, nicht DAG.

Hotel-Vorlage hatte legitime DAG-Use-Cases (z.B. Reservation + Payment +
Email parallelisierbar nach Reservation-Confirm). Trading hat das nicht —
Order-Atomicity verlangt strenge Phasen-Ordnung.

### Saga-Granularitaet: 1 Saga = 1 Multi-Leg-Trade

**Begruendung:** Im Trading ist Saga-Atomicity scope-relevant:
- 1 Pairs-Trade (Long AAPL + Short MSFT) = 1 Saga mit 2 Steps
- 1 Spread-Order (Buy Call + Sell Call) = 1 Saga mit 2 Steps
- 1 Basket-Rebalance (10 Instruments) = 1 Saga mit 10 Steps

Concurrent Sagas (mehrere parallele Trades) via separate `saga_id`. Der
Orchestrator isoliert sie via `_in_progress` + `_outcomes` dict (RLock).

### Compensation-Registry pro Phase (statt pro Step)

**Begruendung:** Compensation-Logik ist phase-typisch, nicht step-typisch:
- VALIDATE-Compensation: no-op (kein Side-Effect)
- RESERVE-Compensation: Margin-Release (broker-API-Call)
- EXECUTE-Compensation: Reverse-Order-Submission (gegenteilige Order)
- CONFIRM-Compensation: Cancel-Pending-Order (broker-API)
- SETTLE-Compensation: Position-Reverse-Booking + Audit-Trail-Mark

Hotel-Vorlage hatte pro-Step `compensate_fn` als Closure. Trading-Pattern
profitiert von zentraler Phase-Registry: Broker-Adapter registriert 1x
seine 5 Phase-Compensators, alle Sagas nutzen sie.

### Action-Data als tuple-of-tuples (frozen-friendly)

**Begruendung:** `SagaStep` ist frozen-Dataclass. Dict-Felder waeren NICHT
frozen-vertraeglich (dict ist mutable). Tuple-of-tuples bleibt hashable
und immutable. Konversion zur Laufzeit:

    action = dict(step.action_data)  # in handler_fn

Hotel-Vorlage hatte `forward_fn: Callable[[], Any]` — closure mit captured
state. Trading-Pattern macht state explizit (action_data) damit der Step
serialisierbar wird (Audit-Trail, Restart-from-checkpoint).

### Cancel-Mechanismus (cancel_in_progress)

**Begruendung:** Trading hat externe Stop-Signale (Risk-Limit-Breach,
Market-Halt, Strategy-Kill-Switch). Eine laufende Saga muss graceful
abbrechen koennen — ohne in den naechsten Step einzutreten, aber mit
Compensation aller bis-dahin-completed Steps.

Hotel-Vorlage hatte das nicht (keine Cancel-Semantik, lediglich
post-hoc `compensate(failed_id)`). Trading-Pattern fuegt `_in_progress`-
State + Pre-Step-Cancel-Check hinzu.

### Compensation-Log-Format

**Begruendung:** MiFID-RTS-25-Pflicht: Audit-Trail muss enthalten WAS
kompensiert wurde (step_id), WANN (Phase), WIE (compensated /
compensation-failed). Tuple-of-tuples macht es JSON-serialisierbar fuer
externe Compliance-Logs.

    compensation_log = (
        ("s3", "execute", "handler-failed: RuntimeError: broker rejected"),
        ("s2", "reserve", "compensated"),
        ("s1", "validate", "compensated"),
    )

Hotel-Vorlage hatte die Info implizit via `SagaStepResult.status` + 
`error`-Feld; Trading-Pattern macht es explizit aggregiert.

## Cross-LLM-Audit-Status

CONDITIONAL bis Cross-LLM-Validierung mit Codex GPT-5.5 + Gemini 2.5 Pro
post-Welle-27-Phase-20. Pflicht per `rules/cross-llm-pflicht-e3-plus.md`
(E3 — Methoden-Audit ueber KPM-Domain-Adjustments).

**Pre-Audit-Checkliste:**
- [ ] Linear-5-Phase vs DAG-Hybrid (Multi-Leg-Tree-Trade-Use-Case?)
- [ ] handler_fn Return-Typ `dict` ausreichend? (vs typed-Pydantic-Model)
- [ ] Compensation-Failure-Behavior: degraded-FAILED-State korrekt?
- [ ] cancel_in_progress: Inter-Step-Granularitaet ausreichend
      oder muessen Handler interruptible sein (z.B. via threading.Event)?
- [ ] Locking: RLock vs Lock-Free-Atomic-Dict (Performance bei
      Lambda > 1000 Sagas/s)
- [ ] saga_id-Collision: was passiert bei Re-Use (heutige Logik:
      `_outcomes[saga_id]` ueberschrieben)? Validation gewuenscht?

## Falsifikations-Bedingung

Pattern-Lift falsifiziert wenn:
- Multi-Leg-Trades brauchen DAG-Topology (z.B. Conditional-Order-Trees:
  "If Leg-1 fills, then submit Leg-2a, else Leg-2b") -> Migration zu
  saga_step_orchestrator-Original mit `depends_on`.
- 5-Phase-Schema zu eng (Trading-Use-Cases brauchen 6+ oder 4 Phasen) ->
  Phasen-Pluralismus mit per-Saga-customizable Phase-List.
- Compensation-Failure-State (FAILED) zu coarse-grained — Compliance
  verlangt detailliertere Failure-Klassifikation (partial-compensated
  vs fully-uncompensated) -> Sub-States im SagaState-Enum.
- cancel_in_progress laesst running handler weiterlaufen bis
  Step-Completion (cooperative-cancel) — Risk-Manager braucht
  preemptive-cancel -> threading.Event + handler-Pflicht-Check.

## CRUX-Bindung

- **K_0:** geschuetzt — Multi-Leg-Atomicity verhindert Half-Open-Position
  (Long-Leg ohne Short-Leg = ungehedged Risk-Exposure). Compensation
  garantiert: alle Legs settle ODER alle reverse.
- **Q_0:** geschuetzt — compensation_log dokumentiert WARUM Saga
  abgebrochen wurde + welche Compensations OK / failed. Audit-Trail
  fuer Strategy-Bug-Forensik (haeufige Saga-Failures = Bug-Signal).
- **I_min:** strukturierte 5-Phase-Pflicht. Steps koennen Phasen NICHT
  skippen oder umordnen (linear State-Machine).
- **W_0:** Margin-Release via RESERVE-Compensation verhindert
  Working-Capital-Lock auf abgebrochenen Trades.

CRUX-MK
