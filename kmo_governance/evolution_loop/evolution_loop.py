"""KMO evolution_loop [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.3 + Patch F5 (Welle-9-delta-Cross-LLM Finding #1).

Bio-Aequivalent: Directed Evolution (Frances Arnold, Nobel 2018). Variation + Selektion
+ Amplifikation in Schleifen, mit Eigen-Threshold (u*L < ln(sigma_max)) gegen
Error-Catastrophe in Quasi-Spezies.

Anorg-Mapping: A-25 Genetic-Algorithm (auf Policy-Layer, nicht Code-Layer).

Komponenten (Patch-F5-Vollausbau):
  - Genome: dataclass repraesentiert eine Policy-Variante
  - PolicyMutator: Variation (Gaussian-Noise + Discrete-Flip + Swap)
  - FitnessEvaluator: Multi-Objective Pareto (rho, conversion, Q_0, L_Martin)
  - GenerationArchive: Genealogy-Tracker
  - EigenThresholdGuard: prueft u*L < threshold gegen Quasi-Spezies-Erosion
  - RegressionCage: Safety-Bounds gegen Catastrophic-Forgetting
  - CanaryGenome: konstanter Baseline-Genome zur Drift-Detection
  - EvolutionLoop: step() mit Pareto-Rollback bei Regression
"""

from __future__ import annotations

import math
import random
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------- Genome ----------

@dataclass
class Genome:
    """One policy-variant in the evolution loop.

    Pre: parameters is dict with float values (Gaussian-mutable)
    Post: mutable; can be cloned + mutated
    """

    genome_id: str
    parameters: dict[str, float]
    fitness: dict[str, float] = field(default_factory=dict)
    generation: int = 0
    parent_id: Optional[str] = None

    def clone(self, new_id: str) -> "Genome":
        return Genome(
            genome_id=new_id,
            parameters=dict(self.parameters),
            generation=self.generation + 1,
            parent_id=self.genome_id,
        )


# ---------- PolicyMutator ----------

class PolicyMutator:
    """Apply variation operators to a Genome.

    Pre: gaussian_sigma > 0
    Post: mutate(genome) returns new Genome with mutations applied
    """

    def __init__(
        self,
        gaussian_sigma: float = 0.1,
        flip_probability: float = 0.05,
        swap_probability: float = 0.05,
        rng: Optional[random.Random] = None,
    ) -> None:
        if gaussian_sigma <= 0:
            raise ValueError("gaussian_sigma must be > 0")
        self.gaussian_sigma = float(gaussian_sigma)
        self.flip_probability = float(flip_probability)
        self.swap_probability = float(swap_probability)
        self._rng = rng or random.Random()

    def mutate(self, genome: Genome, new_id: str) -> Genome:
        """Apply Gaussian-noise + flip + swap operators."""
        offspring = genome.clone(new_id=new_id)
        # Gaussian-noise on each parameter
        for key in offspring.parameters:
            noise = self._rng.gauss(0.0, self.gaussian_sigma)
            offspring.parameters[key] += noise
        # Discrete-flip: randomly negate parameters
        if self._rng.random() < self.flip_probability:
            keys = list(offspring.parameters.keys())
            if keys:
                k = self._rng.choice(keys)
                offspring.parameters[k] = -offspring.parameters[k]
        # Swap: swap two parameter-values
        if self._rng.random() < self.swap_probability:
            keys = list(offspring.parameters.keys())
            if len(keys) >= 2:
                k1, k2 = self._rng.sample(keys, 2)
                offspring.parameters[k1], offspring.parameters[k2] = (
                    offspring.parameters[k2],
                    offspring.parameters[k1],
                )
        return offspring


# ---------- FitnessEvaluator ----------

class FitnessEvaluator:
    """Multi-Objective Pareto-Selektion.

    Pre: objective_funcs is non-empty dict {name: callable(params) -> float}
    Post: evaluate(genome) populates genome.fitness; pareto_front(pop) returns front
    """

    def __init__(self, objective_funcs: dict[str, Callable[[dict], float]]) -> None:
        if not objective_funcs:
            raise ValueError("at least one objective required")
        self.objective_funcs = dict(objective_funcs)

    def evaluate(self, genome: Genome) -> Genome:
        """Compute all objectives for genome.parameters."""
        for name, func in self.objective_funcs.items():
            genome.fitness[name] = float(func(genome.parameters))
        return genome

    def dominates(self, a: Genome, b: Genome) -> bool:
        """True if a Pareto-dominates b (all objectives a>=b, at least one >)."""
        if not a.fitness or not b.fitness:
            return False
        all_geq = all(a.fitness[k] >= b.fitness[k] for k in self.objective_funcs)
        any_gt = any(a.fitness[k] > b.fitness[k] for k in self.objective_funcs)
        return all_geq and any_gt

    def pareto_front(self, population: list[Genome]) -> list[Genome]:
        """Return Pareto-non-dominated genomes."""
        front: list[Genome] = []
        for g in population:
            if any(self.dominates(other, g) for other in population if other is not g):
                continue
            front.append(g)
        return front


# ---------- GenerationArchive ----------

class GenerationArchive:
    """Genealogy-Tracker fuer alle Generationen."""

    def __init__(self) -> None:
        self._archive: dict[int, list[Genome]] = {}
        self._lock = threading.RLock()

    def add(self, genome: Genome) -> None:
        with self._lock:
            self._archive.setdefault(genome.generation, []).append(genome)

    def generation(self, gen: int) -> list[Genome]:
        with self._lock:
            return list(self._archive.get(gen, []))

    def latest_generation(self) -> int:
        with self._lock:
            return max(self._archive.keys()) if self._archive else -1

    def __len__(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._archive.values())


# ---------- Patch F5: EigenThresholdGuard ----------

class EigenThresholdGuard:
    """Patch F5 (Welle-9-delta Cross-LLM Finding #1): Eigen-Threshold-Guard.

    Prevents quasi-species error-catastrophe. The Eigen-Threshold (u * L < ln(sigma)),
    where u = mutation-rate-per-locus, L = genome-length, sigma = max-fitness-ratio,
    bounds the maximum tolerable mutation-rate before genetic information erodes.

    If u * L > eigen_threshold: mutation rate is too high, signal info-erosion-risk.
    """

    def __init__(self, eigen_threshold: float = 1.0) -> None:
        if eigen_threshold <= 0:
            raise ValueError("eigen_threshold must be > 0")
        self.eigen_threshold = float(eigen_threshold)

    def check(self, mutation_rate: float, genome_length: int) -> bool:
        """True if mutation-rate*genome-length is within Eigen-bound (safe)."""
        if mutation_rate < 0 or genome_length <= 0:
            raise ValueError("mutation_rate >= 0 and genome_length > 0 required")
        return (mutation_rate * genome_length) < self.eigen_threshold

    def margin(self, mutation_rate: float, genome_length: int) -> float:
        """How far below threshold we are. Negative = beyond threshold."""
        return self.eigen_threshold - (mutation_rate * genome_length)


# ---------- Patch F5: RegressionCage ----------

class RegressionCage:
    """Patch F5: Safety-Bounds against Pareto-regression / Catastrophic-Forgetting.

    Records best-so-far fitness per objective. Rejects new generations whose
    Pareto-front is strictly dominated by the cage-baseline.
    """

    def __init__(
        self,
        tolerance: float = 0.0,
        noise_sigma: float = 0.0,
    ) -> None:
        """Patch F7 (Gemini-V2 Finding "Stochastic-Noise Sensitivity"):
        noise_sigma allows soft-Pareto-Comparison against expected measurement noise.
        With noise_sigma > 0, regression-detection requires the new generation
        to be worse than baseline by MORE than 2*sigma (95%-noise-band).
        """
        if tolerance < 0:
            raise ValueError("tolerance must be >= 0")
        if noise_sigma < 0:
            raise ValueError("noise_sigma must be >= 0")
        self.tolerance = float(tolerance)
        self.noise_sigma = float(noise_sigma)
        self._best_fitness: dict[str, float] = {}
        self._lock = threading.RLock()

    def update_baseline(self, genomes: list[Genome]) -> None:
        """Update best-so-far per objective from a population."""
        with self._lock:
            for g in genomes:
                for k, v in g.fitness.items():
                    cur = self._best_fitness.get(k, float("-inf"))
                    if v > cur:
                        self._best_fitness[k] = v

    def baseline(self) -> dict[str, float]:
        with self._lock:
            return dict(self._best_fitness)

    def detects_regression(self, new_population: list[Genome]) -> bool:
        """True if entire new population is strictly worse than baseline.

        Patch F7: noise_sigma erlaubt 2-sigma-Toleranz gegen Mess-Rauschen
        (verhindert unnoetige Rollbacks bei verrauschten Fitness-Metriken).
        """
        with self._lock:
            if not self._best_fitness:
                return False  # no baseline yet
            # Patch F7: effective tolerance = static + 2*sigma noise-band
            effective_tol = self.tolerance + 2.0 * self.noise_sigma
            for g in new_population:
                # Any genome that meets-or-beats baseline (within tolerance) on
                # ALL objectives -> no regression
                ok = all(
                    g.fitness.get(k, float("-inf")) >= (v - effective_tol)
                    for k, v in self._best_fitness.items()
                )
                if ok:
                    return False
            return True


# ---------- Patch F5: CanaryGenome (helper) ----------

def make_canary(seed: Genome, suffix: str = "canary") -> Genome:
    """Create a non-mutated canary based on seed (frozen baseline)."""
    canary = Genome(
        genome_id=f"{seed.genome_id}-{suffix}",
        parameters=dict(seed.parameters),
        fitness=dict(seed.fitness),
        generation=seed.generation,
        parent_id=None,
    )
    return canary


# ---------- EvolutionLoop ----------

class EvolutionLoop:
    """Top-Level: Variation + Selektion + Amplifikation in Schleife.

    Patch F5 expansions over SKELETON:
    - eigen_guard: optional EigenThresholdGuard validates u*L bound
    - cage: optional RegressionCage detects catastrophic-forgetting
    - canary: optional Genome NEVER mutated, fitness tracked across generations
    - step() rolls back to previous population if cage detects regression
    """

    def __init__(
        self,
        mutator: PolicyMutator,
        evaluator: FitnessEvaluator,
        archive: Optional[GenerationArchive] = None,
        population_size: int = 10,
        eigen_guard: Optional[EigenThresholdGuard] = None,
        cage: Optional[RegressionCage] = None,
        canary: Optional[Genome] = None,
    ) -> None:
        if population_size < 2:
            raise ValueError("population_size must be >= 2")
        self.mutator = mutator
        self.evaluator = evaluator
        self.archive = archive or GenerationArchive()
        self.population_size = int(population_size)
        # Patch F5
        self.eigen_guard = eigen_guard
        self.cage = cage
        self.canary = canary
        self._regression_count: int = 0
        self._eigen_violations: int = 0

    def initialize_population(self, seed: Genome) -> list[Genome]:
        """Generate initial population from a single seed-genome."""
        population: list[Genome] = [seed]
        self.archive.add(seed)
        for i in range(1, self.population_size):
            child = self.mutator.mutate(seed, new_id=f"{seed.genome_id}-init{i}")
            population.append(child)
            self.archive.add(child)
        return [self.evaluator.evaluate(g) for g in population]

    def step(self, population: list[Genome]) -> list[Genome]:
        """One evolution-step: variation + selection. Returns new population.

        Patch F5: includes Eigen-guard check + cage rollback on regression.
        """
        # Patch F5: Eigen-threshold check (information-erosion warning)
        if self.eigen_guard is not None and population:
            sample_len = len(population[0].parameters) or 1
            if not self.eigen_guard.check(self.mutator.gaussian_sigma, sample_len):
                self._eigen_violations += 1
                # Continue but record — caller can read .eigen_violations()
        # Pareto-front survives
        front = self.evaluator.pareto_front(population)
        if not front:
            front = list(population[:1])  # safety: keep at least one
        # Fill back to population_size via mutation of front
        new_pop = list(front)
        rng = self.mutator._rng
        i = 0
        while len(new_pop) < self.population_size:
            parent = rng.choice(front)
            child = self.mutator.mutate(
                parent,
                new_id=f"{parent.genome_id}-g{parent.generation+1}-c{i}",
            )
            self.evaluator.evaluate(child)
            self.archive.add(child)
            new_pop.append(child)
            i += 1
        # Patch F5: Canary tracking — re-evaluate canary fitness without mutation
        if self.canary is not None:
            self.evaluator.evaluate(self.canary)
        # Patch F5: Cage regression-check (rollback to previous population)
        if self.cage is not None:
            if self.cage.detects_regression(new_pop):
                self._regression_count += 1
                # Rollback: keep previous population
                return population
            self.cage.update_baseline(new_pop)
        return new_pop

    def regression_count(self) -> int:
        """Patch F5: number of cage-rollbacks since loop creation."""
        return self._regression_count

    def eigen_violations(self) -> int:
        """Patch F5: number of Eigen-threshold violations observed."""
        return self._eigen_violations


# CRUX-MK
