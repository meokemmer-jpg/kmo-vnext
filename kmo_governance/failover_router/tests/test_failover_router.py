# [CRUX-MK]
"""Failover-Router Tests."""
from __future__ import annotations

import threading

import pytest

from kmo_governance.failover_router import (
    FailoverRouter,
    FailoverState,
    NodeStatus,
    RouteDecision,
)


def test_router_init_validation():
    with pytest.raises(ValueError):
        FailoverRouter(primary_node_id="", standby_node_ids=["s1"])
    with pytest.raises(ValueError):
        FailoverRouter(primary_node_id="p", standby_node_ids=[])
    with pytest.raises(ValueError):
        FailoverRouter(primary_node_id="p", standby_node_ids=["s"], health_threshold=0)


def test_router_initial_state_primary():
    r = FailoverRouter("p", ["s1", "s2"])
    assert r.state == FailoverState.PRIMARY
    assert r.active_node == "p"


def test_router_route_to_primary_when_healthy():
    r = FailoverRouter("p", ["s1"])
    decision = r.route()
    assert decision.target_node_id == "p"
    assert decision.state == FailoverState.PRIMARY


def test_router_failover_when_primary_down():
    r = FailoverRouter("p", ["s1", "s2"], health_threshold=3)
    for _ in range(3):
        r.record_health("p", healthy=False)
    decision = r.route()
    assert decision.target_node_id == "s1"
    assert decision.state == FailoverState.FAILED_OVER


def test_router_failover_skips_unhealthy_standby():
    r = FailoverRouter("p", ["s1", "s2"], health_threshold=2)
    # Both primary AND s1 down
    for _ in range(2):
        r.record_health("p", healthy=False)
        r.record_health("s1", healthy=False)
    decision = r.route()
    assert decision.target_node_id == "s2"


def test_router_all_down_returns_primary_fallback():
    r = FailoverRouter("p", ["s1"], health_threshold=2)
    for _ in range(2):
        r.record_health("p", healthy=False)
        r.record_health("s1", healthy=False)
    decision = r.route()
    # All-down fallback to primary
    assert "all nodes DOWN" in decision.reason


def test_router_unknown_node_health_raises():
    r = FailoverRouter("p", ["s1"])
    with pytest.raises(ValueError):
        r.record_health("unknown", healthy=True)


def test_router_recovery_state_after_primary_returns_healthy():
    r = FailoverRouter("p", ["s1"], health_threshold=2)
    for _ in range(2):
        r.record_health("p", healthy=False)
    r.route()  # failover
    r.record_health("p", healthy=True)  # recovery
    decision = r.route()
    assert decision.state == FailoverState.RECOVERING


def test_router_promote_to_primary():
    r = FailoverRouter("p", ["s1"], health_threshold=2)
    for _ in range(2):
        r.record_health("p", healthy=False)
    r.route()
    r.record_health("p", healthy=True)
    decision = r.promote_to_primary()
    assert decision.state == FailoverState.PRIMARY
    assert r.active_node == "p"


def test_router_promote_unhealthy_raises():
    r = FailoverRouter("p", ["s1"], health_threshold=2)
    for _ in range(2):
        r.record_health("p", healthy=False)
    with pytest.raises(RuntimeError):
        r.promote_to_primary()


def test_router_health_recovery_resets_fail_count():
    r = FailoverRouter("p", ["s1"], health_threshold=3)
    r.record_health("p", healthy=False)
    r.record_health("p", healthy=False)
    r.record_health("p", healthy=True)  # reset
    r.record_health("p", healthy=False)
    statuses = r.get_node_statuses()
    # Only 1 fail since reset, NOT 3 -> still HEALTHY or DEGRADED
    assert statuses["p"] != NodeStatus.DOWN


def test_router_node_statuses_snapshot():
    r = FailoverRouter("p", ["s1", "s2"])
    statuses = r.get_node_statuses()
    assert statuses["p"] == NodeStatus.HEALTHY
    assert "s1" in statuses
    assert "s2" in statuses


def test_router_concurrent_health_updates_50_threads():
    r = FailoverRouter("p", ["s1"], health_threshold=1000)

    def worker():
        for _ in range(20):
            r.record_health("p", healthy=True)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Health: all OK because all healthy=True
    assert r.get_node_statuses()["p"] == NodeStatus.HEALTHY


def test_router_route_decision_frozen():
    r = FailoverRouter("p", ["s1"])
    decision = r.route()
    with pytest.raises(Exception):
        decision.target_node_id = "modified"
