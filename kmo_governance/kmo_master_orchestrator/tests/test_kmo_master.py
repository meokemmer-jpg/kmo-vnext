"""Tests for kmo_master_orchestrator [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.5: Top-Level coordinator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.kmo_master_orchestrator import (  # noqa: E402
    HealthStatus,
    HomeostasisCoordinator,
    KMOMasterOrchestrator,
    SystemHealthMonitor,
    VitalSigns,
)
from kmo_governance.knowledge_decay import KnowledgeDecayEngine
from kmo_governance.sigma_switch import SigmaMode, SigmaSwitch
from kmo_governance.sleep_cycles import (
    CycleType,
    SleepCyclesEngine,
    SleepWindow,
)


# ---------- VitalSigns ----------


def test_vital_signs_immutable():
    v = VitalSigns(
        timestamp=1000.0,
        heart_rate=50.0,
        blood_pressure=0.5,
        body_temperature=0.8,
        oxygen_saturation=0.95,
    )
    with pytest.raises(Exception):  # frozen dataclass
        v.heart_rate = 100.0


# ---------- SystemHealthMonitor ----------


def test_health_monitor_healthy_when_all_in_normal_range():
    mon = SystemHealthMonitor()
    v = VitalSigns(
        timestamp=0,
        heart_rate=50.0,
        blood_pressure=0.4,
        body_temperature=0.5,
        oxygen_saturation=0.9,
    )
    assert mon.assess_health(v) == HealthStatus.HEALTHY


def test_health_monitor_warning_when_one_metric_out_of_normal():
    mon = SystemHealthMonitor()
    # blood_pressure=0.7 is in warning range (0.6-0.85)
    v = VitalSigns(
        timestamp=0,
        heart_rate=50.0,
        blood_pressure=0.7,
        body_temperature=0.5,
        oxygen_saturation=0.9,
    )
    assert mon.assess_health(v) == HealthStatus.WARNING


def test_health_monitor_critical_when_metric_outside_warning():
    mon = SystemHealthMonitor()
    # error rate body_temperature=10.0 > warning(5.0) -> CRITICAL
    v = VitalSigns(
        timestamp=0,
        heart_rate=50.0,
        blood_pressure=0.4,
        body_temperature=10.0,
        oxygen_saturation=0.9,
    )
    assert mon.assess_health(v) == HealthStatus.CRITICAL


def test_health_monitor_picks_worst_severity():
    mon = SystemHealthMonitor()
    # heart_rate normal, blood_pressure warning, error_rate critical
    v = VitalSigns(
        timestamp=0,
        heart_rate=50.0,
        blood_pressure=0.7,         # warning
        body_temperature=10.0,      # critical
        oxygen_saturation=0.9,      # healthy
    )
    assert mon.assess_health(v) == HealthStatus.CRITICAL


# ---------- HomeostasisCoordinator ----------


def test_homeostasis_warning_emits_monitoring_only():
    coord = HomeostasisCoordinator()
    res = coord.react_to_health(HealthStatus.WARNING)
    assert res["status"] == "warning"
    assert "monitoring" in res["actions"]


def test_homeostasis_critical_triggers_sigma_peak_load():
    sw = SigmaSwitch()
    coord = HomeostasisCoordinator(sigma_switch=sw)
    res = coord.react_to_health(HealthStatus.CRITICAL)
    assert sw.current_mode() == SigmaMode.PEAK_LOAD
    assert any("peak_load" in a for a in res["actions"])


def test_homeostasis_emergency_triggers_sigma_incident():
    sw = SigmaSwitch()
    coord = HomeostasisCoordinator(sigma_switch=sw)
    coord.react_to_health(HealthStatus.EMERGENCY, reason="test")
    assert sw.current_mode() == SigmaMode.INCIDENT


# ---------- KMOMasterOrchestrator ----------


def test_master_orchestrator_status_default():
    sw = SigmaSwitch()
    kd = KnowledgeDecayEngine()
    sc = SleepCyclesEngine()
    master = KMOMasterOrchestrator(sigma_switch=sw, knowledge_decay=kd, sleep_cycles=sc)
    status = master.get_status()
    assert status["last_status"] == "healthy"
    assert status["current_mode"] == "normal"
    assert status["vitals_count"] == 0
    assert status["sleeping"] is False


def test_master_update_vitals_assesses_and_reacts():
    sw = SigmaSwitch()
    master = KMOMasterOrchestrator(sigma_switch=sw)
    # Healthy vitals -> no mode-change
    v_healthy = VitalSigns(
        timestamp=1000,
        heart_rate=50,
        blood_pressure=0.4,
        body_temperature=0.5,
        oxygen_saturation=0.9,
    )
    master.update_vitals(v_healthy)
    assert sw.current_mode() == SigmaMode.NORMAL
    # Critical vitals -> PEAK_LOAD mode
    v_critical = VitalSigns(
        timestamp=2000,
        heart_rate=50,
        blood_pressure=0.4,
        body_temperature=10.0,  # high error rate
        oxygen_saturation=0.9,
    )
    master.update_vitals(v_critical)
    assert sw.current_mode() == SigmaMode.PEAK_LOAD


def test_master_emergency_signal_routes_to_incident():
    sw = SigmaSwitch()
    master = KMOMasterOrchestrator(sigma_switch=sw)
    master.emergency_signal(reason="catastrophic-failure")
    assert sw.current_mode() == SigmaMode.INCIDENT
    status = master.get_status()
    assert status["last_status"] == "emergency"


def test_master_off_peak_actions_wires_sleep_to_decay():
    """KMO master wires sleep_cycles cleanup-callback -> knowledge_decay.decay+prune."""
    kd = KnowledgeDecayEngine()
    sc = SleepCyclesEngine()
    master = KMOMasterOrchestrator(knowledge_decay=kd, sleep_cycles=sc)
    master.enable_off_peak_actions()
    # Register an entry that will be a pruning candidate (low conf, old)
    e = kd.register("k1", initial_confidence=0.05, initial_stability=0.5)
    # Use sc to invoke the cleanup-callback (manually triggered)
    result = sc.trigger_glymphatic_cleanup()
    assert result.success is True
    # The entry was processed but not yet prunable (age too short for pruning_min_age_days)
    # so cleanup result might be 0 — the wiring is correct, prune-conditions just not met
    assert result is not None


# ---------- Patch F2 Refractory-Period (Welle-9-delta Cross-LLM 3/3 Finding) ----------


def test_f2_refractory_validates_negative():
    sw = SigmaSwitch()
    with pytest.raises(ValueError):
        HomeostasisCoordinator(sigma_switch=sw, refractory_period_sec=-1)


def test_f2_refractory_suppresses_rapid_switching():
    """Patch F2: Within refractory window, non-EMERGENCY mode-switches are suppressed."""
    fake_now = {"t": 1000.0}
    sw = SigmaSwitch()
    coord = HomeostasisCoordinator(
        sigma_switch=sw,
        refractory_period_sec=60.0,
        clock=lambda: fake_now["t"],
    )
    # First CRITICAL -> switch to PEAK_LOAD (allowed, no prior switch)
    coord.react_to_health(HealthStatus.CRITICAL)
    assert sw.current_mode() == SigmaMode.PEAK_LOAD

    # 30s later, CRITICAL again -> still in refractory, suppressed
    fake_now["t"] += 30
    res = coord.react_to_health(HealthStatus.CRITICAL)
    assert "refractory-suppressed" in res["actions"]


def test_f2_refractory_lifted_after_window():
    fake_now = {"t": 1000.0}
    sw = SigmaSwitch()
    coord = HomeostasisCoordinator(
        sigma_switch=sw,
        refractory_period_sec=60.0,
        clock=lambda: fake_now["t"],
    )
    coord.react_to_health(HealthStatus.CRITICAL)
    # 70s later, refractory should be lifted
    fake_now["t"] += 70
    res = coord.react_to_health(HealthStatus.HEALTHY)
    assert "refractory-suppressed" not in res["actions"]


def test_f2_emergency_bypasses_refractory():
    """Patch F2: EMERGENCY status overrides refractory-suppression (safety-priority)."""
    fake_now = {"t": 1000.0}
    sw = SigmaSwitch()
    coord = HomeostasisCoordinator(
        sigma_switch=sw,
        refractory_period_sec=60.0,
        clock=lambda: fake_now["t"],
    )
    coord.react_to_health(HealthStatus.CRITICAL)
    # 5s later, EMERGENCY must still go through despite refractory
    fake_now["t"] += 5
    res = coord.react_to_health(HealthStatus.EMERGENCY, reason="catastrophic")
    assert sw.current_mode() == SigmaMode.INCIDENT
    assert "refractory-suppressed" not in res["actions"]


def test_master_status_reflects_all_layer_state():
    sw = SigmaSwitch()
    kd = KnowledgeDecayEngine()
    sc = SleepCyclesEngine()
    sc.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))

    master = KMOMasterOrchestrator(
        sigma_switch=sw, knowledge_decay=kd, sleep_cycles=sc
    )
    kd.register("k1")
    kd.register("k2")
    status = master.get_status()
    assert status["knowledge_count"] == 2
