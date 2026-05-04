"""KMO Chaos-Engineering [CRUX-MK].

KMO-vNext Welle-10 Phase-6.2 Subagent-D: Pre-Production-Layer fuer
Failure-Injection + Recovery-Verifikation.

Bio-Aequivalent: Immunsystem-Stress-Test (kontrollierte Antigen-Exposition).
    FailureInjector  -> Kontrolliertes Antigen (Latenz/Failure-Spike)
    ChaosScenario    -> Pathogen-Profil (Composite mehrerer Injectoren)
    ChaosMonkey      -> Vakzinierungs-Schedule (orchestriert Targets + Scenarios)
    RecoveryVerifier -> Lymphozyten-Antwort-Messung (kommt der Organismus zurueck?)
    ResilienceScore  -> Immun-Kompetenz-Score (Aggregat-Resilienz)

Pattern-Inspiration: Netflix Chaos-Monkey + apoptosis_engine (Cell-Death+Recovery)
+ wound_healing (4-Phase-Lifecycle) + apaleo_adapter (Circuit-Breaker).

K11 Cascade-Containment: ChaosMonkey isoliert Failure-Injection auf registrierte Targets.
K13 Pre-Action-Verification: FailureInjector validiert probability/latency-Bounds vor Injection.

NO external Dependencies (stdlib-only): dataclasses, random, time, threading, typing, enum.

Usage:
    monkey = ChaosMonkey()
    monkey.register_target("hotel_membrane_check", lambda: hotel_check())

    scenario = ChaosScenario(
        name="latency-and-fail",
        steps=[
            FailureInjector(latency_min_ms=50, latency_max_ms=200),
            FailureInjector(failure_probability=0.3),
        ],
    )
    monkey.schedule_chaos("hotel_membrane_check", scenario)

    outcomes = monkey.run_all_scheduled()
    score = ResilienceScore.score(outcomes)
"""

from __future__ import annotations

import enum
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------- Public Types ----------------


class ChaosOutcomeStatus(str, enum.Enum):
    """Resultat eines einzelnen Chaos-Runs."""

    SUCCESS = "success"  # target ueberlebt das chaos
    FAILURE = "failure"  # target wurde von chaos gekillt, kein recovery
    RECOVERED = "recovered"  # target failed und recoverte


@dataclass(frozen=True)
class ChaosOutcome:
    """Immutable outcome of a single chaos-run."""

    target_name: str
    scenario_name: str
    status: ChaosOutcomeStatus
    duration_s: float
    recovery_time_s: Optional[float] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class RecoveryResult:
    """Immutable result of recovery verification."""

    recovered: bool
    attempts: int
    total_time_s: float


@dataclass(frozen=True)
class ResilienceBreakdown:
    """Per-target resilience stats."""

    target_name: str
    total_runs: int
    successes: int
    failures: int
    recoveries: int
    score: float  # [0.0, 1.0]


# ---------------- FailureInjector ----------------


class FailureInjector:
    """Injects controlled failures (latency or exceptions) into target functions.

    Pre-Conditions:
        - failure_probability in [0.0, 1.0]
        - latency_min_ms <= latency_max_ms (if both > 0)
        - rng injectable for deterministic tests

    Post-Conditions:
        - inject_failure() raises exception_type when probability triggers
        - inject_latency() blocks for [min, max] ms uniformly distributed
        - reset() clears internal counters
    """

    def __init__(
        self,
        failure_probability: float = 0.0,
        partial_failure_probability: float = 0.0,
        latency_min_ms: float = 0.0,
        latency_max_ms: float = 0.0,
        exception_type: type[BaseException] = RuntimeError,
        exception_message: str = "Chaos-Injected Failure",
        rng: Optional[random.Random] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0.0 <= failure_probability <= 1.0:
            raise ValueError("failure_probability must be in [0.0, 1.0]")
        if not 0.0 <= partial_failure_probability <= 1.0:
            raise ValueError("partial_failure_probability must be in [0.0, 1.0]")
        if latency_max_ms < latency_min_ms:
            raise ValueError("latency_max_ms must be >= latency_min_ms")
        if latency_min_ms < 0 or latency_max_ms < 0:
            raise ValueError("latency bounds must be non-negative")

        self.failure_probability = failure_probability
        self.partial_failure_probability = partial_failure_probability
        self.latency_min_ms = latency_min_ms
        self.latency_max_ms = latency_max_ms
        self.exception_type = exception_type
        self.exception_message = exception_message
        self._rng = rng if rng is not None else random.Random()
        self._sleep_fn = sleep_fn
        self._lock = threading.RLock()
        self._injection_count: int = 0
        self._failure_count: int = 0
        self._latency_count: int = 0

    def inject_latency(
        self, min_ms: Optional[float] = None, max_ms: Optional[float] = None
    ) -> float:
        """Inject latency in [min, max] ms range. Returns sleep duration in seconds.

        If min/max not given, uses configured latency_min_ms / latency_max_ms.
        """
        with self._lock:
            lo = min_ms if min_ms is not None else self.latency_min_ms
            hi = max_ms if max_ms is not None else self.latency_max_ms
            if hi < lo:
                raise ValueError("max_ms must be >= min_ms")
            if lo == 0.0 and hi == 0.0:
                return 0.0
            ms = self._rng.uniform(lo, hi)
            seconds = ms / 1000.0
            self._sleep_fn(seconds)
            self._latency_count += 1
            self._injection_count += 1
            return seconds

    def inject_failure(self, probability: Optional[float] = None) -> None:
        """Raise exception_type with probability p (default: configured)."""
        with self._lock:
            p = probability if probability is not None else self.failure_probability
            if not 0.0 <= p <= 1.0:
                raise ValueError("probability must be in [0.0, 1.0]")
            self._injection_count += 1
            if p > 0.0 and self._rng.random() < p:
                self._failure_count += 1
                raise self.exception_type(self.exception_message)

    def inject_partial_failure(
        self,
        probability: Optional[float] = None,
        exception_type: Optional[type[BaseException]] = None,
    ) -> None:
        """Inject a partial failure (different exception type, lower probability typical).

        Same semantics as inject_failure but with separate probability/type.
        """
        with self._lock:
            p = (
                probability
                if probability is not None
                else self.partial_failure_probability
            )
            if not 0.0 <= p <= 1.0:
                raise ValueError("probability must be in [0.0, 1.0]")
            etype = exception_type if exception_type is not None else self.exception_type
            self._injection_count += 1
            if p > 0.0 and self._rng.random() < p:
                self._failure_count += 1
                raise etype(f"Partial: {self.exception_message}")

    def reset(self) -> None:
        """Clear internal counters."""
        with self._lock:
            self._injection_count = 0
            self._failure_count = 0
            self._latency_count = 0

    @property
    def injection_count(self) -> int:
        return self._injection_count

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def latency_count(self) -> int:
        return self._latency_count


# ---------------- ChaosScenario ----------------


@dataclass
class ChaosScenario:
    """Composite of FailureInjectors. Applied as pre-step before target_fn runs.

    Pre-Conditions:
        - name non-empty
        - steps list of FailureInjector instances

    Post-Conditions:
        - run() applies all steps in order
        - Records outcome (SUCCESS / FAILURE / RECOVERED)
        - Captures recovery_time if recovery_verifier provided
    """

    name: str
    steps: list[FailureInjector] = field(default_factory=list)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ChaosScenario.name must be non-empty")
        for step in self.steps:
            if not isinstance(step, FailureInjector):
                raise TypeError(
                    f"All steps must be FailureInjector, got {type(step).__name__}"
                )

    def run(
        self,
        target_fn: Callable[..., Any],
        *args: Any,
        target_name: str = "<unnamed>",
        recovery_verifier: Optional["RecoveryVerifier"] = None,
        clock: Callable[[], float] = time.time,
        **kwargs: Any,
    ) -> ChaosOutcome:
        """Apply scenario to target_fn. Returns ChaosOutcome.

        Sequence:
            1. Apply each FailureInjector step in order (latency + failure injection)
            2. If injection raises -> attempt recovery via recovery_verifier (if set)
            3. If no injection raised -> call target_fn(*args, **kwargs)
            4. Return ChaosOutcome with status SUCCESS/FAILURE/RECOVERED.
        """
        start = clock()
        try:
            # Apply chaos steps
            for step in self.steps:
                step.inject_latency()
                step.inject_failure()
            # Run target if chaos passed
            target_fn(*args, **kwargs)
            duration = clock() - start
            return ChaosOutcome(
                target_name=target_name,
                scenario_name=self.name,
                status=ChaosOutcomeStatus.SUCCESS,
                duration_s=duration,
            )
        except Exception as e:
            duration = clock() - start
            error_str = f"{type(e).__name__}: {e}"
            # Attempt recovery if verifier present
            if recovery_verifier is not None:
                rec_result = recovery_verifier.verify_recovery(
                    target_fn, *args, **kwargs
                )
                if rec_result.recovered:
                    return ChaosOutcome(
                        target_name=target_name,
                        scenario_name=self.name,
                        status=ChaosOutcomeStatus.RECOVERED,
                        duration_s=duration,
                        recovery_time_s=rec_result.total_time_s,
                        error=error_str,
                    )
            return ChaosOutcome(
                target_name=target_name,
                scenario_name=self.name,
                status=ChaosOutcomeStatus.FAILURE,
                duration_s=duration,
                error=error_str,
            )


# ---------------- ChaosMonkey ----------------


class ChaosMonkey:
    """Orchestrator: registers targets, schedules scenarios, runs all and records metrics.

    Pre-Conditions:
        - targets registered before scheduling
        - scenarios bound to existing target

    Post-Conditions:
        - run_all_scheduled() returns list[ChaosOutcome] in registration-order
        - get_metrics() aggregates per-target stats
    """

    def __init__(
        self,
        recovery_verifier: Optional["RecoveryVerifier"] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._targets: dict[str, Callable[..., Any]] = {}
        self._schedule: list[tuple[str, ChaosScenario]] = []
        self._recovery_verifier = recovery_verifier
        self._clock = clock
        self._lock = threading.RLock()
        self._outcomes: list[ChaosOutcome] = []

    def register_target(self, name: str, fn: Callable[..., Any]) -> None:
        """Register a callable target by name."""
        if not name:
            raise ValueError("target name must be non-empty")
        if not callable(fn):
            raise TypeError("fn must be callable")
        with self._lock:
            self._targets[name] = fn

    def schedule_chaos(self, target_name: str, scenario: ChaosScenario) -> None:
        """Bind a scenario to a registered target."""
        with self._lock:
            if target_name not in self._targets:
                raise KeyError(f"target '{target_name}' not registered")
            self._schedule.append((target_name, scenario))

    def run_all_scheduled(self) -> list[ChaosOutcome]:
        """Run every scheduled (target, scenario) pair. Returns outcomes in order."""
        with self._lock:
            outcomes: list[ChaosOutcome] = []
            for target_name, scenario in self._schedule:
                fn = self._targets[target_name]
                outcome = scenario.run(
                    fn,
                    target_name=target_name,
                    recovery_verifier=self._recovery_verifier,
                    clock=self._clock,
                )
                outcomes.append(outcome)
            self._outcomes.extend(outcomes)
            return outcomes

    def get_metrics(self) -> dict[str, Any]:
        """Aggregate counters across all runs (cumulative)."""
        with self._lock:
            total = len(self._outcomes)
            successes = sum(
                1 for o in self._outcomes if o.status == ChaosOutcomeStatus.SUCCESS
            )
            failures = sum(
                1 for o in self._outcomes if o.status == ChaosOutcomeStatus.FAILURE
            )
            recoveries = sum(
                1 for o in self._outcomes if o.status == ChaosOutcomeStatus.RECOVERED
            )
            return {
                "total_runs": total,
                "successes": successes,
                "failures": failures,
                "recoveries": recoveries,
                "registered_targets": len(self._targets),
                "scheduled_scenarios": len(self._schedule),
            }

    @property
    def outcomes(self) -> list[ChaosOutcome]:
        with self._lock:
            return list(self._outcomes)

    def reset(self) -> None:
        with self._lock:
            self._outcomes.clear()
            self._schedule.clear()


# ---------------- RecoveryVerifier ----------------


class RecoveryVerifier:
    """Verifies that a target_fn recovers after failure (retries with optional backoff).

    Pre-Conditions:
        - max_attempts >= 1
        - interval_s >= 0
        - exponential_backoff bool

    Post-Conditions:
        - verify_recovery() returns RecoveryResult(recovered, attempts, total_time_s)
        - Stops at first successful call OR after max_attempts
    """

    def __init__(
        self,
        max_attempts: int = 3,
        interval_s: float = 0.1,
        exponential_backoff: bool = False,
        clock: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if interval_s < 0:
            raise ValueError("interval_s must be >= 0")
        self.max_attempts = max_attempts
        self.interval_s = interval_s
        self.exponential_backoff = exponential_backoff
        self._clock = clock
        self._sleep_fn = sleep_fn

    def verify_recovery(
        self,
        target_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> RecoveryResult:
        """Retry target_fn up to max_attempts. Returns RecoveryResult."""
        start = self._clock()
        attempts = 0
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_attempts + 1):
            attempts = attempt
            try:
                target_fn(*args, **kwargs)
                total = self._clock() - start
                return RecoveryResult(
                    recovered=True, attempts=attempts, total_time_s=total
                )
            except Exception as e:
                last_error = e
                if attempt < self.max_attempts:
                    delay = self.interval_s
                    if self.exponential_backoff:
                        delay = self.interval_s * (2 ** (attempt - 1))
                    if delay > 0:
                        self._sleep_fn(delay)
        total = self._clock() - start
        return RecoveryResult(recovered=False, attempts=attempts, total_time_s=total)


# ---------------- ResilienceScore ----------------


class ResilienceScore:
    """Aggregates ChaosOutcome list into resilience_score in [0.0, 1.0].

    Definition:
        resilience_score = (successes + recoveries) / total
        - SUCCESS counted as full resilience (target survived chaos)
        - RECOVERED counted as full resilience (target failed but recovered)
        - FAILURE counted as zero resilience (no recovery)

    Edge case: empty outcomes list -> score = 1.0 (vacuously resilient).
    """

    @staticmethod
    def score(outcomes: list[ChaosOutcome]) -> float:
        """Compute aggregate resilience score in [0.0, 1.0]."""
        if not outcomes:
            return 1.0
        resilient = sum(
            1
            for o in outcomes
            if o.status
            in (ChaosOutcomeStatus.SUCCESS, ChaosOutcomeStatus.RECOVERED)
        )
        return resilient / len(outcomes)

    @staticmethod
    def get_breakdown(outcomes: list[ChaosOutcome]) -> list[ResilienceBreakdown]:
        """Per-target breakdown of resilience metrics."""
        per_target: dict[str, list[ChaosOutcome]] = {}
        for o in outcomes:
            per_target.setdefault(o.target_name, []).append(o)
        result: list[ResilienceBreakdown] = []
        for name, target_outcomes in per_target.items():
            total = len(target_outcomes)
            successes = sum(
                1 for o in target_outcomes if o.status == ChaosOutcomeStatus.SUCCESS
            )
            failures = sum(
                1 for o in target_outcomes if o.status == ChaosOutcomeStatus.FAILURE
            )
            recoveries = sum(
                1 for o in target_outcomes if o.status == ChaosOutcomeStatus.RECOVERED
            )
            local_score = (
                (successes + recoveries) / total if total > 0 else 1.0
            )
            result.append(
                ResilienceBreakdown(
                    target_name=name,
                    total_runs=total,
                    successes=successes,
                    failures=failures,
                    recoveries=recoveries,
                    score=local_score,
                )
            )
        return result


# CRUX-MK
