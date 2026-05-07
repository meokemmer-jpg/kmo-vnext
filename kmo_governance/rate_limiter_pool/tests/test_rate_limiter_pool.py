# [CRUX-MK]
"""Rate-Limiter-Pool Tests (Welle-20 Phase-13.2 Modul 1/3)."""
from __future__ import annotations

import threading
import time
from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.rate_limiter_pool import (
    RateLimitDecision,
    RateLimiterPool,
    TenantConfig,
)


def test_init_validation():
    """Pre-condition checks: capacity > 0, refill_rate > 0."""
    with pytest.raises(ValueError):
        RateLimiterPool(default_capacity=0)
    with pytest.raises(ValueError):
        RateLimiterPool(default_capacity=-1)
    with pytest.raises(ValueError):
        RateLimiterPool(default_refill_rate=0.0)
    with pytest.raises(ValueError):
        RateLimiterPool(default_refill_rate=-5.0)
    # Valid construction
    pool = RateLimiterPool(default_capacity=10, default_refill_rate=2.0)
    assert pool.default_capacity == 10
    assert pool.default_refill_rate == 2.0


def test_register_tenant_basic():
    """Tenant registration returns config and stores bucket."""
    pool = RateLimiterPool()
    cfg = pool.register_tenant("tenant-A", capacity=50, refill_rate=5.0)
    assert isinstance(cfg, TenantConfig)
    assert cfg.tenant_id == "tenant-A"
    assert cfg.capacity == 50
    assert cfg.refill_rate == 5.0
    assert cfg.burst_allowance == 0
    assert "tenant-A" in pool.list_tenants()


def test_register_tenant_uses_defaults():
    """register_tenant without capacity/refill_rate uses pool defaults."""
    pool = RateLimiterPool(default_capacity=42, default_refill_rate=7.5)
    cfg = pool.register_tenant("default-tenant")
    assert cfg.capacity == 42
    assert cfg.refill_rate == 7.5


def test_register_tenant_duplicate_same_config_idempotent():
    """Re-registering with same config returns same config (idempotent)."""
    pool = RateLimiterPool()
    cfg1 = pool.register_tenant("tenant-X", capacity=20, refill_rate=2.0, burst_allowance=5)
    cfg2 = pool.register_tenant("tenant-X", capacity=20, refill_rate=2.0, burst_allowance=5)
    assert cfg1 == cfg2


def test_register_tenant_duplicate_different_config_raises():
    """Re-registering with different config raises ValueError."""
    pool = RateLimiterPool()
    pool.register_tenant("tenant-Y", capacity=10, refill_rate=1.0)
    with pytest.raises(ValueError, match="already registered with different config"):
        pool.register_tenant("tenant-Y", capacity=999, refill_rate=1.0)


def test_register_tenant_empty_id_raises():
    """Empty tenant_id is rejected."""
    pool = RateLimiterPool()
    with pytest.raises(ValueError):
        pool.register_tenant("")


def test_acquire_within_capacity():
    """Acquire within capacity returns allowed=True."""
    pool = RateLimiterPool()
    pool.register_tenant("t1", capacity=10, refill_rate=1.0)
    decision = pool.acquire("t1", tokens=3)
    assert decision.allowed is True
    assert decision.tenant_id == "t1"
    assert decision.tokens_remaining == 7.0
    assert decision.retry_after_s == 0.0
    assert "granted" in decision.reason


def test_acquire_exceeds_capacity_returns_retry_after():
    """Acquire exceeding capacity returns allowed=False with retry_after_s > 0."""
    pool = RateLimiterPool()
    pool.register_tenant("t-small", capacity=2, refill_rate=2.0)
    # Drain
    d1 = pool.acquire("t-small", tokens=2)
    assert d1.allowed is True
    assert d1.tokens_remaining == 0.0
    # Next acquire should fail
    d2 = pool.acquire("t-small", tokens=1)
    assert d2.allowed is False
    assert d2.retry_after_s > 0
    # With refill_rate=2, deficit=1 -> retry_after = 0.5s
    assert 0.4 < d2.retry_after_s < 0.6
    assert "insufficient" in d2.reason


def test_token_refill_over_time():
    """Tokens refill via time.time() delta after sleep."""
    pool = RateLimiterPool()
    pool.register_tenant("t-refill", capacity=10, refill_rate=20.0)
    # Drain completely
    d1 = pool.acquire("t-refill", tokens=10)
    assert d1.allowed is True
    # Sleep should refill ~2 tokens (0.1s * 20.0/s)
    time.sleep(0.15)
    d2 = pool.acquire("t-refill", tokens=2)
    assert d2.allowed is True


def test_burst_allowance():
    """Burst allowance allows temporary excess above capacity."""
    pool = RateLimiterPool()
    pool.register_tenant("t-burst", capacity=10, refill_rate=1.0, burst_allowance=5)
    # Should start with capacity + burst = 15 tokens
    state = pool.get_state("t-burst")
    assert state["tokens"] == 15.0
    # Can drain all 15
    decision = pool.acquire("t-burst", tokens=15)
    assert decision.allowed is True
    assert decision.tokens_remaining == 0.0


def test_release_returns_tokens():
    """Release adds tokens back, capped at capacity + burst."""
    pool = RateLimiterPool()
    pool.register_tenant("t-rel", capacity=10, refill_rate=1.0)
    pool.acquire("t-rel", tokens=5)
    state_before = pool.get_state("t-rel")
    # Allow tiny refill since time has passed (refill_rate=1.0 -> ~0 in microseconds)
    assert 5.0 <= state_before["tokens"] < 5.1
    pool.release("t-rel", tokens=3)
    state_after = pool.get_state("t-rel")
    # 5 + 3 = 8 (allowing tiny refill since time passes)
    assert 8.0 <= state_after["tokens"] <= 10.0


def test_release_caps_at_max():
    """Release does not exceed capacity + burst."""
    pool = RateLimiterPool()
    pool.register_tenant("t-cap", capacity=10, refill_rate=1.0, burst_allowance=2)
    # Bucket starts at max=12. Release should not push past.
    pool.release("t-cap", tokens=100)
    state = pool.get_state("t-cap")
    assert state["tokens"] <= 12.0


def test_release_invalid_tokens_raises():
    """release with tokens < 1 raises."""
    pool = RateLimiterPool()
    pool.register_tenant("t", capacity=5, refill_rate=1.0)
    with pytest.raises(ValueError):
        pool.release("t", tokens=0)


def test_acquire_invalid_tokens_raises():
    """acquire with tokens < 1 raises."""
    pool = RateLimiterPool()
    pool.register_tenant("t", capacity=5, refill_rate=1.0)
    with pytest.raises(ValueError):
        pool.acquire("t", tokens=0)


def test_unknown_tenant_raises():
    """Operations on unregistered tenant raise ValueError."""
    pool = RateLimiterPool()
    with pytest.raises(ValueError, match="unknown tenant"):
        pool.acquire("ghost")
    with pytest.raises(ValueError, match="unknown tenant"):
        pool.release("ghost")
    with pytest.raises(ValueError, match="unknown tenant"):
        pool.get_state("ghost")


def test_concurrent_50_threads_race_safe():
    """50 threads * 20 acquires each must yield consistent total count."""
    pool = RateLimiterPool()
    # Big capacity so all fit; refill_rate huge so refills happen during run
    pool.register_tenant("conc", capacity=2000, refill_rate=1.0)
    granted = []
    granted_lock = threading.Lock()

    def worker():
        local_grants = 0
        for _ in range(20):
            d = pool.acquire("conc", tokens=1)
            if d.allowed:
                local_grants += 1
        with granted_lock:
            granted.append(local_grants)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_granted = sum(granted)
    # Bucket started at 2000; we requested 1000 (50*20). All should be granted.
    assert total_granted == 1000
    state = pool.get_state("conc")
    # Remaining tokens should be ~1000 (with small refill positive bias)
    assert 1000.0 <= state["tokens"] <= 2000.0


def test_decision_frozen_immutability():
    """RateLimitDecision is frozen Dataclass -> immutable."""
    pool = RateLimiterPool()
    pool.register_tenant("frozen-t", capacity=5, refill_rate=1.0)
    decision = pool.acquire("frozen-t", tokens=1)
    with pytest.raises(FrozenInstanceError):
        decision.allowed = False  # type: ignore[misc]


def test_tenant_config_frozen_immutability():
    """TenantConfig is frozen Dataclass -> immutable."""
    cfg = TenantConfig(tenant_id="x", capacity=10, refill_rate=1.0, burst_allowance=0)
    with pytest.raises(FrozenInstanceError):
        cfg.capacity = 999  # type: ignore[misc]


def test_tenant_config_validation():
    """TenantConfig pre-condition checks via __post_init__."""
    with pytest.raises(ValueError):
        TenantConfig(tenant_id="", capacity=10, refill_rate=1.0, burst_allowance=0)
    with pytest.raises(ValueError):
        TenantConfig(tenant_id="x", capacity=0, refill_rate=1.0, burst_allowance=0)
    with pytest.raises(ValueError):
        TenantConfig(tenant_id="x", capacity=10, refill_rate=0.0, burst_allowance=0)
    with pytest.raises(ValueError):
        TenantConfig(tenant_id="x", capacity=10, refill_rate=1.0, burst_allowance=-1)


def test_get_state_snapshot():
    """get_state returns full snapshot dict."""
    pool = RateLimiterPool()
    pool.register_tenant("snap", capacity=20, refill_rate=3.0, burst_allowance=2)
    state = pool.get_state("snap")
    assert state["tenant_id"] == "snap"
    assert state["capacity"] == 20
    assert state["refill_rate"] == 3.0
    assert state["burst_allowance"] == 2
    assert state["tokens"] == 22.0  # capacity + burst
    assert "last_refill" in state


def test_list_tenants():
    """list_tenants returns sorted list of registered tenant_ids."""
    pool = RateLimiterPool()
    assert pool.list_tenants() == []
    pool.register_tenant("zebra")
    pool.register_tenant("alpha")
    pool.register_tenant("mango")
    assert pool.list_tenants() == ["alpha", "mango", "zebra"]


def test_tenant_isolation():
    """Different tenants have isolated buckets - drain one doesn't affect another."""
    pool = RateLimiterPool()
    pool.register_tenant("iso-a", capacity=10, refill_rate=1.0)
    pool.register_tenant("iso-b", capacity=10, refill_rate=1.0)
    # Drain iso-a
    d_a = pool.acquire("iso-a", tokens=10)
    assert d_a.allowed is True
    assert d_a.tokens_remaining == 0.0
    # iso-b still full
    state_b = pool.get_state("iso-b")
    assert state_b["tokens"] == 10.0
    d_b = pool.acquire("iso-b", tokens=5)
    assert d_b.allowed is True


# CRUX-MK
