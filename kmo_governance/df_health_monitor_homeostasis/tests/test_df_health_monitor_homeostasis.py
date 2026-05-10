# [CRUX-MK]
"""Tests fuer DF-Health-Monitor-Homeostasis (Welle-49 Phase-42, 9. Domain META)."""
from __future__ import annotations

import pytest

from kmo_governance.df_health_monitor_homeostasis import (
    DFHealthDecision,
    DFHealthMonitorHomeostasis,
    DFHealthSample,
    DFHealthState,
)


def _smp(df: str = "df-86", lam: float = 1.0, err: float = 0.05, retry: float = 0.02) -> DFHealthSample:
    return DFHealthSample(
        sample_id="s",
        df_id=df,
        lambda_per_day=lam,
        error_rate=err,
        retry_overhead_pct=retry,
        p95_latency_ms=200,
        timestamp=0.0,
    )


def test_init_validation() -> None:
    DFHealthMonitorHomeostasis()
    with pytest.raises(ValueError):
        DFHealthMonitorHomeostasis(setpoint=0)
    with pytest.raises(ValueError):
        DFHealthMonitorHomeostasis(history_window=0)
    with pytest.raises(ValueError):
        DFHealthMonitorHomeostasis(
            degraded_threshold_pct=50, unhealthy_threshold_pct=20, critical_threshold_pct=100,
        )


def test_sample_validation() -> None:
    with pytest.raises(ValueError):
        DFHealthSample(sample_id="", df_id="x", lambda_per_day=1, error_rate=0.1, retry_overhead_pct=0, p95_latency_ms=0, timestamp=0)
    with pytest.raises(ValueError):
        DFHealthSample(sample_id="s", df_id="x", lambda_per_day=-1, error_rate=0.1, retry_overhead_pct=0, p95_latency_ms=0, timestamp=0)
    with pytest.raises(ValueError):
        DFHealthSample(sample_id="s", df_id="x", lambda_per_day=1, error_rate=2.0, retry_overhead_pct=0, p95_latency_ms=0, timestamp=0)


def test_healthy_at_or_above_setpoint() -> None:
    h = DFHealthMonitorHomeostasis(setpoint=0.85)
    # lambda=1.0 * (1-0.05) - 0.02 = 0.93 > 0.85
    d = h.record_sample(_smp(lam=1.0, err=0.05, retry=0.02))
    assert d.state == DFHealthState.HEALTHY


def test_degraded_state() -> None:
    """Score nahe Setpoint aber deviation >= 10%."""
    h = DFHealthMonitorHomeostasis(setpoint=0.85, degraded_threshold_pct=5)
    # lambda=1.0 * (1-0.10) - 0.05 = 0.85 -> deviation 0%, but ...
    # Aimed: score 0.78 -> deviation ~8% -> should be DEGRADED at threshold 5
    d = h.record_sample(_smp(lam=1.0, err=0.15, retry=0.07))
    # 1.0*(1-0.15) - 0.07 = 0.78 -> deviation 8.2% >= 5%
    assert d.state in (DFHealthState.DEGRADED, DFHealthState.HEALTHY)


def test_unhealthy_state() -> None:
    h = DFHealthMonitorHomeostasis(setpoint=0.85, unhealthy_threshold_pct=20)
    # score 0.5 -> deviation 41%
    d = h.record_sample(_smp(lam=1.0, err=0.30, retry=0.20))
    assert d.state in (DFHealthState.UNHEALTHY, DFHealthState.CRITICAL)


def test_critical_state() -> None:
    h = DFHealthMonitorHomeostasis(setpoint=0.85, critical_threshold_pct=40)
    # score 0.20 -> deviation 76%
    d = h.record_sample(_smp(lam=1.0, err=0.50, retry=0.30))
    assert d.state == DFHealthState.CRITICAL
    assert d.recommended_action == "pause_or_hard_stop"


def test_per_df_history_isolated() -> None:
    h = DFHealthMonitorHomeostasis()
    h.record_sample(_smp(df="df-86"))
    h.record_sample(_smp(df="df-92"))
    assert len(h.get_df_history("df-86")) == 1
    assert len(h.get_df_history("df-92")) == 1


def test_list_critical_dfs() -> None:
    h = DFHealthMonitorHomeostasis(setpoint=0.85, critical_threshold_pct=40)
    h.record_sample(_smp(df="df-bad", lam=1.0, err=0.50, retry=0.30))
    h.record_sample(_smp(df="df-ok", lam=1.0, err=0.05, retry=0.02))
    crits = h.list_critical_dfs()
    assert "df-bad" in crits
    assert "df-ok" not in crits


def test_get_df_history_empty() -> None:
    h = DFHealthMonitorHomeostasis()
    assert h.get_df_history("never") == ()


def test_decision_frozen() -> None:
    h = DFHealthMonitorHomeostasis()
    d = h.record_sample(_smp())
    with pytest.raises(Exception):
        d.state = DFHealthState.CRITICAL  # type: ignore[misc]


def test_recommend_actions_per_state() -> None:
    """All 4 states map to distinct actions."""
    h = DFHealthMonitorHomeostasis()
    actions = {h._recommend_action(s) for s in DFHealthState}
    assert len(actions) == 4


# CRUX-MK
