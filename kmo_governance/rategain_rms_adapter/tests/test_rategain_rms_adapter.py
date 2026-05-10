from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.rategain_rms_adapter import (
    CompetitorRatesResult,
    ForecastResult,
    RateDecisionResult,
    RateGainRMSClient,
    RateRecommendationResult,
)


def test_default_backend_is_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RATEGAIN_RMS_BACKEND", raising=False)

    client = RateGainRMSClient()

    assert client.backend == "mock"


def test_env_var_real_backend_is_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATEGAIN_RMS_BACKEND", "real")

    with pytest.raises(NotImplementedError):
        RateGainRMSClient()


def test_get_rate_recommendations_returns_mock_ml_results() -> None:
    client = RateGainRMSClient()

    result = client.get_rate_recommendations(
        property_id="BER001",
        room_type="DLX",
        start_date="2026-06-05",
        nights=2,
        current_rate=150,
    )

    assert isinstance(result, RateRecommendationResult)
    assert len(result.recommendations) == 2
    assert result.recommendations[0].recommended_rate > 150
    assert result.recommendations[0].confidence > 0
    assert result.backend == "mock"


def test_get_rate_recommendations_validates_property_id() -> None:
    client = RateGainRMSClient()

    with pytest.raises(ValueError, match="property_id"):
        client.get_rate_recommendations(
            property_id="",
            room_type="DLX",
            start_date="2026-06-05",
        )


def test_get_rate_recommendations_validates_date() -> None:
    client = RateGainRMSClient()

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        client.get_rate_recommendations(
            property_id="BER001",
            room_type="DLX",
            start_date="06-05-2026",
        )


def test_get_rate_recommendations_validates_nights() -> None:
    client = RateGainRMSClient()

    with pytest.raises(ValueError, match="nights"):
        client.get_rate_recommendations(
            property_id="BER001",
            room_type="DLX",
            start_date="2026-06-05",
            nights=0,
        )


def test_push_rate_decision_stores_decision() -> None:
    client = RateGainRMSClient()

    result = client.push_rate_decision(
        property_id="BER001",
        room_type="STD",
        stay_date="2026-06-05",
        accepted_rate=129.5,
    )

    assert isinstance(result, RateDecisionResult)
    assert result.status == "stored"
    assert result in client.stored_decisions()


def test_push_rate_decision_overwrites_same_decision_key() -> None:
    client = RateGainRMSClient()

    client.push_rate_decision(
        property_id="BER001",
        room_type="STD",
        stay_date="2026-06-05",
        accepted_rate=129.5,
    )
    second = client.push_rate_decision(
        property_id="BER001",
        room_type="STD",
        stay_date="2026-06-05",
        accepted_rate=139.5,
    )

    stored = client.stored_decisions()
    assert len(stored) == 1
    assert stored[0] == second
    assert stored[0].accepted_rate == 139.5


def test_push_rate_decision_validates_rate() -> None:
    client = RateGainRMSClient()

    with pytest.raises(ValueError, match="accepted_rate"):
        client.push_rate_decision(
            property_id="BER001",
            room_type="STD",
            stay_date="2026-06-05",
            accepted_rate=-1,
        )


def test_get_competitor_rates_returns_rates() -> None:
    client = RateGainRMSClient()

    result = client.get_competitor_rates(
        property_id="BER001",
        room_type="STD",
        stay_date="2026-06-05",
        competitors=["A", "B"],
    )

    assert isinstance(result, CompetitorRatesResult)
    assert len(result.rates) == 2
    assert result.rates[0].currency == "EUR"


def test_forecasts_return_expected_points() -> None:
    client = RateGainRMSClient()

    demand = client.demand_forecast(
        property_id="BER001",
        start_date="2026-06-05",
        days=3,
    )
    occupancy = client.occupancy_forecast(
        property_id="BER001",
        start_date="2026-06-05",
        days=2,
    )

    assert isinstance(demand, ForecastResult)
    assert demand.forecast_type == "demand"
    assert len(demand.points) == 3
    assert occupancy.forecast_type == "occupancy"
    assert len(occupancy.points) == 2


def test_result_dataclasses_are_frozen() -> None:
    client = RateGainRMSClient()
    result = client.get_rate_recommendations(
        property_id="BER001",
        room_type="DLX",
        start_date="2026-06-05",
    )

    with pytest.raises(FrozenInstanceError):
        result.backend = "changed"  # type: ignore[misc]
