"""KMO Wound-Healing Lifecycle [CRUX-MK].

KMO-vNext Welle-9α Phase-1 Modul 2.3: 4-Phase Recovery-Lifecycle nach Saga-FAILED.

Bio-Aequivalent: Wound-Healing-Process.
    Hemostasis    -> Blutgerinnung (Circuit-Break, Failure-Containment)
    Inflammation  -> Macrophage-Cleanup (Garbage-Collection, State-Reset)
    Proliferation -> Tissue-Neubildung (Auto-Restart, State-Reconstruction)
    Remodeling    -> Narben-Umbau (Gradual Re-Optimization)
    HEALED

State-Machine: forward-only Transitionen mit expliziten Pre-Conditions.
Integriert mit Saga-Compensation: ersetzt direkte Compensation durch
strukturierte Recovery.

K11 Cascade-Containment: Hemostasis-Phase isoliert Failure.
K13 Pre-Action-Verification: Phase-Transitionen mit pre-condition-Checks.

Usage:
    healing = WoundHealingLifecycle(
        saga_run_id="saga-run-1",
        hotel_id="hotel-A",
        on_phase_transition=lambda old, new, ctx: log(f"{old}->{new}"),
        cleanup_callback=cleanup_state,
        restart_callback=restart_saga,
    )
    healing.start_hemostasis(failure_reason="phase-3-timeout")
    # ... time passes, system stabilizes ...
    healing.transition_to_inflammation()
    healing.transition_to_proliferation()
    healing.transition_to_remodeling()
    healing.complete()
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .phase_transitions import PhaseTransitionError, validate_transition
from .healing_metrics import HealingMetrics


class HealingPhase(str, enum.Enum):
    """4-Phase Wound-Healing-Lifecycle."""

    NOT_STARTED = "not_started"
    HEMOSTASIS = "hemostasis"
    INFLAMMATION = "inflammation"
    PROLIFERATION = "proliferation"
    REMODELING = "remodeling"
    HEALED = "healed"
    ABORTED = "aborted"


# Forward-only transition graph (DAG)
ALLOWED_TRANSITIONS: dict[HealingPhase, set[HealingPhase]] = {
    HealingPhase.NOT_STARTED: {HealingPhase.HEMOSTASIS, HealingPhase.ABORTED},
    HealingPhase.HEMOSTASIS: {HealingPhase.INFLAMMATION, HealingPhase.ABORTED},
    HealingPhase.INFLAMMATION: {HealingPhase.PROLIFERATION, HealingPhase.ABORTED},
    HealingPhase.PROLIFERATION: {HealingPhase.REMODELING, HealingPhase.ABORTED},
    HealingPhase.REMODELING: {HealingPhase.HEALED, HealingPhase.ABORTED},
    HealingPhase.HEALED: set(),  # terminal
    HealingPhase.ABORTED: set(),  # terminal
}


@dataclass
class HealingContext:
    """Mutable context shared across phases."""

    saga_run_id: str
    hotel_id: str
    failure_reason: Optional[str] = None
    phase_log: list[tuple[HealingPhase, float]] = field(default_factory=list)
    cleanup_artifacts: list[Any] = field(default_factory=list)
    restart_attempts: int = 0
    optimization_notes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class WoundHealingLifecycle:
    """4-Phase Recovery State-Machine. Thread-safe via RLock.

    Pre-Conditions:
        - saga_run_id, hotel_id non-empty
        - phase callbacks optional (None = no-op)
        - clock injectable for tests

    Post-Conditions:
        - All transitions enforced via ALLOWED_TRANSITIONS DAG
        - Each transition appends to phase_log AND fires on_phase_transition
        - HealingMetrics tracks MTTR per phase
        - HEALED + ABORTED are terminal (subsequent transitions raise)

    Saga-Compensation-Integration:
        Use Saga-on-failure handler to instantiate and start_hemostasis().
        Cleanup-callback receives (HealingContext) for compensation logic.
    """

    def __init__(
        self,
        saga_run_id: str,
        hotel_id: str,
        on_phase_transition: Optional[
            Callable[[HealingPhase, HealingPhase, HealingContext], None]
        ] = None,
        cleanup_callback: Optional[Callable[[HealingContext], None]] = None,
        restart_callback: Optional[Callable[[HealingContext], None]] = None,
        optimize_callback: Optional[Callable[[HealingContext], None]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not saga_run_id or not hotel_id:
            raise ValueError("saga_run_id and hotel_id required")
        self.context = HealingContext(saga_run_id=saga_run_id, hotel_id=hotel_id)
        self._phase: HealingPhase = HealingPhase.NOT_STARTED
        self._on_phase_transition = on_phase_transition
        self._cleanup_callback = cleanup_callback
        self._restart_callback = restart_callback
        self._optimize_callback = optimize_callback
        self._clock = clock
        self._lock = threading.RLock()
        self._started_at: Optional[float] = None
        self.metrics = HealingMetrics(clock=clock)

    @property
    def phase(self) -> HealingPhase:
        return self._phase

    def start_hemostasis(self, failure_reason: str) -> None:
        """Phase 1: Circuit-Break + Failure-Containment."""
        with self._lock:
            self._transition(HealingPhase.HEMOSTASIS)
            self.context.failure_reason = failure_reason
            self._started_at = self._clock()

    def transition_to_inflammation(self) -> None:
        """Phase 2: Cleanup + Garbage-Collection. Invokes cleanup_callback."""
        with self._lock:
            self._transition(HealingPhase.INFLAMMATION)
            if self._cleanup_callback is not None:
                try:
                    self._cleanup_callback(self.context)
                except Exception as e:
                    self.context.extra.setdefault("cleanup_errors", []).append(
                        f"{type(e).__name__}: {e}"
                    )

    def transition_to_proliferation(self) -> None:
        """Phase 3: Auto-Restart + State-Reconstruction. Invokes restart_callback."""
        with self._lock:
            self._transition(HealingPhase.PROLIFERATION)
            self.context.restart_attempts += 1
            if self._restart_callback is not None:
                try:
                    self._restart_callback(self.context)
                except Exception as e:
                    self.context.extra.setdefault("restart_errors", []).append(
                        f"{type(e).__name__}: {e}"
                    )

    def transition_to_remodeling(self) -> None:
        """Phase 4: Gradual Re-Optimization. Invokes optimize_callback."""
        with self._lock:
            self._transition(HealingPhase.REMODELING)
            if self._optimize_callback is not None:
                try:
                    self._optimize_callback(self.context)
                except Exception as e:
                    self.context.extra.setdefault("optimize_errors", []).append(
                        f"{type(e).__name__}: {e}"
                    )

    def complete(self) -> None:
        """Final transition to HEALED. Records MTTR."""
        with self._lock:
            self._transition(HealingPhase.HEALED)
            if self._started_at is not None:
                total_mttr = self._clock() - self._started_at
                self.metrics.record_total_mttr(total_mttr)

    def abort(self, reason: str) -> None:
        """Abort recovery (terminal). E.g. healing not possible."""
        with self._lock:
            self._transition(HealingPhase.ABORTED)
            self.context.extra["aborted_reason"] = reason

    def _transition(self, target: HealingPhase) -> None:
        """Internal transition with DAG validation + metric recording."""
        validate_transition(self._phase, target, ALLOWED_TRANSITIONS)
        old = self._phase
        now = self._clock()
        # Record duration of *previous* phase (if not the bootstrap phase)
        if self.context.phase_log:
            prev_phase, prev_t = self.context.phase_log[-1]
            self.metrics.record_phase_duration(prev_phase, now - prev_t)
        self.context.phase_log.append((target, now))
        self._phase = target
        if self._on_phase_transition is not None:
            try:
                self._on_phase_transition(old, target, self.context)
            except Exception:
                # transition-callback exceptions must not break state-machine
                pass


# CRUX-MK
