"""KMO kmo_master_orchestrator [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.5: Top-Layer Koordinator ueber alle 4 Layers
(Cell + Tissue + Organ + Organism).

Bio-Aequivalent: Zentralnervensystem + endokrines System + Vital-Signs-Monitor.
Reaktion auf System-weite Krisen (Stress-Response), Multi-System-Koordination,
globale Homoeostase.

Anorg-Mapping: A-13 Top-Level-Hierarchie (Lyapunov-stabilisierender Outer-Loop).

Komponenten:
  - VitalSigns: heart_rate, blood_pressure, body_temperature, oxygen_saturation
  - SystemHealthMonitor: misst alle Layers + aggregiert Health-Score
  - HomeostasisCoordinator: triggert sigma_switch-Modes basierend auf Health
  - KMOMasterOrchestrator: Top-Level-API verbindet alle Welle-9-Module

Vital-Sign-Mapping (HeyLou-OTA-Domain):
  heart_rate          → request_rate per second
  blood_pressure      → backend_load (CPU/Memory %)
  body_temperature    → error_rate per 100 requests
  oxygen_saturation   → cache_hit_ratio (0-1)
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------- Health Status ----------

class HealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


# ---------- VitalSigns ----------

@dataclass(frozen=True)
class VitalSigns:
    """Snapshot of system vital signs at a point in time.

    All metrics are normalized for the target application (HeyLou-Hotel-OTA).
    """

    timestamp: float
    heart_rate: float                    # requests/sec
    blood_pressure: float                # backend-load 0-1.0 (1.0 = maxed)
    body_temperature: float              # error-rate per 100 requests
    oxygen_saturation: float             # cache-hit-ratio 0-1.0


# ---------- Healthy Ranges (Reference) ----------

@dataclass(frozen=True)
class HealthyRanges:
    """Pre-defined healthy + warning ranges for each vital sign."""

    heart_rate_normal: tuple[float, float] = (1.0, 100.0)         # 1-100 rps healthy
    heart_rate_warning: tuple[float, float] = (0.5, 200.0)        # 0.5-200 rps warning
    blood_pressure_normal: tuple[float, float] = (0.0, 0.6)       # CPU < 60%
    blood_pressure_warning: tuple[float, float] = (0.0, 0.85)     # CPU < 85%
    body_temperature_normal: tuple[float, float] = (0.0, 1.0)     # < 1% errors
    body_temperature_warning: tuple[float, float] = (0.0, 5.0)    # < 5% errors
    oxygen_saturation_normal: tuple[float, float] = (0.85, 1.0)   # > 85% cache-hit
    oxygen_saturation_warning: tuple[float, float] = (0.6, 1.0)   # > 60% cache-hit


# ---------- System Health Monitor ----------

class SystemHealthMonitor:
    """Aggregates vital-signs across all Welle-9 layers, computes Health-Score.

    Pre: ranges is HealthyRanges instance
    Post: assess_health(VitalSigns) returns HealthStatus
    """

    def __init__(self, ranges: Optional[HealthyRanges] = None) -> None:
        self.ranges = ranges or HealthyRanges()

    def assess_health(self, vitals: VitalSigns) -> HealthStatus:
        """Assess overall health from vital-signs. Worst single-metric wins."""
        worst = HealthStatus.HEALTHY
        # Heart rate
        worst = self._max_severity(worst, self._eval_metric(
            vitals.heart_rate,
            self.ranges.heart_rate_normal,
            self.ranges.heart_rate_warning,
        ))
        # Blood pressure
        worst = self._max_severity(worst, self._eval_metric(
            vitals.blood_pressure,
            self.ranges.blood_pressure_normal,
            self.ranges.blood_pressure_warning,
        ))
        # Body temp (errors)
        worst = self._max_severity(worst, self._eval_metric(
            vitals.body_temperature,
            self.ranges.body_temperature_normal,
            self.ranges.body_temperature_warning,
        ))
        # Oxygen saturation (cache-hit)
        worst = self._max_severity(worst, self._eval_metric(
            vitals.oxygen_saturation,
            self.ranges.oxygen_saturation_normal,
            self.ranges.oxygen_saturation_warning,
        ))
        return worst

    @staticmethod
    def _eval_metric(
        value: float,
        normal: tuple[float, float],
        warning: tuple[float, float],
    ) -> HealthStatus:
        if normal[0] <= value <= normal[1]:
            return HealthStatus.HEALTHY
        if warning[0] <= value <= warning[1]:
            return HealthStatus.WARNING
        # Outside warning range = critical (anything more extreme = emergency, here we go critical)
        # Emergency only via explicit signaling.
        return HealthStatus.CRITICAL

    @staticmethod
    def _max_severity(a: HealthStatus, b: HealthStatus) -> HealthStatus:
        order = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.WARNING: 1,
            HealthStatus.CRITICAL: 2,
            HealthStatus.EMERGENCY: 3,
        }
        return a if order[a] >= order[b] else b


# ---------- Homeostasis Coordinator ----------

class HomeostasisCoordinator:
    """Bridges Health-Status to action: triggers sigma_switch + sleep_cycles.

    Pre: sigma_switch + sleep_cycles_engine optional but typed for composition
    Post: react_to_health(status) calls appropriate signal_* on dependents

    Patch F2 (Welle-9-delta Cross-LLM 3/3-Finding "Refractory-Period"):
    Mode-Switches are gated by a refractory-period (default 60s) to prevent
    oscillations between NORMAL and PEAK_LOAD at the 0.85/0.55 hysteresis boundary
    when load-bursts occur in fast succession. Within the refractory window,
    same-direction switch-attempts are suppressed (logged in actions).
    """

    def __init__(
        self,
        sigma_switch: Optional[Any] = None,           # SigmaSwitch
        sleep_cycles: Optional[Any] = None,           # SleepCyclesEngine
        refractory_period_sec: float = 60.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if refractory_period_sec < 0:
            raise ValueError("refractory_period_sec must be >= 0")
        self.sigma_switch = sigma_switch
        self.sleep_cycles = sleep_cycles
        self.refractory_period_sec = float(refractory_period_sec)
        self._clock = clock
        self._last_switch_at: float = 0.0  # 0 = never; first switch always allowed

    def _refractory_active(self) -> bool:
        """Patch F2: True if last mode-switch was within refractory window.

        EMERGENCY-status bypasses the refractory check (safety-priority).
        """
        if self._last_switch_at == 0.0:
            return False
        return (self._clock() - self._last_switch_at) < self.refractory_period_sec

    def _record_switch(self) -> None:
        """Patch F2: stamp timestamp of last successful mode-switch."""
        self._last_switch_at = self._clock()

    def react_to_health(self, status: HealthStatus, reason: str = "vital-signs") -> dict:
        """Execute homeostasis-action based on status. Returns action-summary.

        Patch F2: refractory-period gates mode-switches except for EMERGENCY.
        """
        actions: dict[str, Any] = {"status": status.value, "actions": []}
        # Patch F2: refractory check (EMERGENCY bypasses)
        if status != HealthStatus.EMERGENCY and self._refractory_active():
            actions["actions"].append("refractory-suppressed")
            return actions
        if status == HealthStatus.HEALTHY:
            # Try to enter SLEEP mode if off-peak
            if self.sleep_cycles is not None and self.sleep_cycles.should_sleep_now():
                if self.sigma_switch is not None:
                    res = self.sigma_switch.signal_sleep_start()
                    if res is not None:
                        actions["actions"].append(f"sigma->{res.value}")
                        self._record_switch()
                    actions["sleep_window_active"] = True
        elif status == HealthStatus.WARNING:
            # Maybe reduce load via sigma_switch update_load
            actions["actions"].append("monitoring")
        elif status == HealthStatus.CRITICAL:
            # Switch to PEAK_LOAD via signal (force update)
            if self.sigma_switch is not None:
                # Treat as if load > 0.85 to enter PEAK_LOAD
                res = self.sigma_switch.update_load(0.95)
                if res is not None:
                    actions["actions"].append(f"sigma->{res.value}")
                    self._record_switch()
        elif status == HealthStatus.EMERGENCY:
            # Hard incident-signal (refractory bypass)
            if self.sigma_switch is not None:
                res = self.sigma_switch.signal_incident(reason)
                if res is not None:
                    actions["actions"].append(f"sigma->{res.value}")
                    self._record_switch()
        return actions


# ---------- Master Orchestrator ----------

class KMOMasterOrchestrator:
    """Top-Level coordinator over all 4 Welle-9 layers.

    Pre: at least one of {sigma_switch, knowledge_decay, sleep_cycles} provided
    Post:
      - update_vitals(VitalSigns) records + assesses + reacts
      - get_status() returns full snapshot
      - enable_off_peak_actions() wires sleep_cycles to knowledge_decay
    """

    def __init__(
        self,
        sigma_switch: Optional[Any] = None,
        knowledge_decay: Optional[Any] = None,
        sleep_cycles: Optional[Any] = None,
        ranges: Optional[HealthyRanges] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.sigma_switch = sigma_switch
        self.knowledge_decay = knowledge_decay
        self.sleep_cycles = sleep_cycles
        self._clock = clock
        self.health_monitor = SystemHealthMonitor(ranges=ranges)
        self.homeostasis = HomeostasisCoordinator(
            sigma_switch=sigma_switch,
            sleep_cycles=sleep_cycles,
        )
        self._lock = threading.RLock()
        self._vitals_history: list[VitalSigns] = []
        self._last_status: HealthStatus = HealthStatus.HEALTHY

    def update_vitals(self, vitals: VitalSigns) -> dict:
        """Record vitals, assess health, trigger homeostasis action."""
        with self._lock:
            self._vitals_history.append(vitals)
            status = self.health_monitor.assess_health(vitals)
            self._last_status = status
            return self.homeostasis.react_to_health(status)

    def emergency_signal(self, reason: str) -> dict:
        """Force EMERGENCY status (e.g. pilot-detected catastrophic failure)."""
        with self._lock:
            self._last_status = HealthStatus.EMERGENCY
            return self.homeostasis.react_to_health(HealthStatus.EMERGENCY, reason=reason)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "last_status": self._last_status.value,
                "current_mode": self.sigma_switch.current_mode().value if self.sigma_switch else None,
                "vitals_count": len(self._vitals_history),
                "knowledge_count": len(self.knowledge_decay) if self.knowledge_decay else 0,
                "sleeping": self.sleep_cycles.should_sleep_now() if self.sleep_cycles else False,
            }

    def enable_off_peak_actions(self) -> None:
        """Wire sleep_cycles cleanup-callbacks to knowledge_decay decay+prune.

        Pre: both sleep_cycles and knowledge_decay must be set
        Post: glymphatic_cleanup invokes knowledge_decay.decay() + .prune()
        """
        if self.sleep_cycles is None or self.knowledge_decay is None:
            return

        def cleanup_cb() -> int:
            self.knowledge_decay.decay()
            pruned = self.knowledge_decay.prune()
            return len(pruned)

        def consolidation_cb() -> int:
            return self.knowledge_decay.decay()

        self.sleep_cycles.register_cleanup_callback(cleanup_cb)
        self.sleep_cycles.register_consolidation_callback(consolidation_cb)


# CRUX-MK
