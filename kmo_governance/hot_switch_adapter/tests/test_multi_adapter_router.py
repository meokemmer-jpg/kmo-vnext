"""Multi-Adapter-Router Tests [CRUX-MK]."""
import pytest

from src.multi_adapter_router import (
    MultiAdapterRouter, AdapterName, RoutingDecision, AdapterCallResult,
)


def test_primary_success_uses_primary():
    def primary_hook(tid, p): return {"booking_id": "p1"}
    def secondary_hook(tid, p): return {"booking_id": "s1"}
    router = MultiAdapterRouter(
        primary=AdapterName.APALEO, secondary=AdapterName.MEWS,
        adapter_hooks={"apaleo": primary_hook, "mews": secondary_hook},
    )
    result = router.call("tenant-1", {"x": 1})
    assert result.success
    assert result.used_adapter == "apaleo"
    assert result.routing_decision == RoutingDecision.PRIMARY


def test_primary_fails_failover_to_secondary():
    def primary_hook(tid, p):
        raise RuntimeError("apaleo down")
    def secondary_hook(tid, p):
        return {"booking_id": "s1"}
    router = MultiAdapterRouter(
        primary=AdapterName.APALEO, secondary=AdapterName.MEWS,
        adapter_hooks={"apaleo": primary_hook, "mews": secondary_hook},
    )
    result = router.call("tenant-1", {"x": 1})
    assert result.success
    assert result.used_adapter == "mews"
    assert result.routing_decision == RoutingDecision.FAILOVER_SECONDARY


def test_primary_secondary_fail_failover_tertiary():
    def fail_hook(tid, p):
        raise RuntimeError("down")
    def tertiary_hook(tid, p):
        return {"booking_id": "t1"}
    router = MultiAdapterRouter(
        primary="apaleo", secondary="mews", tertiary="cloudbeds",
        adapter_hooks={
            "apaleo": fail_hook, "mews": fail_hook, "cloudbeds": tertiary_hook,
        },
    )
    result = router.call("tenant-1", {})
    assert result.success
    assert result.used_adapter == "cloudbeds"
    assert result.routing_decision == RoutingDecision.FAILOVER_TERTIARY


def test_all_adapters_fail_returns_no_available():
    def fail_hook(tid, p):
        raise RuntimeError("down")
    router = MultiAdapterRouter(
        primary="apaleo", secondary="mews",
        adapter_hooks={"apaleo": fail_hook, "mews": fail_hook},
    )
    result = router.call("tenant-1", {})
    assert not result.success
    assert result.routing_decision == RoutingDecision.NO_AVAILABLE_ADAPTER


def test_circuit_open_skips_adapter():
    """Wenn Circuit OPEN, wird Adapter geskippt."""
    counter = {"apaleo": 0}
    def primary_hook(tid, p):
        counter["apaleo"] += 1
        raise RuntimeError("down")
    def secondary_hook(tid, p):
        return {"ok": True}
    router = MultiAdapterRouter(
        primary="apaleo", secondary="mews",
        adapter_hooks={"apaleo": primary_hook, "mews": secondary_hook},
        fail_threshold=2,
    )
    # 3 calls -> apaleo failt 2x, dann circuit open
    router.call("t", {})
    router.call("t", {})
    router.call("t", {})
    assert counter["apaleo"] == 2  # 3rd call sollte geskippt werden


def test_health_summary_returns_status_per_adapter():
    def hook(tid, p): return {}
    router = MultiAdapterRouter(
        primary="apaleo", secondary="mews",
        adapter_hooks={"apaleo": hook, "mews": hook},
    )
    router.call("t", {})
    summary = router.health_summary()
    assert "apaleo" in summary
    assert "mews" in summary
    assert summary["apaleo"]["consecutive_successes"] == 1


def test_no_hook_failure():
    router = MultiAdapterRouter(primary="apaleo")
    result = router.call("t", {})
    assert not result.success
    assert result.routing_decision == RoutingDecision.NO_AVAILABLE_ADAPTER


def test_fallback_chain_logged():
    def fail(tid, p): raise RuntimeError("x")
    def ok(tid, p): return {}
    router = MultiAdapterRouter(
        primary="apaleo", secondary="mews",
        adapter_hooks={"apaleo": fail, "mews": ok},
    )
    result = router.call("t", {})
    assert "apaleo" in result.fallback_chain
    assert "mews" in result.fallback_chain
