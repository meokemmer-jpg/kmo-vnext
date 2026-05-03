"""CRUX-MK tests for A-21 Pheromone-Trails routing."""

from __future__ import annotations

import random
import threading

import pytest

from df_89.patterns.a21_pheromone import PheromoneTrail


def test_deposit_increases_pheromone_on_success() -> None:
    trail = PheromoneTrail()

    trail.deposit(("planner", "tool-a"), success=True, latency_ms=50.0)

    assert trail.tau(("planner", "tool-a")) == pytest.approx(0.02)


def test_deposit_decreases_on_failure() -> None:
    trail = PheromoneTrail(pheromones={("planner", "tool-a"): 10.0})

    trail.deposit(("planner", "tool-a"), success=False, latency_ms=25.0)

    assert trail.tau(("planner", "tool-a")) == pytest.approx(5.0)


def test_evaporation_decays_all_edges() -> None:
    trail = PheromoneTrail(
        pheromones={("s", "a"): 4.0, ("s", "b"): 6.0},
        evaporation_rate=0.2,
    )

    before = sum(trail.snapshot().values())
    trail.evaporate()
    after = sum(trail.snapshot().values())

    assert after == pytest.approx(before * 0.8)


def test_route_prefers_high_pheromone() -> None:
    trail = PheromoneTrail(
        pheromones={("s", "weak"): 1.0, ("s", "strong"): 20.0},
        rng=random.Random(7),
    )

    routes = [trail.route("s", ["weak", "strong"]) for _ in range(200)]

    assert routes.count("strong") > 180


def test_route_falls_back_to_random_when_all_low() -> None:
    trail = PheromoneTrail(
        pheromones={("s", "a"): 0.0002, ("s", "b"): 0.0003},
        ttl_threshold=0.001,
        rng=random.Random(1),
    )

    routes = {trail.route("s", ["a", "b"]) for _ in range(20)}

    assert routes == {"a", "b"}


def test_anti_spam_cap_at_tau_max() -> None:
    trail = PheromoneTrail(tau_max=1.0)

    for _ in range(10):
        trail.deposit(("s", "a"), success=True, latency_ms=0.1)

    assert trail.tau(("s", "a")) == pytest.approx(1.0)


def test_ttl_purges_stale_edges() -> None:
    trail = PheromoneTrail(
        pheromones={("s", "stale"): 0.0011, ("s", "live"): 1.0},
        evaporation_rate=0.1,
    )

    trail.evaporate()

    assert ("s", "stale") not in trail.snapshot()
    assert trail.tau(("s", "live")) == pytest.approx(0.9)


def test_external_outcome_required() -> None:
    trail = PheromoneTrail()

    with pytest.raises(TypeError):
        trail.deposit(("s", "a"), latency_ms=10.0)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        trail.deposit(("s", "a"), success=1, latency_ms=10.0)  # type: ignore[arg-type]


def test_concurrent_deposits_thread_safe() -> None:
    trail = PheromoneTrail()

    def worker() -> None:
        for _ in range(100):
            trail.deposit(("s", "a"), success=True, latency_ms=10.0)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert trail.tau(("s", "a")) == pytest.approx(80.0)
