# [CRUX-MK]
"""Tests fuer KPM-Pre-Production-Canary (Welle-45 Phase-38)."""
from __future__ import annotations

import pytest

from kmo_governance.kpm_pre_production_canary import (
    CanaryDeployment,
    CanaryStatus,
    KPMPreProductionCanary,
)


def test_init_validation() -> None:
    KPMPreProductionCanary()
    with pytest.raises(ValueError):
        KPMPreProductionCanary(rollback_threshold_pct=200)
    with pytest.raises(ValueError):
        KPMPreProductionCanary(promote_min_runs=0)


def test_deploy_canary_basic() -> None:
    c = KPMPreProductionCanary()
    d = c.deploy_canary("kelly-0.4", "kelly-0.3")
    assert d.status == CanaryStatus.ACTIVE
    assert d.capital_pct == 0.01


def test_deploy_canary_invalid_capital() -> None:
    c = KPMPreProductionCanary()
    with pytest.raises(ValueError):
        c.deploy_canary("kelly", "kelly-base", capital_pct=0.0)
    with pytest.raises(ValueError):
        c.deploy_canary("kelly", "kelly-base", capital_pct=1.5)


def test_record_performance_no_drift_keeps_active() -> None:
    c = KPMPreProductionCanary(rollback_threshold_pct=10, promote_min_runs=5)
    d = c.deploy_canary("k", "kbase")
    updated = c.record_performance(d.deployment_id, canary_pnl_pct=1.0, baseline_pnl_pct=1.0)
    assert updated.status == CanaryStatus.ACTIVE


def test_auto_rollback_on_high_drift() -> None:
    """Canary 5% worse than baseline -> rollback (rollback_threshold=3)."""
    c = KPMPreProductionCanary(rollback_threshold_pct=3.0)
    d = c.deploy_canary("k", "kbase")
    updated = c.record_performance(d.deployment_id, canary_pnl_pct=-2.0, baseline_pnl_pct=3.0)
    # drift = 3 - (-2) = 5%, >= 3% threshold -> rollback
    assert updated.status == CanaryStatus.ROLLED_BACK
    assert "avg_drift" in (updated.decision_reason or "")


def test_auto_promote_after_min_runs() -> None:
    """Canary consistently better -> promote after promote_min_runs."""
    c = KPMPreProductionCanary(promote_min_runs=3, promote_threshold_pct=1.0)
    d = c.deploy_canary("k", "kbase")
    for _ in range(3):
        c.record_performance(d.deployment_id, canary_pnl_pct=3.0, baseline_pnl_pct=1.0)
    # canary 2% better consistently -> promote
    final = c.get_deployment(d.deployment_id)
    assert final.status == CanaryStatus.PROMOTED


def test_record_unknown_deployment_raises() -> None:
    c = KPMPreProductionCanary()
    with pytest.raises(ValueError):
        c.record_performance("nonexistent", 1.0, 1.0)


def test_already_rolled_back_no_op() -> None:
    """Recording on rolled-back deployment is no-op."""
    c = KPMPreProductionCanary(rollback_threshold_pct=1.0)
    d = c.deploy_canary("k", "kbase")
    c.record_performance(d.deployment_id, canary_pnl_pct=-5.0, baseline_pnl_pct=5.0)
    state_before = c.get_deployment(d.deployment_id)
    assert state_before.status == CanaryStatus.ROLLED_BACK
    after = c.record_performance(d.deployment_id, canary_pnl_pct=10.0, baseline_pnl_pct=0.0)
    assert after.status == CanaryStatus.ROLLED_BACK  # no flip


def test_list_active() -> None:
    c = KPMPreProductionCanary()
    d1 = c.deploy_canary("k1", "base")
    d2 = c.deploy_canary("k2", "base")
    active = c.list_active()
    assert len(active) == 2


def test_deployment_frozen() -> None:
    c = KPMPreProductionCanary()
    d = c.deploy_canary("k", "kbase")
    with pytest.raises(Exception):
        d.status = CanaryStatus.PROMOTED  # type: ignore[misc]


def test_get_deployment_unknown_returns_none() -> None:
    c = KPMPreProductionCanary()
    assert c.get_deployment("never-existed") is None


def test_w48p5_unique_deployment_ids_same_ms() -> None:
    """W48-P5 (V20-Race-Risk): UUID-Suffix verhindert Kollision bei gleicher Zeit."""
    c = KPMPreProductionCanary()
    d1 = c.deploy_canary("k", "kbase")
    d2 = c.deploy_canary("k", "kbase")
    assert d1.deployment_id != d2.deployment_id


# CRUX-MK
