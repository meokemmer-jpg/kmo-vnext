from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
import threading
from typing import Any
from uuid import uuid4


class ApaleoError(ValueError):
    pass


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class TokenResult(Result):
    access_token: str = ""
    expires_at: datetime | None = None


@dataclass(frozen=True)
class PropertyResult(Result):
    property: dict[str, Any] | None = None
    properties: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ReservationResult(Result):
    reservation: dict[str, Any] | None = None
    reservations: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RatePlanResult(Result):
    rate_plan: dict[str, Any] | None = None
    rate_plans: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class InventoryUpdated(Result):
    property_id: str = ""
    rate_plan_id: str = ""
    date: str = ""
    count: int = 0


@dataclass(frozen=True)
class ReservationCreated(Result):
    reservation_id: str = ""
    property_id: str = ""
    guest: dict[str, Any] | None = None
    dates: dict[str, str] | None = None
    rate_plan_id: str = ""


@dataclass(frozen=True)
class ReservationCancelled(Result):
    reservation_id: str = ""
    status: str = "cancelled"


class ApaleoClient:
    def __init__(self, *, use_real_api: bool | None = None) -> None:
        self.use_real_api = (
            os.getenv("APALEO_USE_REAL_API", "").lower() in {"1", "true", "yes"}
            if use_real_api is None
            else use_real_api
        )
        self._lock = threading.RLock()
        self._token: TokenResult | None = None
        self._properties: dict[str, dict[str, Any]] = {}
        self._rate_plans: dict[str, dict[str, dict[str, Any]]] = {}
        self._reservations: dict[str, dict[str, Any]] = {}
        self._inventory: dict[tuple[str, str, str], int] = {}
        self._seed_mock_backend()

    def refresh_token(self) -> TokenResult:
        if self.use_real_api:
            raise NotImplementedError("Real Apaleo API mode is gated and not implemented in this MVP.")

        with self._lock:
            self._token = TokenResult(
                ok=True,
                message="mock token refreshed",
                access_token=f"mock-token-{uuid4().hex}",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            return self._token

    def list_properties(self) -> PropertyResult:
        self._ensure_mock_mode()
        with self._lock:
            return PropertyResult(
                ok=True,
                properties=tuple(self._copy(item) for item in self._properties.values()),
            )

    def get_property(self, id: str) -> PropertyResult:
        self._ensure_mock_mode()
        self._require_text(id, "id")
        with self._lock:
            property_item = self._properties.get(id)
            if property_item is None:
                return PropertyResult(ok=False, message=f"Property not found: {id}")
            return PropertyResult(ok=True, property=self._copy(property_item))

    def list_reservations(self, propertyId: str, from_: str | date, to: str | date) -> ReservationResult:
        self._ensure_mock_mode()
        self._require_property(propertyId)
        start = self._parse_date(from_, "from")
        end = self._parse_date(to, "to")
        if start > end:
            raise ApaleoError("from must be before or equal to to")

        with self._lock:
            reservations = []
            for reservation in self._reservations.values():
                if reservation["propertyId"] != propertyId:
                    continue
                arrival = self._parse_date(reservation["dates"]["from"], "reservation.from")
                departure = self._parse_date(reservation["dates"]["to"], "reservation.to")
                if arrival <= end and departure >= start:
                    reservations.append(self._copy(reservation))
            return ReservationResult(ok=True, reservations=tuple(reservations))

    def create_reservation(
        self,
        propertyId: str,
        guest: dict[str, Any],
        dates: dict[str, str],
        ratePlanId: str,
    ) -> ReservationCreated:
        self._ensure_mock_mode()
        self._require_property(propertyId)
        self._require_rate_plan(propertyId, ratePlanId)
        self._validate_guest(guest)
        start, end = self._validate_dates(dates)

        if start > end:
            raise ApaleoError("dates.from must be before or equal to dates.to")

        with self._lock:
            reservation_id = f"RES-{uuid4().hex[:10].upper()}"
            reservation = {
                "id": reservation_id,
                "propertyId": propertyId,
                "guest": self._copy(guest),
                "dates": {"from": start.isoformat(), "to": end.isoformat()},
                "ratePlanId": ratePlanId,
                "status": "confirmed",
            }
            self._reservations[reservation_id] = reservation
            return ReservationCreated(
                ok=True,
                message="reservation created",
                reservation_id=reservation_id,
                property_id=propertyId,
                guest=self._copy(guest),
                dates=self._copy(reservation["dates"]),
                rate_plan_id=ratePlanId,
            )

    def cancel_reservation(self, id: str) -> ReservationCancelled:
        self._ensure_mock_mode()
        self._require_text(id, "id")
        with self._lock:
            reservation = self._reservations.get(id)
            if reservation is None:
                return ReservationCancelled(ok=False, message=f"Reservation not found: {id}", reservation_id=id)
            reservation["status"] = "cancelled"
            return ReservationCancelled(ok=True, message="reservation cancelled", reservation_id=id)

    def list_rate_plans(self, propertyId: str) -> RatePlanResult:
        self._ensure_mock_mode()
        self._require_property(propertyId)
        with self._lock:
            return RatePlanResult(
                ok=True,
                rate_plans=tuple(self._copy(item) for item in self._rate_plans[propertyId].values()),
            )

    def update_inventory(
        self,
        propertyId: str,
        ratePlanId: str,
        date: str | datetime | date,
        count: int,
    ) -> InventoryUpdated:
        self._ensure_mock_mode()
        self._require_property(propertyId)
        self._require_rate_plan(propertyId, ratePlanId)
        inventory_date = self._parse_date(date, "date")
        if not isinstance(count, int) or count < 0:
            raise ApaleoError("count must be a non-negative integer")

        with self._lock:
            key = (propertyId, ratePlanId, inventory_date.isoformat())
            self._inventory[key] = count
            return InventoryUpdated(
                ok=True,
                message="inventory updated",
                property_id=propertyId,
                rate_plan_id=ratePlanId,
                date=inventory_date.isoformat(),
                count=count,
            )

    def get_inventory_count(self, propertyId: str, ratePlanId: str, date: str | datetime | date) -> int | None:
        self._ensure_mock_mode()
        inventory_date = self._parse_date(date, "date")
        with self._lock:
            return self._inventory.get((propertyId, ratePlanId, inventory_date.isoformat()))

    def _seed_mock_backend(self) -> None:
        with self._lock:
            self._properties = {
                "BER001": {"id": "BER001", "name": "KMO Berlin Mitte", "countryCode": "DE"},
                "MUC001": {"id": "MUC001", "name": "KMO Munich Central", "countryCode": "DE"},
            }
            self._rate_plans = {
                "BER001": {
                    "BAR": {"id": "BAR", "propertyId": "BER001", "name": "Best Available Rate"},
                    "NRF": {"id": "NRF", "propertyId": "BER001", "name": "Non Refundable"},
                },
                "MUC001": {
                    "BAR": {"id": "BAR", "propertyId": "MUC001", "name": "Best Available Rate"},
                },
            }

    def _ensure_mock_mode(self) -> None:
        if self.use_real_api:
            raise NotImplementedError("Real Apaleo API mode is gated and not implemented in this MVP.")
        token = self._token
        if token is None or token.expires_at is None or token.expires_at <= datetime.now(timezone.utc):
            self.refresh_token()

    def _require_property(self, property_id: str) -> None:
        self._require_text(property_id, "propertyId")
        with self._lock:
            if property_id not in self._properties:
                raise ApaleoError(f"Unknown propertyId: {property_id}")

    def _require_rate_plan(self, property_id: str, rate_plan_id: str) -> None:
        self._require_text(rate_plan_id, "ratePlanId")
        with self._lock:
            if rate_plan_id not in self._rate_plans.get(property_id, {}):
                raise ApaleoError(f"Unknown ratePlanId for property {property_id}: {rate_plan_id}")

    @staticmethod
    def _require_text(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ApaleoError(f"{name} must be a non-empty string")

    @classmethod
    def _validate_guest(cls, guest: dict[str, Any]) -> None:
        if not isinstance(guest, dict):
            raise ApaleoError("guest must be a dictionary")
        cls._require_text(str(guest.get("firstName", "")), "guest.firstName")
        cls._require_text(str(guest.get("lastName", "")), "guest.lastName")

    @classmethod
    def _validate_dates(cls, dates: dict[str, str]) -> tuple[date, date]:
        if not isinstance(dates, dict):
            raise ApaleoError("dates must be a dictionary")
        return cls._parse_date(dates.get("from"), "dates.from"), cls._parse_date(dates.get("to"), "dates.to")

    @staticmethod
    def _parse_date(value: str | datetime | date | None, name: str) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise ApaleoError(f"{name} must be an ISO date") from exc
        raise ApaleoError(f"{name} must be an ISO date")

    @staticmethod
    def _copy(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: ApaleoClient._copy(item) for key, item in value.items()}
        if isinstance(value, list):
            return [ApaleoClient._copy(item) for item in value]
        if isinstance(value, tuple):
            return tuple(ApaleoClient._copy(item) for item in value)
        return value
