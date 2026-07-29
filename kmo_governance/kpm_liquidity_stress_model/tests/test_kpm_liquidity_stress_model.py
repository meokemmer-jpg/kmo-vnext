from __future__ import annotations

import pytest

from kmo_governance.kpm_liquidity_stress_model import (
    EvidenceGrade,
    PortfolioPosition,
    StressScenario,
    ValidationSnapshot,
    assess_liquidity_buffer,
)


def _scenarios() -> list[StressScenario]:
    return [
        StressScenario(
            name="moderate-stress",
            volatility_multiplier=1.5,
            margin_multiplier=1.2,
            liquidation_multiplier=1.0,
            concentration_multiplier=0.04,
        ),
        StressScenario(
            name="funding-squeeze",
            volatility_multiplier=2.5,
            margin_multiplier=1.8,
            liquidation_multiplier=1.6,
            concentration_multiplier=0.08,
        ),
    ]


def test_dynamic_model_discriminates_between_stable_and_fragile_portfolios() -> None:
    strong_validation = ValidationSnapshot(
        realized_periods=36,
        breach_count=0,
        regime_count=4,
        independent_challenge_runs=3,
        max_model_error=0.06,
    )
    stable_positions = [
        PortfolioPosition(
            instrument_id="bond-a",
            market_value=400.0,
            daily_volatility=0.01,
            margin_ratio=0.08,
            liquidation_days=1.0,
            spread_bps=5.0,
            concentration_group="rates",
        ),
        PortfolioPosition(
            instrument_id="bond-b",
            market_value=350.0,
            daily_volatility=0.012,
            margin_ratio=0.09,
            liquidation_days=1.0,
            spread_bps=6.0,
            concentration_group="rates",
        ),
        PortfolioPosition(
            instrument_id="fx-hedge",
            market_value=250.0,
            daily_volatility=0.008,
            margin_ratio=0.05,
            liquidation_days=1.0,
            spread_bps=4.0,
            concentration_group="fx",
        ),
    ]
    fragile_positions = [
        PortfolioPosition(
            instrument_id="growth-tech",
            market_value=850.0,
            daily_volatility=0.045,
            margin_ratio=0.22,
            liquidation_days=4.0,
            spread_bps=35.0,
            concentration_group="equity",
        ),
        PortfolioPosition(
            instrument_id="micro-cap",
            market_value=150.0,
            daily_volatility=0.07,
            margin_ratio=0.30,
            liquidation_days=6.0,
            spread_bps=80.0,
            concentration_group="equity",
        ),
    ]

    stable = assess_liquidity_buffer(
        stable_positions,
        _scenarios(),
        available_cash=470.0,
        validation=strong_validation,
    )
    fragile = assess_liquidity_buffer(
        fragile_positions,
        _scenarios(),
        available_cash=470.0,
        validation=strong_validation,
    )

    assert stable.evidence_grade is EvidenceGrade.HIGH
    assert fragile.evidence_grade is EvidenceGrade.HIGH
    assert stable.required_cash_ratio < 0.47
    assert fragile.required_cash_ratio > stable.required_cash_ratio
    assert stable.cash_buffer_gap < 0
    assert fragile.cash_buffer_gap > 0
    assert stable.binding_scenario == "funding-squeeze"
    assert fragile.binding_scenario == "funding-squeeze"


def test_high_evidence_is_blocked_without_validation_depth() -> None:
    positions = [
        PortfolioPosition(
            instrument_id="credit-index",
            market_value=600.0,
            daily_volatility=0.02,
            margin_ratio=0.12,
            liquidation_days=2.0,
            spread_bps=12.0,
            concentration_group="credit",
        ),
        PortfolioPosition(
            instrument_id="equity-index",
            market_value=400.0,
            daily_volatility=0.025,
            margin_ratio=0.14,
            liquidation_days=2.5,
            spread_bps=14.0,
            concentration_group="equity",
        ),
    ]
    weak_validation = ValidationSnapshot(
        realized_periods=5,
        breach_count=1,
        regime_count=1,
        independent_challenge_runs=0,
        max_model_error=0.35,
    )
    strong_validation = ValidationSnapshot(
        realized_periods=30,
        breach_count=0,
        regime_count=4,
        independent_challenge_runs=2,
        max_model_error=0.08,
    )

    weak = assess_liquidity_buffer(
        positions,
        _scenarios(),
        available_cash=300.0,
        validation=weak_validation,
    )
    strong = assess_liquidity_buffer(
        positions,
        _scenarios(),
        available_cash=300.0,
        validation=strong_validation,
    )

    assert weak.required_cash_ratio == pytest.approx(strong.required_cash_ratio)
    assert weak.evidence_grade is EvidenceGrade.LOW
    assert strong.evidence_grade is EvidenceGrade.HIGH
    assert any("blocked" in line for line in weak.rationale)
    assert all("blocked" not in line for line in strong.rationale)


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="positions"):
        assess_liquidity_buffer(
            positions=[],
            scenarios=_scenarios(),
            available_cash=10.0,
            validation=ValidationSnapshot(
                realized_periods=12,
                breach_count=0,
                regime_count=2,
                independent_challenge_runs=1,
                max_model_error=0.2,
            ),
        )

    with pytest.raises(ValueError, match="market_value"):
        PortfolioPosition(
            instrument_id="bad",
            market_value=0.0,
            daily_volatility=0.01,
            margin_ratio=0.1,
            liquidation_days=1.0,
            spread_bps=5.0,
        )
