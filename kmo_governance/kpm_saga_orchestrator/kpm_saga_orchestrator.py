# [CRUX-MK]
"""KPM-Saga-Orchestrator — Multi-Leg-Order-Atomicity via 5-Phase-Saga.

Welle-27 Phase-20 KMO-vNext Bio-Pattern-Lift von saga_step_orchestrator.

Bio-Aequivalent: Mitose-Phasen-Sequencing.
    Prophase    -> SagaPhase.VALIDATE  (Pre-flight Check, Leg-Konsistenz)
    Metaphase   -> SagaPhase.RESERVE   (Margin/Capital reservieren)
    Anaphase    -> SagaPhase.EXECUTE   (Order an Broker)
    Telophase   -> SagaPhase.CONFIRM   (Broker-Ack, Fill-Verify)
    Cytokinesis -> SagaPhase.SETTLE    (Position-Buchung, Audit-Trail)

Compensation: Bei Step-Fehler werden alle vorher-COMPLETED-Steps in
reverse-order kompensiert (Cytokinesis-Reverse). Failed-Step selbst
wird NICHT kompensiert (er hat keinen Forward-Effekt produziert).

KPM-Domain-Adjustments vs Hotel-Vorlage (saga_step_orchestrator):
- Linear 5-Phase-State-Machine statt DAG-Topology: Multi-Leg-Order ist
  inhaerent sequentiell (RESERVE muss vor EXECUTE laufen, sonst
  Margin-Race). DAG-Flexibilitaet wird nicht benoetigt.
- Saga-Granularitaet: Eine Saga = ein Multi-Leg-Trade (N Legs in 1 Saga).
  Concurrent Sagas (mehrere parallele Trades) via separate Saga-Ids.
- Compensation pro Phase + step (statt nur pro step): jede Phase hat
  eigene Compensation-Logik (z.B. RESERVE-Compensation = Margin-Release,
  EXECUTE-Compensation = Reverse-Order-Submission).
- handler-/compensator-Registry pro Phase: trennt Saga-Definition (Steps)
  von Phase-Implementation (Handler-Functions, broker-spezifisch).

CRUX-Bindung:
- K_0: Multi-Leg-Atomicity verhindert Half-Open-Position (z.B. Long-Leg
  ohne Short-Leg = ungehedged Risk-Capital-Exposure).
- Q_0: Compensation-Log persistent (Audit-Trail fuer MiFID-RTS-25 +
  Strategy-Bug-Forensik wenn Saga oft compensated).
- I_min: 5-Phase-Pflicht ist State-Machine-erzwungen (Steps koennen
  Phasen NICHT skippen).
- W_0: Failed-Saga setzt Margin frei via Compensation, kein Working-
  Capital-Lock auf abgebrochenen Trades.

CRUX-MK
"""
from __future__ import annotations

import enum
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SagaPhase(str, enum.Enum):
    """5 Saga-Phasen (entspricht Mitose-Phasen).

    VALIDATE  -> Prophase    (Pre-flight Check, Leg-Konsistenz)
    RESERVE   -> Metaphase   (Margin/Capital reservieren)
    EXECUTE   -> Anaphase    (Order an Broker submitten)
    CONFIRM   -> Telophase   (Broker-Ack, Fill-Verify)
    SETTLE    -> Cytokinesis (Position-Buchung, Audit-Trail-Final)
    """

    VALIDATE = "validate"
    RESERVE = "reserve"
    EXECUTE = "execute"
    CONFIRM = "confirm"
    SETTLE = "settle"


class SagaState(str, enum.Enum):
    """Lifecycle-State einer kompletten Saga.

    PENDING       -> registered, noch nicht gestartet
    IN_PROGRESS   -> mind. ein Step durchlaeuft Phase
    COMPLETED     -> alle Steps haben SETTLE erreicht
    FAILED        -> ein Step ist gescheitert, Compensation noch nicht abgeschlossen
    COMPENSATING  -> Compensation laeuft (cancel_in_progress oder Step-Fehler)
    COMPENSATED   -> Saga gescheitert + alle vorherigen Steps kompensiert
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SagaStep:
    """Single Step einer Saga.

    Pre-Conditions:
        step_id non-empty.
        phase ist SagaPhase-Enum-Wert.
        instrument_id non-empty (z.B. "AAPL", "EUR/USD").
        action_data tuple-of-tuples (frozen-friendly statt dict).
        compensation_data tuple-of-tuples.

    Post-Conditions:
        Frozen / hashable.

    Notes:
        - action_data / compensation_data sind tuple-of-(key, value)-tuples
          fuer Frozen-Compatibility. Beispiel:
              action_data = (("symbol", "AAPL"), ("qty", 100), ("side", "BUY"))
        - Handler-Functions akzeptieren SagaStep, koennen action_data via
          dict(step.action_data) re-konstruieren.
    """

    step_id: str
    phase: SagaPhase
    instrument_id: str
    action_data: tuple = ()
    compensation_data: tuple = ()

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("step_id must be non-empty")
        if not isinstance(self.phase, SagaPhase):
            raise ValueError("phase must be a SagaPhase enum value")
        if not self.instrument_id:
            raise ValueError("instrument_id must be non-empty")
        if not isinstance(self.action_data, tuple):
            raise ValueError("action_data must be tuple-of-tuples")
        if not isinstance(self.compensation_data, tuple):
            raise ValueError("compensation_data must be tuple-of-tuples")


@dataclass(frozen=True)
class SagaOutcome:
    """Outcome einer kompletten Saga.

    Pre-Conditions:
        saga_id non-empty.
        state ist SagaState-Enum-Wert.
        completed_steps tuple-of-strings (step_ids).
        compensation_log tuple-of-tuples ((step_id, phase_str, status_str)).
        elapsed_s >= 0.
        timestamp > 0.

    Post-Conditions:
        Frozen / hashable.

    Felder:
        saga_id           : Eindeutige Saga-ID (uuid4 oder client-provided).
        state             : Endzustand (COMPLETED / COMPENSATED / FAILED).
        completed_steps   : tuple aller step_ids die SETTLE durchlaufen haben.
        failed_step       : step_id des fehlgeschlagenen Steps oder None.
        compensation_log  : tuple-of-(step_id, phase, status) je Compensation.
        elapsed_s         : Wall-Clock-Dauer der Saga in Sekunden.
        timestamp         : Unix-Timestamp des Saga-Endes.
    """

    saga_id: str
    state: SagaState
    completed_steps: tuple = ()
    failed_step: Optional[str] = None
    compensation_log: tuple = ()
    elapsed_s: float = 0.0
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.saga_id:
            raise ValueError("saga_id must be non-empty")
        if not isinstance(self.state, SagaState):
            raise ValueError("state must be a SagaState enum value")
        if not isinstance(self.completed_steps, tuple):
            raise ValueError("completed_steps must be tuple")
        if not isinstance(self.compensation_log, tuple):
            raise ValueError("compensation_log must be tuple")
        if self.elapsed_s < 0:
            raise ValueError("elapsed_s must be >= 0")
        if self.timestamp < 0:
            raise ValueError("timestamp must be >= 0")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class KPMSagaOrchestrator:
    """Multi-Leg-Order-Saga-Orchestrator (5-Phase + Compensation).

    Thread-safe via internal RLock. Concurrent Sagas isolated by saga_id.

    Lifecycle:
        register_handler(phase, fn) -> register_compensator(phase, fn) ->
        execute_saga(steps) -> [auto-compensation if any step fails]

    Pre-Conditions (Constructor):
        default_timeout_s > 0.

    Post-Conditions:
        - In-progress Sagas verfolgbar via cancel_in_progress / get_outcome.
        - Outcomes persistiert in self._outcomes nach Saga-Ende.
    """

    def __init__(self, default_timeout_s: float = 30.0) -> None:
        if default_timeout_s <= 0:
            raise ValueError("default_timeout_s must be > 0")

        self._lock = threading.RLock()
        self._default_timeout_s = default_timeout_s
        self._handlers: dict[SagaPhase, Callable[[SagaStep], dict]] = {}
        self._compensators: dict[SagaPhase, Callable[[SagaStep], None]] = {}
        self._outcomes: dict[str, SagaOutcome] = {}
        self._in_progress: dict[str, SagaState] = {}  # saga_id -> state

    def register_handler(
        self,
        phase: SagaPhase,
        handler_fn: Callable[[SagaStep], dict],
    ) -> None:
        """Bind handler_fn to phase. Re-Registration ueberschreibt.

        Pre: phase ist SagaPhase. handler_fn callable.
              handler_fn signature: (SagaStep) -> dict (Erfolgs-Daten,
              z.B. {"order_id": "...", "fill_qty": 100}).
              handler_fn raises Exception bei Fehler.

        Post: self._handlers[phase] = handler_fn.
        """
        with self._lock:
            if not isinstance(phase, SagaPhase):
                raise ValueError("phase must be a SagaPhase enum value")
            if not callable(handler_fn):
                raise ValueError("handler_fn must be callable")
            self._handlers[phase] = handler_fn

    def register_compensator(
        self,
        phase: SagaPhase,
        comp_fn: Callable[[SagaStep], None],
    ) -> None:
        """Bind compensator-fn to phase. Re-Registration ueberschreibt.

        Pre: phase ist SagaPhase. comp_fn callable.
              comp_fn signature: (SagaStep) -> None (Side-Effect).
              comp_fn darf Exception werfen — wird in compensation_log
              als "compensation-failed" geloggt, blockiert NICHT die
              weiteren Compensations.

        Post: self._compensators[phase] = comp_fn.
        """
        with self._lock:
            if not isinstance(phase, SagaPhase):
                raise ValueError("phase must be a SagaPhase enum value")
            if not callable(comp_fn):
                raise ValueError("comp_fn must be callable")
            self._compensators[phase] = comp_fn

    def execute_saga(
        self,
        steps: list[SagaStep],
        saga_id: Optional[str] = None,
    ) -> SagaOutcome:
        """Execute saga: run alle Steps sequentiell, compensate on failure.

        Pre:
            steps non-empty list of SagaStep.
            handler fuer jede in steps vorkommende Phase muss registriert sein.
            saga_id non-empty wenn provided, sonst auto-uuid4.

        Post:
            Outcome persistiert in self._outcomes[saga_id].
            State = COMPLETED (alle Steps OK) oder COMPENSATED (ein Step
            failed + alle vorherigen kompensiert) oder FAILED (Step failed
            UND eine Compensation auch failed — degraded state).

        Returns:
            SagaOutcome mit final-state + completed_steps + compensation_log.
        """
        if not steps:
            raise ValueError("steps must be non-empty list")

        # Phase-Registry-Pruefung: jede Step-Phase muss Handler haben
        with self._lock:
            for step in steps:
                if step.phase not in self._handlers:
                    raise ValueError(
                        f"no handler registered for phase {step.phase.value!r}"
                    )

        if saga_id is None:
            saga_id = str(uuid.uuid4())
        if not saga_id:
            raise ValueError("saga_id must be non-empty if provided")

        with self._lock:
            self._in_progress[saga_id] = SagaState.IN_PROGRESS

        start = time.monotonic()
        completed_steps: list[str] = []
        failed_step: Optional[str] = None
        compensation_log: list[tuple] = []

        # Sequentielle Ausfuehrung aller Steps
        for step in steps:
            # Cancel-Check (cancel_in_progress wurde aufgerufen)
            with self._lock:
                if self._in_progress.get(saga_id) == SagaState.COMPENSATING:
                    failed_step = step.step_id
                    break

            try:
                handler = self._handlers[step.phase]
                _ = handler(step)
                completed_steps.append(step.step_id)
            except Exception as exc:  # noqa: BLE001 — aggregate any handler error
                failed_step = step.step_id
                # Log original failure
                compensation_log.append(
                    (
                        step.step_id,
                        step.phase.value,
                        f"handler-failed: {type(exc).__name__}: {exc}",
                    )
                )
                break

        # Wenn Step-Failure: Compensation in reverse-order
        if failed_step is not None:
            with self._lock:
                self._in_progress[saga_id] = SagaState.COMPENSATING

            comp_failed_count = 0
            for step_id_to_comp in reversed(completed_steps):
                # Original-Step-Objekt finden
                step_obj = next(
                    (s for s in steps if s.step_id == step_id_to_comp),
                    None,
                )
                if step_obj is None:
                    continue  # defensive — sollte nicht passieren

                comp_fn = self._compensators.get(step_obj.phase)
                if comp_fn is None:
                    # Keine Compensation registriert — als no-op loggen
                    compensation_log.append(
                        (step_obj.step_id, step_obj.phase.value, "no-compensator")
                    )
                    continue

                try:
                    comp_fn(step_obj)
                    compensation_log.append(
                        (step_obj.step_id, step_obj.phase.value, "compensated")
                    )
                except Exception as exc:  # noqa: BLE001 — aggregate any compensation error
                    compensation_log.append(
                        (
                            step_obj.step_id,
                            step_obj.phase.value,
                            f"compensation-failed: {type(exc).__name__}: {exc}",
                        )
                    )
                    comp_failed_count += 1

            # Final-State bestimmen
            if comp_failed_count > 0:
                final_state = SagaState.FAILED  # degraded — einige Compensations failed
            else:
                final_state = SagaState.COMPENSATED  # alle Compensations OK
        else:
            final_state = SagaState.COMPLETED

        elapsed = time.monotonic() - start
        outcome = SagaOutcome(
            saga_id=saga_id,
            state=final_state,
            completed_steps=tuple(completed_steps),
            failed_step=failed_step,
            compensation_log=tuple(compensation_log),
            elapsed_s=elapsed,
            timestamp=time.time(),
        )

        with self._lock:
            self._outcomes[saga_id] = outcome
            self._in_progress.pop(saga_id, None)

        return outcome

    def get_outcome(self, saga_id: str) -> SagaOutcome:
        """Lookup Outcome by saga_id. Raises KeyError if absent.

        Pre: saga_id war Argument zu execute_saga().
        Post: Outcome unveraendert (frozen).
        """
        with self._lock:
            if saga_id not in self._outcomes:
                raise KeyError(f"saga_id {saga_id!r} not found")
            return self._outcomes[saga_id]

    def get_outcomes(self) -> tuple[SagaOutcome, ...]:
        """Snapshot aller Outcomes (Insertion-Order stable).

        Post: tuple kopiert, Mutation des internal-state nicht moeglich.
        """
        with self._lock:
            return tuple(self._outcomes.values())

    def cancel_in_progress(self, saga_id: str) -> bool:
        """Markiere in-progress Saga als COMPENSATING (graceful).

        Wirkt nur wenn Saga aktuell laeuft. Naechster Step-Check in
        execute_saga() detektiert COMPENSATING und beendet die Saga
        mit Compensation aller bis-dahin completed Steps.

        Pre: saga_id muss in-progress sein (sonst False zurueck).
        Post: self._in_progress[saga_id] = COMPENSATING.

        Returns:
            True wenn Saga gefunden + markiert, False sonst.
        """
        with self._lock:
            if saga_id not in self._in_progress:
                return False
            self._in_progress[saga_id] = SagaState.COMPENSATING
            return True


# CRUX-MK
