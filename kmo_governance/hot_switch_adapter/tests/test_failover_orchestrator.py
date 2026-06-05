"""Failover-Orchestrator Tests [CRUX-MK]."""
import pytest
from uuid import uuid4

from src.multi_adapter_router import AdapterName
from src.failover_orchestrator import FailoverOrchestrator


def test_call_without_config_fails():
    o = FailoverOrchestrator()
    res = o.call(uuid4(), {})
    assert not res.success
    assert "no router" in res.error


def test_configure_tenant_creates_router():
    def hook(tid, p): return {"ok": True}
    o = FailoverOrchestrator(default_adapter_hooks={"apaleo": hook})
    tid = uuid4()
    o.configure_tenant(tid, primary=AdapterName.APALEO)
    assert o.get_router(tid) is not None


def test_call_uses_tenant_specific_router():
    def hook(tid, p): return {"ok": True}
    o = FailoverOrchestrator(default_adapter_hooks={"apaleo": hook})
    tid = uuid4()
    o.configure_tenant(tid, primary=AdapterName.APALEO)
    res = o.call(tid, {"x": 1})
    assert res.success


def test_per_tenant_isolated_health():
    """Tenant A's failures should not affect Tenant B."""
    counter_a = {"n": 0}
    counter_b = {"n": 0}
    def hook_a(tid, p):
        counter_a["n"] += 1
        raise RuntimeError("a fails")
    def hook_b(tid, p):
        counter_b["n"] += 1
        return {"ok": True}
    o = FailoverOrchestrator()
    tid_a, tid_b = uuid4(), uuid4()
    o.configure_tenant(tid_a, primary=AdapterName.APALEO,
                        adapter_hooks={"apaleo": hook_a})
    o.configure_tenant(tid_b, primary=AdapterName.APALEO,
                        adapter_hooks={"apaleo": hook_b})
    o.call(tid_a, {})
    o.call(tid_b, {})
    # Tenant B shouldn't see tenant A's failures
    overview = o.health_overview()
    a_router_health = overview[str(tid_a)]
    b_router_health = overview[str(tid_b)]
    assert a_router_health["apaleo"]["consecutive_fails"] == 1
    assert b_router_health["apaleo"]["consecutive_successes"] == 1


def test_multiple_tenants_independent():
    o = FailoverOrchestrator()
    for _ in range(3):
        tid = uuid4()
        o.configure_tenant(tid, primary=AdapterName.APALEO,
                            adapter_hooks={"apaleo": lambda tid, p: {}})
    overview = o.health_overview()
    assert len(overview) == 3


def test_secondary_tertiary_configured():
    o = FailoverOrchestrator()
    tid = uuid4()
    o.configure_tenant(
        tid, primary="apaleo", secondary="mews", tertiary="cloudbeds",
        adapter_hooks={"apaleo": lambda tid, p: {},
                       "mews": lambda tid, p: {},
                       "cloudbeds": lambda tid, p: {}},
    )
    router = o.get_router(tid)
    assert router.primary == "apaleo"
    assert router.secondary == "mews"
    assert router.tertiary == "cloudbeds"


def test_fail_threshold_passed_through():
    o = FailoverOrchestrator(fail_threshold=5)
    tid = uuid4()
    o.configure_tenant(tid, primary="apaleo",
                        adapter_hooks={"apaleo": lambda tid, p: {}})
    router = o.get_router(tid)
    assert router.health_monitors["apaleo"].threshold == 5


def test_health_overview_empty_when_no_tenants():
    o = FailoverOrchestrator()
    assert o.health_overview() == {}


def test_get_router_returns_none_for_unknown():
    o = FailoverOrchestrator()
    assert o.get_router(uuid4()) is None


def test_string_tenant_id_works():
    """String-IDs should work."""
    def hook(tid, p): return {"ok": True}
    o = FailoverOrchestrator(default_adapter_hooks={"apaleo": hook})
    o.configure_tenant("hotel-alpha", primary="apaleo")
    res = o.call("hotel-alpha", {})
    assert res.success


def test_no_tenant_hardcoding_in_adapter():
    """Test: adapter receives tenant_id explicitly, never hardcoded."""
    received = {}
    def hook(tid, p):
        received["tid"] = tid
        return {}
    o = FailoverOrchestrator(default_adapter_hooks={"apaleo": hook})
    tid = "hotel-bravo"
    o.configure_tenant(tid, primary="apaleo")
    o.call(tid, {})
    assert received["tid"] == tid
