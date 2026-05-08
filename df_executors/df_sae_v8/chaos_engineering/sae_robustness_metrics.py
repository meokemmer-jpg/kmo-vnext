"""SAE-v8 Robustness-Metrics [CRUX-MK].

Welle-30 W-30-2. Bio-Aequivalent: Cytochrome-c-Snapshot-Forensik.
Mathematik: RTH = inf{t > t_inject : health(t) >= threshold}, else +inf;
CCS = 1 - (affected / total_at_risk_within_hotel); BVK = correct/total.
Variant-Deadlines: Conservative <60s, Aggressive <180s, Contrarian binaer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .sae_failure_injector import (
    FailureMode, MockSlot, SaeFailureInjector, SlotVariant,
)


DEFAULT_HEALTH_RECOVERY_THRESHOLD: float = 0.5
DEFAULT_UNHEALTHY_THRESHOLD: float = 0.3
DEFAULT_CASCADE_RADIUS_LIMIT: int = 3
DEFAULT_RECOVERY_DEADLINE_CONSERVATIVE_SEC: float = 60.0
DEFAULT_RECOVERY_DEADLINE_AGGRESSIVE_SEC: float = 180.0
DEFAULT_RECOVERY_DEADLINE_CONTRARIAN_SEC: float = float("inf")


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
    """Berechnet Robustness-Metriken (read-only)."""

    def __init__(self, injector: SaeFailureInjector) -> None:
        self.injector = injector

    def recovery_time_to_threshold(
        self, slot_id: str, hotel_id: str,
        threshold: float = DEFAULT_HEALTH_RECOVERY_THRESHOLD,
        max_check_sec: float = 600.0, step_sec: float = 1.0,
    ) -> float:
        """RTH analytisch (Conservative: exponential), variant-spezifisch."""
        slot = self.injector.get_slot(slot_id, hotel_id)
        if slot is None or not slot.injection_history:
            return 0.0
        if slot.is_crashed:
            return float("inf")
        h0 = max(slot.health_score, 0.0)

        if slot.variant is SlotVariant.CONSERVATIVE:
            from .sae_failure_injector import DEFAULT_RECOVERY_TIME_CONSTANT_SEC
            tau = DEFAULT_RECOVERY_TIME_CONSTANT_SEC
            if h0 >= threshold:
                return 0.0
            if 1.0 - h0 <= 0:
                return float("inf")
            ratio = (threshold - h0) / (1.0 - h0)
            if ratio >= 1.0:
                return float("inf")
            return -tau * math.log(1.0 - ratio)
        elif slot.variant is SlotVariant.AGGRESSIVE:
            if h0 >= threshold:
                return 0.0
            return float("inf")  # ohne Reset keine Recovery
        else:  # CONTRARIAN
            return 0.0 if h0 >= threshold else float("inf")

    def cascade_radius(
        self, target_slot: MockSlot, peer_slots: list[MockSlot],
        unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
    ) -> int:
        """Anzahl Peer-Slots im selben hotel mit health < threshold (target excluded)."""
        count = 0
        for peer in peer_slots:
            if peer.slot_id == target_slot.slot_id and peer.hotel_id == target_slot.hotel_id:
                continue
            if peer.hotel_id != target_slot.hotel_id:
                continue
            current_health = self.injector.compute_health(peer.slot_id, peer.hotel_id)
            if current_health < unhealthy_threshold:
                count += 1
        return count

    def cascade_containment_score(
        self, target_slot: MockSlot, peer_slots: list[MockSlot],
        unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
    ) -> float:
        """CCS in [0,1]: 1.0 = perfekt isoliert; 0.0 = alles betroffen."""
        peers_at_risk = [
            p for p in peer_slots
            if p.hotel_id == target_slot.hotel_id
            and not (p.slot_id == target_slot.slot_id and p.hotel_id == target_slot.hotel_id)
        ]
        total = len(peers_at_risk)
        if total == 0:
            return 1.0
        affected = self.cascade_radius(target_slot, peer_slots, unhealthy_threshold)
        return max(0.0, 1.0 - (affected / total))

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

        Slot is actually_unhealthy wenn:
            is_crashed OR is_byzantine OR is_partitioned
            OR health_score < threshold
            OR q_norm out of [-2, +2]
        """
        actually_unhealthy = (
            slot.is_crashed or slot.is_byzantine or slot.is_partitioned
            or slot.health_score < unhealthy_threshold
            or not (-2.0 <= slot.q_norm <= 2.0)
        )
        return BoundedVetoOutcome(
            decision_id=decision_id, slot_id=slot.slot_id, hotel_id=slot.hotel_id,
            veto_activated=veto_activated,
            slot_was_actually_unhealthy=actually_unhealthy,
            timestamp=timestamp,
        )

    @staticmethod
    def variant_deadline_sec(variant: SlotVariant) -> float:
        """Variant-spezifische Recovery-Deadline (CRUX-Q_0-Maintenance)."""
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
