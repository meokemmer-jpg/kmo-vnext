from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import sqrt


class EvidenceGrade(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    instrument_id: str
    market_value: float
    daily_volatility: float
    margin_ratio: float
    liquidation_days: float
    spread_bps: float
    concentration_group: str = "default"

    def __post_init__(self) -> None:
        if not self.instrument_id.strip():
            raise ValueError("instrument_id must not be blank")
        if self.market_value <= 0:
            raise ValueError("market_value must be positive")
        if self.daily_volatility < 0:
            raise ValueError("daily_volatility must be non-negative")
        if not 0 <= self.margin_ratio <= 1:
            raise ValueError("margin_ratio must be between 0 and 1")
        if self.liquidation_days <= 0:
            raise ValueError("liquidation_days must be positive")
        if self.spread_bps < 0:
            raise ValueError("spread_bps must be non-negative")
        if not self.concentration_group.strip():
            raise ValueError("concentration_group must not be blank")


@dataclass(frozen=True, slots=True)
class StressScenario:
    name: str
    volatility_multiplier: float
    margin_multiplier: float
    liquidation_multiplier: float
    concentration_multiplier: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")
        for field_name in (
            "volatility_multiplier",
            "margin_multiplier",
            "liquidation_multiplier",
            "concentration_multiplier",
        ):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True, slots=True)
class ValidationSnapshot:
    realized_periods: int
    breach_count: int
    regime_count: int
    independent_challenge_runs: int
    max_model_error: float

    def __post_init__(self) -> None:
        if self.realized_periods < 0:
            raise ValueError("realized_periods must be non-negative")
        if self.breach_count < 0:
            raise ValueError("breach_count must be non-negative")
        if self.regime_count < 0:
            raise ValueError("regime_count must be non-negative")
        if self.independent_challenge_runs < 0:
            raise ValueError("independent_challenge_runs must be non-negative")
        if self.max_model_error < 0:
            raise ValueError("max_model_error must be non-negative")
        if self.breach_count > self.realized_periods:
            raise ValueError("breach_count cannot exceed realized_periods")


@dataclass(frozen=True, slots=True)
class LiquidityDecision:
    required_cash_ratio: float
    available_cash_ratio: float
    cash_buffer_gap: float
    binding_scenario: str
    evidence_grade: EvidenceGrade
    scenario_cash_needs: tuple[tuple[str, float], ...]
    rationale: tuple[str, ...]


def assess_liquidity_buffer(
    positions: list[PortfolioPosition],
    scenarios: list[StressScenario],
    available_cash: float,
    validation: ValidationSnapshot,
) -> LiquidityDecision:
    if not positions:
        raise ValueError("positions must not be empty")
    if not scenarios:
        raise ValueError("scenarios must not be empty")
    if available_cash < 0:
        raise ValueError("available_cash must be non-negative")

    gross_exposure = sum(position.market_value for position in positions)
    scenario_needs: list[tuple[str, float]] = []
    for scenario in scenarios:
        scenario_need = _scenario_cash_need(positions, scenario, gross_exposure)
        scenario_needs.append((scenario.name, scenario_need))

    binding_scenario, required_cash = max(scenario_needs, key=lambda item: item[1])
    required_cash_ratio = required_cash / gross_exposure
    available_cash_ratio = available_cash / gross_exposure
    cash_buffer_gap = required_cash_ratio - available_cash_ratio
    evidence_grade = _grade_validation(validation, len(scenarios))

    rationale = (
        f"binding scenario={binding_scenario}",
        f"gross exposure={gross_exposure:.2f}",
        f"required cash={required_cash:.2f}",
        f"available cash={available_cash:.2f}",
        f"validation grade={evidence_grade.value}",
    )
    if evidence_grade is not EvidenceGrade.HIGH:
        rationale += ("high evidence blocked by insufficient validation depth",)

    return LiquidityDecision(
        required_cash_ratio=required_cash_ratio,
        available_cash_ratio=available_cash_ratio,
        cash_buffer_gap=cash_buffer_gap,
        binding_scenario=binding_scenario,
        evidence_grade=evidence_grade,
        scenario_cash_needs=tuple(sorted(scenario_needs)),
        rationale=rationale,
    )


def _scenario_cash_need(
    positions: list[PortfolioPosition],
    scenario: StressScenario,
    gross_exposure: float,
) -> float:
    group_totals: dict[str, float] = {}
    for position in positions:
        group_totals[position.concentration_group] = (
            group_totals.get(position.concentration_group, 0.0) + position.market_value
        )

    need = 0.0
    for position in positions:
        stress_vol = position.daily_volatility * scenario.volatility_multiplier
        horizon = sqrt(position.liquidation_days * scenario.liquidation_multiplier)
        drawdown = position.market_value * stress_vol * horizon
        margin_call = position.market_value * position.margin_ratio * scenario.margin_multiplier
        execution_cost = (
            position.market_value
            * (position.spread_bps / 10_000.0)
            * horizon
        )
        group_weight = group_totals[position.concentration_group] / gross_exposure
        concentration_drag = (
            position.market_value * group_weight * scenario.concentration_multiplier
        )
        need += drawdown + margin_call + execution_cost + concentration_drag
    return need


def _grade_validation(
    validation: ValidationSnapshot,
    scenario_count: int,
) -> EvidenceGrade:
    if validation.realized_periods == 0:
        return EvidenceGrade.LOW

    breach_rate = validation.breach_count / validation.realized_periods
    scenario_depth_ok = validation.regime_count >= max(3, scenario_count)
    challenge_ok = validation.independent_challenge_runs >= 2
    error_ok = validation.max_model_error <= 0.10

    if (
        validation.realized_periods >= 24
        and breach_rate == 0
        and scenario_depth_ok
        and challenge_ok
        and error_ok
    ):
        return EvidenceGrade.HIGH

    if (
        validation.realized_periods >= 6
        and breach_rate <= 0.10
        and validation.regime_count >= 2
        and validation.max_model_error <= 0.25
    ):
        return EvidenceGrade.MEDIUM

    return EvidenceGrade.LOW
