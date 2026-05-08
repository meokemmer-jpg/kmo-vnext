# [CRUX-MK]
"""SAE-Chaos-Engineering-for-AIOps (Welle-30 Phase-23 Bio-Pattern-Lift 2/3).

Bio-Pattern-Lift von kmo_governance.chaos_engineering (Welle-9, Hotel-Domain)
in SAE-v8-Trinity-Slot-Domain. Kontrollierte Slot-Faults (Slot-Crash, Token-
Budget-Exhaustion, Inter-Agent-Communication-Drop, Trinity-Voting-Failure,
Governance-Violation) injizieren, Recovery-Time + Slots-Impacted +
Trinity-Voting-Recovered + Stability-Score messen, Aggregat-Score liefern.

Pattern-Isomorphie:
- Hotel-Service           -> SAE-Slot (target_slot_id + agent_class)
- ChaosScenario(steps)    -> SAEChaosScenario(fault_type, severity, params)
- FailureInjector         -> fault_handler_fn (per-slot, simuliert Fault)
- ChaosMonkey             -> SAEChaosEngineering (Orchestrator)
- ChaosOutcome (success/failure/recovered) -> SAEChaosOutcome (success +
    actual_recovery_s + slots_impacted + trinity_voting_recovered)
- ResilienceScore         -> get_stability_score(slot_id)
- Bio: Innate-Immunity-Stress-Test (Antigen-Exposition + Lymphocyte-Recovery)

SAE-Domain-spezifische Erweiterung (gegenueber KPM-Variante):
- Trinity-Voting-Aspekt: 200 Slots x 3 Variants (Conservative/Aggressive/
  Contrarian) = 600 Agenten. Fault-Injection auf einen Slot kann das
  Best-of-3-Voting kippen. trinity_voting_recovered: bool dokumentiert
  ob Voting nach Fault wieder funktional (Self-Repair-Eigenschaft).
- agent_class (str) als zweite Klassifikations-Achse: SAE-v8 hat 10
  AgentClasses (HOUSEKEEPING, RECEPTION, REVENUE_MGMT, ...). Outcomes
  filterbar nach agent_class fuer Domain-spezifische Robustheits-Analyse.
- slots_impacted (int) statt pnl_impact (KPM): SAE-Domain misst
  Slot-Cascade (wie viele Slots ist ein Fault unter sich gerissen).

Stdlib only (random, time, threading, dataclasses, enum, uuid, collections,
typing). Pattern-Demo, no real SAE-v8-Live-Tampering. Kill-Switch via
pause_chaos()/resume_chaos().

K_0-Schutz:
- max_concurrent_chaos limitiert parallele Fault-Injections (Default 1)
- pause_chaos blockiert weitere inject()-Calls
- SAEChaosScenario.params als tuple-of-tuples (frozen, hashable)
- SAEChaosOutcome frozen (Audit-Trail-Integritaet)
- max_outcomes_history bounded deque (Anti-OOM)
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# Severity-Multipliers (SAE-Domain-Default-Skala fuer Slot-Recovery)
SEVERITY_RECOVERY_MULTIPLIER: dict[str, float] = {
    "minor": 1.0,
    "moderate": 2.5,
    "severe": 6.0,
    "critical": 15.0,
}


class SAEFaultType(str, Enum):
    """SAE-Domain-Fault-Klassen (was kann einen SAE-Slot aushebeln)."""

    SLOT_CRASH = "slot_crash"
    TOKEN_BUDGET_EXHAUSTION = "token_budget_exhaustion"
    COMM_DROP = "comm_drop"
    TRINITY_VOTING_FAILURE = "trinity_voting_failure"
    GOVERNANCE_VIOLATION = "governance_violation"


class FaultSeverity(str, Enum):
    """Schweregrade der Fault-Injection (skaliert Recovery-Erwartung)."""

    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SAEChaosScenario:
    """Immutable Fault-Profil fuer eine kontrollierte Injection auf SAE-Slot.

    Frozen + tuple-params -> hashable + Audit-Trail-fest.

    Pre-Conditions:
    - scenario_id non-empty
    - target_slot_id non-empty
    - agent_class non-empty
    - duration_s > 0
    - expected_recovery_s > 0
    - params: tuple-of-tuples (jeder inner-tuple = (key, value))
    """

    scenario_id: str
    fault_type: SAEFaultType
    severity: FaultSeverity
    target_slot_id: str
    agent_class: str
    duration_s: float
    params: tuple[tuple[str, object], ...] = field(default_factory=tuple)
    expected_recovery_s: float = 1.0

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if not self.target_slot_id:
            raise ValueError("target_slot_id must be non-empty")
        if not self.agent_class:
            raise ValueError("agent_class must be non-empty")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if self.expected_recovery_s <= 0:
            raise ValueError("expected_recovery_s must be > 0")
        if not isinstance(self.fault_type, SAEFaultType):
            raise TypeError("fault_type must be SAEFaultType")
        if not isinstance(self.severity, FaultSeverity):
            raise TypeError("severity must be FaultSeverity")
        if not isinstance(self.params, tuple):
            raise TypeError("params must be a tuple of (key, value) tuples")
        for entry in self.params:
            if not (isinstance(entry, tuple) and len(entry) == 2):
                raise TypeError(
                    "each params entry must be a 2-tuple (key, value)"
                )


@dataclass(frozen=True)
class SAEChaosOutcome:
    """Immutable Resultat einer Chaos-Injection auf SAE-Slot.

    Frozen -> Audit-Trail kann nicht ex-post manipuliert werden.

    Felder:
    - scenario_id: Verknuepfung zu SAEChaosScenario
    - success: True wenn Slot ueberlebte und Recovery innerhalb expected_recovery_s
    - actual_recovery_s: Real gemessene Recovery-Zeit (0.0 wenn nie failed)
    - slots_impacted: Anzahl Slots die durch den Fault mit-betroffen waren (>= 1)
    - trinity_voting_recovered: Best-of-3-Voting nach Fault wieder funktional?
      SAE-spezifisch: 200 Slots x 3 Trinity-Variants = 600 Agenten.
    - observations: Tuple of str (Audit-Notizen aus Handler)
    - timestamp: time.time() bei Outcome-Erstellung
    """

    scenario_id: str
    success: bool
    actual_recovery_s: float
    slots_impacted: int
    trinity_voting_recovered: bool
    observations: tuple[str, ...] = field(default_factory=tuple)
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id must be non-empty")
        if self.actual_recovery_s < 0:
            raise ValueError("actual_recovery_s must be >= 0")
        if self.slots_impacted < 0:
            raise ValueError("slots_impacted must be >= 0")
        if not isinstance(self.observations, tuple):
            raise TypeError("observations must be a tuple of strings")
        for obs in self.observations:
            if not isinstance(obs, str):
                raise TypeError("each observation must be a string")


class SAEChaosEngineering:
    """Orchestrator fuer SAE-Slot-Chaos-Engineering (AIOps-Robustheit).

    Pre-Conditions:
    - default_severity: FaultSeverity (Default fuer inject_random)
    - max_concurrent_chaos: int >= 1 (limitiert parallele Injections,
      K_0-Schutz vor Multi-Slot-Fault-Storm der Trinity-Voting kippt)
    - max_outcomes_history: int >= 1 (bounded deque, Anti-OOM)

    Post-Conditions:
    - thread-safe (RLock)
    - register_slot() bindet handler fn an (slot_id, agent_class)
    - inject(scenario) ruft handler synchron auf (innerhalb max_concurrent-Limit)
    - inject_random() generiert zufaelligen Scenario auf bekanntem Slot
    - get_outcomes(slot_id?, agent_class?) liefert Audit-Trail (immutable tuple)
    - get_stability_score(slot_id?) liefert success-rate in [0,1]
    - pause_chaos() / resume_chaos() globaler Kill-Switch
    """

    def __init__(
        self,
        default_severity: FaultSeverity = FaultSeverity.MINOR,
        max_concurrent_chaos: int = 3,
        max_outcomes_history: int = 10000,
    ) -> None:
        """Constructor (V13-Patches: Anti-OOM + Race-Schutz).

        Pre-Conditions:
            default_severity: FaultSeverity (Default fuer inject_random).
            max_concurrent_chaos >= 1 (limitiert parallele Injections).
            max_outcomes_history >= 1 (bounded audit-trail to prevent OOM).

        Post-Conditions:
            self._outcomes ist deque mit maxlen=max_outcomes_history.
            Aelteste Outcomes werden bei Ueberlauf automatisch evicted.
        """
        if not isinstance(default_severity, FaultSeverity):
            raise TypeError("default_severity must be FaultSeverity")
        if max_concurrent_chaos < 1:
            raise ValueError("max_concurrent_chaos must be >= 1")
        if max_outcomes_history < 1:
            raise ValueError(
                f"max_outcomes_history must be >= 1: {max_outcomes_history}"
            )

        self.default_severity = default_severity
        self.max_concurrent_chaos = int(max_concurrent_chaos)
        self.max_outcomes_history = int(max_outcomes_history)

        self._lock = threading.RLock()
        # slot_id -> (agent_class, handler_fn)
        self._slots: dict[
            str,
            tuple[str, Callable[[SAEChaosScenario], SAEChaosOutcome]],
        ] = {}
        # Bounded deque (Anti-OOM)
        self._outcomes: deque[SAEChaosOutcome] = deque(
            maxlen=self.max_outcomes_history
        )
        # scenario_id -> SAEChaosScenario (fuer Outcome-Filterung)
        self._scenarios_by_outcome: dict[str, SAEChaosScenario] = {}
        self._paused: bool = False
        self._active_chaos_count: int = 0
        self._rng = random.Random()

    # -------------- Registration --------------

    def register_slot(
        self,
        slot_id: str,
        agent_class: str,
        fault_handler_fn: Callable[[SAEChaosScenario], SAEChaosOutcome],
    ) -> None:
        """Bind a fault handler to a (slot_id, agent_class) pair.

        Race-Schutz gegen mid-injection-replace:
            Wenn _active_chaos_count > 0 UND slot_id BEREITS registriert ist,
            raise RuntimeError. Verhindert dass laufende Injection den Handler
            ohne Versions-Audit unter sich austauscht.

        Pre:
            slot_id non-empty.
            agent_class non-empty.
            fault_handler_fn callable.

        Post:
            Handler signature: (SAEChaosScenario) -> SAEChaosOutcome.
            Handler ist verantwortlich fuer Fault-Simulation und Outcome-
            Erstellung mit gemessener recovery_time + slots_impacted +
            trinity_voting_recovered.
        """
        if not slot_id:
            raise ValueError("slot_id must be non-empty")
        if not agent_class:
            raise ValueError("agent_class must be non-empty")
        if not callable(fault_handler_fn):
            raise TypeError("fault_handler_fn must be callable")
        with self._lock:
            if (
                self._active_chaos_count > 0
                and slot_id in self._slots
            ):
                raise RuntimeError(
                    f"cannot replace handler for slot '{slot_id}' "
                    f"while {self._active_chaos_count} chaos injection(s) active "
                    f"(race-protection)"
                )
            self._slots[slot_id] = (agent_class, fault_handler_fn)

    # -------------- Injection --------------

    def inject(self, scenario: SAEChaosScenario) -> SAEChaosOutcome:
        """Inject scenario via the registered handler. Returns SAEChaosOutcome.

        Pre-Conditions:
        - scenario.target_slot_id is registered
        - chaos is not paused
        - active_chaos_count < max_concurrent_chaos

        Post-Conditions:
        - outcome appended to internal audit trail (bounded deque)
        - active_chaos_count incremented during call (decremented on return)
        - on handler exception: synthetic failed-outcome recorded with observation
        - on handler-protocol-violation (non-Outcome return): synthetic failure
        """
        if not isinstance(scenario, SAEChaosScenario):
            raise TypeError("scenario must be SAEChaosScenario")

        with self._lock:
            if self._paused:
                raise RuntimeError(
                    "chaos is paused; resume via resume_chaos()"
                )
            if scenario.target_slot_id not in self._slots:
                raise KeyError(
                    f"slot '{scenario.target_slot_id}' not registered"
                )
            if self._active_chaos_count >= self.max_concurrent_chaos:
                raise RuntimeError(
                    f"max_concurrent_chaos ({self.max_concurrent_chaos}) "
                    f"exceeded"
                )
            self._active_chaos_count += 1
            _agent_class, handler = self._slots[scenario.target_slot_id]

        # Call handler outside lock to avoid handler-induced deadlocks.
        try:
            outcome = handler(scenario)
            if not isinstance(outcome, SAEChaosOutcome):
                outcome = SAEChaosOutcome(
                    scenario_id=scenario.scenario_id,
                    success=False,
                    actual_recovery_s=0.0,
                    slots_impacted=0,
                    trinity_voting_recovered=False,
                    observations=(
                        f"handler returned non-SAEChaosOutcome: "
                        f"{type(outcome).__name__}",
                    ),
                    timestamp=time.time(),
                )
        except Exception as exc:
            outcome = SAEChaosOutcome(
                scenario_id=scenario.scenario_id,
                success=False,
                actual_recovery_s=0.0,
                slots_impacted=0,
                trinity_voting_recovered=False,
                observations=(
                    f"handler raised {type(exc).__name__}: {exc}",
                ),
                timestamp=time.time(),
            )
        finally:
            with self._lock:
                self._active_chaos_count -= 1

        with self._lock:
            # P-V15-2: _outcomes ist deque(maxlen=N). Bei Ueberlauf
            # evicted die deque automatisch das aelteste Element (links).
            # _scenarios_by_outcome ist dict ohne maxlen — ohne Eviction
            # wuerde das dict unbounded waehrend _outcomes bei N stagniert.
            # Fix: vor append leftmost-id capturen wenn deque voll, NACH
            # append aus dict poppen (wenn noch nicht durch Re-Add ueberschrieben).
            evicted_id: Optional[str] = None
            if len(self._outcomes) == self._outcomes.maxlen:
                evicted_id = self._outcomes[0].scenario_id
            self._outcomes.append(outcome)
            self._scenarios_by_outcome[outcome.scenario_id] = scenario
            if evicted_id is not None:
                # Nur poppen wenn noch keine andere Outcome dieselbe scenario_id
                # in der deque hat (Schutz gegen wiederholte scenario_ids).
                still_referenced = any(
                    out.scenario_id == evicted_id for out in self._outcomes
                )
                if not still_referenced:
                    self._scenarios_by_outcome.pop(evicted_id, None)
        return outcome

    def inject_random(
        self,
        slot_id: str,
        fault_type: Optional[SAEFaultType] = None,
        severity: Optional[FaultSeverity] = None,
    ) -> SAEChaosOutcome:
        """Generate a randomized scenario and inject it on slot_id.

        Picks a random fault_type if not provided; uses default_severity if
        severity not provided. Returns the resulting SAEChaosOutcome.
        """
        with self._lock:
            if slot_id not in self._slots:
                raise KeyError(f"slot '{slot_id}' not registered")
            agent_class, _handler = self._slots[slot_id]

            chosen_fault = (
                fault_type
                if fault_type is not None
                else self._rng.choice(list(SAEFaultType))
            )
            chosen_severity = (
                severity if severity is not None else self.default_severity
            )

            base_recovery_s = 1.0
            multiplier = SEVERITY_RECOVERY_MULTIPLIER.get(
                chosen_severity.value, 1.0
            )
            params = (
                ("base_recovery_s", base_recovery_s),
                ("multiplier", multiplier),
                ("rng_seed", self._rng.random()),
            )
            scenario_id = f"random-{uuid.uuid4().hex[:8]}"
            scenario = SAEChaosScenario(
                scenario_id=scenario_id,
                fault_type=chosen_fault,
                severity=chosen_severity,
                target_slot_id=slot_id,
                agent_class=agent_class,
                duration_s=max(1.0, multiplier),
                params=params,
                expected_recovery_s=multiplier,
            )

        return self.inject(scenario)

    # -------------- Inspection --------------

    def get_outcomes(
        self,
        slot_id: Optional[str] = None,
        agent_class: Optional[str] = None,
    ) -> tuple[SAEChaosOutcome, ...]:
        """Return outcomes (filtered) as immutable tuple.

        Filter-Kombinationen:
        - slot_id only       : alle outcomes fuer den Slot
        - agent_class only   : alle outcomes fuer alle Slots dieser Klasse
        - both               : Schnittmenge (slot_id passt UND agent_class passt)
        - none               : alle outcomes
        """
        with self._lock:
            if slot_id is None and agent_class is None:
                return tuple(self._outcomes)

            filtered: list[SAEChaosOutcome] = []
            for outcome in self._outcomes:
                scenario = self._scenarios_by_outcome.get(outcome.scenario_id)
                if scenario is None:
                    continue
                if (
                    slot_id is not None
                    and scenario.target_slot_id != slot_id
                ):
                    continue
                if (
                    agent_class is not None
                    and scenario.agent_class != agent_class
                ):
                    continue
                filtered.append(outcome)
            return tuple(filtered)

    def get_stability_score(
        self, slot_id: Optional[str] = None
    ) -> float:
        """Return stability_score in [0.0, 1.0].

        Definition:
            stability_score = successes / total

        Wenn slot_id given: score auf den Slot beschraenkt.
        Wenn slot_id None: globaler score ueber alle Slots.

        Edge case: empty outcomes list -> score = 1.0 (vacuously stable).
        """
        with self._lock:
            if slot_id is not None and slot_id not in self._slots:
                raise KeyError(f"slot '{slot_id}' not registered")
            outcomes = (
                self.get_outcomes(slot_id=slot_id)
                if slot_id is not None
                else tuple(self._outcomes)
            )
            if not outcomes:
                return 1.0
            successes = sum(1 for outcome in outcomes if outcome.success)
            return successes / len(outcomes)

    # -------------- Kill-Switch --------------

    def pause_chaos(self) -> None:
        """Block further inject()-calls (K_0-Sicherheit)."""
        with self._lock:
            self._paused = True

    def resume_chaos(self) -> None:
        """Resume inject()-calls."""
        with self._lock:
            self._paused = False

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def active_chaos_count(self) -> int:
        with self._lock:
            return self._active_chaos_count

    @property
    def registered_slots(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._slots.keys())

    @property
    def registered_agent_classes(self) -> tuple[str, ...]:
        """Distinct agent_classes across all registered slots."""
        with self._lock:
            return tuple(
                sorted({ac for (ac, _fn) in self._slots.values()})
            )


# CRUX-MK
