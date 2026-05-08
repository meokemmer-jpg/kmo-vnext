# [CRUX-MK]
"""SAE-v8 Backpressure-Slot-Admission Core (Welle-34 Phase-27 Bio-Pattern-Lift Lift 16).

Baroreflex-on-Slot-Admission:
  Slot-Admission-Velocity wird gesampled (rolling window). Bei Ueberschreiten der
  Schwellen werden FlowState-Wechsel ausgeloest. Throttle-Aktionen reagieren
  reflexiv: ALLOW (NORMAL/ELEVATED) -> DELAY (THROTTLED) -> REJECT (BLOCKED).

Pattern-Quelle: kmo_governance.backpressure_engine (Welle-9, Hotel-Domain).
Bio-Aequivalent: Karotis-Sinus-Baroreflex (Drucksensoren -> vagale Hemmung).

Komponenten:
- SlotFlowState (Enum): NORMAL, ELEVATED, THROTTLED, BLOCKED
- SlotAdmissionSample (frozen): single admission-record fuer rolling window
- AdmissionThrottleAction (frozen): ALLOW/DELAY/REJECT decision
- SAESlotBackpressureDecision (frozen): tick-result mit Audit-Trail
- SAEv8BackpressureSlotAdmission: Orchestriert Sampling + Evaluation + Action-Dispatch

Konfiguration:
- max_admissions_per_minute: hard cap fuer Admission-Rate (admissions/minute)
- max_total_slots: SAE-v8-Constraint (Default 200 Slots)
- history_window: deque-maxlen fuer rolling sample-Behaltung (Default 60)
- elevated_threshold_pct: % der Hard-Caps fuer ELEVATED-Trigger (Default 70%)
- blocked_threshold_pct: % der Hard-Caps fuer BLOCKED-Trigger (Default 95%)

3-Achsen-Throttling:
- Achse 1: Global Slot-Admission-Rate (alle AgentClasses + alle Trinity-Variants)
- Achse 2: Per-AgentClass (z.B. "REVENUE_MANAGEMENT", "HOUSEKEEPING")
- Achse 3: Per-Trinity-Variant ("Conservative" / "Aggressive" / "Contrarian")

Beispiel: Pool ist mit 65% Conservative-Variants gefuellt -> Throttle weitere
Conservative-Admissions, um Trinity-Variant-Diversitaet zu erhalten.

CRUX-MK Bindung:
- K_0: Slot-Pool-Saturation-Schutz verhindert Agent-Spawn-Kaskaden bei Volatilitaets-Phasen.
- Q_0: Trinity-Variant-Imbalance-Schutz haelt 3-Variant-Diversitaet (z.B. nicht alle Conservative).
- I_min: AdmissionThrottleAction frozen + Audit-Trail (SAESlotBackpressureDecision Liste).
- W_0: Rolling-Window O(1) (deque maxlen) - kein O(N)-Overhead bei hoher Frequenz.
"""

from __future__ import annotations

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional


# ---------- SlotFlowState ----------


class SlotFlowState(str, enum.Enum):
    """Slot-Admission-Flow-State (Baroreflex-Tier).

    Pre: aufzaehlbar, immutable, str-enum -> dict-key-tauglich.
    Post: 4 Stufen mit Reflex-Semantik:
        NORMAL:    Admission-Flow im Normbereich -> ALLOW
        ELEVATED:  Flow erhoeht (>elevated_threshold) -> ALLOW (warn)
        THROTTLED: Flow nahe Hard-Cap (>cap-Schwelle, <blocked) -> DELAY
        BLOCKED:   Flow ueber Hard-Cap (>blocked_threshold) -> REJECT
    """

    NORMAL = "normal"
    ELEVATED = "elevated"
    THROTTLED = "throttled"
    BLOCKED = "blocked"


# ---------- SlotAdmissionSample ----------


@dataclass(frozen=True)
class SlotAdmissionSample:
    """Einzelner Slot-Admission-Record fuer rolling window.

    Pre:
      - timestamp > 0
      - agent_class non-empty
      - trinity_variant in {"Conservative", "Aggressive", "Contrarian"}
      - admission_count >= 1 (mindestens 1 Admission pro Sample)
    Post: immutable, hashable, audit-ready.
    """

    timestamp: float
    agent_class: str
    trinity_variant: str
    admission_count: int

    def __post_init__(self) -> None:
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")
        if not self.agent_class:
            raise ValueError("agent_class must be non-empty")
        if not self.trinity_variant:
            raise ValueError("trinity_variant must be non-empty")
        if self.trinity_variant not in ("Conservative", "Aggressive", "Contrarian"):
            raise ValueError(
                f"trinity_variant must be Conservative/Aggressive/Contrarian: "
                f"{self.trinity_variant}"
            )
        if self.admission_count < 1:
            raise ValueError(
                f"admission_count must be >= 1: {self.admission_count}"
            )


# ---------- AdmissionThrottleAction ----------


@dataclass(frozen=True)
class AdmissionThrottleAction:
    """Throttle-Aktion fuer eine Slot-Admission.

    Pre:
      - action_type in {"ALLOW", "DELAY", "REJECT"}
      - delay_ms >= 0 (DELAY benoetigt > 0)
      - reason non-empty
      - timestamp > 0
    Post: immutable, hashable, audit-ready.
    """

    action_type: str
    delay_ms: float
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if self.action_type not in ("ALLOW", "DELAY", "REJECT"):
            raise ValueError(f"unknown action_type: {self.action_type}")
        if self.delay_ms < 0:
            raise ValueError(f"delay_ms must be non-negative: {self.delay_ms}")
        if self.action_type == "DELAY" and self.delay_ms <= 0:
            raise ValueError("DELAY requires delay_ms > 0")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- SAESlotBackpressureDecision ----------


@dataclass(frozen=True)
class SAESlotBackpressureDecision:
    """SAE-v8-Slot-Backpressure-Decision pro evaluate()-Call.

    Pre:
      - state in SlotFlowState
      - current_rate >= 0
      - max_rate > 0
      - action: AdmissionThrottleAction
      - reason non-empty
      - timestamp > 0
    Post: immutable, audit-ready.
    """

    state: SlotFlowState
    current_rate: float
    max_rate: float
    action: AdmissionThrottleAction
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if self.current_rate < 0:
            raise ValueError(
                f"current_rate must be non-negative: {self.current_rate}"
            )
        if self.max_rate <= 0:
            raise ValueError(f"max_rate must be positive: {self.max_rate}")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.timestamp <= 0:
            raise ValueError(f"timestamp must be positive: {self.timestamp}")


# ---------- SAEv8BackpressureSlotAdmission ----------


class SAEv8BackpressureSlotAdmission:
    """Slot-Admission-Backpressure-Controller mit Per-AgentClass + Per-Trinity-Variant + Global FlowState.

    Pre:
      - max_admissions_per_minute > 0
      - max_total_slots > 0 (SAE-v8 Default 200)
      - history_window > 0
      - 0 <= elevated_threshold_pct < blocked_threshold_pct <= 100
    Post: thread-safe via RLock; rolling samples in O(1) via deque(maxlen).

    Default-Action-Map (kann via register_action() ueberschrieben werden):
      NORMAL    -> ALLOW (delay_ms=0)
      ELEVATED  -> ALLOW (delay_ms=0, reason mentions elevated)
      THROTTLED -> DELAY (delay_ms scaled by overage)
      BLOCKED   -> REJECT (delay_ms=0)
    """

    _VALID_TRINITY_VARIANTS = ("Conservative", "Aggressive", "Contrarian")

    def __init__(
        self,
        max_admissions_per_minute: float,
        max_total_slots: int = 200,
        history_window: int = 60,
        elevated_threshold_pct: float = 70.0,
        blocked_threshold_pct: float = 95.0,
        max_decisions_history: int = 10000,
    ) -> None:
        """Constructor mit V13-Patch P-V13-1 unbounded-history-Fix.

        Pre-Conditions:
            max_admissions_per_minute > 0.
            max_total_slots > 0 (SAE-v8 Default 200).
            history_window > 0.
            0 <= elevated_threshold_pct < blocked_threshold_pct <= 100.
            max_decisions_history >= 1 (V13-1: bounded audit-trail to prevent OOM).

        Post-Conditions:
            self._decisions ist deque mit maxlen=max_decisions_history (FIFO eviction).
            Aelteste Decisions werden bei Ueberlauf automatisch evicted.
        """
        if max_admissions_per_minute <= 0:
            raise ValueError("max_admissions_per_minute must be positive")
        if max_total_slots <= 0:
            raise ValueError("max_total_slots must be positive")
        if history_window <= 0:
            raise ValueError("history_window must be positive")
        if not (0.0 <= elevated_threshold_pct <= 100.0):
            raise ValueError(
                f"elevated_threshold_pct out of range: {elevated_threshold_pct}"
            )
        if not (0.0 <= blocked_threshold_pct <= 100.0):
            raise ValueError(
                f"blocked_threshold_pct out of range: {blocked_threshold_pct}"
            )
        if elevated_threshold_pct >= blocked_threshold_pct:
            raise ValueError(
                "require elevated_threshold_pct < blocked_threshold_pct"
            )
        if max_decisions_history < 1:
            raise ValueError(
                f"max_decisions_history must be >= 1: {max_decisions_history}"
            )

        self._max_admissions_per_minute = float(max_admissions_per_minute)
        self._max_total_slots = int(max_total_slots)
        self._history_window = int(history_window)
        self._elevated_pct = float(elevated_threshold_pct)
        self._blocked_pct = float(blocked_threshold_pct)
        self._max_decisions_history = int(max_decisions_history)

        # Global rolling buffer (across all agent_classes + trinity_variants)
        self._samples_global: deque[SlotAdmissionSample] = deque(
            maxlen=history_window
        )
        # Per-agent_class rolling buffers
        self._samples_per_class: dict[str, deque[SlotAdmissionSample]] = {}
        # Per-trinity_variant rolling buffers
        self._samples_per_variant: dict[str, deque[SlotAdmissionSample]] = {}

        # FlowState tracking (3-Achsen)
        self._global_state: SlotFlowState = SlotFlowState.NORMAL
        self._per_class_state: dict[str, SlotFlowState] = {}
        self._per_variant_state: dict[str, SlotFlowState] = {}

        # Custom action handlers per SlotFlowState
        self._action_handlers: dict[
            SlotFlowState, Callable[[float], AdmissionThrottleAction]
        ] = {}

        # Audit-Trail (V13-1: bounded deque statt unbounded list, Anti-OOM)
        self._decisions: deque[SAESlotBackpressureDecision] = deque(
            maxlen=self._max_decisions_history
        )

        self._lock = threading.RLock()

    # ---------- Public API ----------

    def record_admission(
        self,
        agent_class: str,
        trinity_variant: str,
        slot_id: str,
    ) -> None:
        """Records single slot-admission in rolling window (1 admission per call).

        Pre:
          - agent_class non-empty
          - trinity_variant in {"Conservative", "Aggressive", "Contrarian"}
          - slot_id non-empty
        Post:
          - sample appended to global + per-class + per-variant deque
          - older samples auto-evicted via maxlen
        """
        if not agent_class:
            raise ValueError("agent_class must be non-empty")
        if not trinity_variant:
            raise ValueError("trinity_variant must be non-empty")
        if trinity_variant not in self._VALID_TRINITY_VARIANTS:
            raise ValueError(
                f"trinity_variant must be Conservative/Aggressive/Contrarian: "
                f"{trinity_variant}"
            )
        if not slot_id:
            raise ValueError("slot_id must be non-empty")

        sample = SlotAdmissionSample(
            timestamp=time.time(),
            agent_class=agent_class,
            trinity_variant=trinity_variant,
            admission_count=1,
        )

        with self._lock:
            self._samples_global.append(sample)

            buf_class = self._samples_per_class.get(agent_class)
            if buf_class is None:
                buf_class = deque(maxlen=self._history_window)
                self._samples_per_class[agent_class] = buf_class
            buf_class.append(sample)

            buf_variant = self._samples_per_variant.get(trinity_variant)
            if buf_variant is None:
                buf_variant = deque(maxlen=self._history_window)
                self._samples_per_variant[trinity_variant] = buf_variant
            buf_variant.append(sample)

    def evaluate(
        self,
        agent_class: Optional[str] = None,
        trinity_variant: Optional[str] = None,
    ) -> SAESlotBackpressureDecision:
        """Computes current rate + state + action.

        Pre: record_admission() vorher mind. 1x aufgerufen ODER returnt NORMAL/ALLOW.
        Post:
          - Rolling rate = admission_count / window-duration (in minutes)
          - State berechnet aus rate / max_rate (Schwellen elevated/blocked)
          - State-Achse aktualisiert je nach Parameter:
              * agent_class given (trinity_variant None) -> per-class state
              * trinity_variant given (agent_class None) -> per-variant state
              * beide given -> per-variant state (Trinity ist primaere Achse)
              * keine -> global state
          - SAESlotBackpressureDecision in Audit-Trail abgelegt
        """
        with self._lock:
            now = time.time()

            # Wahl der Sample-Quelle (Prioritaet: variant > class > global)
            if trinity_variant is not None:
                if trinity_variant not in self._VALID_TRINITY_VARIANTS:
                    raise ValueError(
                        f"trinity_variant must be Conservative/Aggressive/Contrarian: "
                        f"{trinity_variant}"
                    )
                buf = self._samples_per_variant.get(trinity_variant)
                if buf is None:
                    buf = deque(maxlen=self._history_window)
                    self._samples_per_variant[trinity_variant] = buf
            elif agent_class is not None:
                if not agent_class:
                    raise ValueError("agent_class must be non-empty")
                buf = self._samples_per_class.get(agent_class)
                if buf is None:
                    buf = deque(maxlen=self._history_window)
                    self._samples_per_class[agent_class] = buf
            else:
                buf = self._samples_global

            # Rate berechnen: admissions / window-duration (in minutes)
            current_rate = self._compute_rate(buf, now)
            max_rate = self._max_admissions_per_minute

            # State bestimmen anhand pct-Schwellen
            pct = (current_rate / max_rate) * 100.0 if max_rate > 0 else 0.0
            new_state = self._classify_state(pct)

            # State-Update auf entsprechender Achse
            if trinity_variant is not None:
                prev_state = self._per_variant_state.get(
                    trinity_variant, SlotFlowState.NORMAL
                )
                self._per_variant_state[trinity_variant] = new_state
            elif agent_class is not None:
                prev_state = self._per_class_state.get(
                    agent_class, SlotFlowState.NORMAL
                )
                self._per_class_state[agent_class] = new_state
            else:
                prev_state = self._global_state
                self._global_state = new_state

            # Action ableiten (custom handler oder default)
            action = self._dispatch_action(new_state, current_rate, max_rate, now)

            axis_label = (
                f"variant={trinity_variant}"
                if trinity_variant is not None
                else (
                    f"class={agent_class}"
                    if agent_class is not None
                    else "global"
                )
            )
            reason = (
                f"rate={current_rate:.2f}/min ({pct:.1f}% of "
                f"max={max_rate:.2f}/min) [{axis_label}] "
                f"state={prev_state.value}->{new_state.value}"
            )

            decision = SAESlotBackpressureDecision(
                state=new_state,
                current_rate=current_rate,
                max_rate=max_rate,
                action=action,
                reason=reason,
                timestamp=now,
            )
            self._decisions.append(decision)
            return decision

    def register_action(
        self,
        state: SlotFlowState,
        action_fn: Callable[[float], AdmissionThrottleAction],
    ) -> None:
        """Registers custom action-handler for a given SlotFlowState.

        Pre:
          - state in SlotFlowState
          - action_fn callable, takes (current_rate) -> AdmissionThrottleAction
        Post: bei evaluate() wird action_fn(current_rate) aufgerufen statt Default.
        """
        if not isinstance(state, SlotFlowState):
            raise TypeError("state must be SlotFlowState")
        if not callable(action_fn):
            raise TypeError("action_fn must be callable")
        with self._lock:
            self._action_handlers[state] = action_fn

    def get_state(
        self,
        agent_class: Optional[str] = None,
        trinity_variant: Optional[str] = None,
    ) -> SlotFlowState:
        """Returns current SlotFlowState.

        Pre: -
        Post:
          - trinity_variant given -> per-variant state (NORMAL falls keine Samples)
          - agent_class given (trinity_variant None) -> per-class state
          - keine Args -> global state
        """
        with self._lock:
            if trinity_variant is not None:
                if trinity_variant not in self._VALID_TRINITY_VARIANTS:
                    raise ValueError(
                        f"trinity_variant must be Conservative/Aggressive/Contrarian: "
                        f"{trinity_variant}"
                    )
                return self._per_variant_state.get(
                    trinity_variant, SlotFlowState.NORMAL
                )
            if agent_class is not None:
                return self._per_class_state.get(
                    agent_class, SlotFlowState.NORMAL
                )
            return self._global_state

    def get_decisions(self) -> tuple[SAESlotBackpressureDecision, ...]:
        """Read-only Audit-Trail aller bisherigen Decisions (immutable Snapshot).

        Post: tuple in Insertion-Order, len = Anzahl evaluate()-Calls.
        """
        with self._lock:
            return tuple(self._decisions)

    def reset(self) -> None:
        """Loescht alle Samples + States + Decisions (kompletter Reset).

        Post:
          - Global + per-class + per-variant buffers leer
          - States auf NORMAL
          - Decision-Trail leer
        """
        with self._lock:
            self._samples_global.clear()
            self._samples_per_class.clear()
            self._samples_per_variant.clear()
            self._global_state = SlotFlowState.NORMAL
            self._per_class_state.clear()
            self._per_variant_state.clear()
            self._decisions.clear()

    # ---------- Internals ----------

    def _compute_rate(
        self,
        buf: deque[SlotAdmissionSample],
        now: float,
    ) -> float:
        """Computes admissions/minute als rolling-window-rate.

        Pre: buf ist deque[SlotAdmissionSample], now > 0.
        Post:
          - empty buf -> 0.0
          - sonst sum(admission_count) / window_duration_minutes
          - window_duration = max(1.0, (now - oldest_sample_ts) / 60) in minutes
            (min 1 minute damit Rate stabil)
        """
        if not buf:
            return 0.0

        # Snapshot to avoid mutation during iteration
        snapshot = list(buf)
        oldest_ts = snapshot[0].timestamp
        duration_s = max(60.0, now - oldest_ts)
        duration_min = duration_s / 60.0

        total_admissions = sum(s.admission_count for s in snapshot)
        return total_admissions / duration_min

    def _classify_state(self, pct: float) -> SlotFlowState:
        """Maps Pct-of-Cap -> SlotFlowState (Schmitt-Trigger ohne Hysterese).

        Pre: pct >= 0.
        Post:
          - pct < elevated_pct       -> NORMAL
          - pct < mid_band           -> ELEVATED
          - pct < blocked_pct        -> THROTTLED
          - pct >= blocked_pct       -> BLOCKED

        Schwellen-Mapping:
          [0, elevated)             = NORMAL
          [elevated, mid_band)      = ELEVATED
          [mid_band, blocked)       = THROTTLED
          [blocked, ...)            = BLOCKED
        wo mid_band = (elevated + blocked) / 2
        """
        if pct >= self._blocked_pct:
            return SlotFlowState.BLOCKED
        mid_band = (self._elevated_pct + self._blocked_pct) / 2.0
        if pct >= mid_band:
            return SlotFlowState.THROTTLED
        if pct >= self._elevated_pct:
            return SlotFlowState.ELEVATED
        return SlotFlowState.NORMAL

    def _dispatch_action(
        self,
        state: SlotFlowState,
        current_rate: float,
        max_rate: float,
        now: float,
    ) -> AdmissionThrottleAction:
        """Dispatches AdmissionThrottleAction (custom handler oder Default).

        Pre: state in SlotFlowState, current_rate >= 0, max_rate > 0, now > 0.
        Post: returnt AdmissionThrottleAction (immutable).

        Default-Map:
          NORMAL    -> ALLOW (delay_ms=0)
          ELEVATED  -> ALLOW (delay_ms=0, reason warns)
          THROTTLED -> DELAY (delay_ms = 100 * (rate/max - 1) ... gerundet, min 1ms)
          BLOCKED   -> REJECT (delay_ms=0)
        """
        # Custom handler hat Vorrang
        handler = self._action_handlers.get(state)
        if handler is not None:
            return handler(current_rate)

        # Default-Map
        if state == SlotFlowState.NORMAL:
            return AdmissionThrottleAction(
                action_type="ALLOW",
                delay_ms=0.0,
                reason="slot-admission flow normal",
                timestamp=now,
            )
        if state == SlotFlowState.ELEVATED:
            return AdmissionThrottleAction(
                action_type="ALLOW",
                delay_ms=0.0,
                reason="slot-admission flow elevated (warn-only)",
                timestamp=now,
            )
        if state == SlotFlowState.THROTTLED:
            # Linear scaling: ueber max_rate -> staerker drosseln
            overage_factor = max(0.0, (current_rate / max_rate) - 1.0)
            delay = max(1.0, 100.0 * (1.0 + overage_factor))
            return AdmissionThrottleAction(
                action_type="DELAY",
                delay_ms=delay,
                reason=(
                    f"slot-admission throttled "
                    f"(overage_factor={overage_factor:.2f})"
                ),
                timestamp=now,
            )
        # BLOCKED
        return AdmissionThrottleAction(
            action_type="REJECT",
            delay_ms=0.0,
            reason="slot-admission blocked (cap exceeded, max 200 slots)",
            timestamp=now,
        )


# CRUX-MK
