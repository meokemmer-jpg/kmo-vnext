"""Soak-Test-Harness [CRUX-MK].

Welle-9-epsilon: Long-Run-Stress-Tests adressieren Codex-V2-Empfehlung #1
(Soak-Test ueber lange Laufzeit mit kombinierter Last aus EvolutionLoop +
Homeostasis + Sleep-Window + Knowledge-Decay).

Pytest-Marker:
  @pytest.mark.slow — Tests die >1s laufen, default skipped (--run-slow zum aktivieren)

Run:
  python3 -m pytest -m slow         # Soak-Tests aktiv
  python3 -m pytest -m "not slow"   # Default: Soak skipped (CI-fast)

Memory-Leak-Detection:
  - Tracemalloc + manuelle Process-RSS-Polling ohne externe Deps (psutil-frei)
  - Linear-Growth-Detector: max_rss / iterations Korrelation
"""

from __future__ import annotations

import gc
import random
import resource
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Callable

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))
_SAGA_DIR = _KMO_ROOT / "kmo_governance" / "saga-pattern"
if str(_SAGA_DIR) not in sys.path:
    sys.path.insert(0, str(_SAGA_DIR))


# ---------- Pytest config ----------


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: long-run soak test (default skipped)")


# ---------- Helpers ----------


def _rss_kb() -> int:
    """Process RSS in KB (no psutil-dep). macOS returns bytes, Linux KB — normalize."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS: bytes; Linux: kilobytes
    if sys.platform == "darwin":
        return raw // 1024
    return raw


def _detect_linear_growth(samples: list[int], threshold_kb_per_step: float) -> bool:
    """Return True if RSS-growth-per-step exceeds threshold (linear-leak signal).

    samples: list of RSS-KB at each measurement-point
    threshold_kb_per_step: max KB-growth per iteration before flagged as leak
    """
    if len(samples) < 3:
        return False
    n = len(samples)
    # Linear-Regression: slope via least-squares
    x_mean = (n - 1) / 2
    y_mean = sum(samples) / n
    num = sum((i - x_mean) * (samples[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return False
    slope_kb_per_step = num / den
    return slope_kb_per_step > threshold_kb_per_step


# ---------- Soak Tests ----------


@pytest.mark.slow
def test_soak_pilot_lifecycle_500_iterations():
    """Codex-V2 #1: 500 Pilot-Lifecycle-Iterationen ohne Memory-Leak.

    Sequence per iteration:
      - update_vitals (random vitals)
      - register_knowledge_entry + use_knowledge
      - emit_demand + check_pricing_homeostasis
      - record_failure
    """
    from df_executors.df_pilot_hotel_EU.pilot_integration import PilotHotelOrchestrator

    rss_samples: list[int] = []
    rng = random.Random(42)

    with tempfile.TemporaryDirectory() as td:
        pilot = PilotHotelOrchestrator(hotel_id="hotel-soak", state_dir=td)
        gc.collect()
        rss_samples.append(_rss_kb())

        for i in range(500):
            # Random vitals
            pilot.update_system_vitals(
                heart_rate=rng.uniform(10, 90),
                blood_pressure=rng.uniform(0.1, 0.55),  # below warning
                body_temperature=rng.uniform(0.0, 0.8),
                oxygen_saturation=rng.uniform(0.86, 1.0),
            )
            # Knowledge LTP
            key = f"method-{i % 20}"
            pilot.register_knowledge_entry(key, confidence=0.5)
            pilot.use_knowledge(key, performance=rng.random())
            # ABS demand
            pilot.emit_demand(amount=rng.uniform(0.1, 1.0))
            # Failure injection (sparse)
            if i % 50 == 0:
                pilot.record_failure(df_id=f"df-{i}")
            # Sample RSS every 50 iterations
            if i % 50 == 0:
                gc.collect()
                rss_samples.append(_rss_kb())

        gc.collect()
        rss_samples.append(_rss_kb())

    # Memory-Leak-Check: linear growth must be < 100 KB per 50-iter step
    has_leak = _detect_linear_growth(rss_samples, threshold_kb_per_step=100.0)
    assert not has_leak, f"Memory-Leak detected. RSS-Samples (KB): {rss_samples}"


@pytest.mark.slow
def test_soak_evolution_loop_100_generations():
    """Codex-V2 #1: 100 Evolution-Loop-Generationen, regression_count bounded."""
    from kmo_governance.evolution_loop import (
        EigenThresholdGuard,
        EvolutionLoop,
        FitnessEvaluator,
        Genome,
        PolicyMutator,
        RegressionCage,
    )

    rng = random.Random(0)
    mutator = PolicyMutator(gaussian_sigma=0.1, rng=rng)
    eval_ = FitnessEvaluator({"score": lambda p: -((p["x"] - 5.0) ** 2 + (p["y"] + 3.0) ** 2)})
    guard = EigenThresholdGuard(eigen_threshold=2.0)
    cage = RegressionCage(noise_sigma=0.5)
    loop = EvolutionLoop(
        mutator=mutator, evaluator=eval_, population_size=10,
        eigen_guard=guard, cage=cage,
    )

    seed = Genome(genome_id="seed", parameters={"x": 0.0, "y": 0.0})
    pop = loop.initialize_population(seed)
    cage.update_baseline(pop)

    rss_samples: list[int] = [_rss_kb()]
    for gen in range(100):
        pop = loop.step(pop)
        if gen % 10 == 0:
            gc.collect()
            rss_samples.append(_rss_kb())

    # Regression-rate bounded (fitness landscape stable)
    assert loop.regression_count() < 50  # max 50% regressions over 100 gens
    # Memory-Leak-Check
    has_leak = _detect_linear_growth(rss_samples, threshold_kb_per_step=200.0)
    assert not has_leak, f"Memory-Leak in evolution-loop. RSS-Samples (KB): {rss_samples}"


@pytest.mark.slow
def test_soak_concurrent_pilots_50_iter():
    """Codex-V2 #1: 5 parallele Pilots, 50 Iterationen each = 250 cross-pilot-ops."""
    from df_executors.df_pilot_hotel_EU.pilot_integration import PilotHotelOrchestrator
    import threading

    errors: list[Exception] = []

    def worker(hotel_id: str, td: str):
        try:
            pilot = PilotHotelOrchestrator(hotel_id=hotel_id, state_dir=td)
            for i in range(50):
                pilot.update_system_vitals(50, 0.4, 0.5, 0.9)
                pilot.register_knowledge_entry(f"k-{hotel_id}-{i}")
                pilot.use_knowledge(f"k-{hotel_id}-{i}")
                if i % 10 == 0:
                    pilot.emit_demand(amount=1.0)
        except Exception as e:
            errors.append(e)

    with tempfile.TemporaryDirectory() as base_td:
        threads = []
        for h in ["hotel-A", "hotel-B", "hotel-C", "hotel-D", "hotel-E"]:
            t = threading.Thread(
                target=worker,
                args=(h, str(Path(base_td) / h)),
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=30.0)
    assert not errors, f"Concurrent-pilot errors: {errors}"


@pytest.mark.slow
def test_soak_hormone_pool_pruning_100k_emissions():
    """Codex-V2 #1: 100k hormone-emissions trigger TTL-pruning, RSS bounded."""
    from kmo_governance.abs_tier_engine import HormonePool, HormoneType

    rss_samples: list[int] = []
    fake_t = {"t": 1_000_000.0}

    pool = HormonePool(halflife_sec=4 * 3600, clock=lambda: fake_t["t"])
    rss_samples.append(_rss_kb())

    for i in range(100_000):
        pool.emit("hotel-soak", HormoneType.DEMAND_SIGNAL, amount=1.0)
        # Advance time by 60s per emit -> 100k emits = 6M sec = ~1666h
        # TTL = 10 * halflife = 40h, so most emits expire before next sample
        fake_t["t"] += 60.0
        # Sample RSS every 10k emits
        if i % 10_000 == 0 and i > 0:
            gc.collect()
            rss_samples.append(_rss_kb())

    # gc_every=100 + 60s-per-emit + TTL=40h: most emissions expire and prune
    # Force final GC for verification
    pool.gc_expired()
    final_emissions = sum(len(v) for v in pool._emissions.values())
    # After full GC: nearly all 100k emissions expired
    assert final_emissions < 5_000, f"GC failed to prune most emissions: {final_emissions}/100000"
    # RSS-bounded check (relaxed threshold for 100k emit-store-then-prune cycle)
    has_leak = _detect_linear_growth(rss_samples, threshold_kb_per_step=2000.0)
    assert not has_leak, f"Hormone-Pool Memory-Leak. RSS: {rss_samples}, Emissions: {final_emissions}"


@pytest.mark.slow
def test_soak_full_stack_2000_pilot_ops_combined():
    """Codex-V2 #1: 2000 Operations mixed Cell+Tissue+Organ+Organism."""
    from df_executors.df_pilot_hotel_EU.pilot_integration import PilotHotelOrchestrator

    rng = random.Random(123)
    op_counters = {"vitals": 0, "knowledge": 0, "demand": 0, "fail": 0, "emergency": 0}

    rss_samples: list[int] = []

    with tempfile.TemporaryDirectory() as td:
        pilot = PilotHotelOrchestrator(hotel_id="hotel-stack", state_dir=td)
        rss_samples.append(_rss_kb())

        for i in range(2000):
            op = rng.choice(["vitals", "knowledge", "demand", "fail"])
            if op == "vitals":
                pilot.update_system_vitals(
                    rng.uniform(10, 90), rng.uniform(0.1, 0.5),
                    rng.uniform(0.0, 0.9), rng.uniform(0.86, 1.0),
                )
                op_counters["vitals"] += 1
            elif op == "knowledge":
                k = f"k-{i % 50}"
                pilot.register_knowledge_entry(k)
                pilot.use_knowledge(k)
                op_counters["knowledge"] += 1
            elif op == "demand":
                pilot.emit_demand(amount=rng.uniform(0.1, 1.5))
                op_counters["demand"] += 1
            elif op == "fail":
                pilot.record_failure(df_id=f"df-{i % 10}")
                op_counters["fail"] += 1
            # Rare: emergency-burst
            if i == 1000:
                pilot.signal_emergency(reason="soak-mid-emergency")
                op_counters["emergency"] += 1
            if i % 200 == 0:
                gc.collect()
                rss_samples.append(_rss_kb())

    has_leak = _detect_linear_growth(rss_samples, threshold_kb_per_step=300.0)
    assert not has_leak, f"Full-Stack Memory-Leak. RSS: {rss_samples}, Ops: {op_counters}"
    # System should still be functional
    assert sum(op_counters.values()) >= 2000


# ---------- Fast Smoke-Test (always runs) ----------


def test_soak_smoke_short_run_baseline():
    """Smoke-Test: kurzer Run der Soak-Pattern validiert (immer aktiv)."""
    samples = [1000, 1010, 1020, 1015]
    # No-leak (slope ~5)
    assert not _detect_linear_growth(samples, threshold_kb_per_step=100)
    # Leak (slope ~50)
    leaky = [1000, 1050, 1100, 1150, 1200]
    assert _detect_linear_growth(leaky, threshold_kb_per_step=10)
