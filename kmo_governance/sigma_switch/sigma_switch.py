"""KMO sigma_switch Engine [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.1: Mode-State-Machine fuer System-weite Konsequenzen.

Bio-Aequivalent: E.coli Sigma-Faktoren (sigma-70/32/S/E). Verschiedene Sigma-Faktoren
binden RNAP an verschiedene Promotor-Klassen. EIN globaler Sigma-Wechsel reprogrammiert
das gesamte Transkriptions-Profil — analog zu Mode-Switch der gesamten DF-Pipeline.

Anorg-Mapping: A-04 Schmitt-Trigger (Hysterese-Threshold gegen Mode-Flapping).

Komponenten:
  - SigmaMode (Enum): NORMAL, PEAK_LOAD, INCIDENT, RECOVERY, MAINTENANCE, SLEEP
  - ModePolicy: pro Mode aktive_dfs_list, resource_quotas, policy_overrides, alert_levels
  - SigmaSwitch: Schmitt-Trigger-Hysterese + Audit-Trail aller Mode-Wechsel

Hysterese-Math:
  Aufwaerts: switch nur bei load > THRESHOLD_HIGH (z.B. 0.85)
  Abwaerts: switch nur bei load < THRESHOLD_LOW (z.B. 0.55)
  Differenz HIGH - LOW = Hysterese-Bandbreite (Anti-Flapping)
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------- Sigma-Modes (Enum) ----------

class SigmaMode(str, enum.Enum):
    """Top-Level System-Modes, analog zu E.coli Sigma-Faktoren.

    NORMAL       — sigma-70 (housekeeping): regulaerer Pipeline-Betrieb
    PEAK_LOAD    — sigma-32 (heat-shock): hohe Last, aggressive Throttling
    INCIDENT     — sigma-E (envelope-stress): Failure-Mode, Damage-Control
    RECOVERY     — sigma-32 (post-shock): Wound-Healing aktiv, langsamer Wiederaufbau
    MAINTENANCE  — sigma-S (stationary): geplante Wartungs-Aktionen
    SLEEP        — sigma-S (stationary off-peak): nur essential DFs aktiv
    """

    NORMAL = "normal"
    PEAK_LOAD = "peak_load"
    INCIDENT = "incident"
    RECOVERY = "recovery"
    MAINTENANCE = "maintenance"
    SLEEP = "sleep"


# ---------- ModePolicy ----------

@dataclass(frozen=True)
class ModePolicy:
    """Per-mode resource policy.

    Pre: alert_level in {0,1,2,3}; resource_multipliers > 0
    Post: immutable; consumed by ResourceQuotaResolver and orchestrator-DFs
    """

    mode: SigmaMode
    active_dfs: tuple[str, ...]                  # whitelist of df-ids enabled in this mode
    resource_multipliers: dict[str, float]       # e.g. {"cpu": 1.0, "tokens": 0.5}
    policy_overrides: dict[str, Any]             # arbitrary mode-specific overrides
    alert_level: int                             # 0=quiet, 1=info, 2=warn, 3=critical


# Built-in default policies (can be overridden via load_yaml_config).
DEFAULT_POLICIES: dict[SigmaMode, ModePolicy] = {
    SigmaMode.NORMAL: ModePolicy(
        mode=SigmaMode.NORMAL,
        active_dfs=(),  # empty means "all DFs allowed"
        resource_multipliers={"cpu": 1.0, "memory": 1.0, "tokens": 1.0},
        policy_overrides={},
        alert_level=0,
    ),
    SigmaMode.PEAK_LOAD: ModePolicy(
        mode=SigmaMode.PEAK_LOAD,
        active_dfs=("df-pilot-hotel-EU", "df-revenue-mgmt", "df-ota-sync"),
        resource_multipliers={"cpu": 1.5, "memory": 1.2, "tokens": 0.8},
        policy_overrides={"throttle_low_priority": True, "skip_optional_audits": True},
        alert_level=1,
    ),
    SigmaMode.INCIDENT: ModePolicy(
        mode=SigmaMode.INCIDENT,
        active_dfs=("df-pilot-hotel-EU", "df-incident-response"),
        resource_multipliers={"cpu": 1.0, "memory": 1.0, "tokens": 0.3},
        policy_overrides={"freeze_writes": True, "alert_martin": True},
        alert_level=3,
    ),
    SigmaMode.RECOVERY: ModePolicy(
        mode=SigmaMode.RECOVERY,
        active_dfs=("df-pilot-hotel-EU", "df-wound-healing", "df-incident-response"),
        resource_multipliers={"cpu": 0.7, "memory": 0.8, "tokens": 0.5},
        policy_overrides={"slow_ramp_up": True},
        alert_level=2,
    ),
    SigmaMode.MAINTENANCE: ModePolicy(
        mode=SigmaMode.MAINTENANCE,
        active_dfs=("df-knowledge-janitor", "df-gc"),
        resource_multipliers={"cpu": 0.5, "memory": 1.0, "tokens": 0.3},
        policy_overrides={"allow_destructive_gc": True},
        alert_level=1,
    ),
    SigmaMode.SLEEP: ModePolicy(
        mode=SigmaMode.SLEEP,
        active_dfs=("df-glymphatic-cleanup", "df-memory-consolidation"),
        resource_multipliers={"cpu": 0.2, "memory": 0.5, "tokens": 0.1},
        policy_overrides={"system_idle": True},
        alert_level=0,
    ),
}


# ---------- ModeTransitionEvent (Audit) ----------

@dataclass(frozen=True)
class ModeTransitionEvent:
    """Append-only audit-trail entry for mode-switches."""

    timestamp: float
    from_mode: SigmaMode
    to_mode: SigmaMode
    trigger: str                # e.g. "load>0.85", "manual", "incident:cell-failure"
    metric_value: Optional[float] = None  # observed metric that triggered the switch


# ---------- Hysterese-Thresholds ----------

@dataclass(frozen=True)
class HysteresisThresholds:
    """Schmitt-Trigger thresholds for one mode-transition pair.

    Pre: low < high
    Post: switch up at metric > high; switch down at metric < low.
    """

    low: float
    high: float

    def __post_init__(self):
        if self.low >= self.high:
            raise ValueError(f"low ({self.low}) must be < high ({self.high})")


# ---------- SigmaSwitch (Engine) ----------

class SigmaSwitch:
    """Mode-State-Machine with Schmitt-Trigger hysteresis.

    Pre: policies dict has entries for all SigmaMode values
    Post:
      - current_mode() returns the latest accepted mode
      - update(load_metric, signals) may transition mode if hysteresis-window crossed
      - audit_trail() returns immutable list of all ModeTransitionEvents

    Thread-safe via internal RLock.
    """

    def __init__(
        self,
        policies: Optional[dict[SigmaMode, ModePolicy]] = None,
        load_thresholds: Optional[HysteresisThresholds] = None,
        clock: Callable[[], float] = time.time,
        initial_mode: SigmaMode = SigmaMode.NORMAL,
    ) -> None:
        self._policies = dict(policies) if policies is not None else dict(DEFAULT_POLICIES)
        # Default Schmitt-Trigger: switch UP to PEAK_LOAD at load>0.85,
        # switch DOWN to NORMAL at load<0.55 (Anti-Flapping-Band 0.30 wide).
        self._load_thresholds = load_thresholds or HysteresisThresholds(low=0.55, high=0.85)
        self._clock = clock
        self._current: SigmaMode = initial_mode
        self._lock = threading.RLock()
        self._audit: list[ModeTransitionEvent] = []

    def current_mode(self) -> SigmaMode:
        with self._lock:
            return self._current

    def current_policy(self) -> ModePolicy:
        with self._lock:
            return self._policies[self._current]

    def is_df_active(self, df_id: str) -> bool:
        """Check whether a DF is allowed to run in the current mode.

        Empty active_dfs tuple means "all DFs allowed" (e.g. NORMAL mode).
        """
        with self._lock:
            policy = self._policies[self._current]
            if not policy.active_dfs:
                return True
            return df_id in policy.active_dfs

    def force_mode(self, mode: SigmaMode, trigger: str = "manual") -> bool:
        """Manual mode-switch (bypasses hysteresis). Returns True if changed."""
        with self._lock:
            if mode == self._current:
                return False
            old = self._current
            self._current = mode
            self._audit.append(
                ModeTransitionEvent(
                    timestamp=self._clock(),
                    from_mode=old,
                    to_mode=mode,
                    trigger=trigger,
                    metric_value=None,
                )
            )
            return True

    def update_load(self, load: float) -> Optional[SigmaMode]:
        """Update mode based on load-metric with Schmitt-Trigger hysteresis.

        Returns new mode if switched, None if no change.
        Only NORMAL <-> PEAK_LOAD transitions are load-driven; other modes
        require explicit triggers (incident_signal, maintenance_signal etc.).
        """
        with self._lock:
            if self._current == SigmaMode.NORMAL and load > self._load_thresholds.high:
                self._switch(SigmaMode.PEAK_LOAD, f"load>{self._load_thresholds.high}", load)
                return SigmaMode.PEAK_LOAD
            if self._current == SigmaMode.PEAK_LOAD and load < self._load_thresholds.low:
                self._switch(SigmaMode.NORMAL, f"load<{self._load_thresholds.low}", load)
                return SigmaMode.NORMAL
            return None

    def signal_incident(self, reason: str) -> Optional[SigmaMode]:
        """Trigger INCIDENT-mode (e.g. cell-cascade-failure)."""
        with self._lock:
            if self._current == SigmaMode.INCIDENT:
                return None
            self._switch(SigmaMode.INCIDENT, f"incident:{reason}", None)
            return SigmaMode.INCIDENT

    def signal_recovery_start(self) -> Optional[SigmaMode]:
        """Begin recovery from INCIDENT (wound-healing-orchestration)."""
        with self._lock:
            if self._current != SigmaMode.INCIDENT:
                return None
            self._switch(SigmaMode.RECOVERY, "recovery-start", None)
            return SigmaMode.RECOVERY

    def signal_recovery_complete(self) -> Optional[SigmaMode]:
        """Recovery done — back to NORMAL."""
        with self._lock:
            if self._current != SigmaMode.RECOVERY:
                return None
            self._switch(SigmaMode.NORMAL, "recovery-complete", None)
            return SigmaMode.NORMAL

    def signal_maintenance_start(self) -> Optional[SigmaMode]:
        """Scheduled maintenance window starts (e.g. nightly GC)."""
        with self._lock:
            if self._current in (SigmaMode.INCIDENT, SigmaMode.RECOVERY):
                return None  # don't enter maintenance during incident
            self._switch(SigmaMode.MAINTENANCE, "maintenance-start", None)
            return SigmaMode.MAINTENANCE

    def signal_maintenance_complete(self) -> Optional[SigmaMode]:
        with self._lock:
            if self._current != SigmaMode.MAINTENANCE:
                return None
            self._switch(SigmaMode.NORMAL, "maintenance-complete", None)
            return SigmaMode.NORMAL

    def signal_sleep_start(self) -> Optional[SigmaMode]:
        """Enter SLEEP-mode (off-peak, system-idle). Cannot enter from INCIDENT/RECOVERY."""
        with self._lock:
            if self._current in (SigmaMode.INCIDENT, SigmaMode.RECOVERY):
                return None
            self._switch(SigmaMode.SLEEP, "sleep-start", None)
            return SigmaMode.SLEEP

    def signal_sleep_end(self) -> Optional[SigmaMode]:
        with self._lock:
            if self._current != SigmaMode.SLEEP:
                return None
            self._switch(SigmaMode.NORMAL, "sleep-end", None)
            return SigmaMode.NORMAL

    def audit_trail(self) -> list[ModeTransitionEvent]:
        """Immutable copy of mode-transition history."""
        with self._lock:
            return list(self._audit)

    def _switch(
        self, new_mode: SigmaMode, trigger: str, metric_value: Optional[float]
    ) -> None:
        """Internal mode-switch (must hold lock)."""
        old = self._current
        self._current = new_mode
        self._audit.append(
            ModeTransitionEvent(
                timestamp=self._clock(),
                from_mode=old,
                to_mode=new_mode,
                trigger=trigger,
                metric_value=metric_value,
            )
        )


# CRUX-MK
