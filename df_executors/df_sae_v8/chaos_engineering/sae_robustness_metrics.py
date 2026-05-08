"""SAE-v8 Robustness-Metrics (Domain-Adapter ueber Apoptose-Core) [CRUX-MK].

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

Domain-Adapter:
- `apoptose_core.cascade_containment_score` + `slot_is_actually_unhealthy`  (Pattern-Core)
- `trinity_decay_profile`-spezifische RTH + Deadlines                        (Extension)

Mathematik: RTH = inf{t > t_inject : health(t) >= threshold}, else +inf;
CCS = 1 - (affected / total_at_risk_within_hotel); BVK = correct/total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .apoptose_core import (
    DEFAULT_UNHEALTHY_THRESHOLD,
    cascade_containment_score as core_ccs,
    cascade_radius_in_tenant,
    slot_is_actually_unhealthy,
)
from .sae_failure_injector import MockSlot, SaeFailureInjector
from .trinity_decay_profile import (
    DEFAULT_RECOVERY_DEADLINE_AGGRESSIVE_SEC,
    DEFAULT_RECOVERY_DEADLINE_CONSERVATIVE_SEC,
    DEFAULT_RECOVERY_DEADLINE_CONTRARIAN_SEC,
    SlotVariant,
    profile_for_variant,
)


DEFAULT_HEALTH_RECOVERY_THRESHOLD: float = 0.5
DEFAULT_CASCADE_RADIUS_LIMIT: int = 3


@dataclass(frozen=True)
class BoundedVetoOutcome:
    """COSMOS Bounded-Veto-Decision-Outcome (immutable)."""
    decision_id: str
    slot_id: str
    hotel_id: str
    veto_activated: bool
    slot_was_actually_unhealthy: bool
    timestamp: float

    @property
    def is_correct(self) -> bool:
        return self.veto_activated == self.slot_was_actually_unhealthy

    @property
    def is_false_positive(self) -> bool:
        return self.veto_activated and not self.slot_was_actually_unhealthy

    @property
    def is_false_negative(self) -> bool:
        return not self.veto_activated and self.slot_was_actually_unhealthy


@dataclass
class RobustnessReport:
    """Zusammenfassung eines Chaos-Experiment-Runs.

    overall_score = 0.4*ccs + 0.4*bvk + 0.2*deadline_met (in [0,1]).
    """
    recovery_time_sec: float
    cascade_radius: int
    cascade_containment_score: float
    bounded_veto_correctness: float
    veto_outcomes: list[BoundedVetoOutcome] = field(default_factory=list)
    deadline_met: bool = False
    cascade_within_limits: bool = True
    target_slot_id: Optional[str] = None
    target_hotel_id: Optional[str] = None
    variant: Optional[SlotVariant] = None

    @property
    def overall_score(self) -> float:
        return (
            0.4 * self.cascade_containment_score
            + 0.4 * self.bounded_veto_correctness
            + 0.2 * (1.0 if self.deadline_met else 0.0)
        )


class SaeRobustnessMetrics:
    """Berechnet Robustness-Metriken (read-only).

    Domain-Adapter: delegiert cascade-radius/cascade-containment/
    is-actually-unhealthy an apoptose_core, RTH+Deadlines an
    trinity_decay_profile.
    """

    def __init__(self, injector: SaeFailureInjector) -> None:
        self.injector = injector

    def recovery_time_to_threshold(
        self, slot_id: str, hotel_id: str,
        threshold: float = DEFAULT_HEALTH_RECOVERY_THRESHOLD,
        max_check_sec: float = 600.0, step_sec: float = 1.0,
    ) -> float:
        """RTH variant-spezifisch via DecayProfile (Domain-Extension)."""
        slot = self.injector.get_slot(slot_id, hotel_id)
        if slot is None or not slot.injection_history:
            return 0.0
        h0 = max(slot.health_score, 0.0)
        profile = profile_for_variant(slot.variant)
        return profile.recovery_time_to_threshold(h0, threshold, slot.is_crashed)

    def cascade_radius(
        self, target_slot: MockSlot, peer_slots: list[MockSlot],
        unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
    ) -> int:
        """Anzahl Peer-Slots im selben hotel mit health < threshold (target excluded).

        Delegate to apoptose_core.cascade_radius_in_tenant. SAE-Domain
        nutzt 'hotel_id' als Tenant-Feld (Pattern-Core: 'tenant_attr').
        """
        return cascade_radius_in_tenant(
            target_slot_id=target_slot.slot_id,
            target_tenant_id=target_slot.hotel_id,
            peers=peer_slots,
            tenant_attr="hotel_id",
            health_lookup=self.injector.compute_health,
            unhealthy_threshold=unhealthy_threshold,
        )

    def cascade_containment_score(
        self, target_slot: MockSlot, peer_slots: list[MockSlot],
        unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
    ) -> float:
        """CCS in [0,1]: 1.0 = perfekt isoliert. Delegate to apoptose_core."""
        return core_ccs(
            target_slot_id=target_slot.slot_id,
            target_tenant_id=target_slot.hotel_id,
            peers=peer_slots,
            tenant_attr="hotel_id",
            health_lookup=self.injector.compute_health,
            unhealthy_threshold=unhealthy_threshold,
        )

    def bounded_veto_correctness(
        self, outcomes: list[BoundedVetoOutcome]
    ) -> float:
        """BVK in [0,1]: correct/total."""
        if not outcomes:
            return 1.0
        return sum(1 for o in outcomes if o.is_correct) / len(outcomes)

    def evaluate_bounded_veto(
        self, slot: MockSlot, veto_activated: bool, decision_id: str,
        timestamp: float,
        unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
    ) -> BoundedVetoOutcome:
        """Erstellt BoundedVetoOutcome durch Vergleich Veto vs Ground-Truth.

        Ground-truth via apoptose_core.slot_is_actually_unhealthy (Pattern-Core).
        """
        actually_unhealthy = slot_is_actually_unhealthy(slot, unhealthy_threshold)
        return BoundedVetoOutcome(
            decision_id=decision_id, slot_id=slot.slot_id, hotel_id=slot.hotel_id,
            veto_activated=veto_activated,
            slot_was_actually_unhealthy=actually_unhealthy,
            timestamp=timestamp,
        )

    @staticmethod
    def variant_deadline_sec(variant: SlotVariant) -> float:
        """Variant-spezifische Recovery-Deadline (Domain-Extension)."""
        if variant is SlotVariant.CONSERVATIVE:
            return DEFAULT_RECOVERY_DEADLINE_CONSERVATIVE_SEC
        if variant is SlotVariant.AGGRESSIVE:
            return DEFAULT_RECOVERY_DEADLINE_AGGRESSIVE_SEC
        return DEFAULT_RECOVERY_DEADLINE_CONTRARIAN_SEC

    def build_report(
        self, target_slot: MockSlot, peer_slots: list[MockSlot],
        veto_outcomes: list[BoundedVetoOutcome],
        unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
        recovery_threshold: float = DEFAULT_HEALTH_RECOVERY_THRESHOLD,
        cascade_limit: int = DEFAULT_CASCADE_RADIUS_LIMIT,
    ) -> RobustnessReport:
        """Synthese aller Metriken in RobustnessReport."""
        rth = self.recovery_time_to_threshold(
            target_slot.slot_id, target_slot.hotel_id, recovery_threshold
        )
        radius = self.cascade_radius(target_slot, peer_slots, unhealthy_threshold)
        ccs = self.cascade_containment_score(target_slot, peer_slots, unhealthy_threshold)
        bvk = self.bounded_veto_correctness(veto_outcomes)
        deadline = self.variant_deadline_sec(target_slot.variant)
        deadline_met = rth <= deadline

        return RobustnessReport(
            recovery_time_sec=rth, cascade_radius=radius,
            cascade_containment_score=ccs, bounded_veto_correctness=bvk,
            veto_outcomes=list(veto_outcomes), deadline_met=deadline_met,
            cascade_within_limits=radius <= cascade_limit,
            target_slot_id=target_slot.slot_id,
            target_hotel_id=target_slot.hotel_id, variant=target_slot.variant,
        )


# CRUX-MK
