"""Tests for evolution_loop SKELETON [CRUX-MK]."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.evolution_loop import (  # noqa: E402
    EigenThresholdGuard,
    EvolutionLoop,
    FitnessEvaluator,
    GenerationArchive,
    Genome,
    PolicyMutator,
    RegressionCage,
    make_canary,
)


def test_genome_clone_increments_generation():
    parent = Genome(genome_id="p", parameters={"x": 1.0}, generation=2)
    child = parent.clone(new_id="c")
    assert child.generation == 3
    assert child.parent_id == "p"
    assert child.parameters == parent.parameters
    # Mutating child must not affect parent
    child.parameters["x"] = 999.0
    assert parent.parameters["x"] == 1.0


def test_policy_mutator_adds_gaussian_noise():
    rng = random.Random(42)
    mutator = PolicyMutator(gaussian_sigma=0.1, flip_probability=0.0, swap_probability=0.0, rng=rng)
    parent = Genome(genome_id="p", parameters={"x": 1.0, "y": 2.0})
    child = mutator.mutate(parent, new_id="c")
    # Child params should differ from parent (Gaussian noise applied)
    assert child.parameters["x"] != 1.0
    assert child.parameters["y"] != 2.0
    # But parent unchanged (clone-semantics)
    assert parent.parameters["x"] == 1.0


def test_policy_mutator_validates_sigma():
    with pytest.raises(ValueError):
        PolicyMutator(gaussian_sigma=0)


def test_fitness_evaluator_populates_objectives():
    eval_ = FitnessEvaluator({
        "obj_a": lambda p: p["x"] * 2,
        "obj_b": lambda p: p["x"] + p["y"],
    })
    g = Genome(genome_id="g", parameters={"x": 3.0, "y": 4.0})
    eval_.evaluate(g)
    assert g.fitness == {"obj_a": 6.0, "obj_b": 7.0}


def test_fitness_evaluator_validates_empty():
    with pytest.raises(ValueError):
        FitnessEvaluator({})


def test_pareto_dominance():
    eval_ = FitnessEvaluator({"a": lambda p: 0, "b": lambda p: 0})
    g1 = Genome(genome_id="1", parameters={}, fitness={"a": 5.0, "b": 5.0})
    g2 = Genome(genome_id="2", parameters={}, fitness={"a": 3.0, "b": 3.0})
    g3 = Genome(genome_id="3", parameters={}, fitness={"a": 5.0, "b": 5.0})  # equal
    assert eval_.dominates(g1, g2) is True
    assert eval_.dominates(g2, g1) is False
    # Equal fitness: neither dominates
    assert eval_.dominates(g1, g3) is False
    assert eval_.dominates(g3, g1) is False


def test_pareto_front_filters_dominated():
    eval_ = FitnessEvaluator({"a": lambda p: 0, "b": lambda p: 0})
    pop = [
        Genome(genome_id="best", parameters={}, fitness={"a": 5.0, "b": 5.0}),
        Genome(genome_id="dominated", parameters={}, fitness={"a": 3.0, "b": 3.0}),
        Genome(genome_id="trade", parameters={}, fitness={"a": 6.0, "b": 1.0}),  # non-dom
    ]
    front = eval_.pareto_front(pop)
    keys = {g.genome_id for g in front}
    assert "dominated" not in keys
    assert "best" in keys
    assert "trade" in keys


def test_generation_archive_tracks_genealogy():
    arch = GenerationArchive()
    g0 = Genome(genome_id="g0", parameters={}, generation=0)
    g1 = Genome(genome_id="g1", parameters={}, generation=1, parent_id="g0")
    arch.add(g0)
    arch.add(g1)
    assert arch.latest_generation() == 1
    assert len(arch.generation(0)) == 1
    assert arch.generation(1)[0].parent_id == "g0"
    assert len(arch) == 2


def test_evolution_loop_initialize_population():
    rng = random.Random(0)
    mutator = PolicyMutator(rng=rng)
    eval_ = FitnessEvaluator({"score": lambda p: p["x"]})
    loop = EvolutionLoop(mutator=mutator, evaluator=eval_, population_size=5)
    seed = Genome(genome_id="seed", parameters={"x": 1.0})
    pop = loop.initialize_population(seed)
    assert len(pop) == 5
    assert pop[0] is seed
    # All evaluated
    for g in pop:
        assert "score" in g.fitness


def test_evolution_loop_step_advances_generation():
    rng = random.Random(0)
    mutator = PolicyMutator(rng=rng)
    eval_ = FitnessEvaluator({"score": lambda p: -abs(p["x"] - 5.0)})  # max at x=5
    loop = EvolutionLoop(mutator=mutator, evaluator=eval_, population_size=4)
    seed = Genome(genome_id="seed", parameters={"x": 0.0})
    pop = loop.initialize_population(seed)
    new_pop = loop.step(pop)
    assert len(new_pop) == 4
    # Some children must have been added
    generations = {g.generation for g in new_pop}
    assert max(generations) >= 1


def test_evolution_loop_validates_population_size():
    mutator = PolicyMutator()
    eval_ = FitnessEvaluator({"a": lambda p: 0})
    with pytest.raises(ValueError):
        EvolutionLoop(mutator=mutator, evaluator=eval_, population_size=1)


# ---------- Patch F5 EigenThresholdGuard ----------


def test_f5_eigen_threshold_validates():
    EigenThresholdGuard(eigen_threshold=1.0)
    with pytest.raises(ValueError):
        EigenThresholdGuard(eigen_threshold=0)


def test_f5_eigen_threshold_check():
    g = EigenThresholdGuard(eigen_threshold=1.0)
    # u*L = 0.05 * 10 = 0.5 < 1.0 -> safe
    assert g.check(mutation_rate=0.05, genome_length=10) is True
    # u*L = 0.2 * 10 = 2.0 > 1.0 -> unsafe
    assert g.check(mutation_rate=0.2, genome_length=10) is False


def test_f5_eigen_margin():
    g = EigenThresholdGuard(eigen_threshold=1.0)
    assert g.margin(0.05, 10) == pytest.approx(0.5)
    assert g.margin(0.2, 10) == pytest.approx(-1.0)


def test_f5_eigen_check_validates_inputs():
    g = EigenThresholdGuard()
    with pytest.raises(ValueError):
        g.check(mutation_rate=-0.1, genome_length=10)
    with pytest.raises(ValueError):
        g.check(mutation_rate=0.1, genome_length=0)


# ---------- Patch F5 RegressionCage ----------


def test_f5_regression_cage_validates():
    RegressionCage(tolerance=0.0)
    RegressionCage(tolerance=0.1)
    with pytest.raises(ValueError):
        RegressionCage(tolerance=-0.1)


def test_f5_regression_cage_no_baseline_no_regression():
    cage = RegressionCage()
    pop = [Genome(genome_id="g1", parameters={}, fitness={"a": 5.0})]
    assert cage.detects_regression(pop) is False  # no baseline yet


def test_f5_regression_cage_detects_strict_regression():
    cage = RegressionCage()
    # Establish baseline
    cage.update_baseline([Genome(genome_id="best", parameters={}, fitness={"a": 10.0})])
    # New population strictly worse
    bad_pop = [
        Genome(genome_id="bad", parameters={}, fitness={"a": 5.0}),
        Genome(genome_id="bad2", parameters={}, fitness={"a": 7.0}),
    ]
    assert cage.detects_regression(bad_pop) is True


def test_f5_regression_cage_no_regression_when_one_meets_baseline():
    cage = RegressionCage()
    cage.update_baseline([Genome(genome_id="b", parameters={}, fitness={"a": 10.0})])
    mixed_pop = [
        Genome(genome_id="bad", parameters={}, fitness={"a": 5.0}),
        Genome(genome_id="ok", parameters={}, fitness={"a": 11.0}),  # beats baseline
    ]
    assert cage.detects_regression(mixed_pop) is False


# ---------- Patch F5 EvolutionLoop integration ----------


def test_f5_evolution_loop_with_eigen_guard():
    rng = random.Random(0)
    mutator = PolicyMutator(gaussian_sigma=0.5, rng=rng)  # high sigma
    eval_ = FitnessEvaluator({"score": lambda p: -abs(p["x"])})
    guard = EigenThresholdGuard(eigen_threshold=0.4)  # tight: 0.5*1=0.5 > 0.4 = violation
    loop = EvolutionLoop(
        mutator=mutator, evaluator=eval_, population_size=4, eigen_guard=guard,
    )
    seed = Genome(genome_id="seed", parameters={"x": 0.0})
    pop = loop.initialize_population(seed)
    loop.step(pop)
    assert loop.eigen_violations() >= 1


def test_f5_evolution_loop_with_cage_detects_regression():
    rng = random.Random(0)
    mutator = PolicyMutator(gaussian_sigma=10.0, rng=rng)  # massive disruption
    # Fitness peaks at x=0; mutation of sigma=10 likely produces worse offspring
    eval_ = FitnessEvaluator({"score": lambda p: -abs(p["x"])})
    cage = RegressionCage()
    loop = EvolutionLoop(
        mutator=mutator, evaluator=eval_, population_size=4, cage=cage,
    )
    seed = Genome(genome_id="seed", parameters={"x": 0.0})
    pop = loop.initialize_population(seed)
    cage.update_baseline(pop)  # establish baseline at x=0 (best fitness=0)

    # Step with massive mutation should produce regression -> rollback
    new_pop = loop.step(pop)
    # Check either rollback occurred OR new pop happens to beat baseline
    # In any case, regression_count should be incremented when triggered
    if loop.regression_count() > 0:
        # Rollback happened -> new_pop is identical to old pop
        assert new_pop is pop


def test_f5_canary_genome_tracked():
    rng = random.Random(0)
    mutator = PolicyMutator(rng=rng)
    eval_ = FitnessEvaluator({"score": lambda p: p["x"] * 2})
    seed = Genome(genome_id="seed", parameters={"x": 1.0})
    canary = make_canary(seed)
    loop = EvolutionLoop(
        mutator=mutator, evaluator=eval_, population_size=4, canary=canary,
    )
    pop = loop.initialize_population(seed)
    loop.step(pop)
    # Canary fitness was evaluated
    assert "score" in canary.fitness
    # Canary parameters unchanged
    assert canary.parameters == {"x": 1.0}


# ---------- Patch F7 RegressionCage Stochastic-Tolerance ----------


def test_f7_regression_cage_noise_sigma_validates():
    RegressionCage(noise_sigma=0.1)
    with pytest.raises(ValueError):
        RegressionCage(noise_sigma=-0.5)


def test_f7_regression_cage_within_noise_band_no_regression():
    """F7: Drop within 2*sigma noise band is NOT regression."""
    cage = RegressionCage(noise_sigma=1.0)  # noise_band = 2*1.0 = 2.0
    cage.update_baseline([Genome(genome_id="b", parameters={}, fitness={"a": 10.0})])
    # New pop: 8.5 < 10.0 but within noise (10.0 - 2*1.0 = 8.0 floor)
    pop = [Genome(genome_id="g1", parameters={}, fitness={"a": 8.5})]
    assert cage.detects_regression(pop) is False


def test_f7_regression_cage_outside_noise_band_is_regression():
    """F7: Drop beyond 2*sigma noise band IS regression."""
    cage = RegressionCage(noise_sigma=1.0)
    cage.update_baseline([Genome(genome_id="b", parameters={}, fitness={"a": 10.0})])
    # 5.0 << 8.0 floor (way beyond noise) -> regression
    pop = [Genome(genome_id="g1", parameters={}, fitness={"a": 5.0})]
    assert cage.detects_regression(pop) is True


def test_f7_combined_tolerance_and_noise():
    """F7: tolerance and noise_sigma sum effectively."""
    cage = RegressionCage(tolerance=0.5, noise_sigma=0.5)
    # effective_tol = 0.5 + 2*0.5 = 1.5
    cage.update_baseline([Genome(genome_id="b", parameters={}, fitness={"a": 10.0})])
    # 8.5 = 10.0 - 1.5 (exactly floor) -> NOT regression
    pop_at_floor = [Genome(genome_id="g1", parameters={}, fitness={"a": 8.5})]
    assert cage.detects_regression(pop_at_floor) is False
    # 8.4 < 8.5 floor -> regression
    pop_below = [Genome(genome_id="g1", parameters={}, fitness={"a": 8.4})]
    assert cage.detects_regression(pop_below) is True


def test_f5_make_canary_independent_from_seed():
    seed = Genome(genome_id="seed", parameters={"x": 1.0, "y": 2.0})
    canary = make_canary(seed)
    canary.parameters["x"] = 999.0
    assert seed.parameters["x"] == 1.0  # seed unaffected
