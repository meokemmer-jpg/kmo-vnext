"""Tests for sigma_switch [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.1: Mode-State-Machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Test-runner path: kmo/ root must be on sys.path
_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.sigma_switch import (  # noqa: E402
    DEFAULT_POLICIES,
    HysteresisThresholds,
    ModePolicy,
    SigmaMode,
    SigmaSwitch,
)


# ---------- HysteresisThresholds ----------


def test_hysteresis_thresholds_validates_low_lt_high():
    HysteresisThresholds(low=0.5, high=0.8)  # ok
    with pytest.raises(ValueError):
        HysteresisThresholds(low=0.8, high=0.5)
    with pytest.raises(ValueError):
        HysteresisThresholds(low=0.5, high=0.5)  # equal not allowed


# ---------- DEFAULT_POLICIES ----------


def test_default_policies_cover_all_modes():
    assert set(DEFAULT_POLICIES.keys()) == set(SigmaMode)
    for mode, policy in DEFAULT_POLICIES.items():
        assert policy.mode == mode
        assert 0 <= policy.alert_level <= 3
        assert all(v > 0 for v in policy.resource_multipliers.values())


# ---------- SigmaSwitch: Initial-State + current_mode ----------


def test_sigma_switch_starts_in_normal():
    sw = SigmaSwitch()
    assert sw.current_mode() == SigmaMode.NORMAL
    assert sw.current_policy().mode == SigmaMode.NORMAL


def test_sigma_switch_initial_mode_override():
    sw = SigmaSwitch(initial_mode=SigmaMode.SLEEP)
    assert sw.current_mode() == SigmaMode.SLEEP


# ---------- update_load + Hysterese ----------


def test_update_load_below_high_no_switch():
    sw = SigmaSwitch()
    assert sw.update_load(0.5) is None  # below threshold
    assert sw.current_mode() == SigmaMode.NORMAL


def test_update_load_crosses_high_switches_to_peak():
    sw = SigmaSwitch()
    new_mode = sw.update_load(0.90)  # > 0.85
    assert new_mode == SigmaMode.PEAK_LOAD
    assert sw.current_mode() == SigmaMode.PEAK_LOAD


def test_hysteresis_anti_flapping():
    """Schmitt-Trigger: load 0.86 -> PEAK; load 0.60 stays PEAK; load 0.50 -> NORMAL."""
    sw = SigmaSwitch()
    sw.update_load(0.86)  # -> PEAK_LOAD
    assert sw.current_mode() == SigmaMode.PEAK_LOAD

    # load drops to 0.60 — still above LOW=0.55, must stay PEAK_LOAD
    result = sw.update_load(0.60)
    assert result is None
    assert sw.current_mode() == SigmaMode.PEAK_LOAD

    # load drops to 0.50 — crosses LOW threshold, switches DOWN to NORMAL
    result = sw.update_load(0.50)
    assert result == SigmaMode.NORMAL
    assert sw.current_mode() == SigmaMode.NORMAL


# ---------- signal_incident / recovery / maintenance / sleep ----------


def test_signal_incident_switches_mode():
    sw = SigmaSwitch()
    sw.signal_incident("cell-cascade-failure")
    assert sw.current_mode() == SigmaMode.INCIDENT
    assert sw.current_policy().alert_level == 3


def test_recovery_only_from_incident():
    sw = SigmaSwitch()
    # NORMAL -> recovery_start: should NOT switch (precondition violation)
    assert sw.signal_recovery_start() is None
    assert sw.current_mode() == SigmaMode.NORMAL

    sw.signal_incident("test")
    assert sw.signal_recovery_start() == SigmaMode.RECOVERY
    assert sw.current_mode() == SigmaMode.RECOVERY


def test_maintenance_blocked_during_incident():
    sw = SigmaSwitch()
    sw.signal_incident("test")
    assert sw.signal_maintenance_start() is None  # blocked
    assert sw.current_mode() == SigmaMode.INCIDENT


def test_sleep_blocked_during_incident_and_recovery():
    sw = SigmaSwitch()
    sw.signal_incident("test")
    assert sw.signal_sleep_start() is None
    sw.signal_recovery_start()
    assert sw.signal_sleep_start() is None
    sw.signal_recovery_complete()
    assert sw.signal_sleep_start() == SigmaMode.SLEEP


# ---------- is_df_active ----------


def test_is_df_active_normal_allows_all():
    sw = SigmaSwitch()
    # NORMAL has empty active_dfs tuple => all DFs allowed
    assert sw.is_df_active("df-anything") is True
    assert sw.is_df_active("df-pilot-hotel-EU") is True


def test_is_df_active_peak_load_whitelist():
    sw = SigmaSwitch()
    sw.update_load(0.90)  # -> PEAK_LOAD
    assert sw.is_df_active("df-pilot-hotel-EU") is True
    assert sw.is_df_active("df-revenue-mgmt") is True
    # df-knowledge-janitor is NOT in PEAK_LOAD whitelist
    assert sw.is_df_active("df-knowledge-janitor") is False


def test_is_df_active_sleep_only_essential():
    sw = SigmaSwitch()
    sw.signal_sleep_start()
    assert sw.is_df_active("df-glymphatic-cleanup") is True
    assert sw.is_df_active("df-pilot-hotel-EU") is False  # disabled in SLEEP


# ---------- audit_trail ----------


def test_audit_trail_records_all_transitions():
    sw = SigmaSwitch()
    sw.update_load(0.90)             # NORMAL -> PEAK_LOAD
    sw.update_load(0.50)             # PEAK_LOAD -> NORMAL
    sw.signal_incident("test")       # NORMAL -> INCIDENT
    sw.signal_recovery_start()       # INCIDENT -> RECOVERY
    sw.signal_recovery_complete()    # RECOVERY -> NORMAL

    audit = sw.audit_trail()
    assert len(audit) == 5
    assert audit[0].from_mode == SigmaMode.NORMAL and audit[0].to_mode == SigmaMode.PEAK_LOAD
    assert audit[1].from_mode == SigmaMode.PEAK_LOAD and audit[1].to_mode == SigmaMode.NORMAL
    assert audit[2].to_mode == SigmaMode.INCIDENT
    assert audit[3].to_mode == SigmaMode.RECOVERY
    assert audit[4].to_mode == SigmaMode.NORMAL


def test_audit_trail_metric_value_recorded_on_load_transitions():
    sw = SigmaSwitch()
    sw.update_load(0.92)
    audit = sw.audit_trail()
    assert audit[0].metric_value == 0.92


# ---------- force_mode ----------


def test_force_mode_bypasses_hysteresis():
    sw = SigmaSwitch()
    changed = sw.force_mode(SigmaMode.MAINTENANCE, trigger="manual-test")
    assert changed is True
    assert sw.current_mode() == SigmaMode.MAINTENANCE


def test_force_mode_same_mode_returns_false():
    sw = SigmaSwitch()
    assert sw.force_mode(SigmaMode.NORMAL) is False  # already NORMAL


# ---------- Backwards-Compat: clock injection ----------


def test_custom_clock_used_in_audit():
    fake_now = {"t": 100.0}
    sw = SigmaSwitch(clock=lambda: fake_now["t"])
    sw.update_load(0.90)
    fake_now["t"] = 200.0
    sw.update_load(0.50)
    audit = sw.audit_trail()
    assert audit[0].timestamp == 100.0
    assert audit[1].timestamp == 200.0
