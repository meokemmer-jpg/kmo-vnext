from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ErrorResult:
    ok: bool
    error: str
    status_code: int = 400


@dataclass(frozen=True)
class HotelsResult:
    ok: bool
    hotels: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class HotelDetailsResult:
    ok: bool
    hotel: dict[str, Any]


@dataclass(frozen=True)
class ReservationsResult:
    ok: bool
    reservations: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ReservationResult:
    ok: bool
    reservation: dict[str, Any]


@dataclass(frozen=True)
class RoomTypesResult:
    ok: bool
    room_types: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PaymentResult:
    ok: bool
    payment: dict[str, Any]


@dataclass(frozen=True)
class GuestHistoryResult:
    ok: bool
    guest_id: str
    reservations: tuple[dict[str, Any], ...]
    payments: tuple[dict[str, Any], ...]


class CloudbedsClient:
    """MVP Cloudbeds PMS adapter with a mock backend by default.

    Set KMO_CLOUDBEDS_BACKEND=real to route calls to the real backend stub.
    The real backend is intentionally not implemented in this MVP.
    """

    BACKEND_ENV_VAR = "KMO_CLOUDBEDS_BACKEND"

    def __init__(
        self,
        client_id: str = "mock-client-id",
        client_secret: str = "mock-client-secret",
        access_token: str | None = None,
        backend: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.backend = backend or os.getenv(self.BACKEND_ENV_VAR, "mock")
        self._lock = threading.RLock()
        self._access_token = access_token
        self._state = self._initial_state()

    def authenticate(self) -> str:
        if self.backend == "real":
            raise NotImplementedError("Real Cloudbeds API is not enabled in MVP adapter.")
        with self._lock:
            if not self.client_id or not self.client_secret:
                raise ValueError("client_id and client_secret are required")
            self._access_token = f"mock-oauth2-token-{uuid4().hex}"
            return self._access_token

    @property
    def access_token(self) -> str | None:
        with self._lock:
            return self._access_token

    def list_hotels(self) -> HotelsResult | ErrorResult:
        self._ensure_mock_backend()
        with self._lock:
            return HotelsResult(ok=True, hotels=tuple(self._copy(v) for v in self._state["hotels"].values()))

    def get_hotel_details(self, hotel_id: str) -> HotelDetailsResult | ErrorResult:
        self._ensure_mock_backend()
        error = self._require_fields({"hotel_id": hotel_id})
        if error:
            return error

        with self._lock:
            hotel = self._state["hotels"].get(hotel_id)
            if not hotel:
                return ErrorResult(ok=False, error="hotel not found", status_code=404)
            return HotelDetailsResult(ok=True, hotel=self._copy(hotel))

    def list_reservations(
        self,
        hotel_id: str | None = None,
        guest_id: str | None = None,
    ) -> ReservationsResult | ErrorResult:
        self._ensure_mock_backend()
        with self._lock:
            reservations = list(self._state["reservations"].values())
            if hotel_id is not None:
                reservations = [r for r in reservations if r["hotel_id"] == hotel_id]
            if guest_id is not None:
                reservations = [r for r in reservations if r["guest_id"] == guest_id]
            return ReservationsResult(ok=True, reservations=tuple(self._copy(r) for r in reservations))

    def post_reservation(
        self,
        hotel_id: str,
        guest_id: str,
        room_type_id: str,
        check_in: str,
        check_out: str,
        status: str = "confirmed",
    ) -> ReservationResult | ErrorResult:
        self._ensure_mock_backend()
        error = self._require_fields(
            {
                "hotel_id": hotel_id,
                "guest_id": guest_id,
                "room_type_id": room_type_id,
                "check_in": check_in,
                "check_out": check_out,
            }
        )
        if error:
            return error

        with self._lock:
            if hotel_id not in self._state["hotels"]:
                return ErrorResult(ok=False, error="hotel not found", status_code=404)
            if room_type_id not in self._state["room_types"]:
                return ErrorResult(ok=False, error="room type not found", status_code=404)
            if self._state["room_types"][room_type_id]["hotel_id"] != hotel_id:
                return ErrorResult(ok=False, error="room type does not belong to hotel", status_code=400)

            reservation_id = f"res_{uuid4().hex[:12]}"
            reservation = {
                "id": reservation_id,
                "hotel_id": hotel_id,
                "guest_id": guest_id,
                "room_type_id": room_type_id,
                "check_in": check_in,
                "check_out": check_out,
                "status": status,
                "created_at": self._now(),
            }
            self._state["reservations"][reservation_id] = reservation
            return ReservationResult(ok=True, reservation=self._copy(reservation))

    def list_room_types(self, hotel_id: str) -> RoomTypesResult | ErrorResult:
        self._ensure_mock_backend()
        error = self._require_fields({"hotel_id": hotel_id})
        if error:
            return error

        with self._lock:
            if hotel_id not in self._state["hotels"]:
                return ErrorResult(ok=False, error="hotel not found", status_code=404)
            room_types = [r for r in self._state["room_types"].values() if r["hotel_id"] == hotel_id]
            return RoomTypesResult(ok=True, room_types=tuple(self._copy(r) for r in room_types))

    def post_payment(
        self,
        reservation_id: str,
        amount: float,
        currency: str,
        method: str,
    ) -> PaymentResult | ErrorResult:
        self._ensure_mock_backend()
        error = self._require_fields(
            {
                "reservation_id": reservation_id,
                "currency": currency,
                "method": method,
            }
        )
        if error:
            return error
        if amount <= 0:
            return ErrorResult(ok=False, error="amount must be positive", status_code=400)

        with self._lock:
            reservation = self._state["reservations"].get(reservation_id)
            if not reservation:
                return ErrorResult(ok=False, error="reservation not found", status_code=404)

            payment_id = f"pay_{uuid4().hex[:12]}"
            payment = {
                "id": payment_id,
                "reservation_id": reservation_id,
                "guest_id": reservation["guest_id"],
                "hotel_id": reservation["hotel_id"],
                "amount": float(amount),
                "currency": currency.upper(),
                "method": method,
                "created_at": self._now(),
            }
            self._state["payments"][payment_id] = payment
            return PaymentResult(ok=True, payment=self._copy(payment))

    def get_guest_history(self, guest_id: str) -> GuestHistoryResult | ErrorResult:
        self._ensure_mock_backend()
        error = self._require_fields({"guest_id": guest_id})
        if error:
            return error

        with self._lock:
            reservations = [r for r in self._state["reservations"].values() if r["guest_id"] == guest_id]
            payments = [p for p in self._state["payments"].values() if p["guest_id"] == guest_id]
            return GuestHistoryResult(
                ok=True,
                guest_id=guest_id,
                reservations=tuple(self._copy(r) for r in reservations),
                payments=tuple(self._copy(p) for p in payments),
            )

    def _ensure_mock_backend(self) -> None:
        if self.backend == "real":
            raise NotImplementedError("Real Cloudbeds API is not enabled in MVP adapter.")
        if self.backend != "mock":
            raise ValueError(f"Unsupported Cloudbeds backend: {self.backend}")

    @staticmethod
    def _copy(value: dict[str, Any]) -> dict[str, Any]:
        return dict(value)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _require_fields(fields: dict[str, Any]) -> ErrorResult | None:
        missing = [name for name, value in fields.items() if value is None or value == ""]
        if missing:
            return ErrorResult(ok=False, error=f"missing required field: {', '.join(missing)}", status_code=400)
        return None

    @staticmethod
    def _initial_state() -> dict[str, dict[str, dict[str, Any]]]:
        return {
            "hotels": {
                "hotel_berlin": {
                    "id": "hotel_berlin",
                    "name": "KMO Berlin Mitte",
                    "city": "Berlin",
                    "country": "DE",
                    "timezone": "Europe/Berlin",
                },
                "hotel_hamburg": {
                    "id": "hotel_hamburg",
                    "name": "KMO Hamburg Hafen",
                    "city": "Hamburg",
                    "country": "DE",
                    "timezone": "Europe/Berlin",
                },
            },
            "room_types": {
                "rt_single_berlin": {
                    "id": "rt_single_berlin",
                    "hotel_id": "hotel_berlin",
                    "name": "Single",
                    "max_occupancy": 1,
                    "base_rate": 89.0,
                    "currency": "EUR",
                },
                "rt_double_berlin": {
                    "id": "rt_double_berlin",
                    "hotel_id": "hotel_berlin",
                    "name": "Double",
                    "max_occupancy": 2,
                    "base_rate": 129.0,
                    "currency": "EUR",
                },
                "rt_suite_hamburg": {
                    "id": "rt_suite_hamburg",
                    "hotel_id": "hotel_hamburg",
                    "name": "Suite",
                    "max_occupancy": 3,
                    "base_rate": 219.0,
                    "currency": "EUR",
                },
            },
            "reservations": {
                "res_seed_001": {
                    "id": "res_seed_001",
                    "hotel_id": "hotel_berlin",
                    "guest_id": "guest_001",
                    "room_type_id": "rt_single_berlin",
                    "check_in": "2026-06-01",
                    "check_out": "2026-06-03",
                    "status": "confirmed",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            },
            "payments": {
                "pay_seed_001": {
                    "id": "pay_seed_001",
                    "reservation_id": "res_seed_001",
                    "guest_id": "guest_001",
                    "hotel_id": "hotel_berlin",
                    "amount": 178.0,
                    "currency": "EUR",
                    "method": "card",
                    "created_at": "2026-01-01T00:01:00+00:00",
                }
            },
        }
