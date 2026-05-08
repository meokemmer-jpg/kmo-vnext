"""SAE-v8 Failure-Injector [CRUX-MK].

Welle-30 W-30-2. Bio->SAE Mapping: SLOT_CRASH/TOKEN_STARVATION/NETWORK_PARTITION/
BYZANTINE_FAULT/GOVERNANCE_DRIFT/HEARTBEAT_TIMEOUT. K_0 (Mock-only) + K11/K12/K13/K14.
Variant-Decay (Trinity): Conservative=exp-recovery, Aggressive=linear-ramp, Contrarian=binaer.
"""

from __future__ import annotations

import enum
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional


DEFAULT_TOKEN_BUDGET: int = 50_000  # SAE T_CAP
DEFAULT_RECOVERY_TIME_CONSTANT_SEC: float = 30.0
DEFAULT_AGGRESSIVE_RAMP_PER_SEC: float = 0.1
DEFAULT_BYZANTINE_LIE_AMPLITUDE: float = 0.5


class FailureMode(enum.Enum):
    """SAE-Slot-Failure-Modi."""
    SLOT_CRASH = "slot_crash"
    TOKEN_STARVATION = "token_starvation"
    NETWORK_PARTITION = "network_partition"
    BYZANTINE_FAULT = "byzantine_fault"
    GOVERNANCE_DRIFT = "governance_drift"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"


class SlotVariant(str, enum.Enum):
    """SAE-Trinity-Slot-Varianten."""
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    CONTRARIAN = "contrarian"


@dataclass(frozen=True)
class InjectionEvent:
    """Immutable Failure-Injection-Record (audit-trail, K12)."""
    event_id: str
    slot_id: str
    hotel_id: str
    variant: SlotVariant
    mode: FailureMode
    intensity: float
    injected_at: float
    metadata: Optional[dict] = None


@dataclass
class MockSlot:
    """In-Memory Mock-SAE-Slot. KEIN echter Trinity-Slot.

    Pre: slot_id, hotel_id non-empty; variant ist SlotVariant; mock_mode_only=True.
    Post: State lebt nur in-memory. Keine externe Verbindung.
    """
    slot_id: str
    hotel_id: str
    variant: SlotVariant
    mock_mode_only: bool = True
    health_score: float = 1.0
    token_consumed: int = 0
    token_budget: int = DEFAULT_TOKEN_BUDGET
    q_norm: float = 0.0
    is_partitioned: bool = False
    is_byzantine: bool = False
    is_crashed: bool = False
    last_heartbeat: float = field(default_factory=time.time)
    injection_history: list[InjectionEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.slot_id or not self.hotel_id:
            raise ValueError("slot_id und hotel_id required")
        if not isinstance(self.variant, SlotVariant):
            raise TypeError(f"variant must be SlotVariant, got {type(self.variant)}")
        if not self.mock_mode_only:
            raise PermissionError(
                "K_0-Schutz: MockSlot.mock_mode_only MUST be True. "
                "SAE-v8-Production darf NIE durch chaos_engineering aktiviert werden."
            )


class SaeFailureInjector:
    """Injiziert Failure-Modes in MockSlots. Thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._slots: dict[tuple[str, str], MockSlot] = {}

    def register_slot(self, slot: MockSlot) -> None:
        if not slot.mock_mode_only:
            raise PermissionError("K_0-Schutz: only mock_mode_only=True permitted")
        with self._lock:
            self._slots[(slot.slot_id, slot.hotel_id)] = slot

    def get_slot(self, slot_id: str, hotel_id: str) -> Optional[MockSlot]:
        with self._lock:
            return self._slots.get((slot_id, hotel_id))

    def list_slots_for_hotel(self, hotel_id: str) -> list[MockSlot]:
        with self._lock:
            return [s for (sid, hid), s in self._slots.items() if hid == hotel_id]

    def inject(
        self,
        slot_id: str,
        hotel_id: str,
        mode: FailureMode,
        intensity: float = 1.0,
        metadata: Optional[dict] = None,
    ) -> InjectionEvent:
        """Injiziert Failure-Mode in registrierten MockSlot. Atomic + audit-trail."""
        if not isinstance(mode, FailureMode):
            raise TypeError(f"mode must be FailureMode, got {type(mode)}")
        if not (0.0 <= intensity <= 1.0):
            raise ValueError(f"intensity must be in [0,1], got {intensity}")

        with self._lock:
            slot = self._slots.get((slot_id, hotel_id))
            if slot is None:
                raise KeyError(f"MockSlot not registered: {slot_id!r}/{hotel_id!r}")
            if not slot.mock_mode_only:
                raise PermissionError("K_0-Schutz: slot.mock_mode_only=False")

            now = self._clock()
            event = InjectionEvent(
                event_id=str(uuid.uuid4()),
                slot_id=slot_id, hotel_id=hotel_id, variant=slot.variant,
                mode=mode, intensity=float(intensity), injected_at=now,
                metadata=dict(metadata) if metadata else None,
            )
            self._apply_mode(slot, mode, intensity, now)
            slot.injection_history.append(event)
            return event

    def _apply_mode(self, slot: MockSlot, mode: FailureMode,
                    intensity: float, now: float) -> None:
        if mode is FailureMode.SLOT_CRASH:
            if intensity >= 0.5:
                slot.is_crashed = True
                slot.health_score = 0.0
            else:
                slot.health_score = max(0.0, slot.health_score - intensity)
        elif mode is FailureMode.TOKEN_STARVATION:
            consume = int(slot.token_budget * intensity)
            slot.token_consumed = min(slot.token_consumed + consume, slot.token_budget)
            ratio = slot.token_consumed / max(1, slot.token_budget)
            slot.health_score = max(0.0, 1.0 - ratio)
        elif mode is FailureMode.NETWORK_PARTITION:
            if intensity >= 0.5:
                slot.is_partitioned = True
            slot.health_score *= (1.0 - 0.7 * intensity)
        elif mode is FailureMode.BYZANTINE_FAULT:
            slot.is_byzantine = True
            slot.q_norm += DEFAULT_BYZANTINE_LIE_AMPLITUDE * intensity
            # Byzantine doesn't reduce health directly (subtle by design)
        elif mode is FailureMode.GOVERNANCE_DRIFT:
            slot.q_norm = 2.0 + intensity if slot.q_norm >= 0 else -2.0 - intensity
            slot.health_score = max(0.0, slot.health_score - 0.3 * intensity)
        elif mode is FailureMode.HEARTBEAT_TIMEOUT:
            slot.last_heartbeat = now - (60.0 * intensity)
            slot.health_score = max(0.0, slot.health_score - 0.5 * intensity)

    def reset_slot(self, slot_id: str, hotel_id: str) -> None:
        with self._lock:
            slot = self._slots.get((slot_id, hotel_id))
            if slot is None:
                return
            slot.health_score = 1.0
            slot.token_consumed = 0
            slot.q_norm = 0.0
            slot.is_partitioned = False
            slot.is_byzantine = False
            slot.is_crashed = False
            slot.last_heartbeat = self._clock()

    def compute_health(self, slot_id: str, hotel_id: str) -> float:
        """Berechnet Health-Score mit variant-spezifischer Decay/Ramp."""
        with self._lock:
            slot = self._slots.get((slot_id, hotel_id))
            if slot is None:
                return 0.0
            if slot.is_crashed:
                return 0.0
            if not slot.injection_history:
                return slot.health_score
            last_inject = slot.injection_history[-1]
            dt = self._clock() - last_inject.injected_at

            if slot.variant is SlotVariant.CONSERVATIVE:
                missing = 1.0 - slot.health_score
                recovered = missing * (1.0 - math.exp(-dt / DEFAULT_RECOVERY_TIME_CONSTANT_SEC))
                return min(1.0, slot.health_score + recovered)
            elif slot.variant is SlotVariant.AGGRESSIVE:
                ramp = DEFAULT_AGGRESSIVE_RAMP_PER_SEC * dt
                return max(0.0, slot.health_score - ramp)
            else:  # CONTRARIAN
                return slot.health_score

    def is_healthy(self, slot_id: str, hotel_id: str, threshold: float = 0.5) -> bool:
        return self.compute_health(slot_id, hotel_id) >= threshold


# CRUX-MK
