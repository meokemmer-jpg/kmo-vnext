# [CRUX-MK]
"""Unit-Tests kpm_sizing_engine Batch-2: HIVE + Regime + Portfolio + DecisionEngine.

Erwartungswerte portiert aus den TS-Test-Files der Referenz
~/Projects/heylou-v10-foundation/packages/kpm-sizing/tests/ (Commit f4083f4)
bzw. per Hand aus den 1:1-Formeln (HIVE-Grenzen 0.5/0.7, Gate-Pipeline).
"""

from __future__ import annotations

import math

import pytest

from kmo_governance.kpm_sizing_engine.hive_governance_gate import (
    HIVECalibrationScenario,
    HIVEGovernanceGate,
    shannon_from_counts,
)
from kmo_governance.kpm_sizing_engine.regime_break_detector import RegimeBreakDetector
from kmo_governance.kpm_sizing_engine.portfolio_optimizer import (
    Asset,
    PortfolioOptimizer,
    covariance_from_samples,
)
from kmo_governance.kpm_sizing_engine.drawdown_governance import DrawdownGovernance
from kmo_governance.kpm_sizing_engine.decision_engine import (
    DecisionEngineConfig,
    KPMVarianteDDecisionEngine,
    TradeOpportunity,
)

TOL = 1e-9


def _diverse_gate() -> HIVEGovernanceGate:
    return HIVEGovernanceGate([[1.0, -1.0, 0.0], [1.0, 1.0, -1.0], [0.0, -1.0, 1.0]])


class TestHIVEGovernanceGate:
    def test_uniform_distribution_max_entropy(self) -> None:
        # 3 pos, 3 neg, 3 neu -> Gleichverteilung -> H = log2(3), HIVE = 1.0
        gate = _diverse_gate()
        assert abs(gate.shannon_entropy() - math.log2(3)) < TOL
        assert abs(gate.normalized_hive() - 1.0) < TOL

    def test_concentration_zero_entropy(self) -> None:
        gate = HIVEGovernanceGate([[1.0, 1.0], [1.0, 1.0]])
        assert gate.shannon_entropy() == 0.0
        assert gate.normalized_hive() == 0.0

    def test_gate_boundaries_exactly_05_and_07(self) -> None:
        gate = _diverse_gate()
        # < 0.5 -> deleverage
        assert gate.leverage_gate(0.49, "positive").recommended_action == "deleverage"
        # == 0.5 -> maintain (Grenze inklusiv fuer maintain-Band)
        assert gate.leverage_gate(0.5, "positive").recommended_action == "maintain"
        # knapp unter 0.7 -> maintain
        assert gate.leverage_gate(0.699999, "positive").recommended_action == "maintain"
        # == 0.7 + positive -> increase
        res = gate.leverage_gate(0.7, "positive")
        assert res.recommended_action == "increase"
        assert res.allow_leverage is True

    def test_gate_negative_market_signal_blocks_increase(self) -> None:
        gate = _diverse_gate()
        res = gate.leverage_gate(0.9, "negative")
        assert res.recommended_action == "maintain"
        assert res.allow_leverage is False

    def test_set_thresholds_validation(self) -> None:
        gate = _diverse_gate()
        gate.set_thresholds(leverage=0.8, deleverage=0.4)
        assert gate.get_thresholds() == {"leverage": 0.8, "deleverage": 0.4}
        with pytest.raises(ValueError):
            gate.set_thresholds(leverage=0.4, deleverage=0.8)
        with pytest.raises(ValueError):
            gate.leverage_gate(1.5, "neutral")

    def test_shannon_from_counts(self) -> None:
        # counts [10, 5, 3]: H = -sum(p*log2 p)
        total = 18.0
        expected = -sum((c / total) * math.log2(c / total) for c in (10.0, 5.0, 3.0))
        assert abs(shannon_from_counts([10.0, 5.0, 3.0]) - expected) < TOL
        assert shannon_from_counts([0.0, 0.0]) == 0.0

    def test_calibration_fallback_below_20_samples(self) -> None:
        scen = [
            HIVECalibrationScenario("2008", [[1.0, -1.0, 0.0]], "bad")
            for _ in range(5)
        ]
        res = HIVEGovernanceGate.calibrate_thresholds(scen)
        assert res.fallback_used is True
        assert res.method == "fallback-default"
        assert res.leverage_threshold == 0.7
        assert res.deleverage_threshold == 0.5
        assert res.sample_size == 5

    def test_validation_errors(self) -> None:
        with pytest.raises(ValueError):
            HIVEGovernanceGate([])
        with pytest.raises(ValueError):
            HIVEGovernanceGate([[1.0, 2.0], [1.0]])
        with pytest.raises(ValueError):
            HIVEGovernanceGate([[float("nan")]])


def _regime_series() -> list:
    # 30 ruhige + 30 hoch-volatile Beobachtungen (deterministisch)
    calm = [0.005 if i % 2 == 0 else -0.005 for i in range(30)]
    wild = [0.03 if i % 2 == 0 else -0.03 for i in range(30)]
    return calm + wild


class TestRegimeBreakDetector:
    def test_break_detected_on_vol_shift(self) -> None:
        det = RegimeBreakDetector(_regime_series())
        res = det.detect_regime_break(60)
        assert res.break_detected is True
        assert res.ratio is not None and res.ratio > 2.0
        assert 0.0 <= res.confidence <= 1.0

    def test_no_break_on_stable_series(self) -> None:
        det = RegimeBreakDetector([0.01 if i % 2 == 0 else -0.01 for i in range(60)])
        res = det.detect_regime_break(60)
        assert res.break_detected is False

    def test_min_observations_and_window(self) -> None:
        with pytest.raises(ValueError):
            RegimeBreakDetector([0.01] * 29)
        det = RegimeBreakDetector([0.01, -0.01] * 15)
        with pytest.raises(ValueError):
            det.detect_regime_break(9)

    def test_dispersion_monitor(self) -> None:
        det = RegimeBreakDetector([0.01, -0.01] * 15)
        res = det.forecast_dispersion_monitor([0.01, 0.02, 0.08], threshold=0.05)
        assert res.alarm_triggered is False  # stddev([.01,.02,.08]) ~ 0.0379 < 0.05
        res2 = det.forecast_dispersion_monitor([0.01, 0.02, 0.15], threshold=0.05)
        assert res2.alarm_triggered is True

    def test_edge_decay_trailing_count(self) -> None:
        det = RegimeBreakDetector([0.01, -0.01] * 15)
        realized = [0.02, 0.01, 0.005, 0.001]
        forecast = [0.01, 0.02, 0.02, 0.02]
        res = det.edge_decay_alert(realized, forecast)
        assert res.consecutive_months == 3
        assert res.decay is True
        assert abs(res.mean_delta - ((0.01 - 0.015 - 0.019) + 0.01) / 4) < 1e-12

    def test_combined_regime_status(self) -> None:
        det = RegimeBreakDetector(_regime_series())
        status = det.combined_regime_status()
        assert status.regime == "regime-break"
        assert status.components.break_detected is True


def _two_asset_optimizer() -> PortfolioOptimizer:
    return PortfolioOptimizer(
        [Asset("a1", "Aktien"), Asset("a2", "Anleihen")],
        [[0.04, 0.006], [0.006, 0.09]],
        [0.08, 0.12],
    )


class TestPortfolioOptimizer:
    def test_markowitz_2asset_analytic(self) -> None:
        opt = _two_asset_optimizer()
        res = opt.markowitz_mv_optimum(0.10)
        # w1 = (0.10 - 0.12) / (0.08 - 0.12) = 0.5
        assert abs(res.weights[0] - 0.5) < TOL
        assert abs(res.weights[1] - 0.5) < TOL
        assert abs(res.expected_return - 0.10) < TOL
        expected_risk = math.sqrt(0.25 * 0.04 + 0.25 * 0.09 + 2 * 0.25 * 0.006)
        assert abs(res.risk - expected_risk) < TOL

    def test_target_return_out_of_range(self) -> None:
        opt = _two_asset_optimizer()
        with pytest.raises(ValueError):
            opt.markowitz_mv_optimum(0.5)

    def test_risk_parity_inverse_vol(self) -> None:
        opt = _two_asset_optimizer()
        weights = opt.risk_parity()
        inv = [1 / 0.2, 1 / 0.3]  # sigma = sqrt(0.04), sqrt(0.09)
        total = inv[0] + inv[1]
        assert abs(weights[0] - inv[0] / total) < TOL
        assert abs(weights[1] - inv[1] / total) < TOL

    def test_covariance_from_samples_symmetry(self) -> None:
        cov = covariance_from_samples([[0.01, 0.02, -0.01, 0.03], [0.02, 0.01, 0.00, 0.02]])
        assert abs(cov[0][1] - cov[1][0]) < TOL

    def test_symmetry_validation(self) -> None:
        with pytest.raises(ValueError, match="not symmetric"):
            PortfolioOptimizer(
                [Asset("a", "A"), Asset("b", "B")],
                [[0.04, 0.01], [0.02, 0.09]],
                [0.08, 0.12],
            )

    def test_cvar_lp_simplex_invariants(self) -> None:
        opt = _two_asset_optimizer()
        # Deterministische Szenarien (LCG-frei, explizit)
        scenarios = [
            [0.01 * ((i % 7) - 3), 0.008 * ((i % 5) - 2)] for i in range(40)
        ]
        res = opt.cvar_optimization_lp(scenarios, beta=0.95)
        assert abs(sum(res.weights) - 1.0) < 1e-9
        assert all(w >= 0 for w in res.weights)
        assert res.cvar >= res.var - 1e-12

    def test_efficient_frontier_monotone_returns(self) -> None:
        opt = _two_asset_optimizer()
        frontier = opt.efficient_frontier(5)
        assert len(frontier) == 5
        rets = [p.expected_return for p in frontier]
        assert rets == sorted(rets)


def _engine(
    equity_path: list,
    config: DecisionEngineConfig = DecisionEngineConfig(),
) -> KPMVarianteDDecisionEngine:
    gov = DrawdownGovernance(100_000.0)
    for v in equity_path:
        gov.record_equity(v)
    gate = HIVEGovernanceGate([[1.0, -1.0, 0.0], [1.0, 1.0, -1.0], [0.0, -1.0, 1.0]])
    return KPMVarianteDDecisionEngine(gov, gate, config)


def _opportunity() -> TradeOpportunity:
    return TradeOpportunity(
        asset="TEST", win_probability=0.6, win_amount=2.0, loss_amount=1.0, notional=100_000.0
    )


class TestKPMVarianteDDecisionEngine:
    def test_normal_pass_pipeline_conservative_pilot(self) -> None:
        eng = _engine([])
        dec = eng.decide_trade_size(_opportunity(), 0.75, "normal", "positive", "high")
        # f* = (0.6*2 - 0.4*1) / 2 = 0.4; ctx=0.40*0.4=0.16; dd=1.0; hive=1.0;
        # trinity conservative 0.7 -> 0.112; pilot-cap 0.25 greift nicht
        assert dec.rejected is False
        assert abs(dec.fraction - 0.4 * 0.4 * 0.7) < TOL
        assert abs(dec.size - dec.fraction * 100_000.0) < TOL
        assert dec.gates.drawdown_passed and dec.gates.hive_passed and dec.gates.regime_passed

    def test_negative_edge_rejected(self) -> None:
        eng = _engine([])
        opp = TradeOpportunity("X", 0.3, 1.0, 1.0, 50_000.0)
        dec = eng.decide_trade_size(opp, 0.75)
        assert dec.rejected is True
        assert dec.size == 0.0
        assert "Negative Edge" in dec.warnings

    def test_drawdown_hard_cap_rejects(self) -> None:
        eng = _engine([80_000.0])  # dd = 0.20 -> hard-cap
        dec = eng.decide_trade_size(_opportunity(), 0.75, "normal", "positive", "high")
        assert dec.rejected is True
        assert dec.gates.drawdown_passed is False

    def test_soft_brake_halves_position(self) -> None:
        eng = _engine([85_000.0])  # dd = 0.15 -> soft-brake 0.5x
        dec = eng.decide_trade_size(_opportunity(), 0.75, "normal", "positive", "high")
        assert dec.rejected is False
        assert abs(dec.fraction - 0.4 * 0.4 * 0.5 * 0.7) < TOL
        assert any("soft-brake" in w for w in dec.warnings)

    def test_hive_deleverage_rejects(self) -> None:
        eng = _engine([])
        dec = eng.decide_trade_size(_opportunity(), 0.4, "normal", "positive", "high")
        assert dec.rejected is True
        assert dec.gates.hive_passed is False
        assert "HIVE Auto-Deleverage" in dec.warnings

    def test_regime_break_rejects(self) -> None:
        eng = _engine([])
        dec = eng.decide_trade_size(_opportunity(), 0.75, "regime-break", "positive", "high")
        assert dec.rejected is True
        assert dec.gates.regime_passed is False
        assert dec.gates.drawdown_passed is True and dec.gates.hive_passed is True

    def test_pilot_cap_at_025_aggressive_no_pilot(self) -> None:
        # aggressive + high-edge: ctx=0.4*f*; f*=0.4 -> 0.16 -> x1.0 trinity = 0.16 (kein Cap)
        # groesserer Edge: p=0.8, w=4, l=1 -> f* = (3.2-0.2)/4 = 0.75 -> ctx 0.3
        opp = TradeOpportunity("BIG", 0.8, 4.0, 1.0, 100_000.0)
        eng_pilot = _engine([], DecisionEngineConfig(True, False, "aggressive"))
        dec_pilot = eng_pilot.decide_trade_size(opp, 0.75, "normal", "positive", "high")
        assert abs(dec_pilot.fraction - 0.25) < TOL  # Pilot-Cap greift (0.30 -> 0.25)
        assert any("Pilot-Mode-Cap" in w for w in dec_pilot.warnings)
        eng_free = _engine([], DecisionEngineConfig(False, False, "aggressive"))
        dec_free = eng_free.decide_trade_size(opp, 0.75, "normal", "positive", "high")
        assert abs(dec_free.fraction - 0.30) < TOL  # ohne Pilot: 0.40 * 0.75 = 0.30

    def test_withdrawal_phase_context(self) -> None:
        eng = _engine([], DecisionEngineConfig(True, True, "aggressive"))
        dec = eng.decide_trade_size(_opportunity(), 0.75, "normal", "positive", "high")
        # withdrawal-phase: 0.20 * f*(0.4) = 0.08 -> x1.0 -> 0.08
        assert abs(dec.fraction - 0.08) < TOL

    def test_drawdown_status_delegate(self) -> None:
        eng = _engine([90_000.0])
        status = eng.drawdown_status()
        assert status.level == "normal"
        assert abs(status.drawdown - 0.10) < TOL
        eng.record_equity(70_000.0)
        assert eng.drawdown_status().level == "absolute-no-go"
