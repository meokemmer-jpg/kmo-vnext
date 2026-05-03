"""KMO Lateral-Inhibition Tests [CRUX-MK].

Spec: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-2.3.

Pflicht (5+):
- test_lateral_inhibition_blocks_neighbor_overlap
- test_lateral_inhibition_pseudorandom_delay
- test_correlated_failure_detection_z_score_threshold
- test_lateral_inhibition_topology_loading
- test_lateral_inhibition_with_quorum_no_conflict
"""

from __future__ import annotations

import random

import pytest

from kmo_governance.lateral_inhibition import (
    CorrelatedFailureDetector,
    LateralInhibitor,
)
from kmo_governance.quorum_sensing import QuorumEngine


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
def topology_4dfs():
    # Linear topology: A-B-C-D (each df has 2 neighbors except boundaries)
    return {
        "df-A": ["df-B"],
        "df-B": ["df-A", "df-C"],
        "df-C": ["df-B", "df-D"],
        "df-D": ["df-C"],
    }


@pytest.fixture
def inhibitor(topology_4dfs, fixed_clock):
    return LateralInhibitor(
        topology=topology_4dfs,
        K_i=1.0,
        hill_n=2.5,
        base_prob=1.0,
        clock=fixed_clock,
        rng=random.Random(0),  # deterministic
    )


# ---------------- Pflicht-Tests ----------------


def test_lateral_inhibition_blocks_neighbor_overlap(inhibitor):
    """When neighbor recently signaled same action: inhibition strength rises."""
    # Initially no inhibition
    assert inhibitor.inhibition_strength("df-B", "scale_up") == 0.0
    # Neighbor df-A signals same action
    inhibitor.signal_intent("df-A", "scale_up")
    inh = inhibitor.inhibition_strength("df-B", "scale_up")
    assert inh > 0.0
    # admit_probability decreases
    p = inhibitor.admit_probability("df-B", "scale_up")
    assert p < 1.0


def test_lateral_inhibition_pseudorandom_delay(inhibitor):
    """pseudorandom_delay_sec returns reproducible value within range."""
    d1 = inhibitor.pseudorandom_delay_sec("df-A", "scale_up", max_delay_sec=0.5)
    d2 = inhibitor.pseudorandom_delay_sec("df-A", "scale_up", max_delay_sec=0.5)
    assert d1 == d2  # same input -> same output (deterministic within tick)
    assert 0 <= d1 <= 0.5


def test_correlated_failure_detection_z_score_threshold():
    """Z-score above threshold triggers correlated-failure-alarm."""
    detector = CorrelatedFailureDetector(window_sec=60, z_threshold=3.0)
    # Build baseline: 10 samples with low failure-counts
    for _ in range(50):
        detector.add_baseline_sample("tissue-A", 1)
    mean, sigma = detector.baseline_stats("tissue-A")
    assert mean == pytest.approx(1.0)
    assert sigma == pytest.approx(0.0)

    # Add some variance
    for c in [1, 0, 2, 1, 1, 0, 2, 1, 1, 1]:
        detector.add_baseline_sample("tissue-A", c)
    mean, sigma = detector.baseline_stats("tissue-A")
    assert sigma > 0

    # Inject many failures within window -> Z high
    for i in range(20):
        detector.record_failure("tissue-A", f"df-{i}")
    n = detector.failure_count_in_window("tissue-A")
    assert n == 20
    # n=20 vs mean ~1, sigma small -> Z huge
    assert detector.is_correlated_failure("tissue-A", mean=mean, sigma=sigma)


def test_lateral_inhibition_topology_loading(inhibitor, topology_4dfs):
    """Topology dict accessible + neighbors enforced."""
    assert inhibitor.topology == topology_4dfs
    # signal_intent for non-existent df raises
    with pytest.raises(KeyError):
        inhibitor.signal_intent("df-XYZ", "scale_up")


def test_lateral_inhibition_with_quorum_no_conflict(fixed_clock, topology_4dfs):
    """Lateral inhibition + quorum_sensing on same tissue compose without conflict.

    Scenario: quorum activates synchronized action; lateral_inhibition limits
    SAME-action duplication across neighbors. Both should be admissible.
    """
    quorum = QuorumEngine(K_d=2.0, hill_n=2.7, decay_lambda=0,
                          activation_threshold=0.5, min_unique_dfs=3,
                          clock=fixed_clock)
    inh = LateralInhibitor(topology=topology_4dfs, K_i=1.0, hill_n=2.5,
                           base_prob=1.0, clock=fixed_clock,
                           rng=random.Random(0))

    # 3 DFs trigger quorum
    quorum.emit_signal("tissue-A", "scale_up", "df-A", strength=2.0)
    quorum.emit_signal("tissue-A", "scale_up", "df-B", strength=2.0)
    quorum.emit_signal("tissue-A", "scale_up", "df-C", strength=2.0)
    assert quorum.is_quorum_active("tissue-A", "scale_up")

    # df-A signals first -> lateral inhibits df-B
    inh.signal_intent("df-A", "scale_up")
    inhB = inh.inhibition_strength("df-B", "scale_up")
    assert inhB > 0  # df-B inhibited

    # df-D not adjacent to df-A: NO inhibition
    inhD = inh.inhibition_strength("df-D", "scale_up")
    assert inhD == 0


# ---------------- Edge: decorator behavior ----------------


def test_lateral_inhibition_decorator_blocks_when_inhibited(topology_4dfs):
    inh = LateralInhibitor(
        topology=topology_4dfs,
        K_i=0.1,  # very low K_i: any neighbor signal = strong inhibition
        hill_n=4.0,
        base_prob=1.0,
        rng=random.Random(0),
    )
    inh.signal_intent("df-A", "scale_up")  # neighbor active

    @inh.lateral_decorator("df-B", "scale_up")
    def critical_action():
        return "did-it"

    # df-B is fully inhibited (admit_probability ~ 0)
    with pytest.raises(PermissionError):
        critical_action()


def test_lateral_inhibition_constructor_validation():
    with pytest.raises(ValueError):
        LateralInhibitor(topology={}, K_i=0)
    with pytest.raises(ValueError):
        LateralInhibitor(topology={}, hill_n=-1)
    with pytest.raises(ValueError):
        LateralInhibitor(topology={}, base_prob=2)


def test_correlated_failure_constructor_validation():
    with pytest.raises(ValueError):
        CorrelatedFailureDetector(window_sec=0)
    with pytest.raises(ValueError):
        CorrelatedFailureDetector(window_sec=60, z_threshold=0)
    d = CorrelatedFailureDetector()
    with pytest.raises(ValueError):
        d.record_failure("", "df-A")
