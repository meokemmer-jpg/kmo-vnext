"""SAE-v8 Failure-Injector (Domain-Adapter ueber Apoptose-Core) [CRUX-MK].

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

Domain-Adapter combining:
- `apoptose_core`               (Pattern-Core)
- `trinity_decay_profile`       (Domain-Extension, optional)
- SAE-FailureMode-Enum          (Extension)
- SlotVariant-typed MockSlot    (Extension)

Bio->SAE Mapping: SLOT_CRASH/TOKEN_STARVATION/NETWORK_PARTITION/
BYZANTINE_FAULT/GOVERNANCE_DRIFT/HEARTBEAT_TIMEOUT.
K_0 (Mock-only) + K11/K12/K13/K14.
"""

from __future__ import annotations

import enum
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from .apoptose_core import (
    DEFAULT_BYZANTINE_LIE_AMPLITUDE,
    DEFAULT_TOKEN_BUDGET,
    apply_failure_mode,
    reset_slot_state,
)
from .trinity_decay_profile import (
    DEFAULT_AGGRESSIVE_RAMP_PER_SEC,
    DEFAULT_RECOVERY_TIME_CONSTANT_SEC,
    SlotVariant,
    profile_for_variant,
)


class FailureMode(enum.Enum):
    """SAE-Slot-Failure-Modi (Domain-Extension Enum)."""
    SLOT_CRASH = "slot_crash"
    TOKEN_STARVATION = "token_starvation"
    NETWORK_PARTITION = "network_partition"
    BYZANTINE_FAULT = "byzantine_fault"
    GOVERNANCE_DRIFT = "governance_drift"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"


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
    """In-Memory Mock-SAE-Slot (Domain-Adapter ueber CoreSlotState).

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
    """Injiziert Failure-Modes in MockSlots. Thread-safe.

    Domain-Adapter: kombiniert MockSlot (Domain-typed) mit Apoptose-Core
    (apply_failure_mode) und Trinity-Decay-Profiles (compute_health).
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        use_trinity_decay: bool = True,
    ) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._slots: dict[tuple[str, str], MockSlot] = {}
        self.use_trinity_decay = use_trinity_decay

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
        """Injiziert Failure-Mode in registrierten MockSlot. Atomic + audit-trail.

        Delegates the actual state-mutation to apoptose_core.apply_failure_mode.
        """
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
            # Pattern-Core: delegate state-mutation
            apply_failure_mode(slot, mode.value, intensity, now)
            slot.injection_history.append(event)
            return event

    def reset_slot(self, slot_id: str, hotel_id: str) -> None:
        with self._lock:
            slot = self._slots.get((slot_id, hotel_id))
            if slot is None:
                return
            reset_slot_state(slot, self._clock())

    def compute_health(self, slot_id: str, hotel_id: str) -> float:
        """Health-Score with variant-spezifischer Decay/Recovery.

        Extension: when use_trinity_decay=False, returns raw slot.health_score.
        """
        with self._lock:
            slot = self._slots.get((slot_id, hotel_id))
            if slot is None:
                return 0.0
            if slot.is_crashed:
                return 0.0
            if not slot.injection_history:
                return slot.health_score
            if not self.use_trinity_decay:
                return slot.health_score
            last_inject = slot.injection_history[-1]
            dt = self._clock() - last_inject.injected_at
            profile = profile_for_variant(slot.variant)
            return profile.compute_health(slot.health_score, dt, slot.is_crashed)

    def is_healthy(self, slot_id: str, hotel_id: str, threshold: float = 0.5) -> bool:
        return self.compute_health(slot_id, hotel_id) >= threshold


# CRUX-MK
