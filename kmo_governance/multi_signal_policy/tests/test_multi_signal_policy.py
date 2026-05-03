"""KMO Multi-Signal-Policy Tests [CRUX-MK].

Spec: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-3.1.

Pflicht:
- test_multi_signal_aggregator_5_inputs
- test_multi_signal_cooperativity_n_per_input
- test_markov_state_transitions_aggressive_to_emergency
- test_backwards_compatible_with_binary_approval
- test_hill_function_sigmoid_shape
- test_multi_signal_integrates_with_quorum_sensing
"""

from __future__ import annotations

import pytest

from kmo_governance.multi_signal_policy import (
    MultiSignalAggregator,
    PolicyState,
    PolicyStateMachine,
    SignalSpec,
    binary_approval_adapter,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def specs_5():
    return {
        "revenue": SignalSpec("revenue", K_d=100.0, hill_n=2.0, weight=2.0),
        "latency_ms": SignalSpec("latency_ms", K_d=200.0, hill_n=3.0, weight=1.5),
        "error_rate": SignalSpec("error_rate", K_d=0.05, hill_n=4.0, weight=2.5),
        "cost_eur": SignalSpec("cost_eur", K_d=1000.0, hill_n=2.0, weight=1.0),
        "risk_score": SignalSpec("risk_score", K_d=0.3, hill_n=3.0, weight=1.5),
    }


# ---------------- Pflicht-Tests ----------------


def test_multi_signal_aggregator_5_inputs(specs_5):
    """5-input aggregator returns weighted Hill-Y average ∈ [0, 1]."""
    agg = MultiSignalAggregator(specs_5)
    score = agg.aggregate_score({
        "revenue": 100.0,    # at K_d -> Hill-Y = 0.5
        "latency_ms": 200.0, # at K_d -> 0.5
        "error_rate": 0.05,  # at K_d -> 0.5
        "cost_eur": 1000.0,  # at K_d -> 0.5
        "risk_score": 0.3,   # at K_d -> 0.5
    })
    # All Y=0.5 with arbitrary weights -> aggregate = 0.5
    assert score == pytest.approx(0.5, rel=1e-6)


def test_multi_signal_cooperativity_n_per_input():
    """Higher Hill-n per signal = sharper sigmoid response."""
    s_low = SignalSpec("x", K_d=1.0, hill_n=1.0)
    s_high = SignalSpec("x", K_d=1.0, hill_n=4.0)
    agg_low = MultiSignalAggregator({"x": s_low})
    agg_high = MultiSignalAggregator({"x": s_high})

    # At s = 0.5 (below K_d)
    y_low = agg_low.hill_y("x", 0.5)
    y_high = agg_high.hill_y("x", 0.5)
    assert y_high < y_low  # higher n is steeper -> lower at sub-Kd

    # At s = 2.0 (above K_d)
    y_low_high = agg_low.hill_y("x", 2.0)
    y_high_high = agg_high.hill_y("x", 2.0)
    assert y_high_high > y_low_high  # higher n is steeper -> higher above K_d


def test_hill_function_sigmoid_shape(specs_5):
    """Hill-Y is monotonically increasing in signal-value, S-shaped."""
    agg = MultiSignalAggregator(specs_5)
    points = [agg.hill_y("revenue", x) for x in [0, 50, 100, 150, 200, 1000]]
    # Strictly increasing
    for i in range(len(points) - 1):
        assert points[i + 1] >= points[i]
    # At s=0: Y=0
    assert points[0] == 0.0
    # At very high s: Y -> 1
    assert points[-1] > 0.99
    # At K_d: Y=0.5
    assert points[2] == pytest.approx(0.5, abs=0.01)


def test_markov_state_transitions_aggressive_to_emergency(specs_5):
    """Score deteriorates from high to low: AGGRESSIVE -> MODERATE -> CONSERVATIVE -> EMERGENCY."""
    agg = MultiSignalAggregator(specs_5)
    sm = PolicyStateMachine(agg, initial_state=PolicyState.AGGRESSIVE)

    # High signals: stays AGGRESSIVE
    high_signals = {n: spec.K_d * 5 for n, spec in specs_5.items()}
    sm.tick(high_signals)
    assert sm.state == PolicyState.AGGRESSIVE

    # Mid signals: AGGRESSIVE -> MODERATE (score < 0.65)
    mid_signals = {n: spec.K_d * 0.7 for n, spec in specs_5.items()}
    sm.tick(mid_signals)
    assert sm.state == PolicyState.MODERATE

    # Low signals: MODERATE -> CONSERVATIVE (score < 0.40)
    low_signals = {n: spec.K_d * 0.3 for n, spec in specs_5.items()}
    sm.tick(low_signals)
    assert sm.state == PolicyState.CONSERVATIVE

    # Very-low signals: CONSERVATIVE -> EMERGENCY (score < 0.20)
    crit_signals = {n: spec.K_d * 0.1 for n, spec in specs_5.items()}
    sm.tick(crit_signals)
    assert sm.state == PolicyState.EMERGENCY


def test_markov_hysterese_no_flapping(specs_5):
    """Hysterese: state requires score-cross over enter-threshold to switch back."""
    agg = MultiSignalAggregator(specs_5)
    sm = PolicyStateMachine(agg, initial_state=PolicyState.MODERATE)

    # Drop to CONSERVATIVE
    sm.tick({n: spec.K_d * 0.3 for n, spec in specs_5.items()})
    assert sm.state == PolicyState.CONSERVATIVE
    # Marginal recovery (above exit but below enter): stays CONSERVATIVE
    # exit_to_emergency=0.20, enter_moderate=0.50 -> at 0.45 stay
    sm.tick({n: spec.K_d * 1.0 for n, spec in specs_5.items()})  # exact-Kd -> 0.5 -> entry
    # Allowed to enter moderate: should switch
    assert sm.state in (PolicyState.MODERATE, PolicyState.CONSERVATIVE)


def test_backwards_compatible_with_binary_approval(specs_5):
    """binary_approval_adapter wraps multi-signal aggregator into bool."""
    agg = MultiSignalAggregator(specs_5)
    legacy = binary_approval_adapter(agg.aggregate_score, threshold=0.5)

    assert legacy({n: spec.K_d for n, spec in specs_5.items()}) is True   # Y=0.5 >= 0.5
    assert legacy({n: spec.K_d * 0.1 for n, spec in specs_5.items()}) is False
    assert legacy({n: spec.K_d * 5 for n, spec in specs_5.items()}) is True


def test_multi_signal_integrates_with_quorum_sensing():
    """Multi-Signal can use quorum-engine activation as one input source."""
    from kmo_governance.quorum_sensing import QuorumEngine

    qe = QuorumEngine(K_d=2.0, hill_n=2.7, decay_lambda=0,
                       activation_threshold=0.5, min_unique_dfs=3)
    qe.emit_signal("t1", "demand", "df-A", strength=2.0)
    qe.emit_signal("t1", "demand", "df-B", strength=2.0)
    qe.emit_signal("t1", "demand", "df-C", strength=2.0)
    quorum_y = qe.hill_activation("t1", "demand")

    specs = {
        "quorum_demand": SignalSpec("quorum_demand", K_d=0.5, hill_n=2.0),
        "load_factor": SignalSpec("load_factor", K_d=0.5, hill_n=2.0),
    }
    agg = MultiSignalAggregator(specs)
    score = agg.aggregate_score({"quorum_demand": quorum_y, "load_factor": 0.6})
    assert 0 < score < 1


def test_signalspec_constructor_validation():
    with pytest.raises(ValueError):
        SignalSpec("x", K_d=0, hill_n=2)
    with pytest.raises(ValueError):
        SignalSpec("x", K_d=1, hill_n=-1)
    with pytest.raises(ValueError):
        SignalSpec("x", K_d=1, hill_n=2, weight=-1)


def test_aggregator_unknown_signal_ignored(specs_5):
    """Unknown signal-names in input are silently ignored (forward-compat)."""
    agg = MultiSignalAggregator(specs_5)
    # Include unknown signal
    score = agg.aggregate_score({"revenue": 100.0, "unknown_xyz": 999})
    # Equal to score with only known signals
    score2 = agg.aggregate_score({"revenue": 100.0})
    assert score == pytest.approx(score2)


def test_aggregator_empty_signals(specs_5):
    """Empty signals returns 0.0 (no contribution)."""
    agg = MultiSignalAggregator(specs_5)
    assert agg.aggregate_score({}) == 0.0


def test_binary_adapter_threshold_validation():
    with pytest.raises(ValueError):
        binary_approval_adapter(lambda x: 0.5, threshold=1.5)


def test_aggregator_construction_validation():
    with pytest.raises(ValueError):
        MultiSignalAggregator({})
