"""SAE-v8 Chaos-Orchestrator [CRUX-MK].

Welle-30 W-30-2. Bio-Aequivalent: ApoptosisEngine + Bcl2Modulator.
SaeChaosOrchestrator~ApoptosisEngine; ProtectionTokens~Bcl2Modulator;
ExperimentResult~ApoptoseState; InjectionEvent~SignalEvent.
K11/K12/K13/K14 + K_0 (SAE-Production-Schutz, Mock-only).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .sae_failure_injector import (
    FailureMode, InjectionEvent, SaeFailureInjector, SlotVariant,
)
from .sae_robustness_metrics import (
    BoundedVetoOutcome, RobustnessReport, SaeRobustnessMetrics,
)


DEFAULT_RECOVERY_TIMEOUT_SEC: float = 300.0
DEFAULT_INJECTION_INTERVAL_SEC: float = 1.0
DEFAULT_VETO_DECISION_INTERVAL_SEC: float = 0.5
DEFAULT_VETO_PROTECTION_TTL_SEC: float = 60.0


@dataclass(frozen=True)
class ChaosCampaign:
    """Definition einer Chaos-Engineering-Campaign (immutable contract)."""
    campaign_id: str
    hotel_id: str
    target_slot_id: str
    modes: tuple[FailureMode, ...] = ()
    intensities: Optional[tuple[float, ...]] = None
    veto_protection_decision_ids: tuple[str, ...] = ()
    metadata: Optional[dict] = None

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.hotel_id or not self.target_slot_id:
            raise ValueError("campaign_id, hotel_id, target_slot_id required")
        if not self.modes:
            raise ValueError("modes must contain at least 1 FailureMode")
        for m in self.modes:
            if not isinstance(m, FailureMode):
                raise TypeError(f"all modes must be FailureMode, got {type(m)}")
        if self.intensities is not None:
            if len(self.intensities) != len(self.modes):
                raise ValueError(
                    f"intensities length {len(self.intensities)} "
                    f"!= modes length {len(self.modes)}"
                )
            for i in self.intensities:
                if not (0.0 <= i <= 1.0):
                    raise ValueError(f"intensity {i} not in [0, 1]")


@dataclass
class ExperimentResult:
    """Mutable Result-Objekt (analog ApoptoseState)."""
    campaign_id: str
    hotel_id: str
    target_slot_id: str
    completed: bool = False
    injection_events: list[InjectionEvent] = field(default_factory=list)
    veto_outcomes: list[BoundedVetoOutcome] = field(default_factory=list)
    report: Optional[RobustnessReport] = None
    started_at: float = 0.0
    completed_at: float = 0.0
    error: Optional[str] = None


class SaeChaosOrchestrator:
    """Orchestriert Chaos-Engineering-Campaigns. Thread-safe."""

    def __init__(
        self, injector: SaeFailureInjector, metrics: SaeRobustnessMetrics,
        bounded_veto_provider: Optional[Callable[..., bool]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.injector = injector
        self.metrics = metrics
        self._clock = clock
        self._lock = threading.RLock()
        self._results: dict[str, ExperimentResult] = {}
        self._veto_protected: dict[str, float] = {}
        self._bounded_veto_provider = (
            bounded_veto_provider if bounded_veto_provider is not None
            else self._default_bounded_veto_provider
        )

    # ---------------- Bounded-Veto Bcl-2 Analogon ----------------

    def protect_decision(
        self, decision_id: str,
        ttl_sec: float = DEFAULT_VETO_PROTECTION_TTL_SEC,
    ) -> str:
        """Registriert Bounded-Veto-Protection (analog Bcl-2.protect_pending_decision)."""
        if not decision_id:
            raise ValueError("decision_id required")
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be > 0")
        with self._lock:
            self._veto_protected[decision_id] = self._clock() + float(ttl_sec)
        return decision_id

    def release_protection(self, decision_id: str) -> bool:
        with self._lock:
            return self._veto_protected.pop(decision_id, None) is not None

    def _is_protected(self, decision_id: str) -> bool:
        with self._lock:
            exp = self._veto_protected.get(decision_id)
            if exp is None:
                return False
            if exp <= self._clock():
                del self._veto_protected[decision_id]
                return False
            return True

    @staticmethod
    def _default_bounded_veto_provider(slot, decision_id: str) -> bool:
        """Default Bounded-Veto-Heuristik (COSMOS-Compliance-Layer-Analog)."""
        return (
            slot.is_crashed or slot.is_byzantine or slot.is_partitioned
            or slot.health_score < 0.3
            or not (-2.0 <= slot.q_norm <= 2.0)
        )

    # ---------------- Campaign Execution ----------------

    def run_campaign(
        self, campaign: ChaosCampaign, n_veto_decisions: int = 3,
    ) -> ExperimentResult:
        """Fuehrt Campaign aus.

        Schritte: Pre-Run-Check (K_0), Bcl-2-Protections, Failure-Inject-Sequence,
        Bounded-Veto-Decisions, RobustnessReport, completion.
        """
        with self._lock:
            result = ExperimentResult(
                campaign_id=campaign.campaign_id,
                hotel_id=campaign.hotel_id,
                target_slot_id=campaign.target_slot_id,
                started_at=self._clock(),
            )
            try:
                self._pre_run_verify(campaign)
                for did in campaign.veto_protection_decision_ids:
                    self.protect_decision(did)

                target = self.injector.get_slot(
                    campaign.target_slot_id, campaign.hotel_id
                )
                if target is None:
                    raise KeyError(
                        f"Target-Slot not registered: "
                        f"{campaign.target_slot_id}/{campaign.hotel_id}"
                    )

                intensities = (
                    campaign.intensities if campaign.intensities is not None
                    else tuple(1.0 for _ in campaign.modes)
                )
                for idx, mode in enumerate(campaign.modes):
                    intensity = intensities[idx]
                    event = self.injector.inject(
                        slot_id=campaign.target_slot_id,
                        hotel_id=campaign.hotel_id,
                        mode=mode, intensity=intensity,
                        metadata={"campaign_id": campaign.campaign_id, "step": idx},
                    )
                    result.injection_events.append(event)

                for d_idx in range(n_veto_decisions):
                    decision_id = f"{campaign.campaign_id}-decision-{d_idx}"
                    is_protected = self._is_protected(decision_id) or any(
                        self._is_protected(p)
                        for p in campaign.veto_protection_decision_ids
                    )
                    veto_should_fire = self._bounded_veto_provider(target, decision_id)
                    veto_fired = veto_should_fire and not is_protected
                    outcome = self.metrics.evaluate_bounded_veto(
                        slot=target, veto_activated=veto_fired,
                        decision_id=decision_id, timestamp=self._clock(),
                    )
                    result.veto_outcomes.append(outcome)

                peer_slots = self.injector.list_slots_for_hotel(campaign.hotel_id)
                report = self.metrics.build_report(
                    target_slot=target, peer_slots=peer_slots,
                    veto_outcomes=result.veto_outcomes,
                )
                result.report = report
                result.completed = True
                result.completed_at = self._clock()
            except Exception as e:
                result.error = f"{type(e).__name__}: {e}"
                result.completed = False
                result.completed_at = self._clock()
            finally:
                for did in campaign.veto_protection_decision_ids:
                    self.release_protection(did)
                self._results[campaign.campaign_id] = result
            return result

    def _pre_run_verify(self, campaign: ChaosCampaign) -> None:
        """K11+K13: pruefe alle Slots in target-hotel auf mock_mode_only=True."""
        slots = self.injector.list_slots_for_hotel(campaign.hotel_id)
        if not any(s.slot_id == campaign.target_slot_id for s in slots):
            raise KeyError(
                f"Target-Slot {campaign.target_slot_id} not in hotel {campaign.hotel_id}"
            )
        for s in slots:
            if not s.mock_mode_only:
                raise PermissionError(
                    f"K_0-Schutz: Slot {s.slot_id} mock_mode_only=False. "
                    "SAE-v8-Production darf NIE an chaos_engineering teilnehmen."
                )

    # ---------------- Result-Lookup ----------------

    def get_result(self, campaign_id: str) -> Optional[ExperimentResult]:
        with self._lock:
            return self._results.get(campaign_id)

    def list_results(self, hotel_id: Optional[str] = None) -> list[ExperimentResult]:
        with self._lock:
            if hotel_id is None:
                return list(self._results.values())
            return [r for r in self._results.values() if r.hotel_id == hotel_id]


# CRUX-MK
