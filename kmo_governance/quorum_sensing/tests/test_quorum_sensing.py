"""KMO Quorum-Sensing Tests [CRUX-MK].

Spec: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-2.1.

Pflicht (8):
- test_quorum_hill_function_threshold
- test_quorum_auto_inducer_decay_evaporation
- test_quorum_3_df_independence_required
- test_quorum_decorator_blocks_below_threshold
- test_quorum_synchronized_activation_above_threshold
- test_quorum_cooperativity_n_parameter
- test_quorum_purge_tissue_cascade
- test_quorum_constructor_validation
"""

from __future__ import annotations

import pytest

from kmo_governance.quorum_sensing import (
    QuorumEngine,
    quorum_required,
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
def engine(fixed_clock):
    return QuorumEngine(
        K_d=2.0, hill_n=2.7, decay_lambda=0.05,
        activation_threshold=0.5, min_unique_dfs=3, clock=fixed_clock,
    )


# ---------------- Pflicht-Tests ----------------


def test_quorum_hill_function_threshold(engine):
    """Hill-Y = s^n / (K_d^n + s^n). At s = K_d: Y = 0.5."""
    # Below threshold: 1 contribution at s=1.0, K_d=2.0, n=2.7 -> Y small
    engine.emit_signal("t1", "alarm", "df-A", strength=1.0)
    y_low = engine.hill_activation("t1", "alarm")
    assert 0.0 < y_low < 0.5

    # At K_d: Y = 0.5 exactly (within float tolerance)
    fresh = QuorumEngine(K_d=2.0, hill_n=2.7, decay_lambda=0)
    fresh.emit_signal("t2", "alarm", "df-A", strength=2.0)
    y_at_kd = fresh.hill_activation("t2", "alarm")
    assert y_at_kd == pytest.approx(0.5, rel=1e-6)

    # Above K_d: Y -> 1
    fresh.emit_signal("t2", "alarm", "df-B", strength=10.0)
    y_high = fresh.hill_activation("t2", "alarm")
    assert y_high > 0.95


def test_quorum_auto_inducer_decay_evaporation(engine, fixed_clock):
    """Concentration decays exponentially with lambda."""
    engine.emit_signal("t1", "demand", "df-A", strength=10.0)
    c0 = engine.current_concentration("t1", "demand")
    assert c0 == pytest.approx(10.0, rel=1e-6)

    fixed_clock.tick(20.0)  # decay: exp(-0.05 * 20) = exp(-1) ≈ 0.368
    c1 = engine.current_concentration("t1", "demand")
    assert c1 == pytest.approx(10.0 * 0.367879, rel=1e-3)


def test_quorum_3_df_independence_required(engine):
    """Quorum requires unique_df_count >= min_unique_dfs (default 3)."""
    # Single DF emits 10x: Hill-Y high, but unique_dfs = 1 < 3
    for _ in range(10):
        engine.emit_signal("t1", "alarm", "df-only", strength=2.0)
    y = engine.hill_activation("t1", "alarm")
    assert y > 0.5  # Hill above threshold
    assert not engine.is_quorum_active("t1", "alarm")  # but unique_dfs = 1

    # 3 unique DFs, even if total strength is moderate
    e2 = QuorumEngine(K_d=2.0, hill_n=2.7, decay_lambda=0, min_unique_dfs=3)
    e2.emit_signal("t1", "alarm", "df-A", strength=2.0)
    e2.emit_signal("t1", "alarm", "df-B", strength=2.0)
    e2.emit_signal("t1", "alarm", "df-C", strength=2.0)
    assert e2.is_quorum_active("t1", "alarm")


def test_quorum_decorator_blocks_below_threshold(engine):
    """quorum_required decorator raises PermissionError when quorum NOT active."""
    @quorum_required(engine, "t1", "alarm")
    def synchronized_action():
        return "fired"

    with pytest.raises(PermissionError):
        synchronized_action()

    # Activate quorum
    engine.emit_signal("t1", "alarm", "df-A", strength=2.0)
    engine.emit_signal("t1", "alarm", "df-B", strength=2.0)
    engine.emit_signal("t1", "alarm", "df-C", strength=2.0)
    assert synchronized_action() == "fired"


def test_quorum_synchronized_activation_above_threshold(engine):
    """3 DFs each contributing strength=1.0 -> total ≈ 3.0 > K_d=2.0 -> Hill > 0.5."""
    engine.emit_signal("t1", "demand", "df-A", strength=1.0)
    engine.emit_signal("t1", "demand", "df-B", strength=1.0)
    engine.emit_signal("t1", "demand", "df-C", strength=1.0)
    assert engine.is_quorum_active("t1", "demand")


def test_quorum_cooperativity_n_parameter():
    """Higher n = steeper sigmoid; n=1 (no cooperativity) vs n=4 (strong)."""
    e_low = QuorumEngine(K_d=2.0, hill_n=1.0, decay_lambda=0)
    e_high = QuorumEngine(K_d=2.0, hill_n=4.0, decay_lambda=0)

    for e in (e_low, e_high):
        e.emit_signal("t", "x", "df-A", strength=1.5)  # below K_d

    # At s=1.5 < K_d: n=4 should give lower activation than n=1
    y_low_n = e_low.hill_activation("t", "x")
    y_high_n = e_high.hill_activation("t", "x")
    assert y_high_n < y_low_n


def test_quorum_purge_tissue_cascade(engine):
    """purge_tissue removes all signal-pools for that tissue."""
    engine.emit_signal("t1", "demand", "df-A", strength=1.0)
    engine.emit_signal("t1", "alarm", "df-A", strength=1.0)
    engine.emit_signal("t2", "demand", "df-A", strength=1.0)

    deleted = engine.purge_tissue("t1")
    assert deleted == 2
    assert engine.list_pools_for_tissue("t1") == []
    # t2 unaffected
    assert len(engine.list_pools_for_tissue("t2")) == 1


def test_quorum_constructor_validation():
    with pytest.raises(ValueError):
        QuorumEngine(K_d=0)
    with pytest.raises(ValueError):
        QuorumEngine(K_d=1.0, hill_n=-1)
    with pytest.raises(ValueError):
        QuorumEngine(K_d=1.0, decay_lambda=-1)
    with pytest.raises(ValueError):
        QuorumEngine(K_d=1.0, activation_threshold=1.5)
    with pytest.raises(ValueError):
        QuorumEngine(K_d=1.0, min_unique_dfs=0)


# ---------------- Edge: Cross-Tissue isolation ----------------


def test_cross_tissue_isolation(engine):
    """Signals on tissue-A do not affect quorum on tissue-B."""
    engine.emit_signal("tA", "alarm", "df-A", strength=2.0)
    engine.emit_signal("tA", "alarm", "df-B", strength=2.0)
    engine.emit_signal("tA", "alarm", "df-C", strength=2.0)
    assert engine.is_quorum_active("tA", "alarm")
    assert not engine.is_quorum_active("tB", "alarm")


# ---------------- Edge: emit_signal validation ----------------


def test_emit_signal_validation(engine):
    with pytest.raises(ValueError):
        engine.emit_signal("", "alarm", "df-A")
    with pytest.raises(ValueError):
        engine.emit_signal("t1", "", "df-A")
    with pytest.raises(ValueError):
        engine.emit_signal("t1", "alarm", "")
    with pytest.raises(ValueError):
        engine.emit_signal("t1", "alarm", "df-A", strength=-1.0)


# ---------------- Patch C1: TTL-Binding fuer unique_df_count (Welle-9β.5) ----------------


def test_quorum_unique_df_count_ttl_window_decays(fixed_clock):
    """unique_df_count drops as old contributions exit the TTL-window (decay-based)."""
    engine = QuorumEngine(
        K_d=2.0, hill_n=2.7, decay_lambda=0.05,  # 5/0.05 = 100s TTL-window
        activation_threshold=0.5, min_unique_dfs=3, clock=fixed_clock,
    )
    # 3 unique DFs at t=0
    engine.emit_signal("t1", "alarm", "df-A", strength=2.0)
    engine.emit_signal("t1", "alarm", "df-B", strength=2.0)
    engine.emit_signal("t1", "alarm", "df-C", strength=2.0)
    # All 3 within TTL: quorum active
    assert engine.is_quorum_active("t1", "alarm")

    # Wait beyond TTL-window (5/decay_lambda = 5/0.05 = 100s); fast-forward 200s
    fixed_clock.tick(200.0)
    # 3 historical contributions, 0 in TTL -> NOT quorum
    pool = engine._pools[("t1", "alarm")]
    n_recent = pool.unique_df_count(now=fixed_clock(), ttl_window_sec=engine.unique_df_ttl_sec)
    assert n_recent == 0
    # Hill-Y has decayed too; quorum NOT active
    assert not engine.is_quorum_active("t1", "alarm")
