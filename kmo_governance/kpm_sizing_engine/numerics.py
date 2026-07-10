# [CRUX-MK]
"""Numerics: statistische Helfer fuer Sizing-Mathematik (Python-Port).

1:1-Port der TS-Referenz (Paritaets-Ziel, keine fachlichen Aenderungen):
    ~/Projects/heylou-v10-foundation/packages/kpm-sizing/src/numerics.ts
    (Commit-Stand f4083f4)

Foundation:
- Sharpe (1966): Sharpe-Ratio
- Young (1991): Calmar-Ratio
- Jorion (1996): Value at Risk
- Rockafellar-Uryasev (2000): Conditional VaR

KPM-Kontext per ~/.claude/rules/kpm-sizing.md. ALPHA-NOT-K0-READY.
Reine Sizing-Mathematik: KEIN Broker-Zugang, KEIN Echtgeld, keine Order-Ausfuehrung.

Hinweis Float-Paritaet: Akkumulation erfolgt wie in der TS-Referenz als
Links-nach-rechts-Summation (keine fsum/Kahan), damit IEEE-754-double-Ergebnisse
bitkompatibel zur Node-Ausfuehrung bleiben.
"""

from __future__ import annotations

import math
from typing import Sequence

__all__ = [
    "mean",
    "variance",
    "std_dev",
    "correlation",
    "quantile",
    "geometric_mean",
    "max_drawdown",
    "sharpe_ratio",
    "calmar_ratio",
    "value_at_risk",
    "conditional_var",
    "sum_values",
    "clamp",
    "CALMAR_NO_DRAWDOWN_CAP",
]

# Cap statt +Infinity wenn Max-Drawdown = 0 (dimensionslos, per TS-Referenz)
CALMAR_NO_DRAWDOWN_CAP: float = 1000.0


def mean(x: Sequence[float]) -> float:
    """Arithmetisches Mittel.

    Pre: len(x) > 0
    Post: returns sum(x) / len(x)
    """
    if len(x) == 0:
        raise ValueError("mean: empty array")
    s = 0.0
    for v in x:
        s += v
    return s / len(x)


def variance(x: Sequence[float]) -> float:
    """Stichproben-Varianz (n-1-Nenner).

    Pre: len(x) >= 2
    Post: returns SUM((x_i - mu)^2) / (n - 1) >= 0
    """
    if len(x) < 2:
        raise ValueError("variance: need at least 2 samples")
    mu = mean(x)
    s = 0.0
    for v in x:
        d = v - mu
        s += d * d
    return s / (len(x) - 1)


def std_dev(x: Sequence[float]) -> float:
    """Stichproben-Standardabweichung."""
    return math.sqrt(variance(x))


def correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Pearson-Korrelationskoeffizient.

    Pre: len(x) == len(y), len(x) >= 2
    Post: -1 <= rho <= 1
    """
    if len(x) != len(y):
        raise ValueError("correlation: arrays must have equal length")
    if len(x) < 2:
        raise ValueError("correlation: need at least 2 samples")
    mx = mean(x)
    my = mean(y)
    num = 0.0
    dx2 = 0.0
    dy2 = 0.0
    for i in range(len(x)):
        dx = x[i] - mx
        dy = y[i] - my
        num += dx * dy
        dx2 += dx * dx
        dy2 += dy * dy
    denom = math.sqrt(dx2 * dy2)
    if denom == 0:
        return 0.0
    return num / denom


def quantile(x: Sequence[float], alpha: float) -> float:
    """Empirisches Quantil via linearer Interpolation.

    Pre: 0 <= alpha <= 1, len(x) >= 1
    Post: returns interpoliertes Quantil
    """
    if len(x) == 0:
        raise ValueError("quantile: empty array")
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


def geometric_mean(returns: Sequence[float]) -> float:
    """Geometrisches Mittel von Returns (dezimal, z.B. 0.05 = +5%).

    Pre: len(returns) > 0, alle (1 + r_i) > 0
    Post: returns geometric-mean - 1 (compounded period return)
    """
    if len(returns) == 0:
        raise ValueError("geometricMean: empty array")
    log_sum = 0.0
    for r in returns:
        if 1 + r <= 0:
            raise ValueError("geometricMean: (1+r) must be > 0 for log")
        log_sum += math.log(1 + r)
    return math.exp(log_sum / len(returns)) - 1


def max_drawdown(equity: Sequence[float]) -> float:
    """Maximum Drawdown (Peak-to-Trough).

    Pre: len(equity) > 0, alle Werte > 0
    Post: 0 <= drawdown <= 1 (dezimal, z.B. 0.20 = 20%)
    """
    if len(equity) == 0:
        raise ValueError("maxDrawdown: empty array")
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def sharpe_ratio(returns: Sequence[float], risk_free_rate: float = 0.0) -> float:
    """Sharpe-Ratio: SR = (mean(r) - r_f) / stddev(r). NICHT annualisiert.

    Pre: len(returns) >= 2
    Post: returns endliche Sharpe-Ratio (oder 0 wenn stddev = 0)
    """
    if len(returns) < 2:
        raise ValueError("sharpeRatio: need at least 2 returns")
    sigma = std_dev(returns)
    if sigma == 0:
        return 0.0
    return (mean(returns) - risk_free_rate) / sigma


def calmar_ratio(returns: Sequence[float], period: float = 12) -> float:
    """Calmar-Ratio (annualisierter Return / Max-Drawdown), per Young (1991).

    Pre: len(returns) >= 2, period > 0
    Post: returns Calmar (oder CALMAR_NO_DRAWDOWN_CAP wenn Max-DD = 0)
    """
    if len(returns) < 2:
        raise ValueError("calmarRatio: need at least 2 returns")
    if period <= 0:
        raise ValueError("calmarRatio: period must be > 0")
    # Equity-Kurve aus Returns, Start bei 1.0
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    max_dd = max_drawdown(equity)
    # Annualisierter Return
    total_return = equity[-1] - 1
    years = len(returns) / period
    annualized = math.pow(1 + total_return, 1 / years) - 1 if years > 0 else total_return
    if max_dd == 0:
        # Kein Drawdown - extrem hoher Calmar - Cap gegen Infinity
        return CALMAR_NO_DRAWDOWN_CAP
    return annualized / max_dd


def value_at_risk(returns: Sequence[float], alpha: float = 0.05) -> float:
    """Value at Risk (historisch, single-period), als POSITIVER Verlust.

    Pre: len(returns) > 0, 0 < alpha < 1
    Post: returns >= 0
    """
    if len(returns) == 0:
        raise ValueError("valueAtRisk: empty array")
    if alpha <= 0 or alpha >= 1:
        raise ValueError("valueAtRisk: alpha must be in (0, 1)")
    q = quantile(returns, alpha)
    return max(0.0, -q)


def conditional_var(returns: Sequence[float], alpha: float = 0.05) -> float:
    """Conditional VaR (Expected Shortfall), per Rockafellar-Uryasev (2000).

    Pre: len(returns) > 0, 0 < alpha < 1
    Post: CVaR >= VaR >= 0
    """
    if len(returns) == 0:
        raise ValueError("conditionalVaR: empty array")
    if alpha <= 0 or alpha >= 1:
        raise ValueError("conditionalVaR: alpha must be in (0, 1)")
    var_ = value_at_risk(returns, alpha)
    tail_losses = []
    for r in returns:
        if r <= -var_:
            tail_losses.append(-r)  # positive Verluste
    if len(tail_losses) == 0:
        return var_
    return mean(tail_losses)


def sum_values(x: Sequence[float]) -> float:
    """Summe eines Arrays (links-nach-rechts, TS-paritaetisch)."""
    s = 0.0
    for v in x:
        s += v
    return s


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp value auf [lo, hi]."""
    return max(lo, min(hi, v))
