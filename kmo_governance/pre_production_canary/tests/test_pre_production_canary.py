"""Tests for pre_production_canary SKELETON [CRUX-MK]."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.pre_production_canary import (  # noqa: E402
    CanaryAuditLog,
    CanaryDeployment,
    CanaryHealthMonitor,
    ProgressiveRollout,
    RollbackReason,
    RollbackTrigger,
    RolloutStep,
)


# ---------- 1. CanaryDeployment ----------


def test_canary_deployment_register_and_route():
    """Register canary + baseline; route_request returns valid version_id."""
    dep = CanaryDeployment()
    dep.register_baseline("v1.0")
    dep.register_canary("v1.1", 10.0)

    # Distribution should be 10% canary + 90% baseline
    dist = dep.get_distribution()
    assert dist["v1.1"] == 10.0
    assert dist["v1.0"] == pytest.approx(90.0)

    # Routing should yield only known versions
    for i in range(50):
        v = dep.route_request(f"req-{i}")
        assert v in {"v1.0", "v1.1"}


def test_canary_deterministic_routing():
    """Same request_id always returns same version_id."""
    dep = CanaryDeployment()
    dep.register_baseline("v1.0")
    dep.register_canary("v1.1", 25.0)

    # Repeat the same request_ids, must get same answers each round
    request_ids = [f"req-{i}" for i in range(100)]
    first_pass = [dep.route_request(rid) for rid in request_ids]
    second_pass = [dep.route_request(rid) for rid in request_ids]
    third_pass = [dep.route_request(rid) for rid in request_ids]
    assert first_pass == second_pass == third_pass


def test_canary_distribution_matches_percentages():
    """Distribution over 10000 requests should match percentages within +/-5%."""
    dep = CanaryDeployment()
    dep.register_baseline("v1.0")
    dep.register_canary("v1.1", 10.0)

    n = 10000
    counts = {"v1.0": 0, "v1.1": 0}
    for i in range(n):
        v = dep.route_request(f"req-{i}-pid-{i*7919}")
        counts[v] += 1
    canary_frac = counts["v1.1"] / n
    # Hash-Verteilung: Erwartung 0.10, Tolerance +/-5%
    assert 0.05 <= canary_frac <= 0.15, (
        f"canary fraction {canary_frac:.4f} outside [0.05, 0.15]"
    )


# ---------- 2. CanaryHealthMonitor ----------


def test_health_monitor_records_outcomes():
    """record_outcome appends; sample_count reflects."""
    mon = CanaryHealthMonitor(window_capacity=100)
    mon.record_outcome("v1.1", success=True, latency_ms=50.0)
    mon.record_outcome("v1.1", success=True, latency_ms=60.0)
    mon.record_outcome("v1.1", success=False, latency_ms=200.0)
    assert mon.sample_count("v1.1") == 3
    err = mon.get_error_rate("v1.1")
    assert err == pytest.approx(1.0 / 3.0)


def test_health_monitor_error_rate_within_window():
    """Outcomes outside window_s are excluded."""
    mon = CanaryHealthMonitor(window_capacity=100)
    now = time.time()
    # Old failure (outside 60s window)
    mon.record_outcome("v1.1", success=False, latency_ms=50.0, ts=now - 120.0)
    # Recent successes
    mon.record_outcome("v1.1", success=True, latency_ms=50.0, ts=now - 10.0)
    mon.record_outcome("v1.1", success=True, latency_ms=50.0, ts=now - 5.0)
    # Window=60s should drop the old failure
    err_60 = mon.get_error_rate("v1.1", window_s=60.0)
    assert err_60 == pytest.approx(0.0)
    # Window=300s should include the failure
    err_300 = mon.get_error_rate("v1.1", window_s=300.0)
    assert err_300 == pytest.approx(1.0 / 3.0)


# ---------- 3. RollbackTrigger ----------


def test_rollback_trigger_fires_on_high_error_rate():
    """High error_rate -> RollbackDecision.rollback=True with ERROR_RATE_EXCEEDED."""
    mon = CanaryHealthMonitor()
    trig = RollbackTrigger(
        error_threshold=0.1,
        latency_threshold_ms=1000.0,
        cooldown_s=300.0,
        min_samples=5,
    )
    trig.register_canary_monitor(mon)

    # Record 10 outcomes, half failures -> error_rate=0.5 > 0.1
    for i in range(5):
        mon.record_outcome("v1.1", success=True, latency_ms=50.0)
    for i in range(5):
        mon.record_outcome("v1.1", success=False, latency_ms=50.0)

    decision = trig.check_rollback_needed("v1.1")
    assert decision.rollback is True
    assert decision.reason == RollbackReason.ERROR_RATE_EXCEEDED
    assert decision.affected_version == "v1.1"


def test_rollback_trigger_cooldown_blocks_repeat():
    """After firing once, cooldown blocks repeat-fire within cooldown_s."""
    mon = CanaryHealthMonitor()
    trig = RollbackTrigger(
        error_threshold=0.1,
        latency_threshold_ms=1000.0,
        cooldown_s=300.0,
        min_samples=5,
    )
    trig.register_canary_monitor(mon)

    # Trigger first rollback
    for i in range(5):
        mon.record_outcome("v1.1", success=False, latency_ms=50.0)
    for i in range(5):
        mon.record_outcome("v1.1", success=True, latency_ms=50.0)
    first = trig.check_rollback_needed("v1.1")
    assert first.rollback is True

    # Immediate second call should be blocked by cooldown
    second = trig.check_rollback_needed("v1.1")
    assert second.rollback is False
    assert second.reason == RollbackReason.NONE
    assert "cooldown" in second.detail.lower()
    # Cooldown remaining > 0
    assert trig.cooldown_remaining_s("v1.1") > 0


# ---------- 4. ProgressiveRollout ----------


def test_progressive_rollout_advances_steps():
    """advance() returns due steps in order; not-due steps return None."""
    dep = CanaryDeployment()
    dep.register_baseline("v1.0")
    schedule = [
        RolloutStep(time_s=0.0, percentage=5.0),
        RolloutStep(time_s=10.0, percentage=25.0),
        RolloutStep(time_s=20.0, percentage=50.0),
        RolloutStep(time_s=30.0, percentage=100.0),
    ]
    rollout = ProgressiveRollout(
        canary_version_id="v1.1",
        baseline_version_id="v1.0",
        schedule=schedule,
        deployment=dep,
        start_ts=1000.0,
    )

    # At t=1000.0, only first step (time_s=0) is due
    step1 = rollout.advance(now=1000.0)
    assert step1 is not None
    assert step1.percentage == 5.0
    # At t=1000.0, no further step due
    step_none = rollout.advance(now=1000.0)
    assert step_none is None
    # At t=1010, second step due
    step2 = rollout.advance(now=1010.0)
    assert step2 is not None
    assert step2.percentage == 25.0
    # Deployment percentage updated to last applied step
    dist = dep.get_distribution()
    assert dist["v1.1"] == 25.0
    assert rollout.fired_count() == 2


def test_progressive_rollout_complete_when_at_100():
    """is_complete() True after final step fires."""
    dep = CanaryDeployment()
    dep.register_baseline("v1.0")
    schedule = [
        RolloutStep(time_s=0.0, percentage=10.0),
        RolloutStep(time_s=5.0, percentage=100.0),
    ]
    rollout = ProgressiveRollout(
        canary_version_id="v1.1",
        baseline_version_id="v1.0",
        schedule=schedule,
        deployment=dep,
        start_ts=2000.0,
    )

    # Fire step 1
    s1 = rollout.advance(now=2000.0)
    assert s1 is not None
    assert not rollout.is_complete()
    # Fire step 2
    s2 = rollout.advance(now=2005.0)
    assert s2 is not None
    assert s2.percentage == 100.0
    assert rollout.is_complete()
    # Further advance is no-op
    assert rollout.advance(now=2100.0) is None


# ---------- 5. CanaryAuditLog ----------


def test_audit_log_thread_safe_append():
    """Concurrent log_decision from N threads preserves all records."""
    audit = CanaryAuditLog()
    n_threads = 8
    n_per_thread = 50

    def writer(thread_id: int) -> None:
        for i in range(n_per_thread):
            audit.log_decision(
                version_id=f"v1.1-t{thread_id}",
                action="record",
                reason=f"step-{i}",
            )

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    history = audit.get_history()
    assert len(history) == n_threads * n_per_thread
    # Every (thread, step) pair must be present
    seen = {(rec.version_id, rec.reason) for rec in history}
    expected = {
        (f"v1.1-t{t}", f"step-{i}")
        for t in range(n_threads)
        for i in range(n_per_thread)
    }
    assert seen == expected


# CRUX-MK


# ---------------------------------------------------------------------------
# P-W10-1 Test-Density-Patch v2 (Cross-LLM-V4-CRITICAL, API-aware)
# ---------------------------------------------------------------------------
import threading as _t
from kmo_governance.pre_production_canary import (
    CanaryDeployment,
    CanaryHealthMonitor,
    RollbackTrigger,
    ProgressiveRollout,
    CanaryAuditLog,
    CanaryOutcome,
    RollbackDecision,
    RolloutStep,
    RollbackReason,
)


def test_canary_register_requires_baseline_first_before_route():
    d = CanaryDeployment()
    with pytest.raises(RuntimeError):
        d.route_request("req-1")


def test_canary_register_canary_traffic_zero_raises():
    d = CanaryDeployment()
    with pytest.raises(ValueError):
        d.register_canary("v2", traffic_percentage=0.0)


def test_canary_register_canary_traffic_over_100_raises():
    d = CanaryDeployment()
    with pytest.raises(ValueError):
        d.register_canary("v2", traffic_percentage=101.0)


def test_canary_register_canary_total_over_100_raises():
    d = CanaryDeployment()
    d.register_canary("v2", traffic_percentage=70.0)
    with pytest.raises(ValueError):
        d.register_canary("v3", traffic_percentage=40.0)  # total 110


def test_canary_register_baseline_empty_raises():
    d = CanaryDeployment()
    with pytest.raises(ValueError):
        d.register_baseline("")


def test_canary_unregister_canary_idempotent():
    d = CanaryDeployment()
    d.register_baseline("v1")
    d.register_canary("v2", traffic_percentage=10.0)
    d.unregister_canary("v2")
    d.unregister_canary("v2")  # idempotent


def test_canary_route_distribution_5pct_within_tolerance():
    """1000 routes, 5% canary, real distribution +/-3pct."""
    d = CanaryDeployment()
    d.register_baseline("v1")
    d.register_canary("v2", traffic_percentage=5.0)
    canary_count = sum(
        1 for i in range(1000) if d.route_request(f"req-{i}") == "v2"
    )
    assert 20 <= canary_count <= 80, f"got {canary_count} canary routes"


def test_canary_route_distribution_100pct_baseline_when_only_canary():
    d = CanaryDeployment()
    d.register_baseline("v1")
    d.register_canary("v2", traffic_percentage=99.99)
    # 1 in 10000 might still go to baseline
    counts = {"v1": 0, "v2": 0}
    for i in range(1000):
        v = d.route_request(f"req-{i}")
        counts[v] += 1
    # Most should be canary
    assert counts["v2"] > 950


def test_canary_route_deterministic():
    d = CanaryDeployment()
    d.register_baseline("v1")
    d.register_canary("v2", traffic_percentage=50.0)
    # Same request_id always -> same version
    for _ in range(20):
        assert d.route_request("req-X") == d.route_request("req-X")


def test_canary_get_distribution_includes_baseline():
    d = CanaryDeployment()
    d.register_baseline("v1")
    d.register_canary("v2", traffic_percentage=20.0)
    dist = d.get_distribution()
    assert dist.get("v1") == 80.0
    assert dist.get("v2") == 20.0


def test_canary_health_monitor_window_capacity_validation():
    with pytest.raises(ValueError):
        CanaryHealthMonitor(window_capacity=0)
    with pytest.raises(ValueError):
        CanaryHealthMonitor(window_capacity=-10)


def test_canary_health_monitor_record_outcome_negative_latency_raises():
    hm = CanaryHealthMonitor()
    with pytest.raises(ValueError):
        hm.record_outcome("v2", success=True, latency_ms=-1.0)


def test_canary_health_monitor_unknown_version_returns_zero():
    hm = CanaryHealthMonitor()
    assert hm.get_error_rate("nonexistent") == 0.0
    assert hm.get_p99_latency("nonexistent") == 0.0


def test_canary_health_monitor_all_failures_100pct():
    hm = CanaryHealthMonitor()
    for _ in range(20):
        hm.record_outcome("v2", success=False, latency_ms=10.0)
    assert hm.get_error_rate("v2") == 1.0


def test_canary_health_monitor_all_success_zero_error():
    hm = CanaryHealthMonitor()
    for _ in range(20):
        hm.record_outcome("v2", success=True, latency_ms=10.0)
    assert hm.get_error_rate("v2") == 0.0


def test_canary_health_monitor_p99_latency():
    hm = CanaryHealthMonitor()
    for i in range(100):
        hm.record_outcome("v2", success=True, latency_ms=float(i))
    p99 = hm.get_p99_latency("v2")
    # P99 of [0..99] is ~99
    assert 95.0 <= p99 <= 99.0


def test_canary_health_monitor_window_overflow_drops_oldest():
    hm = CanaryHealthMonitor(window_capacity=10)
    for _ in range(20):
        hm.record_outcome("v2", success=False, latency_ms=1.0)
    # Window only contains last 10
    assert hm.sample_count("v2") <= 10


def test_canary_rollback_trigger_no_monitor_raises():
    rt = RollbackTrigger()
    with pytest.raises(RuntimeError):
        rt.check_rollback_needed("v2")


def test_canary_rollback_trigger_insufficient_samples_no_fire():
    hm = CanaryHealthMonitor()
    rt = RollbackTrigger(min_samples=10)
    rt.register_canary_monitor(hm)
    for _ in range(5):  # only 5 samples
        hm.record_outcome("v2", success=False, latency_ms=10.0)
    decision = rt.check_rollback_needed("v2")
    assert not decision.rollback


def test_canary_rollback_trigger_high_error_rate_fires():
    hm = CanaryHealthMonitor()
    rt = RollbackTrigger(error_threshold=0.05, min_samples=10)
    rt.register_canary_monitor(hm)
    for _ in range(20):
        hm.record_outcome("v2", success=False, latency_ms=10.0)
    decision = rt.check_rollback_needed("v2")
    assert decision.rollback
    assert decision.reason == RollbackReason.ERROR_RATE_EXCEEDED


def test_canary_rollback_trigger_high_latency_fires():
    hm = CanaryHealthMonitor()
    rt = RollbackTrigger(latency_threshold_ms=100.0, min_samples=10, error_threshold=0.99)
    rt.register_canary_monitor(hm)
    for _ in range(20):
        hm.record_outcome("v2", success=True, latency_ms=200.0)
    decision = rt.check_rollback_needed("v2")
    assert decision.rollback
    assert decision.reason == RollbackReason.LATENCY_REGRESSION


def test_canary_rollback_trigger_manual_override_fires():
    hm = CanaryHealthMonitor()
    rt = RollbackTrigger(min_samples=1)
    rt.register_canary_monitor(hm)
    rt.trigger_manual_override("v2", reason="testing")
    decision = rt.check_rollback_needed("v2")
    assert decision.rollback
    assert decision.reason == RollbackReason.MANUAL_OVERRIDE


def test_canary_rollback_trigger_cooldown_blocks_repeat():
    hm = CanaryHealthMonitor()
    rt = RollbackTrigger(error_threshold=0.05, min_samples=10, cooldown_s=60.0)
    rt.register_canary_monitor(hm)
    for _ in range(20):
        hm.record_outcome("v2", success=False, latency_ms=10.0)
    rt.check_rollback_needed("v2")  # first fire
    # Second check within cooldown -> no fire
    decision = rt.check_rollback_needed("v2")
    assert not decision.rollback


def test_progressive_rollout_empty_schedule_raises():
    with pytest.raises(ValueError):
        ProgressiveRollout(
            canary_version_id="v2",
            baseline_version_id="v1",
            schedule=[],
        )


def test_progressive_rollout_advance_returns_step():
    d = CanaryDeployment()
    d.register_baseline("v1")
    schedule = [RolloutStep(time_s=0.0, percentage=10.0)]
    pr = ProgressiveRollout(
        canary_version_id="v2",
        baseline_version_id="v1",
        schedule=schedule,
        deployment=d,
    )
    step = pr.advance()
    assert step is not None
    assert step.percentage == 10.0


def test_progressive_rollout_complete_after_all_steps():
    d = CanaryDeployment()
    d.register_baseline("v1")
    schedule = [
        RolloutStep(time_s=0.0, percentage=10.0),
        RolloutStep(time_s=0.0, percentage=50.0),
        RolloutStep(time_s=0.0, percentage=100.0),
    ]
    pr = ProgressiveRollout(
        canary_version_id="v2",
        baseline_version_id="v1",
        schedule=schedule,
        deployment=d,
    )
    while not pr.is_complete():
        pr.advance()
    assert pr.is_complete()


def test_progressive_rollout_rollback_marks_complete():
    d = CanaryDeployment()
    d.register_baseline("v1")
    schedule = [RolloutStep(time_s=0.0, percentage=10.0)]
    pr = ProgressiveRollout(
        canary_version_id="v2",
        baseline_version_id="v1",
        schedule=schedule,
        deployment=d,
    )
    pr.rollback_to_baseline()
    assert pr.is_complete()


def test_canary_audit_log_records_decisions():
    al = CanaryAuditLog()
    al.log_decision(
        version_id="v2",
        action="ROLLBACK",
        reason="error_rate",
        ts=12345.0,
    )
    history = al.get_history()
    assert len(history) == 1
    assert history[0].version_id == "v2"


def test_canary_audit_log_concurrent_50_threads():
    al = CanaryAuditLog()

    def worker(n: int):
        al.log_decision(
            version_id=f"v{n}",
            action="TEST",
            reason=f"reason-{n}",
            ts=float(n),
        )

    threads = [_t.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(al) == 50


def test_canary_outcome_frozen_dataclass():
    o = CanaryOutcome(
        version_id="v2",
        success=True,
        latency_ms=10.0,
        ts=1234.0,
    )
    with pytest.raises(Exception):
        o.success = False


def test_rollback_decision_frozen():
    rd = RollbackDecision(
        rollback=True,
        reason=RollbackReason.ERROR_RATE_EXCEEDED,
        affected_version="v2",
        detail="test",
    )
    with pytest.raises(Exception):
        rd.rollback = False
