"""KMO ABS-Tier-Engine Tests [CRUX-MK].

Spec: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-3.3.
"""

from __future__ import annotations

import math

import pytest

from kmo_governance.abs_tier_engine import (
    ABSTier,
    ABSTierRouter,
    HormonePool,
    HormoneType,
    PricingHomeostasis,
)


@pytest.fixture
def fixed_clock():
    state = {"t": 1_000_000.0}

    def clock():
        return state["t"]

    def tick(dt):
        state["t"] += dt

    clock.tick = tick  # type: ignore[attr-defined]
    return clock


@pytest.fixture
def pool(fixed_clock):
    return HormonePool(halflife_sec=3600, clock=fixed_clock)


# ---------------- HormonePool Tests ----------------


def test_hormone_pool_append_only(pool):
    """Each emit creates immutable HormoneEmission record."""
    e1 = pool.emit("hA", HormoneType.DEMAND_SIGNAL, 1.0)
    e2 = pool.emit("hA", HormoneType.DEMAND_SIGNAL, 2.0)
    assert e1.amount == 1.0
    assert e2.amount == 2.0
    assert e1.timestamp <= e2.timestamp


def test_hormone_decay_halflife(pool, fixed_clock):
    """concentration drops by 50% after one half-life."""
    pool.emit("hA", HormoneType.DEMAND_SIGNAL, 100.0)
    c0 = pool.concentration("hA", HormoneType.DEMAND_SIGNAL)
    assert c0 == pytest.approx(100.0, rel=0.001)
    fixed_clock.tick(3600)  # one half-life
    c_half = pool.concentration("hA", HormoneType.DEMAND_SIGNAL)
    assert c_half == pytest.approx(50.0, rel=0.01)
    fixed_clock.tick(3600)  # 2nd half-life: 25%
    c_quarter = pool.concentration("hA", HormoneType.DEMAND_SIGNAL)
    assert c_quarter == pytest.approx(25.0, rel=0.01)


def test_hormone_aggregation_sum_with_decay(pool, fixed_clock):
    """Multiple emissions sum with proper decay."""
    pool.emit("hA", HormoneType.DEMAND_SIGNAL, 50.0)
    fixed_clock.tick(3600)  # decay -> 25
    pool.emit("hA", HormoneType.DEMAND_SIGNAL, 100.0)
    c = pool.concentration("hA", HormoneType.DEMAND_SIGNAL)
    # 50*exp(-ln2*1) + 100 = 25 + 100 = 125
    assert c == pytest.approx(125.0, rel=0.01)


def test_cross_hotel_concentration_aggregates(pool, fixed_clock):
    """cross_hotel_concentration sums across all hotels for a hormone-type."""
    pool.emit("hA", HormoneType.DEMAND_SIGNAL, 50.0)
    pool.emit("hB", HormoneType.DEMAND_SIGNAL, 30.0)
    pool.emit("hC", HormoneType.DEMAND_SIGNAL, 20.0)
    pool.emit("hA", HormoneType.CAPACITY_PRESSURE, 10.0)  # different type, not counted
    total = pool.cross_hotel_concentration(HormoneType.DEMAND_SIGNAL)
    assert total == pytest.approx(100.0, rel=0.01)


def test_no_pricing_spiral_through_negative_feedback(pool, fixed_clock):
    """PricingHomeostasis detects spiral + emits anti-pricing damping."""
    # Push pricing-tier hormone above threshold
    for _ in range(10):
        pool.emit("hA", HormoneType.PRICING_TIER, 1.0)
    homeostasis = PricingHomeostasis(pool, spiral_threshold=5.0)
    pricing_before = pool.concentration("hA", HormoneType.PRICING_TIER)
    assert pricing_before > 5.0
    # Trigger dampening
    triggered = homeostasis.check_and_dampen("hA")
    assert triggered is True
    # Anti-pricing now > 0
    anti = pool.concentration("hA", HormoneType.ANTI_PRICING)
    assert anti > 0
    # Damping-factor in (0, 1)
    damp = homeostasis.damping_factor("hA")
    assert 0 < damp < 1


def test_hormone_pool_purge_hotel_gdpr(pool):
    """purge_hotel cascade-deletes all hormone-emissions for a hotel."""
    pool.emit("hA", HormoneType.DEMAND_SIGNAL, 1.0)
    pool.emit("hA", HormoneType.PRICING_TIER, 2.0)
    pool.emit("hB", HormoneType.DEMAND_SIGNAL, 3.0)
    deleted = pool.purge_hotel("hA")
    assert deleted == 2
    assert pool.concentration("hA", HormoneType.DEMAND_SIGNAL) == 0.0
    assert pool.concentration("hB", HormoneType.DEMAND_SIGNAL) == pytest.approx(3.0, rel=0.01)


def test_hormone_pool_validation(pool):
    with pytest.raises(ValueError):
        pool.emit("", HormoneType.DEMAND_SIGNAL, 1)
    with pytest.raises(TypeError):
        pool.emit("hA", "demand_signal", 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        pool.emit("hA", HormoneType.DEMAND_SIGNAL, -1)


def test_hormone_pool_constructor_validation():
    with pytest.raises(ValueError):
        HormonePool(halflife_sec=0)


# ---------------- ABSTierRouter Tests ----------------


def test_abs_tier_routing_based_on_hormones(pool):
    """route() returns SMART/HYBRID/VOLL based on receptor-response Hill-Y."""
    router = ABSTierRouter(pool, K_d=10.0, hill_n=3.0, smart_max_y=0.3, hybrid_max_y=0.7)

    # No hormones: SMART
    assert router.route("hA") == ABSTier.SMART

    # Mid hormones: HYBRID
    pool.emit("hB", HormoneType.DEMAND_SIGNAL, 10.0)  # at K_d
    pool.emit("hB", HormoneType.CAPACITY_PRESSURE, 0.0)
    # Y at K_d = 0.5 -> HYBRID (0.3 <= 0.5 < 0.7)
    assert router.route("hB") == ABSTier.HYBRID

    # High hormones: VOLL
    pool.emit("hC", HormoneType.DEMAND_SIGNAL, 50.0)
    pool.emit("hC", HormoneType.CAPACITY_PRESSURE, 30.0)
    assert router.route("hC") == ABSTier.VOLL


def test_abs_tier_router_constructor_validation(pool):
    with pytest.raises(ValueError):
        ABSTierRouter(pool, K_d=0)
    with pytest.raises(ValueError):
        ABSTierRouter(pool, K_d=1, hill_n=-1)
    with pytest.raises(ValueError):
        ABSTierRouter(pool, K_d=1, hill_n=2, smart_max_y=0.8, hybrid_max_y=0.7)


# ---------------- Cross-Hotel-Synchronization (Hormonal-Hormone) ----------------


def test_cross_hotel_pricing_synchronization_delay(pool, fixed_clock):
    """Hotel-A emits demand; Hotel-B-receptor sees decayed concentration after time-lag."""
    pool.emit("hA", HormoneType.DEMAND_SIGNAL, 100.0)
    # Hotel-A current
    cA_now = pool.concentration("hA", HormoneType.DEMAND_SIGNAL)
    assert cA_now == pytest.approx(100.0, rel=0.01)
    # Hotel-B has not received own demand
    assert pool.concentration("hB", HormoneType.DEMAND_SIGNAL) == 0.0
    # Cross-hotel total includes hotel-A
    total = pool.cross_hotel_concentration(HormoneType.DEMAND_SIGNAL)
    assert total == pytest.approx(100.0, rel=0.01)
    # After 1 half-life: pool decayed
    fixed_clock.tick(3600)
    total_decayed = pool.cross_hotel_concentration(HormoneType.DEMAND_SIGNAL)
    assert total_decayed == pytest.approx(50.0, rel=0.01)


def test_homeostasis_constructor_validation(pool):
    with pytest.raises(ValueError):
        PricingHomeostasis(pool, spiral_threshold=0)
    with pytest.raises(ValueError):
        PricingHomeostasis(pool, anti_K_a=0)
