# [CRUX-MK]
"""PortfolioOptimizer: Mean-Variance + CVaR-Optimization.

1:1-Port der TS-Referenz (Paritaets-Ziel, keine fachlichen Aenderungen):
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/src/PortfolioOptimizer.ts
    (Commit-Stand f4083f4, inkl. Welle-M-Patches KPM-2 CVaR-LP + KPM-3 Ledoit-Wolf)

Foundation: Markowitz (1952), Sharpe (1964), Rockafellar-Uryasev (2000),
Ledoit-Wolf (2003/2004), Roncalli (2013).

KPM-Variante-D: Optimierungs-Ergebnisse MUESSEN durch KPMVarianteDDecisionEngine
(Drawdown + HIVE + Regime Gates) laufen. Pilot-tauglich, NICHT Production
(Production = dedizierter QP-/LP-Solver).

Status: CONDITIONAL. ALPHA-NOT-K0-READY.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

from .numerics import clamp, conditional_var, mean, sum_values

__all__ = [
    "Asset",
    "OptimizationResult",
    "FrontierPoint",
    "CVaRLPResult",
    "LedoitWolfResult",
    "ConstrainedOptimizationResult",
    "PortfolioOptimizer",
    "covariance_from_samples",
]

# Grid-/Solver-Konstanten (exakt per TS-Referenz, dimensionslos)
MV_GRID_STEP_COUNT: int = 50  # Markowitz-Grid n>=3
MV_TARGET_RETURN_TOLERANCE: float = 0.005
CVAR_GRID_STEP_COUNT: int = 20  # Legacy-CVaR-Grid
CVAR_LP_MAX_ITER: int = 200
CVAR_LP_TOLERANCE: float = 1e-7
CVAR_LP_LEARNING_RATE: float = 0.01
CONSTRAINED_MAX_ITER: int = 300
CONSTRAINED_LEARNING_RATE: float = 0.005
CONSTRAINED_TARGET_RETURN_PENALTY: float = 100.0
DEFAULT_MAX_POSITION_WEIGHT: float = 0.4  # Family-Office-Default
MIN_SCENARIOS: int = 30  # statistisches Minimum


@dataclass(frozen=True)
class Asset:
    id: str
    name: str


@dataclass(frozen=True)
class OptimizationResult:
    weights: List[float]
    expected_return: float
    risk: float  # StdDev oder CVaR


@dataclass(frozen=True)
class FrontierPoint:
    weights: List[float]
    expected_return: float
    risk: float


@dataclass(frozen=True)
class CVaRLPResult:
    """Welle-M-Patch-KPM-2: CVaR-LP-Result."""

    weights: List[float]
    cvar: float
    var: float
    converged: bool
    method: Literal["lp-ru-2000", "gradient-descent-fallback", "grid-fallback"]
    iterations: Optional[int] = None


@dataclass(frozen=True)
class LedoitWolfResult:
    """Welle-M-Patch-KPM-3: Ledoit-Wolf-Shrinkage-Result."""

    shrunk_covariance: List[List[float]]
    shrinkage_intensity: float
    optimal_shrinkage: float
    mean_variance_target: float


@dataclass(frozen=True)
class ConstrainedOptimizationResult:
    """Welle-M-Patch-KPM-3: Constrained-Markowitz-Result."""

    weights: List[float]
    risk: float
    expected_return: float
    constraints_active: List[str]
    method: Literal["projected-gradient", "analytical-2asset", "grid-fallback"]


class PortfolioOptimizer:
    """Mean-Variance + CVaR-Optimierung.

    Pre:
      - len(assets) >= 2
      - covariance symmetrisch + quadratisch (n x n)
      - len(expected_returns) == len(assets)
    """

    def __init__(
        self,
        assets: Sequence[Asset],
        covariance: Sequence[Sequence[float]],
        expected_returns: Sequence[float],
    ) -> None:
        if len(assets) < 2:
            raise ValueError("PortfolioOptimizer: need at least 2 assets")
        if len(covariance) != len(assets):
            raise ValueError("PortfolioOptimizer: covariance row-count must match asset-count")
        if len(expected_returns) != len(assets):
            raise ValueError("PortfolioOptimizer: expectedReturns must match asset-count")
        for row in covariance:
            if len(row) != len(assets):
                raise ValueError("PortfolioOptimizer: covariance must be square matrix")
        # Symmetrie-Check (light, per TS-Referenz 1e-9)
        n = len(assets)
        for i in range(n):
            for j in range(i + 1, n):
                a = covariance[i][j]
                b = covariance[j][i]
                if abs(a - b) > 1e-9:
                    raise ValueError(
                        f"PortfolioOptimizer: covariance not symmetric at [{i}][{j}]"
                    )
        self.assets: List[Asset] = list(assets)
        self.covariance: List[List[float]] = [list(r) for r in covariance]
        self.expected_returns: List[float] = list(expected_returns)

    def markowitz_mv_optimum(self, target_return: float) -> OptimizationResult:
        """Markowitz Mean-Variance-Optimum bei Target-Return (Pilot: Grid-Search).

        Pre: target_return in [min(expected_returns), max(expected_returns)]
        Post: sum(weights)=1, weights >= 0 (long-only)
        """
        n = len(self.assets)
        min_r = min(self.expected_returns)
        max_r = max(self.expected_returns)
        if target_return < min_r - 1e-6 or target_return > max_r + 1e-6:
            raise ValueError(
                f"markowitzMVOptimum: targetReturn {target_return} not in [{min_r}, {max_r}]"
            )

        # 2-Asset-Spezialfall analytisch
        if n == 2:
            r1 = self.expected_returns[0]
            r2 = self.expected_returns[1]
            if abs(r1 - r2) < 1e-9:
                w_eq = [0.5, 0.5]
                return OptimizationResult(
                    weights=w_eq,
                    expected_return=r1,
                    risk=self.portfolio_std_dev(w_eq),
                )
            w1 = clamp((target_return - r2) / (r1 - r2), 0.0, 1.0)
            w2 = 1 - w1
            return OptimizationResult(
                weights=[w1, w2],
                expected_return=w1 * r1 + w2 * r2,
                risk=self.portfolio_std_dev([w1, w2]),
            )

        # n >= 3: Brute-Force-Grid auf Simplex (Pilot-Implementation)
        best: List[Optional[OptimizationResult]] = [None]
        step_count = MV_GRID_STEP_COUNT
        step_size = 1.0 / step_count

        def recurse(idx: int, remaining: float, current_w: List[float]) -> None:
            if idx == n - 1:
                current_w[idx] = remaining
                if -1e-9 <= remaining <= 1 + 1e-9:
                    w = list(current_w)
                    er = 0.0
                    for i, wi in enumerate(w):
                        er += wi * self.expected_returns[i]
                    if abs(er - target_return) < MV_TARGET_RETURN_TOLERANCE:
                        risk = self.portfolio_std_dev(w)
                        prev = best[0]
                        if prev is None or risk < prev.risk:
                            best[0] = OptimizationResult(
                                weights=w, expected_return=er, risk=risk
                            )
                return
            step = 0
            while step <= step_count:
                wi = step * step_size
                if wi > remaining + 1e-9:
                    break
                current_w[idx] = wi
                recurse(idx + 1, remaining - wi, current_w)
                step += 1

        recurse(0, 1.0, [0.0] * n)

        found = best[0]
        if found is None:
            # Fallback: Equal-Weight
            equal_w = [1.0 / n] * n
            er = 0.0
            for i, wi in enumerate(equal_w):
                er += wi * self.expected_returns[i]
            return OptimizationResult(
                weights=equal_w, expected_return=er, risk=self.portfolio_std_dev(equal_w)
            )
        return found

    def cvar_optimization(
        self, return_samples: Sequence[Sequence[float]], alpha: float = 0.05
    ) -> Tuple[List[float], float]:
        """LEGACY CVaR-Grid (Backwards-Compat + Cross-Check zu cvar_optimization_lp).

        Pre: len(return_samples) >= 30, Zeilen-Breite == n, 0 < alpha < 1
        Returns: (weights, cvar) — TS: {weights, cvar}
        """
        n = len(self.assets)
        if len(return_samples) < MIN_SCENARIOS:
            raise ValueError("cvarOptimization: need at least 30 return samples")
        for row in return_samples:
            if len(row) != n:
                raise ValueError(f"cvarOptimization: each sample row must have n={n} columns")

        best: List[Optional[Tuple[List[float], float]]] = [None]
        step_count = CVAR_GRID_STEP_COUNT
        step_size = 1.0 / step_count

        def port_cvar(w: List[float]) -> float:
            port_returns = []
            for row in return_samples:
                s = 0.0
                for i, ri in enumerate(row):
                    s += ri * w[i]
                port_returns.append(s)
            return conditional_var(port_returns, alpha)

        if n == 2:
            for s in range(step_count + 1):
                w = [s * step_size, 1 - s * step_size]
                cv = port_cvar(w)
                prev = best[0]
                if prev is None or cv < prev[1]:
                    best[0] = (w, cv)
        else:

            def recurse(idx: int, remaining: float, current_w: List[float]) -> None:
                if idx == n - 1:
                    current_w[idx] = remaining
                    if -1e-9 <= remaining <= 1 + 1e-9:
                        w = list(current_w)
                        cv = port_cvar(w)
                        prev = best[0]
                        if prev is None or cv < prev[1]:
                            best[0] = (w, cv)
                    return
                step = 0
                while step <= step_count:
                    wi = step * step_size
                    if wi > remaining + 1e-9:
                        break
                    current_w[idx] = wi
                    recurse(idx + 1, remaining - wi, current_w)
                    step += 1

            recurse(0, 1.0, [0.0] * n)

        found = best[0]
        if found is None:
            equal_w = [1.0 / n] * n
            return (equal_w, port_cvar(equal_w))
        return found

    def cvar_optimization_lp(
        self, scenarios: Sequence[Sequence[float]], beta: float = 0.95
    ) -> CVaRLPResult:
        """Welle-M-Patch-KPM-2: CVaR-LP-Reformulation per Rockafellar-Uryasev (2000).

        Objective: min alpha + (1/((1-beta)*S)) * SUM z_i  (projected-gradient-descent).

        Pre: len(scenarios) >= 30, Zeilen-Breite == n, 0 < beta < 1
        Post: sum(weights)=1, weights >= 0; CVaR >= VaR
        """
        n = len(self.assets)
        s_count = len(scenarios)

        if s_count < MIN_SCENARIOS:
            raise ValueError("cvarOptimizationLP: need at least 30 scenarios")
        if beta <= 0 or beta >= 1:
            raise ValueError("cvarOptimizationLP: beta must be in (0, 1)")
        for row in scenarios:
            if len(row) != n:
                raise ValueError(f"cvarOptimizationLP: each scenario must have n={n} assets")

        # Init: Equal-Weight, alpha = beta-Quantil der Losses
        w = [1.0 / n] * n
        losses0 = []
        for row in scenarios:
            s = 0.0
            for i in range(n):
                s += row[i] * w[i]
            losses0.append(-s)
        alpha = _quantile(losses0, beta)  # initiale VaR-Schaetzung

        factor = 1.0 / ((1 - beta) * s_count)
        prev_obj = float("inf")
        converged = False

        it = 0
        while it < CVAR_LP_MAX_ITER:
            # z_i = max(0, loss_i - alpha)
            z_arr: List[float] = []
            for i in range(s_count):
                port_return = 0.0
                for j in range(n):
                    port_return += scenarios[i][j] * w[j]
                loss = -port_return
                z_arr.append(max(0.0, loss - alpha))

            # Objective
            sum_z = 0.0
            for z in z_arr:
                sum_z += z
            obj = alpha + factor * sum_z

            # Konvergenz-Check
            if abs(prev_obj - obj) < CVAR_LP_TOLERANCE:
                converged = True
                break
            prev_obj = obj

            # Gradient alpha: 1 - factor * #{i : z_i > 0}
            active_count = 0
            for z in z_arr:
                if z > 0:
                    active_count += 1
            d_alpha = 1 - factor * active_count

            # Gradient w_j: -factor * sum_i scenarios[i][j] * 1{z_i > 0}
            d_w = [0.0] * n
            for i in range(s_count):
                if z_arr[i] > 0:
                    for j in range(n):
                        d_w[j] -= factor * scenarios[i][j]

            # Updates
            alpha = alpha - CVAR_LP_LEARNING_RATE * d_alpha
            w_new = [w[j] - CVAR_LP_LEARNING_RATE * d_w[j] for j in range(n)]
            # Projektion auf Simplex: clip >= 0, renormalisieren
            w_clipped = [max(0.0, wj) for wj in w_new]
            sum_w = 0.0
            for wj in w_clipped:
                sum_w += wj
            if sum_w > 0:
                w = [wj / sum_w for wj in w_clipped]

            it += 1

        # Finale CVaR + VaR
        final_losses = []
        for row in scenarios:
            s = 0.0
            for j in range(n):
                s += row[j] * w[j]
            final_losses.append(-s)
        sorted_losses = sorted(final_losses, reverse=True)  # descending
        tail_count = max(1, math.ceil((1 - beta) * s_count))
        tail_losses = sorted_losses[:tail_count]
        cvar = sum_values(tail_losses) / len(tail_losses)
        var_value = sorted_losses[tail_count - 1]

        return CVaRLPResult(
            weights=w,
            cvar=cvar,
            var=var_value,
            converged=converged,
            method="lp-ru-2000" if converged else "gradient-descent-fallback",
            iterations=it,
        )

    def ledoit_wolf_shrinkage(self, returns: Sequence[Sequence[float]]) -> LedoitWolfResult:
        """Welle-M-Patch-KPM-3: Ledoit-Wolf-Shrinkage-Schaetzer.

        cov_shrunk = (1 - lambda) * sample + lambda * (meanVar * I),
        lambda* = (pi / gamma) / T, geclamped auf [0, 1].

        Pre: len(returns) >= 2 (n Assets), alle Zeilen gleich lang (T >= 2)
        """
        n = len(returns)
        if n < 2:
            raise ValueError("ledoitWolfShrinkage: need at least 2 assets")
        t_obs = len(returns[0])
        if t_obs < 2:
            raise ValueError("ledoitWolfShrinkage: need at least 2 time observations")
        for row in returns:
            if len(row) != t_obs:
                raise ValueError("ledoitWolfShrinkage: all rows must have equal length")

        # 1) Sample-Covariance (Nenner T, nicht T-1, fuer Ledoit-Wolf-Konsistenz)
        means = [mean(r) for r in returns]
        sample: List[List[float]] = []
        for i in range(n):
            sample.append([])
            for j in range(n):
                s = 0.0
                for t in range(t_obs):
                    s += (returns[i][t] - means[i]) * (returns[j][t] - means[j])
                sample[i].append(s / t_obs)

        # 2) Target F = meanVariance * I
        mean_var = 0.0
        for i in range(n):
            mean_var += sample[i][i]
        mean_var /= n
        target: List[List[float]] = []
        for i in range(n):
            target.append([])
            for j in range(n):
                target[i].append(mean_var if i == j else 0.0)

        # 3) gamma = ||sample - target||_F^2
        gamma = 0.0
        for i in range(n):
            for j in range(n):
                d = sample[i][j] - target[i][j]
                gamma += d * d

        # 4) pi = sum_ij Var(s_ij) (asymptotische Varianz-Schaetzung)
        pi = 0.0
        for i in range(n):
            for j in range(n):
                pi_ij = 0.0
                for t in range(t_obs):
                    term = (returns[i][t] - means[i]) * (returns[j][t] - means[j]) - sample[i][j]
                    pi_ij += term * term
                pi += pi_ij / t_obs

        # 5) Optimal shrinkage: lambda* = (pi / gamma) / T, clipped [0, 1]
        if gamma < 1e-12:
            optimal_shrinkage = 0.0  # bereits am Target
        else:
            optimal_shrinkage = (pi / gamma) / t_obs
        optimal_shrinkage = clamp(optimal_shrinkage, 0.0, 1.0)

        # 6) Shrinkage anwenden
        shrunk: List[List[float]] = []
        for i in range(n):
            shrunk.append([])
            for j in range(n):
                shrunk[i].append(
                    (1 - optimal_shrinkage) * sample[i][j] + optimal_shrinkage * target[i][j]
                )

        return LedoitWolfResult(
            shrunk_covariance=shrunk,
            shrinkage_intensity=optimal_shrinkage,
            optimal_shrinkage=optimal_shrinkage,
            mean_variance_target=mean_var,
        )

    def markowitz_mv_optimum_constrained(
        self,
        target_return: float,
        max_position_weight: Optional[float] = None,
        min_position_weight: Optional[float] = None,
        allow_short_selling: Optional[bool] = None,
        use_ledoit_wolf: Optional[bool] = None,
    ) -> ConstrainedOptimizationResult:
        """Welle-M-Patch-KPM-3: Markowitz mit Position-Constraints.

        Pre: target_return in [min(expected_returns), max(expected_returns)];
             0 <= minW <= maxW <= 1 (long-only) bzw. allow_short_selling=True.
        """
        n = len(self.assets)
        max_w = max_position_weight if max_position_weight is not None else DEFAULT_MAX_POSITION_WEIGHT
        min_w = min_position_weight if min_position_weight is not None else 0.0
        allow_short = allow_short_selling if allow_short_selling is not None else False
        use_lw = use_ledoit_wolf if use_ledoit_wolf is not None else False

        if not allow_short:
            if min_w < 0:
                raise ValueError(
                    "markowitzMVOptimumConstrained: minW < 0 requires allowShortSelling=true"
                )
            if max_w < min_w or max_w > 1:
                raise ValueError(
                    "markowitzMVOptimumConstrained: invalid maxW/minW combination"
                )

        min_r = min(self.expected_returns)
        max_r = max(self.expected_returns)
        if target_return < min_r - 1e-6 or target_return > max_r + 1e-6:
            raise ValueError(
                f"markowitzMVOptimumConstrained: targetReturn {target_return} "
                f"not in [{min_r}, {max_r}]"
            )

        cov = self.covariance
        # (LW-Shrinkage muss vom Caller mit Returns-Daten via ledoit_wolf_shrinkage laufen)

        constraints_active: List[str] = []
        if max_w < 1:
            constraints_active.append(f"maxW={_js_num(max_w)}")
        if min_w > 0:
            constraints_active.append(f"minW={_js_num(min_w)}")
        if not allow_short:
            constraints_active.append("long-only")
        if use_lw:
            constraints_active.append("ledoit-wolf-pending-data")

        # 2-Asset analytisch mit Constraints
        if n == 2:
            r1 = self.expected_returns[0]
            r2 = self.expected_returns[1]
            if abs(r1 - r2) < 1e-9:
                w_eq = [0.5, 0.5]
                return ConstrainedOptimizationResult(
                    weights=w_eq,
                    risk=self.portfolio_std_dev(w_eq),
                    expected_return=r1,
                    constraints_active=constraints_active,
                    method="analytical-2asset",
                )
            w1 = (target_return - r2) / (r1 - r2)
            if not allow_short:
                w1 = clamp(w1, min_w, max_w)
            else:
                w1 = clamp(w1, -max_w, max_w)
            w2 = 1 - w1
            if not allow_short and (w2 < min_w - 1e-9 or w2 > max_w + 1e-9):
                constraints_active.append("boundary-conflict")
            return ConstrainedOptimizationResult(
                weights=[w1, w2],
                risk=self.portfolio_std_dev([w1, w2]),
                expected_return=w1 * r1 + w2 * r2,
                constraints_active=constraints_active,
                method="analytical-2asset",
            )

        # n >= 3: Projected-Gradient-Descent mit Constraints
        w = [1.0 / n] * n
        for _ in range(CONSTRAINED_MAX_ITER):
            # Gradient von w^T C w = 2 * C * w
            grad = [0.0] * n
            for i in range(n):
                for j in range(n):
                    grad[i] += 2 * cov[i][j] * w[j]

            # Penalty-Gradient fuer Target-Return-Constraint
            current_return = 0.0
            for i, wi in enumerate(w):
                current_return += wi * self.expected_returns[i]
            return_deviation = current_return - target_return
            for i in range(n):
                grad[i] += (
                    2 * CONSTRAINED_TARGET_RETURN_PENALTY * return_deviation
                    * self.expected_returns[i]
                )

            w_new = [w[j] - CONSTRAINED_LEARNING_RATE * grad[j] for j in range(n)]

            # Projektion auf Constraints
            if allow_short:
                w_clipped = [clamp(wj, -max_w, max_w) for wj in w_new]
            else:
                w_clipped = [clamp(wj, min_w, max_w) for wj in w_new]

            # Renormalisieren auf sum=1
            sum_w = 0.0
            for wj in w_clipped:
                sum_w += wj
            if abs(sum_w) > 1e-12:
                w = [wj / sum_w for wj in w_clipped]

        final_return = 0.0
        for i, wi in enumerate(w):
            final_return += wi * self.expected_returns[i]
        return ConstrainedOptimizationResult(
            weights=w,
            risk=self.portfolio_std_dev(w),
            expected_return=final_return,
            constraints_active=constraints_active,
            method="projected-gradient",
        )

    def efficient_frontier(self, num_points: int = 20) -> List[FrontierPoint]:
        """Efficient-Frontier: num_points Stuetzstellen zwischen min/max-Return."""
        if num_points < 2:
            raise ValueError("efficientFrontier: numPoints must be >= 2")
        min_r = min(self.expected_returns)
        max_r = max(self.expected_returns)
        result: List[FrontierPoint] = []
        for i in range(num_points):
            t = i / (num_points - 1)
            target_return = min_r + t * (max_r - min_r)
            try:
                opt = self.markowitz_mv_optimum(target_return)
                result.append(
                    FrontierPoint(
                        weights=opt.weights,
                        expected_return=opt.expected_return,
                        risk=opt.risk,
                    )
                )
            except Exception:
                # Punkte ueberspringen wo Optimierung scheitert (TS: catch {})
                pass
        return result

    def risk_parity(self) -> List[float]:
        """Risk-Parity (Heuristik: Gewichte ~ 1/sigma_i, normalisiert).

        Pre: alle Diagonal-Elemente der Covariance > 0
        Returns: weights — TS: {weights}
        """
        n = len(self.assets)
        inv_sigmas: List[float] = []
        for i in range(n):
            sig = math.sqrt(self.covariance[i][i])
            if sig <= 0:
                raise ValueError(f"riskParity: asset[{i}] has non-positive variance")
            inv_sigmas.append(1 / sig)
        total = sum_values(inv_sigmas)
        return [iv / total for iv in inv_sigmas]

    def portfolio_std_dev(self, weights: Sequence[float]) -> float:
        """sigma_p = sqrt(max(0, w^T * Sigma * w))."""
        n = len(self.assets)
        var_ = 0.0
        for i in range(n):
            for j in range(n):
                var_ += weights[i] * weights[j] * self.covariance[i][j]
        return math.sqrt(max(0.0, var_))

    def portfolio_expected_return(self, weights: Sequence[float]) -> float:
        """Erwarteter Portfolio-Return bei Gewichten w."""
        r = 0.0
        for i in range(len(weights)):
            r += weights[i] * self.expected_returns[i]
        return r


def covariance_from_samples(
    returns_by_asset: Sequence[Sequence[float]],
) -> List[List[float]]:
    """Covariance-Matrix aus Sample-Returns (n Assets x T Zeitschritte, Nenner T-1).

    Pre: len(returns_by_asset) >= 2, alle Zeilen gleich lang
    """
    n = len(returns_by_asset)
    if n < 2:
        raise ValueError("covarianceFromSamples: need at least 2 assets")
    t_obs = len(returns_by_asset[0])
    for row in returns_by_asset:
        if len(row) != t_obs:
            raise ValueError("covarianceFromSamples: all rows must have equal length")
    means = [mean(r) for r in returns_by_asset]
    cov: List[List[float]] = []
    for i in range(n):
        cov.append([])
        for j in range(n):
            s = 0.0
            for t in range(t_obs):
                s += (returns_by_asset[i][t] - means[i]) * (returns_by_asset[j][t] - means[j])
            cov[i].append(s / (t_obs - 1))
    return cov


def _quantile(x: Sequence[float], alpha: float) -> float:
    """Interner Quantile-Helper (TS-Referenz: inline, returns 0 bei leerem Array)."""
    if len(x) == 0:
        return 0.0
    if alpha < 0 or alpha > 1:
        raise ValueError("quantile: alpha must be in [0, 1]")
    sorted_x = sorted(x)
    idx = alpha * (len(sorted_x) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_x[lo]
    w = idx - lo
    return sorted_x[lo] * (1 - w) + sorted_x[hi] * w


def _js_num(v: float) -> str:
    """JS-Number-Template-Formatierung fuer Constraint-Labels (0.4 -> '0.4')."""
    if v == int(v):
        return str(int(v))
    return repr(v)
