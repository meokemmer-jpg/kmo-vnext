# [CRUX-MK]
"""Unit-Tests kpm_sizing_engine Batch-1: numerics + kelly_criterion + drawdown_governance.

Erwartungswerte portiert aus den TS-Test-Files der Referenz
~/Projects/heylou-v10-foundation/packages/kpm-sizing/tests/ (Commit f4083f4)
bzw. per Hand aus den 1:1-Formeln abgeleitet (Grenzfaelle 15%/20%/25%, Kelly-Kontexte).
"""

from __future__ import annotations

import math

import pytest

from kmo_governance.kpm_sizing_engine.numerics import (
    calmar_ratio,
    clamp,
    conditional_var,
    correlation,
    geometric_mean,
    max_drawdown,
    mean,
    quantile,
    sharpe_ratio,
    std_dev,
    sum_values,
    value_at_risk,
    variance,
)
from kmo_governance.kpm_sizing_engine.kelly_criterion import KellyCriterion
from kmo_governance.kpm_sizing_engine.drawdown_governance import (
    DEFAULT_THRESHOLDS,
    DrawdownGovernance,
    DrawdownThresholds,
)

TOL = 1e-9


class TestNumerics:
    def test_mean_variance_stddev(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert abs(mean(x) - 3.0) < TOL
        assert abs(variance(x) - 2.5) < TOL
        assert abs(std_dev(x) - math.sqrt(2.5)) < TOL

    def test_mean_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="mean: empty array"):
            mean([])

    def test_variance_needs_two(self) -> None:
        with pytest.raises(ValueError, match="variance"):
            variance([1.0])

    def test_correlation_perfect(self) -> None:
        x = [1.0, 2.0, 3.0]
        y = [2.0, 4.0, 6.0]
        assert abs(correlation(x, y) - 1.0) < TOL
        assert abs(correlation(x, [-v for v in y]) + 1.0) < TOL

    def test_quantile_interpolation(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0]
        # idx = 0.5 * 3 = 1.5 -> 2*0.5 + 3*0.5 = 2.5
        assert abs(quantile(x, 0.5) - 2.5) < TOL
        assert abs(quantile(x, 0.0) - 1.0) < TOL
        assert abs(quantile(x, 1.0) - 4.0) < TOL

    def test_geometric_mean(self) -> None:
        # (1.1 * 0.9)^(1/2) - 1 = sqrt(0.99) - 1
        got = geometric_mean([0.1, -0.1])
        assert abs(got - (math.sqrt(0.99) - 1)) < TOL

    def test_max_drawdown(self) -> None:
        equity = [100.0, 120.0, 90.0, 110.0]
        # Peak 120 -> Trough 90 -> dd = 30/120 = 0.25
        assert abs(max_drawdown(equity) - 0.25) < TOL

    def test_sharpe_zero_sigma(self) -> None:
        assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0

    def test_calmar_no_drawdown_cap(self) -> None:
        # Monoton steigende Returns -> Max-DD = 0 -> Cap 1000
        assert calmar_ratio([0.01, 0.02, 0.01]) == 1000.0

    def test_var_cvar_relation(self) -> None:
        returns = [-0.10, -0.05, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07]
        var_ = value_at_risk(returns, 0.05)
        cvar = conditional_var(returns, 0.05)
        assert var_ >= 0
        assert cvar >= var_ - TOL

    def test_sum_and_clamp(self) -> None:
        assert abs(sum_values([0.5, 0.25, 0.25]) - 1.0) < TOL
        assert clamp(1.5, 0.0, 1.0) == 1.0
        assert clamp(-0.5, 0.0, 1.0) == 0.0
        assert clamp(0.3, 0.0, 1.0) == 0.3


class TestKellyCriterion:
    def test_symmetric_kelly(self) -> None:
        # p=0.55, w=l=1: f* = (0.55*1 - 0.45*1) / (1*1) = 0.1
        k = KellyCriterion(0.55, 1.0, 1.0)
        assert abs(k.optimal_fraction() - 0.1) < TOL
        assert abs(k.half_kelly() - 0.05) < TOL

    def test_asymmetric_kelly_patch_kpm1(self) -> None:
        # Welle-M-Patch-KPM-1: f* = (p*w - q*l) / (w*l)
        # p=0.6, w=15000, l=5000: (0.6*15000 - 0.4*5000) / (15000*5000)
        k = KellyCriterion(0.6, 15000.0, 5000.0)
        expected = (0.6 * 15000.0 - 0.4 * 5000.0) / (15000.0 * 5000.0)
        assert abs(k.optimal_fraction() - expected) < TOL

    def test_context_table_variante_d(self) -> None:
        k = KellyCriterion(0.55, 1.0, 1.0)
        f_opt = k.optimal_fraction()
        assert abs(k.context_adaptive_fraction("normal-high-confidence") - 0.40 * f_opt) < TOL
        assert abs(k.context_adaptive_fraction("normal-medium") - 0.30 * f_opt) < TOL
        assert abs(k.context_adaptive_fraction("high-vola") - 0.25 * f_opt) < TOL
        assert abs(k.context_adaptive_fraction("withdrawal-phase") - 0.20 * f_opt) < TOL
        assert k.context_adaptive_fraction("regime-break") == 0.0

    def test_negative_edge_no_bet(self) -> None:
        k = KellyCriterion(0.4, 1.0, 1.0)
        assert k.optimal_fraction() < 0
        assert k.context_adaptive_fraction("normal-medium") == 0.0
        res = k.growth_at_risk_of_ruin(0.1)
        assert res.growth == 0.0
        assert res.ruin_risk == 1.0

    def test_growth_rate_and_bankrupt(self) -> None:
        k = KellyCriterion(0.55, 1.0, 1.0)
        g = k.expected_growth_rate(0.1)
        expected = 0.55 * math.log(1.1) + 0.45 * math.log(0.9)
        assert abs(g - expected) < TOL
        assert k.expected_growth_rate(1.0) == float("-inf")  # f*l >= 1 -> Bankrupt

    def test_validation_errors(self) -> None:
        with pytest.raises(ValueError):
            KellyCriterion(0.0, 1.0, 1.0)
        with pytest.raises(ValueError):
            KellyCriterion(1.0, 1.0, 1.0)
        with pytest.raises(ValueError):
            KellyCriterion(0.5, 0.0, 1.0)
        with pytest.raises(ValueError):
            KellyCriterion(0.5, 1.0, -1.0)
        with pytest.raises(ValueError):
            KellyCriterion(0.55, 1.0, 1.0).expected_growth_rate(-0.1)


class TestDrawdownGovernance:
    def test_normal_below_soft_brake(self) -> None:
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(102_000.0)
        gov.record_equity(98_000.0)
        # dd = (102000 - 98000) / 102000 ~ 3.92%
        res = gov.enforce_level()
        assert res.level == "normal"
        assert res.position_multiplier == 1.0

    def test_soft_brake_exact_15_percent(self) -> None:
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(85_000.0)  # dd = 0.15 exakt
        assert abs(gov.current_drawdown() - 0.15) < TOL
        res = gov.enforce_level()
        assert res.level == "soft-brake"
        assert res.position_multiplier == 0.5

    def test_hard_cap_exact_20_percent(self) -> None:
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(80_000.0)  # dd = 0.20 exakt
        res = gov.enforce_level()
        assert res.level == "hard-cap"
        assert res.position_multiplier == 0.0

    def test_absolute_no_go_exact_25_percent(self) -> None:
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(75_000.0)  # dd = 0.25 exakt
        res = gov.enforce_level()
        assert res.level == "absolute-no-go"
        assert res.position_multiplier == 0.0

    def test_peak_update_and_recovery(self) -> None:
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(110_000.0)  # neuer Peak
        assert gov.current_drawdown() == 0.0
        gov.record_equity(100_000.0)
        gov.record_equity(99_000.0)
        rec = gov.peak_recovery()
        assert rec.recovered is False
        assert rec.periods_since_recovery == 2
        gov.record_equity(111_000.0)  # Peak recovered
        rec2 = gov.peak_recovery()
        assert rec2.recovered is True
        assert rec2.periods_since_recovery == 0

    def test_threshold_validation(self) -> None:
        with pytest.raises(ValueError):
            DrawdownGovernance(0.0)
        with pytest.raises(ValueError):
            DrawdownGovernance(1.0, DrawdownThresholds(0.2, 0.15, 0.25))
        with pytest.raises(ValueError):
            DrawdownGovernance(1.0, DrawdownThresholds(0.15, 0.20, 1.0))
        with pytest.raises(ValueError):
            DrawdownGovernance(100.0).record_equity(0.0)

    def test_dynamic_vol_adjustment_tightens(self) -> None:
        # currentVol=0.30, baselineVol=0.15 -> volRatio=2 -> factor=0.7 (clamp)
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(88_000.0)  # dd = 0.12
        res = gov.enforce_level_dynamic(current_volatility=0.30, baseline_volatility=0.15)
        assert abs(res.volatility_factor - 0.7) < TOL
        assert abs(res.adjusted_thresholds.soft_brake - 0.15 * 0.7) < TOL
        assert abs(res.adjusted_thresholds.hard_cap - 0.20 * 0.7) < TOL
        assert abs(res.adjusted_thresholds.absolute_no_go - 0.25 * 0.7) < TOL
        # dd 0.12 >= 0.105 (vol-adj soft-brake) -> soft-brake
        assert res.level == "soft-brake"
        assert res.position_multiplier == 0.5

    def test_dynamic_cooldown_cycle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_now = [1_000_000.0]
        monkeypatch.setattr(DrawdownGovernance, "_now_ms", staticmethod(lambda: fake_now[0]))
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(80_000.0)  # dd = 0.20 -> hard-cap (default vol=1)
        res = gov.enforce_level_dynamic()
        assert res.level == "hard-cap"
        assert res.cooldown_remaining_ms == 5 * 86_400_000
        # Innerhalb Cooldown: level=cooldown, multiplier=0
        fake_now[0] += 1_000.0
        res2 = gov.enforce_level_dynamic()
        assert res2.level == "cooldown"
        assert res2.position_multiplier == 0.0
        assert gov.is_in_cooldown().in_cooldown is True
        # Nach Ablauf: Cooldown weg, aber dd weiterhin hard-cap -> erneut hard-cap
        fake_now[0] += 6 * 86_400_000.0
        res3 = gov.enforce_level_dynamic()
        assert res3.level == "hard-cap"

    def test_clear_cooldown_logs_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_now = [5_000_000.0]
        monkeypatch.setattr(DrawdownGovernance, "_now_ms", staticmethod(lambda: fake_now[0]))
        gov = DrawdownGovernance(100_000.0)
        gov.record_equity(80_000.0)
        gov.enforce_level_dynamic()  # triggert Cooldown
        gov.clear_cooldown({"user": "martin", "reason": "phronesis-override-test"})
        assert gov.is_in_cooldown().in_cooldown is False
        log = gov.get_override_log()
        assert len(log) == 1
        assert log[0].user == "martin"
        assert log[0].level == "cooldown"

    def test_snapshot_shape(self) -> None:
        gov = DrawdownGovernance(100_000.0, DEFAULT_THRESHOLDS)
        gov.record_equity(90_000.0)
        snap = gov.snapshot()
        assert snap["peak"] == 100_000.0
        assert snap["current"] == 90_000.0
        assert snap["level"] == "normal"
        assert snap["history_len"] == 2
        assert snap["cooldown_active"] is False
