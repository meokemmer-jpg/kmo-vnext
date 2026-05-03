"""KMO Apoptosis-Engine [CRUX-MK].

KMO-vNext Phase-1 Modul 2.2: Programmierter Cell-Tod via Multi-Signal-Trigger
+ 3-Stage-Caspase-Cascade + Bcl-2-Modulation + Cytochrome-c-Snapshot.

Bio-Aequivalent: Caspase-Kaskade. Initiator-Caspase 8/9 erhaelt Apoptose-Signale,
aktiviert Effector-Caspase 3/7, die Substrate cleavt -> kontrollierte
Cell-Fragmentierung OHNE Entzuendung. Bcl-2-Familie modulisiert Anti-Apoptose-
Schutz fuer kritische Decisions. Cytochrome-c-Release als Pre-Death-Snapshot.

Mathematisch:
    P(apoptose) = sigmoid(Σ w_i * signal_i - threshold_with_bcl2_offset)
    Bcl-2-Offset:  offset = -log(1 + n_active_protections)

Implementiert §Phase-1.2.2 der SPEC-KMO-VNEXT-BIO-ARCHITEKTUR-2026-05-01.

K11 Cascade-Containment: Apoptose isoliert pro Cell, kein Spillover.
K12 Distillation-Resistenz: Cytochrome-c-Snapshot mit Provenance.
K13 Pre-Action-Verification: Trigger-Conditions VOR Cell-Tod geprueft.
K14 Human-Override-Decay: Bcl-2-Protection als 1-Funktions-Override.

Usage:
    engine = ApoptosisEngine(snapshot_dir=Path.home() / ".kmo/apoptose")
    engine.signal(cell_id="cell-1", hotel_id="hotel-A",
                   trigger=TriggerType.STATE_KORRUPTION, intensity=0.8)
    engine.signal(cell_id="cell-1", hotel_id="hotel-A",
                   trigger=TriggerType.MAX_RETRIES, intensity=1.0)
    # Wenn Threshold erreicht: 3-Stage-Cascade laeuft
    state = engine.get_state("cell-1", "hotel-A")
"""

from __future__ import annotations

import enum
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .bcl2_modulator import Bcl2Modulator
from .cytochrome_c_snapshot import CytochromeCSnapshotter


# Constants with units (no magic numbers).
DEFAULT_THRESHOLD: float = 0.5
DEFAULT_STOP_FLAG_WEIGHT: float = 1_000.0  # effectively immediate trigger
DEFAULT_STATE_KORRUPTION_WEIGHT: float = 1.0
DEFAULT_MAX_RETRIES_WEIGHT: float = 0.5

CASCADE_STAGE_INITIAL_CHECK: str = "initial_check"
CASCADE_STAGE_EFFECTOR_CASCADE: str = "effector_cascade"
CASCADE_STAGE_CLEANUP: str = "cleanup"


class TriggerType(enum.Enum):
    """Apoptose-Trigger-Quellen (Bio-Aequivalent: Death-Receptor-Pathways)."""

    STATE_KORRUPTION = "state_korruption"      # DNA-Damage-Analog
    STOP_FLAG = "stop_flag"                     # Death-Receptor (Fas/TNF)
    MAX_RETRIES = "max_retries"                 # Stress-Signal (ER-Stress)
    QUOTA_EXHAUSTED = "quota_exhausted"         # Glucose-Deprivation-Analog
    HEALTH_CHECK_FAILED = "health_check_failed" # Mitochondrial-Damage


class CascadeStage(str, enum.Enum):
    """3-Stage-Caspase-Cascade phases."""

    NOT_TRIGGERED = "not_triggered"
    INITIAL_CHECK = "initial_check"
    EFFECTOR_CASCADE = "effector_cascade"
    CLEANUP = "cleanup"
    APOPTOSED = "apoptosed"


@dataclass(frozen=True)
class SignalEvent:
    """Immutable record of a single apoptose-signal (audit-trail)."""

    cell_id: str
    hotel_id: str
    trigger: TriggerType
    intensity: float          # [0, 1+] signal strength
    timestamp: float
    weight: float             # weight at-receive-time (frozen for replay)


@dataclass
class ApoptoseState:
    """Mutable state per cell. Tracks accumulated signals + cascade-stage."""

    cell_id: str
    hotel_id: str
    accumulated_score: float = 0.0  # Σ w_i * signal_i
    signals: list[SignalEvent] = field(default_factory=list)
    cascade_stage: CascadeStage = CascadeStage.NOT_TRIGGERED
    triggered_at: Optional[float] = None
    apoptose_reason: Optional[str] = None
    snapshot_path: Optional[str] = None


class ApoptosisEngine:
    """Multi-Signal-Trigger-Engine + 3-Stage-Caspase-Cascade.

    Pre-Conditions:
        - snapshot_dir: writable Path for cytochrome-c-snapshots
        - bcl2_modulator: optional override (default: in-process Bcl2Modulator)
        - on_apoptosed: optional callback fired AFTER cleanup (notification hook)
        - clock: injectable for tests

    Post-Conditions:
        - signal() is atomic; cascade triggered exactly once per cell on threshold
        - Each cascade stage transition persists state (idempotent on re-call)
        - Cytochrome-c-snapshot written before EFFECTOR_CASCADE (forensic trail)

    Threshold-Math:
        score = Σ w_i * signal_i
        eff_threshold = threshold + bcl2_offset
        bcl2_offset = -log(1 + n_active_protections) * scale  (always <= 0, NEGATIVE-EXP)
        # NOTE: spec-text says "-log(1 + n)"; we apply with sign s.t. higher protection
        # raises eff_threshold (= harder to trigger).
        triggered = score >= eff_threshold
    """

    def __init__(
        self,
        snapshot_dir: Optional[Path] = None,
        bcl2_modulator: Optional[Bcl2Modulator] = None,
        threshold: float = DEFAULT_THRESHOLD,
        weights: Optional[dict] = None,
        on_apoptosed: Optional[Callable[[ApoptoseState], None]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.snapshot_dir = (
            Path(snapshot_dir)
            if snapshot_dir
            else Path.home() / "Library" / "Application Support" / "kmo" / "apoptose"
        )
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.snapshotter = CytochromeCSnapshotter(self.snapshot_dir)
        self.bcl2 = bcl2_modulator if bcl2_modulator is not None else Bcl2Modulator()
        self.threshold = threshold
        self.weights = weights or {
            TriggerType.STATE_KORRUPTION: DEFAULT_STATE_KORRUPTION_WEIGHT,
            TriggerType.STOP_FLAG: DEFAULT_STOP_FLAG_WEIGHT,
            TriggerType.MAX_RETRIES: DEFAULT_MAX_RETRIES_WEIGHT,
            TriggerType.QUOTA_EXHAUSTED: DEFAULT_STATE_KORRUPTION_WEIGHT,
            TriggerType.HEALTH_CHECK_FAILED: DEFAULT_STATE_KORRUPTION_WEIGHT,
        }
        self._on_apoptosed = on_apoptosed
        self._clock = clock
        self._lock = threading.RLock()
        self._states: dict[tuple[str, str], ApoptoseState] = {}
        # cell_state_provider: optional callable(cell_id, hotel_id) -> dict for snapshots
        self._state_provider: Optional[Callable[[str, str], dict]] = None

    def register_state_provider(
        self, provider: Callable[[str, str], dict]
    ) -> None:
        """Register a callback that returns cell-state dict for snapshot purposes.

        Called pre-EFFECTOR_CASCADE to capture forensic state (consumed_quotas,
        last_io_events, etc.). If None: snapshot only contains apoptose-meta.
        """
        self._state_provider = provider

    # ---------------- Public API ----------------

    def signal(
        self,
        cell_id: str,
        hotel_id: str,
        trigger: TriggerType,
        intensity: float = 1.0,
    ) -> ApoptoseState:
        """Record a trigger-signal. Triggers cascade if threshold reached.

        Pre:
            - cell_id, hotel_id non-empty
            - trigger is TriggerType
            - intensity >= 0
        Post:
            - SignalEvent appended; accumulated_score updated atomically
            - If score >= eff_threshold AND not yet triggered: cascade starts
            - Returns current state snapshot
        """
        if not cell_id or not hotel_id:
            raise ValueError("cell_id and hotel_id required")
        if not isinstance(trigger, TriggerType):
            raise TypeError(f"trigger must be TriggerType, got {type(trigger)}")
        if intensity < 0:
            raise ValueError(f"intensity must be >= 0, got {intensity}")

        weight = float(self.weights.get(trigger, DEFAULT_STATE_KORRUPTION_WEIGHT))
        ts = self._clock()
        event = SignalEvent(
            cell_id=cell_id,
            hotel_id=hotel_id,
            trigger=trigger,
            intensity=float(intensity),
            timestamp=ts,
            weight=weight,
        )

        with self._lock:
            key = (cell_id, hotel_id)
            state = self._states.get(key)
            if state is None:
                state = ApoptoseState(cell_id=cell_id, hotel_id=hotel_id)
                self._states[key] = state

            # Already apoptosed? Just record signal, no re-cascade.
            if state.cascade_stage == CascadeStage.APOPTOSED:
                state.signals.append(event)
                return state

            state.signals.append(event)
            state.accumulated_score += weight * float(intensity)

            eff_threshold = self._effective_threshold(cell_id, hotel_id)
            if state.accumulated_score >= eff_threshold and state.cascade_stage == CascadeStage.NOT_TRIGGERED:
                state.cascade_stage = CascadeStage.INITIAL_CHECK
                state.triggered_at = ts
                state.apoptose_reason = trigger.value
                # Run cascade synchronously inside lock to ensure single-execution.
                self._run_cascade(state)

            return state

    def get_state(self, cell_id: str, hotel_id: str) -> Optional[ApoptoseState]:
        """Returns current state for cell (or None if no signals received)."""
        with self._lock:
            return self._states.get((cell_id, hotel_id))

    def is_apoptosed(self, cell_id: str, hotel_id: str) -> bool:
        s = self.get_state(cell_id, hotel_id)
        return s is not None and s.cascade_stage == CascadeStage.APOPTOSED

    def trigger_probability(self, cell_id: str, hotel_id: str) -> float:
        """Return current sigmoid(score - eff_threshold) ∈ (0, 1)."""
        with self._lock:
            state = self._states.get((cell_id, hotel_id))
            score = state.accumulated_score if state else 0.0
            eff_t = self._effective_threshold(cell_id, hotel_id)
            return _sigmoid(score - eff_t)

    # ---------------- Internals ----------------

    def _effective_threshold(self, cell_id: str, hotel_id: str) -> float:
        """eff = threshold + bcl2_offset. More protection -> higher threshold."""
        n_protections = self.bcl2.count_active_protections(cell_id, hotel_id)
        # offset is non-negative; raises threshold (= harder to apoptose)
        offset = math.log1p(n_protections)
        return self.threshold + offset

    def _run_cascade(self, state: ApoptoseState) -> None:
        """3-Stage Caspase-Cascade: idempotent, persistent state transitions.

        Called under self._lock.
        """
        # Stage 1: INITIAL_CHECK (validate, prepare)
        state.cascade_stage = CascadeStage.INITIAL_CHECK

        # Snapshot BEFORE effector cascade (forensic provenance)
        cell_state_payload = {}
        if self._state_provider is not None:
            try:
                cell_state_payload = self._state_provider(state.cell_id, state.hotel_id) or {}
            except Exception as e:
                cell_state_payload = {"_state_provider_error": f"{type(e).__name__}: {e}"}

        snapshot_path = self.snapshotter.snapshot(
            cell_id=state.cell_id,
            hotel_id=state.hotel_id,
            apoptose_reason=state.apoptose_reason or "unknown",
            triggered_at=state.triggered_at or self._clock(),
            accumulated_score=state.accumulated_score,
            cell_state=cell_state_payload,
            signals=[
                {
                    "trigger": ev.trigger.value,
                    "intensity": ev.intensity,
                    "timestamp": ev.timestamp,
                    "weight": ev.weight,
                }
                for ev in state.signals
            ],
        )
        state.snapshot_path = str(snapshot_path)

        # Stage 2: EFFECTOR_CASCADE (mark apoptosing)
        state.cascade_stage = CascadeStage.EFFECTOR_CASCADE

        # Stage 3: CLEANUP (idempotent; multiple calls do not re-trigger)
        state.cascade_stage = CascadeStage.CLEANUP

        # Final state
        state.cascade_stage = CascadeStage.APOPTOSED

        # Notification hook (best-effort)
        if self._on_apoptosed is not None:
            try:
                self._on_apoptosed(state)
            except Exception:
                pass


def _sigmoid(x: float) -> float:
    """Standard sigmoid. Numerically stable for large |x|."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# CRUX-MK
