from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class RateRecommendation:
    property_id: str
    room_type: str
    stay_date: str
    current_rate: float
    recommended_rate: float
    confidence: float
    rationale: str


@dataclass(frozen=True)
class RateRecommendationResult:
    recommendations: tuple[RateRecommendation, ...]
    backend: str


@dataclass(frozen=True)
class RateDecisionResult:
    decision_id: str
    property_id: str
    room_type: str
    stay_date: str
    accepted_rate: float
    status: str
    backend: str


@dataclass(frozen=True)
class CompetitorRate:
    competitor: str
    room_type: str
    stay_date: str
    rate: float
    currency: str


@dataclass(frozen=True)
class CompetitorRatesResult:
    property_id: str
    rates: tuple[CompetitorRate, ...]
    backend: str


@dataclass(frozen=True)
class ForecastPoint:
    property_id: str
    stay_date: str
    value: float
    confidence: float


@dataclass(frozen=True)
class ForecastResult:
    forecast_type: str
    points: tuple[ForecastPoint, ...]
    backend: str


class RateGainRMSClient:
    ENV_BACKEND = "RATEGAIN_RMS_BACKEND"

    def __init__(self, *, backend: str | None = None) -> None:
        self.backend = backend or os.getenv(self.ENV_BACKEND, "mock")
        self._lock = threading.RLock()
        self._rate_decisions: dict[str, RateDecisionResult] = {}

        if self.backend != "mock":
            raise NotImplementedError(
                "Real RateGain RMS API backend is gated for future integration. "
                "Use RATEGAIN_RMS_BACKEND=mock for MVP testing."
            )

    def get_rate_recommendations(
        self,
        *,
        property_id: str,
        room_type: str,
        start_date: str,
        nights: int = 1,
        current_rate: float = 100.0,
    ) -> RateRecommendationResult:
        self._validate_text("property_id", property_id)
        self._validate_text("room_type", room_type)
        start = self._parse_date(start_date)
        self._validate_positive_int("nights", nights)
        self._validate_positive_number("current_rate", current_rate)

        recommendations: list[RateRecommendation] = []
        with self._lock:
            for offset in range(nights):
                stay = start + timedelta(days=offset)
                seasonal_factor = 1.0 + ((stay.weekday() in (4, 5)) * 0.18)
                demand_factor = 1.0 + min(offset, 14) * 0.01
                recommended = round(current_rate * seasonal_factor * demand_factor, 2)
                confidence = round(max(0.72, 0.92 - offset * 0.01), 2)
                recommendations.append(
                    RateRecommendation(
                        property_id=property_id,
                        room_type=room_type,
                        stay_date=stay.isoformat(),
                        current_rate=float(current_rate),
                        recommended_rate=recommended,
                        confidence=confidence,
                        rationale="Mock ML recommendation using weekday demand and booking-window uplift.",
                    )
                )

        return RateRecommendationResult(
            recommendations=tuple(recommendations),
            backend=self.backend,
        )

    def push_rate_decision(
        self,
        *,
        property_id: str,
        room_type: str,
        stay_date: str,
        accepted_rate: float,
    ) -> RateDecisionResult:
        self._validate_text("property_id", property_id)
        self._validate_text("room_type", room_type)
        parsed_date = self._parse_date(stay_date)
        self._validate_positive_number("accepted_rate", accepted_rate)

        decision_id = (
            f"{property_id}:{room_type}:{parsed_date.isoformat()}".replace(" ", "_")
        )

        with self._lock:
            result = RateDecisionResult(
                decision_id=decision_id,
                property_id=property_id,
                room_type=room_type,
                stay_date=parsed_date.isoformat(),
                accepted_rate=float(accepted_rate),
                status="stored",
                backend=self.backend,
            )
            self._rate_decisions[decision_id] = result
            return result

    def get_competitor_rates(
        self,
        *,
        property_id: str,
        room_type: str,
        stay_date: str,
        competitors: tuple[str, ...] | list[str] | None = None,
    ) -> CompetitorRatesResult:
        self._validate_text("property_id", property_id)
        self._validate_text("room_type", room_type)
        parsed_date = self._parse_date(stay_date)
        names = tuple(competitors or ("CompSet Alpha", "CompSet Beta", "CompSet Gamma"))

        if not names:
            raise ValueError("competitors must not be empty")

        rates: list[CompetitorRate] = []
        with self._lock:
            for index, competitor in enumerate(names):
                self._validate_text("competitor", competitor)
                rates.append(
                    CompetitorRate(
                        competitor=competitor,
                        room_type=room_type,
                        stay_date=parsed_date.isoformat(),
                        rate=round(104.0 + index * 7.5 + len(property_id) * 0.4, 2),
                        currency="EUR",
                    )
                )

        return CompetitorRatesResult(
            property_id=property_id,
            rates=tuple(rates),
            backend=self.backend,
        )

    def demand_forecast(
        self,
        *,
        property_id: str,
        start_date: str,
        days: int = 7,
    ) -> ForecastResult:
        return self._forecast(
            forecast_type="demand",
            property_id=property_id,
            start_date=start_date,
            days=days,
            base=68.0,
            step=2.5,
            cap=100.0,
        )

    def occupancy_forecast(
        self,
        *,
        property_id: str,
        start_date: str,
        days: int = 7,
    ) -> ForecastResult:
        return self._forecast(
            forecast_type="occupancy",
            property_id=property_id,
            start_date=start_date,
            days=days,
            base=61.0,
            step=3.0,
            cap=98.0,
        )

    def stored_decisions(self) -> tuple[RateDecisionResult, ...]:
        with self._lock:
            return tuple(self._rate_decisions.values())

    def _forecast(
        self,
        *,
        forecast_type: str,
        property_id: str,
        start_date: str,
        days: int,
        base: float,
        step: float,
        cap: float,
    ) -> ForecastResult:
        self._validate_text("property_id", property_id)
        start = self._parse_date(start_date)
        self._validate_positive_int("days", days)

        points: list[ForecastPoint] = []
        with self._lock:
            for offset in range(days):
                stay = start + timedelta(days=offset)
                weekend_lift = 8.0 if stay.weekday() in (4, 5) else 0.0
                value = min(cap, base + offset * step + weekend_lift)
                points.append(
                    ForecastPoint(
                        property_id=property_id,
                        stay_date=stay.isoformat(),
                        value=round(value, 2),
                        confidence=round(max(0.7, 0.9 - offset * 0.015), 2),
                    )
                )

        return ForecastResult(
            forecast_type=forecast_type,
            points=tuple(points),
            backend=self.backend,
        )

    @staticmethod
    def _validate_text(name: str, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")

    @staticmethod
    def _validate_positive_int(name: str, value: Any) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    @staticmethod
    def _validate_positive_number(name: str, value: Any) -> None:
        if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{name} must be a positive number")

    @staticmethod
    def _parse_date(value: str) -> date:
        if not isinstance(value, str):
            raise ValueError("date must be an ISO date string")
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD format") from exc
