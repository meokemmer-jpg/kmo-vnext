# [CRUX-MK]
"""Fixture-Paritaets-Tests: Python-Port vs TS-Referenz (@heylou/kpm-sizing).

Erwartungswerte in fixtures/parity_cases.json wurden per Node/tsx DIREKT gegen
die TS-Referenz gerechnet (~/Projects/heylou-v10-foundation/packages/kpm-sizing/src,
Commit f4083f4). Paritaets-Kriterium: |diff| < 1e-6 (6 Nachkommastellen) fuer Floats,
Exakt-Gleichheit fuer Bools/Strings/Ints/Struktur.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from kmo_governance.kpm_sizing_engine import (
    Asset,
    DecisionEngineConfig,
    DrawdownGovernance,
    HIVEGovernanceGate,
    KPMVarianteDDecisionEngine,
    KellyCriterion,
    PortfolioOptimizer,
    RegimeBreakDetector,
    TradeOpportunity,
    calmar_ratio,
    conditional_var,
    correlation,
    covariance_from_samples,
    geometric_mean,
    max_drawdown,
    mean,
    quantile,
    shannon_from_counts,
    sharpe_ratio,
    std_dev,
    sum_values,
    value_at_risk,
    variance,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "parity_cases.json"
PARITY_TOLERANCE = 1e-6  # 6 Nachkommastellen (per AP-K1-Brief)

with FIXTURES.open() as fh:
    _DATA = json.load(fh)
_CASES: Dict[str, Dict[str, Any]] = {c["id"]: c for c in _DATA["cases"]}


def _assert_parity(got: Any, expected: Any, path: str = "") -> None:
    """Rekursiver Paritaets-Vergleich: Floats < 1e-6, Rest exakt."""
    if isinstance(expected, bool):
        assert got == expected, f"{path}: {got!r} != {expected!r}"
    elif isinstance(expected, (int, float)):
        assert isinstance(got, (int, float)), f"{path}: type {type(got)}"
        assert abs(float(got) - float(expected)) < PARITY_TOLERANCE, (
            f"{path}: |{got!r} - {expected!r}| >= {PARITY_TOLERANCE}"
        )
    elif expected is None:
        assert got is None, f"{path}: {got!r} != None"
    elif isinstance(expected, str):
        assert got == expected, f"{path}: {got!r} != {expected!r}"
    elif isinstance(expected, list):
        assert len(got) == len(expected), f"{path}: len {len(got)} != {len(expected)}"
        for i, (g, e) in enumerate(zip(got, expected)):
            _assert_parity(g, e, f"{path}[{i}]")
    elif isinstance(expected, dict):
        for k, e in expected.items():
            assert k in got, f"{path}.{k}: fehlt in got"
            _assert_parity(got[k], e, f"{path}.{k}")
    else:  # pragma: no cover
        raise AssertionError(f"{path}: unerwarteter Typ {type(expected)}")


def _mk_engine(path: list, config: Dict[str, Any]) -> KPMVarianteDDecisionEngine:
    gov = DrawdownGovernance(100_000.0)
    for v in path:
        gov.record_equity(v)
    gate = HIVEGovernanceGate([[1.0, -1.0, 0.0], [1.0, 1.0, -1.0], [0.0, -1.0, 1.0]])
    cfg = DecisionEngineConfig(
        pilot_mode=config["pilotMode"],
        withdrawal_phase=config["withdrawalPhase"],
        trinity_variant=config["trinityVariant"],
    )
    return KPMVarianteDDecisionEngine(gov, gate, cfg)


def _mk_opp(o: Dict[str, Any]) -> TradeOpportunity:
    return TradeOpportunity(
        asset=o["asset"],
        win_probability=o["winProbability"],
        win_amount=o["winAmount"],
        loss_amount=o["lossAmount"],
        notional=o["notional"],
    )


def _opt(cov: list, er: list) -> PortfolioOptimizer:
    assets = [Asset(f"a{i + 1}", f"A{i + 1}") for i in range(len(er))]
    return PortfolioOptimizer(assets, cov, er)


# --- Runner pro Fixture-Case: berechnet 'got' strukturgleich zu 'expected' ---

def _run_n1(inp):
    x = inp["x"]
    return {
        "mean": mean(x), "variance": variance(x), "stdDev": std_dev(x),
        "quantile25": quantile(x, 0.25), "sum": sum_values(x),
    }


def _run_n2(inp):
    r = inp["returns"]
    return {
        "geometricMean": geometric_mean(r), "maxDrawdown": max_drawdown(inp["equity"]),
        "sharpe": sharpe_ratio(r), "calmar": calmar_ratio(r, 12),
        "var5": value_at_risk(r, 0.05), "cvar5": conditional_var(r, 0.05),
        "correlation": correlation(inp["cx"], inp["cy"]),
    }


def _run_k3(inp):
    k = KellyCriterion(inp["p"], inp["w"], inp["l"])
    return {
        "optimalFraction": k.optimal_fraction(), "halfKelly": k.half_kelly(),
        "growth": k.expected_growth_rate(inp["f"]),
        "ctxNormalMedium": k.context_adaptive_fraction("normal-medium"),
    }


def _run_k4(inp):
    k = KellyCriterion(inp["p"], inp["w"], inp["l"])
    return {
        "optimalFraction": k.optimal_fraction(), "halfKelly": k.half_kelly(),
        "ctxHigh": k.context_adaptive_fraction("normal-high-confidence"),
        "ctxMedium": k.context_adaptive_fraction("normal-medium"),
        "ctxVola": k.context_adaptive_fraction("high-vola"),
        "ctxWithdrawal": k.context_adaptive_fraction("withdrawal-phase"),
        "ctxRegimeBreak": k.context_adaptive_fraction("regime-break"),
    }


def _run_k5(inp):
    k = KellyCriterion(inp["p"], inp["w"], inp["l"])
    ruin = k.growth_at_risk_of_ruin(inp["f"])
    return {
        "optimalFraction": k.optimal_fraction(),
        "ctxNormalMedium": k.context_adaptive_fraction("normal-medium"),
        "ruinGrowth": ruin.growth, "ruinRisk": ruin.ruin_risk,
    }


def _run_k6(inp):
    k = KellyCriterion(inp["p"], inp["w"], inp["l"])
    ruin = k.growth_at_risk_of_ruin(inp["f"])
    return {
        "growth": k.expected_growth_rate(inp["f"]),
        "ruinGrowth": ruin.growth, "ruinRisk": ruin.ruin_risk,
    }


def _run_dd(inp):
    gov = DrawdownGovernance(inp["initialEquity"])
    for v in inp["path"]:
        gov.record_equity(v)
    res = gov.enforce_level()
    return {
        "drawdown": gov.current_drawdown(), "level": res.level,
        "positionMultiplier": res.position_multiplier,
    }


def _run_d11(inp):
    gov = DrawdownGovernance(inp["initialEquity"])
    for v in inp["path"]:
        gov.record_equity(v)
    res = gov.enforce_level_dynamic(
        current_volatility=inp["currentVolatility"],
        baseline_volatility=inp["baselineVolatility"],
    )
    return {
        "level": res.level, "positionMultiplier": res.position_multiplier,
        "volatilityFactor": res.volatility_factor,
        "adjSoftBrake": res.adjusted_thresholds.soft_brake,
        "adjHardCap": res.adjusted_thresholds.hard_cap,
        "adjAbsoluteNoGo": res.adjusted_thresholds.absolute_no_go,
    }


def _run_h12(inp):
    gate = HIVEGovernanceGate(inp["teamSignals"])
    return {
        "shannon": gate.shannon_entropy(), "normalized": gate.normalized_hive(),
        "shannonFromCounts": shannon_from_counts(inp["counts"]),
    }


def _run_h13(inp):
    gate = HIVEGovernanceGate(inp["teamSignals"])
    gates = []
    for hive, sig in inp["combos"]:
        r = gate.leverage_gate(hive, sig)
        gates.append(
            {"hive": hive, "signal": sig, "action": r.recommended_action, "allow": r.allow_leverage}
        )
    return {"gates": gates}


def _run_r14(inp):
    det = RegimeBreakDetector(inp["returns"])
    res = det.detect_regime_break(inp["window"])
    combined = det.combined_regime_status()
    return {
        "breakDetected": res.break_detected, "breakDate": res.break_date,
        "confidence": res.confidence, "ratio": res.ratio,
        "combinedRegime": combined.regime, "combinedConfidence": combined.confidence,
    }


def _run_r15(inp):
    det = RegimeBreakDetector(inp["returns"])
    res = det.detect_regime_break(inp["window"])
    combined = det.combined_regime_status()
    return {
        "breakDetected": res.break_detected, "confidence": res.confidence, "ratio": res.ratio,
        "combinedRegime": combined.regime, "combinedConfidence": combined.confidence,
    }


def _run_r16(inp):
    det = RegimeBreakDetector(inp["returns"])
    disp = det.forecast_dispersion_monitor(inp["forecasts"], inp["threshold"])
    decay = det.edge_decay_alert(inp["realized"], inp["forecast"])
    return {
        "dispersion": disp.dispersion, "alarm": disp.alarm_triggered,
        "decay": decay.decay, "consecutiveMonths": decay.consecutive_months,
        "meanDelta": decay.mean_delta,
    }


def _run_p17(inp):
    opt = _opt(inp["cov"], inp["er"])
    mv = opt.markowitz_mv_optimum(inp["target"])
    return {
        "weights": mv.weights, "expectedReturn": mv.expected_return, "risk": mv.risk,
        "riskParity": opt.risk_parity(),
        "stdDev": opt.portfolio_std_dev(inp["sdWeights"]),
        "portER": opt.portfolio_expected_return(inp["sdWeights"]),
    }


def _run_p18(inp):
    opt = _opt(inp["cov"], inp["er"])
    mv = opt.markowitz_mv_optimum(inp["target"])
    return {"weights": mv.weights, "expectedReturn": mv.expected_return, "risk": mv.risk}


def _run_p19(inp):
    opt = _opt(inp["cov"], inp["er"])
    legacy_w, legacy_cvar = opt.cvar_optimization(inp["scenarios"], inp["alpha"])
    lp = opt.cvar_optimization_lp(inp["scenarios"], inp["beta"])
    return {
        "legacyWeights": legacy_w, "legacyCvar": legacy_cvar,
        "lpWeights": lp.weights, "lpCvar": lp.cvar, "lpVar": lp.var,
        "lpConverged": lp.converged, "lpIterations": lp.iterations,
    }


def _run_p20(inp):
    opt = _opt(inp["cov"], inp["er"])
    lw = opt.ledoit_wolf_shrinkage(inp["returns"])
    return {
        "shrunkCovariance": lw.shrunk_covariance,
        "shrinkageIntensity": lw.shrinkage_intensity,
        "meanVarianceTarget": lw.mean_variance_target,
        "covFromSamples": covariance_from_samples(inp["returns"]),
    }


def _run_p21(inp):
    opt = _opt(inp["cov"], inp["er"])
    con = opt.markowitz_mv_optimum_constrained(inp["target"])
    frontier = opt.efficient_frontier(inp["numPoints"])
    return {
        "weights": con.weights, "risk": con.risk, "expectedReturn": con.expected_return,
        "constraintsActive": con.constraints_active, "method": con.method,
        "frontierReturns": [p.expected_return for p in frontier],
        "frontierRisks": [p.risk for p in frontier],
    }


def _run_e22(inp):
    eng = _mk_engine(inp["path"], inp["config"])
    dec = eng.decide_trade_size(
        _mk_opp(inp["opp"]), inp["hive"], inp["regime"], inp["signal"], inp["edge"]
    )
    return {
        "size": dec.size, "fraction": dec.fraction, "rejected": dec.rejected,
        "gates": dataclasses.asdict(dec.gates), "warningsCount": len(dec.warnings),
    }


def _run_e23(inp):
    opp = _mk_opp(inp["opp"])
    dec_pilot = _mk_engine(
        [85_000.0], {"pilotMode": True, "withdrawalPhase": False, "trinityVariant": "aggressive"}
    ).decide_trade_size(opp, 0.75, "normal", "positive", "high")
    dec_free = _mk_engine(
        [], {"pilotMode": False, "withdrawalPhase": False, "trinityVariant": "aggressive"}
    ).decide_trade_size(opp, 0.75, "normal", "positive", "high")
    dec_wd = _mk_engine(
        [], {"pilotMode": True, "withdrawalPhase": True, "trinityVariant": "contrarian"}
    ).decide_trade_size(opp, 0.6, "normal", "neutral", "medium")
    return {
        "pilotFraction": dec_pilot.fraction, "pilotSize": dec_pilot.size,
        "pilotWarningsCount": len(dec_pilot.warnings),
        "freeFraction": dec_free.fraction, "freeSize": dec_free.size,
        "wdFraction": dec_wd.fraction, "wdSize": dec_wd.size,
        "wdWarningsCount": len(dec_wd.warnings),
    }


def _run_e24(inp):
    opp = _mk_opp(inp["opp"])
    cfg = {"pilotMode": True, "withdrawalPhase": False, "trinityVariant": "conservative"}
    dec_dd = _mk_engine([80_000.0], cfg).decide_trade_size(opp, 0.75, "normal", "positive", "high")
    dec_hive = _mk_engine([], cfg).decide_trade_size(opp, 0.4, "normal", "positive", "high")
    dec_reg = _mk_engine([], cfg).decide_trade_size(
        opp, 0.75, "regime-break", "positive", "high"
    )
    neg_opp = dataclasses.replace(opp, win_probability=0.3, win_amount=1.0)
    dec_neg = _mk_engine([], cfg).decide_trade_size(neg_opp, 0.75, "normal", "positive", "high")
    return {
        "ddRejected": dec_dd.rejected, "ddGates": dataclasses.asdict(dec_dd.gates),
        "hiveRejected": dec_hive.rejected, "hiveGates": dataclasses.asdict(dec_hive.gates),
        "regRejected": dec_reg.rejected, "regGates": dataclasses.asdict(dec_reg.gates),
        "negRejected": dec_neg.rejected, "negFraction": dec_neg.fraction,
    }


_RUNNERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "n1-numerics-basic": _run_n1,
    "n2-numerics-risk": _run_n2,
    "k3-kelly-symmetric": _run_k3,
    "k4-kelly-asymmetric": _run_k4,
    "k5-kelly-negative-edge": _run_k5,
    "k6-kelly-growth-ruin": _run_k6,
    "d7-drawdown-normal": _run_dd,
    "d8-drawdown-soft-brake-15": _run_dd,
    "d9-drawdown-hard-cap-20": _run_dd,
    "d10-drawdown-no-go-25": _run_dd,
    "d11-drawdown-dynamic-vol": _run_d11,
    "h12-hive-entropy": _run_h12,
    "h13-hive-gate-boundaries": _run_h13,
    "r14-regime-break": _run_r14,
    "r15-regime-stable": _run_r15,
    "r16-regime-dispersion-edge": _run_r16,
    "p17-portfolio-markowitz2": _run_p17,
    "p18-portfolio-markowitz3-grid": _run_p18,
    "p19-portfolio-cvar": _run_p19,
    "p20-portfolio-ledoit-wolf": _run_p20,
    "p21-portfolio-constrained-frontier": _run_p21,
    "e22-engine-pass": _run_e22,
    "e23-engine-modifiers": _run_e23,
    "e24-engine-rejects": _run_e24,
}


def test_fixture_file_meta() -> None:
    assert _DATA["meta"]["caseCount"] == len(_DATA["cases"]) == 24
    assert set(_RUNNERS) == set(_CASES), "Runner-Abdeckung != Fixture-Faelle"


@pytest.mark.parametrize("case_id", sorted(_CASES.keys()))
def test_parity_case(case_id: str) -> None:
    case = _CASES[case_id]
    got = _RUNNERS[case_id](case["input"])
    _assert_parity(got, case["expected"], path=case_id)
