# [CRUX-MK]
"""KPM-Feature-Flag-Engine (Welle-29 Phase-22 Bio-Pattern-Lift).

Genexpressions-Regulation-Pattern auf Trading-Strategy-Activation:
Wie Gene durch Promoter/Repressor-Bindung graduell aktiviert werden
(DISABLED -> RAMP_UP -> ENABLED, mit Expression-Gradient als percentage_rollout),
schalten Feature-Flags Trading-Strategies graduell ein/aus.

Pattern-Quelle: kmo_governance.feature_flag_engine (Welle-9, Hotel-Domain).
KPM-Domain-Lift: FlagRule -> FlagDefinition (mit FlagState-Maschine),
                  FlagContext.user_id -> request_id (deterministic Bucket-Hash),
                  FlagEvalRecord -> FlagDecision (typisierter Output mit Reason),
                  + neue FlagAuditEvent fuer State-Change-Trail (Compliance-Pflicht).

Pre-Conditions: flag_id non-empty, strategy_id non-empty,
                percentage_pct in [0, 100], default_audit_retention_h > 0.
Post-Conditions: thread-safe (RLock), idempotent State-Wechsel,
                 deterministisch via md5(flag_id+request_id) modulo 100.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FlagState(str, Enum):
    """State-Machine fuer Feature-Flag-Lebenszyklus.

    DISABLED       : Strategy aus (Repressor-bound, keine Expression).
    RAMP_UP        : Graduelle Aktivierung via percentage_rollout (Partial-Promoter).
    ENABLED        : Voll aktiv (Full-Expression).
    EMERGENCY_OFF  : Sofort-Stop, blockiert weitere Aenderungen bis clear_emergency
                     (Apoptosis-Trigger, irreversibel ohne expliziten Override).
    """

    DISABLED = "disabled"
    RAMP_UP = "ramp_up"
    ENABLED = "enabled"
    EMERGENCY_OFF = "emergency_off"


@dataclass(frozen=True)
class FlagDefinition:
    """Immutable Flag-Definition (Registrations-Snapshot).

    Pre: flag_id non-empty, strategy_id non-empty,
         default_state ist FlagState, percentage_rollout in [0, 100],
         description ist string (kann leer sein), owner_session_id ist string.
    Post: hashable + immutable.
    """

    flag_id: str
    strategy_id: str
    default_state: FlagState
    description: str
    owner_session_id: str
    created_at: float
    percentage_rollout: float = 0.0  # nur in RAMP_UP relevant

    def __post_init__(self) -> None:
        if not self.flag_id:
            raise ValueError("flag_id required")
        if not self.strategy_id:
            raise ValueError("strategy_id required")
        if not isinstance(self.default_state, FlagState):
            raise TypeError("default_state must be FlagState")
        if not (0.0 <= self.percentage_rollout <= 100.0):
            raise ValueError("percentage_rollout must be in [0, 100]")


@dataclass(frozen=True)
class FlagDecision:
    """Immutable Evaluation-Output pro evaluate(flag_id, request_id).

    Pre: flag_id + strategy_id non-empty, state ist FlagState,
         percentage_rollout in [0, 100], enabled ist bool.
    Post: hashable + immutable; deterministisch fuer (flag_id, request_id).
    """

    flag_id: str
    strategy_id: str
    state: FlagState
    percentage_rollout: float
    enabled: bool
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.flag_id:
            raise ValueError("flag_id required")
        if not self.strategy_id:
            raise ValueError("strategy_id required")
        if not isinstance(self.state, FlagState):
            raise TypeError("state must be FlagState")
        if not (0.0 <= self.percentage_rollout <= 100.0):
            raise ValueError("percentage_rollout must be in [0, 100]")


@dataclass(frozen=True)
class FlagAuditEvent:
    """Immutable Audit-Eintrag pro State-Wechsel oder Rollout-Anpassung.

    Pre: flag_id non-empty, old_state + new_state sind FlagState,
         changed_by non-empty, reason ist string (kann leer sein).
    Post: hashable + immutable; chronologisch in deque appended.
    """

    flag_id: str
    old_state: FlagState
    new_state: FlagState
    changed_by: str
    reason: str
    timestamp: float

    def __post_init__(self) -> None:
        if not self.flag_id:
            raise ValueError("flag_id required")
        if not isinstance(self.old_state, FlagState):
            raise TypeError("old_state must be FlagState")
        if not isinstance(self.new_state, FlagState):
            raise TypeError("new_state must be FlagState")
        if not self.changed_by:
            raise ValueError("changed_by required")


class KPMFeatureFlagEngine:
    """Feature-Flag-Engine fuer Trading-Strategy-Activation (KPM-Domain).

    Pre: default_audit_retention_h > 0.
    Post: thread-safe via RLock, deterministisch fuer evaluate(),
          state-machine-konform (EMERGENCY_OFF blockiert set_state).

    State-Machine:
        register_flag -> default_state (typisch DISABLED)
        set_state -> beliebiger FlagState (ausser wenn aktuell EMERGENCY_OFF
                     -> dann nur clear_emergency erlaubt)
        set_percentage_rollout -> nur erlaubt wenn state == RAMP_UP
        emergency_off -> setzt EMERGENCY_OFF (von jedem State aus)
        clear_emergency -> verlaesst EMERGENCY_OFF zurueck zu DISABLED

    Determinismus:
        evaluate(flag_id, request_id) -> FlagDecision
            DISABLED       -> enabled=False
            ENABLED        -> enabled=True
            EMERGENCY_OFF  -> enabled=False
            RAMP_UP        -> enabled = (md5(flag_id+request_id) % 100) < percentage_rollout
        Selber request_id liefert immer gleiches Ergebnis (Bucket-Stabilitaet).
    """

    DEFAULT_AUDIT_RETENTION_HOURS = 168.0  # MiFID-RTS-25-konform (7 Tage)
    DEFAULT_AUDIT_MAX_SIZE = 100_000  # Hardcap gegen unbegrenztes Wachstum

    def __init__(self, default_audit_retention_h: float = 168.0) -> None:
        if default_audit_retention_h <= 0:
            raise ValueError("default_audit_retention_h must be > 0")
        self.default_audit_retention_h = float(default_audit_retention_h)
        self._flags: dict = {}  # flag_id -> FlagDefinition
        self._states: dict = {}  # flag_id -> FlagState (current)
        self._rollouts: dict = {}  # flag_id -> percentage_rollout
        self._audit: deque = deque(maxlen=self.DEFAULT_AUDIT_MAX_SIZE)
        self._lock = threading.RLock()

    # -------------------------------------------------------------- register_flag
    def register_flag(
        self,
        flag_id: str,
        strategy_id: str,
        default_state: FlagState = FlagState.DISABLED,
        description: str = "",
        owner_session_id: str = "",
    ) -> FlagDefinition:
        """Registriert neues Flag.

        Pre: flag_id + strategy_id non-empty, default_state ist FlagState.
        Post: Flag im Registry, current_state = default_state, percentage_rollout = 0.0.
              Raises ValueError wenn flag_id schon registriert.
        """
        if not flag_id:
            raise ValueError("flag_id required")
        if not strategy_id:
            raise ValueError("strategy_id required")
        if not isinstance(default_state, FlagState):
            raise TypeError("default_state must be FlagState")

        with self._lock:
            if flag_id in self._flags:
                raise ValueError(f"flag_id {flag_id!r} already registered")
            definition = FlagDefinition(
                flag_id=flag_id,
                strategy_id=strategy_id,
                default_state=default_state,
                description=description,
                owner_session_id=owner_session_id,
                created_at=time.time(),
            )
            self._flags[flag_id] = definition
            self._states[flag_id] = default_state
            self._rollouts[flag_id] = 0.0
        return definition

    # -------------------------------------------------------------------- get_flag
    def get_flag(self, flag_id: str) -> FlagDefinition:
        """Gibt FlagDefinition fuer flag_id zurueck.

        Pre: flag_id registriert.
        Post: gibt unveraenderliche FlagDefinition.
              Raises KeyError wenn flag_id unbekannt.
        """
        if not flag_id:
            raise ValueError("flag_id required")
        with self._lock:
            if flag_id not in self._flags:
                raise KeyError(f"flag_id {flag_id!r} not registered")
            return self._flags[flag_id]

    # -------------------------------------------------------------------- set_state
    def set_state(
        self,
        flag_id: str,
        new_state: FlagState,
        changed_by: str,
        reason: str = "",
    ) -> FlagAuditEvent:
        """Aendert State eines Flags. Erzeugt FlagAuditEvent.

        Pre: flag_id registriert, new_state ist FlagState, changed_by non-empty.
        Post: state aktualisiert, audit-event appended.
              Raises RuntimeError wenn current_state == EMERGENCY_OFF und
              new_state != EMERGENCY_OFF (clear_emergency required).
        """
        if not flag_id:
            raise ValueError("flag_id required")
        if not isinstance(new_state, FlagState):
            raise TypeError("new_state must be FlagState")
        if not changed_by:
            raise ValueError("changed_by required")

        with self._lock:
            if flag_id not in self._flags:
                raise KeyError(f"flag_id {flag_id!r} not registered")
            old_state = self._states[flag_id]

            # EMERGENCY_OFF blockiert State-Aenderungen ausser:
            # - new_state == EMERGENCY_OFF (idempotent)
            # - clear_emergency() (separate API)
            if old_state == FlagState.EMERGENCY_OFF and new_state != FlagState.EMERGENCY_OFF:
                raise RuntimeError(
                    f"flag_id {flag_id!r} is EMERGENCY_OFF; "
                    "use clear_emergency() before set_state()"
                )

            self._states[flag_id] = new_state
            event = FlagAuditEvent(
                flag_id=flag_id,
                old_state=old_state,
                new_state=new_state,
                changed_by=changed_by,
                reason=reason,
                timestamp=time.time(),
            )
            self._audit.append(event)
            return event

    # ------------------------------------------------------- set_percentage_rollout
    def set_percentage_rollout(
        self,
        flag_id: str,
        percentage_pct: float,
        changed_by: str,
        reason: str = "",
    ) -> FlagAuditEvent:
        """Setzt percentage_rollout fuer flag_id. Nur in RAMP_UP-State erlaubt.

        Pre: flag_id registriert, current_state == RAMP_UP,
             percentage_pct in [0, 100], changed_by non-empty.
        Post: percentage_rollout aktualisiert, audit-event appended.
              Raises RuntimeError wenn current_state != RAMP_UP.
        """
        if not flag_id:
            raise ValueError("flag_id required")
        if not (0.0 <= percentage_pct <= 100.0):
            raise ValueError("percentage_pct must be in [0, 100]")
        if not changed_by:
            raise ValueError("changed_by required")

        with self._lock:
            if flag_id not in self._flags:
                raise KeyError(f"flag_id {flag_id!r} not registered")
            current_state = self._states[flag_id]
            if current_state != FlagState.RAMP_UP:
                raise RuntimeError(
                    f"flag_id {flag_id!r} is in {current_state.value!r}; "
                    "set_percentage_rollout requires RAMP_UP"
                )

            self._rollouts[flag_id] = float(percentage_pct)
            event = FlagAuditEvent(
                flag_id=flag_id,
                old_state=current_state,
                new_state=current_state,  # state unchanged, only rollout shifts
                changed_by=changed_by,
                reason=f"percentage_rollout={percentage_pct:.2f} | {reason}",
                timestamp=time.time(),
            )
            self._audit.append(event)
            return event

    # -------------------------------------------------------------------- evaluate
    def evaluate(self, flag_id: str, request_id: str) -> FlagDecision:
        """Deterministische Evaluation. Returns FlagDecision (immutable).

        Pre: flag_id registriert, request_id non-empty.
        Post: gleiche (flag_id, request_id) liefert immer gleiches enabled-Resultat.
              md5(flag_id+request_id) % 100 < percentage_rollout -> enabled=True (RAMP_UP).
        """
        if not flag_id:
            raise ValueError("flag_id required")
        if not request_id:
            raise ValueError("request_id required")

        with self._lock:
            if flag_id not in self._flags:
                raise KeyError(f"flag_id {flag_id!r} not registered")
            definition = self._flags[flag_id]
            current_state = self._states[flag_id]
            current_rollout = self._rollouts[flag_id]

        # Deterministic Bucket via md5(flag_id+request_id) % 100
        if current_state == FlagState.DISABLED:
            enabled = False
            reason = "state=DISABLED"
        elif current_state == FlagState.ENABLED:
            enabled = True
            reason = "state=ENABLED"
        elif current_state == FlagState.EMERGENCY_OFF:
            enabled = False
            reason = "state=EMERGENCY_OFF"
        elif current_state == FlagState.RAMP_UP:
            key = f"{flag_id}:{request_id}".encode("utf-8")
            digest = hashlib.md5(key).hexdigest()
            bucket = int(digest[:8], 16) % 100  # 0-99
            enabled = bucket < current_rollout
            reason = f"state=RAMP_UP bucket={bucket} rollout={current_rollout:.2f}"
        else:
            # Defensive: unbekannter State
            enabled = False
            reason = f"state=UNKNOWN({current_state!r})"

        return FlagDecision(
            flag_id=flag_id,
            strategy_id=definition.strategy_id,
            state=current_state,
            percentage_rollout=current_rollout,
            enabled=enabled,
            reason=reason,
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------ emergency_off
    def emergency_off(
        self,
        flag_id: str,
        changed_by: str,
        reason: str,
    ) -> FlagAuditEvent:
        """Sofort-Stop fuer Flag. Setzt EMERGENCY_OFF von jedem State aus.

        Pre: flag_id registriert, changed_by + reason non-empty.
        Post: state = EMERGENCY_OFF, audit-event appended.
              Reason ist Pflicht (Apoptosis-Trigger braucht Begruendung).
        """
        if not flag_id:
            raise ValueError("flag_id required")
        if not changed_by:
            raise ValueError("changed_by required")
        if not reason:
            raise ValueError("reason required for emergency_off")

        with self._lock:
            if flag_id not in self._flags:
                raise KeyError(f"flag_id {flag_id!r} not registered")
            old_state = self._states[flag_id]
            self._states[flag_id] = FlagState.EMERGENCY_OFF
            event = FlagAuditEvent(
                flag_id=flag_id,
                old_state=old_state,
                new_state=FlagState.EMERGENCY_OFF,
                changed_by=changed_by,
                reason=f"EMERGENCY_OFF | {reason}",
                timestamp=time.time(),
            )
            self._audit.append(event)
            return event

    # -------------------------------------------------------------- clear_emergency
    def clear_emergency(self, flag_id: str, changed_by: str) -> bool:
        """Verlaesst EMERGENCY_OFF zurueck zu DISABLED. Idempotent (False-Return).

        Pre: flag_id registriert, changed_by non-empty.
        Post: True wenn aus EMERGENCY_OFF nach DISABLED gewechselt,
              False wenn aktueller State != EMERGENCY_OFF (idempotent).
              Erzeugt FlagAuditEvent nur bei tatsaechlichem Wechsel.
        """
        if not flag_id:
            raise ValueError("flag_id required")
        if not changed_by:
            raise ValueError("changed_by required")

        with self._lock:
            if flag_id not in self._flags:
                raise KeyError(f"flag_id {flag_id!r} not registered")
            current_state = self._states[flag_id]
            if current_state != FlagState.EMERGENCY_OFF:
                return False
            self._states[flag_id] = FlagState.DISABLED
            event = FlagAuditEvent(
                flag_id=flag_id,
                old_state=FlagState.EMERGENCY_OFF,
                new_state=FlagState.DISABLED,
                changed_by=changed_by,
                reason="clear_emergency: back to DISABLED",
                timestamp=time.time(),
            )
            self._audit.append(event)
            return True

    # ------------------------------------------------------------------- get_audit_log
    def get_audit_log(self, flag_id: Optional[str] = None) -> tuple:
        """Snapshot des Audit-Logs.

        Pre: flag_id optional (None = alle Flags).
        Post: tuple[FlagAuditEvent] in chronologischer Reihenfolge.
              Wenn flag_id gesetzt, nur Events fuer dieses Flag.
        """
        with self._lock:
            if flag_id is None:
                return tuple(self._audit)
            return tuple(e for e in self._audit if e.flag_id == flag_id)

    # --------------------------------------------------------------------- list_flags
    def list_flags(self) -> tuple:
        """Sortierte Liste aller registrierten flag_ids."""
        with self._lock:
            return tuple(sorted(self._flags.keys()))


# CRUX-MK
