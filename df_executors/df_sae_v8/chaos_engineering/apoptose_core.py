"""Apoptose-Core (Pattern-Core, variant-agnostic) [CRUX-MK].

Welle-31 P-W31-1 Pattern-Core-vs-Domain-Extension-Trennung.

Pattern-Core fuer Failure-Injection + Cascade-Containment +
Bounded-Veto-Hold. Variant-Agnostic: kennt KEINE Trinity-Profile
(Conservative/Aggressive/Contrarian). Decay-Curves leben in
`trinity_decay_profile.py` (Domain-Extension).

Pattern-Zustandsmaschine (per Slot):
    HEALTHY --inject--> DAMAGED --(decay-fn)--> RECOVERED|UNHEALTHY|CRASHED

Invariants:
    I-AC-1: health_score in [0.0, 1.0] zu jedem Zeitpunkt
    I-AC-2: is_crashed implies health_score == 0.0
    I-AC-3: injection_history is append-only audit-log
    I-AC-4: Bounded-Veto-Protection ist TTL-bounded; expired protections
            werden lazy entfernt
    I-AC-5: Cascade-Containment-Score = 1 - affected/at_risk im selben
            Tenant; cross-tenant disjoint per Definition

Failure-Model:
    F-AC-1: Inject auf nicht-registrierten Slot -> KeyError
    F-AC-2: Inject mit invalid mode -> TypeError
    F-AC-3: Inject mit intensity ausserhalb [0,1] -> ValueError
    F-AC-4: Slot ohne mock_mode_only=True -> PermissionError (K_0-Schutz)

Decay-Pluggability: ein DecayProfile-Adapter steckt aktuelle Decay-Curve
ein. Pattern-Core ruft profile.compute(slot, dt) und delegiert.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol


# Pattern-Core Defaults (variant-agnostic)
DEFAULT_TOKEN_BUDGET: int = 50_000
DEFAULT_BYZANTINE_LIE_AMPLITUDE: float = 0.5
DEFAULT_UNHEALTHY_THRESHOLD: float = 0.3


class DecayProfile(Protocol):
    """Domain-Extension-Adapter for variant-specific decay/recovery.

    Implementations live in `trinity_decay_profile.py` (Cape-SAE-Domain).
    A DecayProfile is variant-agnostic data: it converts a (slot_state, dt)
    into a current health-value.
    """

    name: str

    def compute_health(self, baseline: float, dt_since_last_inject: float,
                       is_crashed: bool) -> float:
        ...

    def recovery_time_to_threshold(
        self, current_health: float, threshold: float, is_crashed: bool,
    ) -> float:
        ...

    def recovery_deadline_sec(self) -> float:
        ...


@dataclass(frozen=True)
class CoreInjectionEvent:
    """Immutable Pattern-Core injection record (audit, K12)."""
    event_id: str
    slot_id: str
    tenant_id: str
    mode: str  # mode-name as string (variant-agnostic)
    intensity: float
    injected_at: float
    metadata: Optional[dict] = None


@dataclass
class CoreSlotState:
    """Pattern-Core mutable slot-state (variant-agnostic).

    Domain-Extensions add typed `variant` enum + custom defaults; the
    core only treats `profile_name` as opaque tag (used for cross-tenant
    isolation? No - tenant_id alone is sufficient).
    """
    slot_id: str
    tenant_id: str  # generic name; domain-call: "hotel_id"
    profile_name: str  # opaque tag; domain links to DecayProfile
    mock_mode_only: bool = True
    health_score: float = 1.0
    token_consumed: int = 0
    token_budget: int = DEFAULT_TOKEN_BUDGET
    q_norm: float = 0.0
    is_partitioned: bool = False
    is_byzantine: bool = False
    is_crashed: bool = False
    last_heartbeat: float = 0.0


def apply_failure_mode(
    slot: CoreSlotState,
    mode_kind: str,
    intensity: float,
    now: float,
) -> None:
    """Pattern-Core failure-application (variant-agnostic).

    `mode_kind` is one of:
      'slot_crash' | 'token_starvation' | 'network_partition' |
      'byzantine_fault' | 'governance_drift' | 'heartbeat_timeout'

    Pre: slot.mock_mode_only is True; intensity in [0, 1].
    Post: slot mutated in-place; I-AC-1, I-AC-2, I-AC-3 maintained.
    """
    if not slot.mock_mode_only:
        raise PermissionError("K_0-Schutz: slot.mock_mode_only=False")
    if not (0.0 <= intensity <= 1.0):
        raise ValueError(f"intensity must be in [0,1], got {intensity}")

    if mode_kind == "slot_crash":
        if intensity >= 0.5:
            slot.is_crashed = True
            slot.health_score = 0.0
        else:
            slot.health_score = max(0.0, slot.health_score - intensity)
    elif mode_kind == "token_starvation":
        consume = int(slot.token_budget * intensity)
        slot.token_consumed = min(slot.token_consumed + consume, slot.token_budget)
        ratio = slot.token_consumed / max(1, slot.token_budget)
        slot.health_score = max(0.0, 1.0 - ratio)
    elif mode_kind == "network_partition":
        if intensity >= 0.5:
            slot.is_partitioned = True
        slot.health_score *= (1.0 - 0.7 * intensity)
    elif mode_kind == "byzantine_fault":
        slot.is_byzantine = True
        slot.q_norm += DEFAULT_BYZANTINE_LIE_AMPLITUDE * intensity
        # Byzantine doesn't reduce health directly (subtle)
    elif mode_kind == "governance_drift":
        slot.q_norm = 2.0 + intensity if slot.q_norm >= 0 else -2.0 - intensity
        slot.health_score = max(0.0, slot.health_score - 0.3 * intensity)
    elif mode_kind == "heartbeat_timeout":
        slot.last_heartbeat = now - (60.0 * intensity)
        slot.health_score = max(0.0, slot.health_score - 0.5 * intensity)
    else:
        raise ValueError(f"unknown mode_kind {mode_kind!r}")


def reset_slot_state(slot: CoreSlotState, now: float) -> None:
    """Pattern-Core: restore pristine slot state (used by Domain-Adapter)."""
    slot.health_score = 1.0
    slot.token_consumed = 0
    slot.q_norm = 0.0
    slot.is_partitioned = False
    slot.is_byzantine = False
    slot.is_crashed = False
    slot.last_heartbeat = now


def cascade_radius_in_tenant(
    target_slot_id: str,
    target_tenant_id: str,
    peers: list,
    tenant_attr: str,
    health_lookup: Callable[[str, str], float],
    unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
) -> int:
    """Pattern-Core: count peers in same tenant with health < threshold.

    Field-name-agnostic: Domain-Adapter passes `tenant_attr` (e.g. 'hotel_id'
    in SAE, 'project_id' in another domain). I-AC-5: cross-tenant disjoint.
    Target excluded.
    """
    count = 0
    for peer in peers:
        peer_tenant = getattr(peer, tenant_attr)
        if peer.slot_id == target_slot_id and peer_tenant == target_tenant_id:
            continue
        if peer_tenant != target_tenant_id:
            continue
        h = health_lookup(peer.slot_id, peer_tenant)
        if h < unhealthy_threshold:
            count += 1
    return count


def cascade_containment_score(
    target_slot_id: str,
    target_tenant_id: str,
    peers: list,
    tenant_attr: str,
    health_lookup: Callable[[str, str], float],
    unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
) -> float:
    """CCS in [0,1]: 1.0 = perfect isolation; 0.0 = total cascade."""
    at_risk = [
        p for p in peers
        if getattr(p, tenant_attr) == target_tenant_id
        and not (p.slot_id == target_slot_id
                 and getattr(p, tenant_attr) == target_tenant_id)
    ]
    total = len(at_risk)
    if total == 0:
        return 1.0
    affected = cascade_radius_in_tenant(
        target_slot_id, target_tenant_id, peers, tenant_attr,
        health_lookup, unhealthy_threshold,
    )
    return max(0.0, 1.0 - (affected / total))


def slot_is_actually_unhealthy(
    slot: CoreSlotState,
    unhealthy_threshold: float = DEFAULT_UNHEALTHY_THRESHOLD,
) -> bool:
    """Ground-truth: pattern-level unhealth detection (variant-agnostic).

    Used by Bounded-Veto-Correctness: was the actual veto justified?
    """
    return (
        slot.is_crashed or slot.is_byzantine or slot.is_partitioned
        or slot.health_score < unhealthy_threshold
        or not (-2.0 <= slot.q_norm <= 2.0)
    )


# [CRUX-MK]
