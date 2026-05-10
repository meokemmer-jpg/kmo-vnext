from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol


class PMSAdapterError(Exception):
    """Base exception for PMS adapter failures."""


class PMSValidationError(PMSAdapterError, ValueError):
    """Raised when adapter input validation fails."""


class PMSNotFoundError(PMSAdapterError, KeyError):
    """Raised when a PMS object cannot be found."""


@dataclass(frozen=True)
class Result:
    ok: bool
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    error: str | None = None


@dataclass(frozen=True)
class PropertyResult(Result):
    property_id: str | None = None


@dataclass(frozen=True)
class ReservationResult(Result):
    reservation_id: str | None = None


class PMSBackend(Protocol):
    def get_property(self, property_id: str) -> PropertyResult:
        ...

    def list_reservations(self, property_id: str) -> Result:
        ...

    def create_reservation(self, property_id: str, payload: dict[str, Any]) -> ReservationResult:
        ...

    def get_reservation(self, reservation_id: str) -> ReservationResult:
        ...

    def update_reservation(self, reservation_id: str, payload: dict[str, Any]) -> ReservationResult:
        ...

    def cancel_reservation(self, reservation_id: str) -> ReservationResult:
        ...


@dataclass
class MockPMSBackend:
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _next_reservation_id: int = 1

    def __post_init__(self) -> None:
        if not self.properties:
            self.properties["prop_1"] = {
                "id": "prop_1",
                "name": "Mock Hotel",
                "currency": "EUR",
                "timezone": "Europe/Berlin",
            }

    def get_property(self, property_id: str) -> PropertyResult:
        _validate_id(property_id, "property_id")
        with self._lock:
            property_data = self.properties.get(property_id)
            if property_data is None:
                return PropertyResult(ok=False, error="property_not_found", property_id=property_id)
            return PropertyResult(ok=True, data=dict(property_data), property_id=property_id)

    def list_reservations(self, property_id: str) -> Result:
        _validate_id(property_id, "property_id")
        with self._lock:
            if property_id not in self.properties:
                return Result(ok=False, error="property_not_found")

            rows = [
                dict(reservation)
                for reservation in self.reservations.values()
                if reservation["property_id"] == property_id
            ]
            rows.sort(key=lambda item: item["id"])
            return Result(ok=True, data=rows)

    def create_reservation(self, property_id: str, payload: dict[str, Any]) -> ReservationResult:
        _validate_id(property_id, "property_id")
        _validate_reservation_payload(payload, require_guest=True)

        with self._lock:
            if property_id not in self.properties:
                return ReservationResult(ok=False, error="property_not_found")

            reservation_id = f"res_{self._next_reservation_id}"
            self._next_reservation_id += 1

            reservation = {
                "id": reservation_id,
                "property_id": property_id,
                "guest_name": payload["guest_name"],
                "arrival_date": payload["arrival_date"],
                "departure_date": payload["departure_date"],
                "status": payload.get("status", "confirmed"),
                "room_type": payload.get("room_type", "standard"),
            }
            self.reservations[reservation_id] = reservation
            return ReservationResult(
                ok=True,
                data=dict(reservation),
                reservation_id=reservation_id,
            )

    def get_reservation(self, reservation_id: str) -> ReservationResult:
        _validate_id(reservation_id, "reservation_id")
        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None:
                return ReservationResult(
                    ok=False,
                    error="reservation_not_found",
                    reservation_id=reservation_id,
                )
            return ReservationResult(
                ok=True,
                data=dict(reservation),
                reservation_id=reservation_id,
            )

    def update_reservation(self, reservation_id: str, payload: dict[str, Any]) -> ReservationResult:
        _validate_id(reservation_id, "reservation_id")
        _validate_reservation_payload(payload, require_guest=False)

        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None:
                return ReservationResult(
                    ok=False,
                    error="reservation_not_found",
                    reservation_id=reservation_id,
                )

            updated = dict(reservation)
            allowed_fields = {
                "guest_name",
                "arrival_date",
                "departure_date",
                "status",
                "room_type",
            }
            for key in allowed_fields:
                if key in payload:
                    updated[key] = payload[key]

            self.reservations[reservation_id] = updated
            return ReservationResult(
                ok=True,
                data=dict(updated),
                reservation_id=reservation_id,
            )

    def cancel_reservation(self, reservation_id: str) -> ReservationResult:
        _validate_id(reservation_id, "reservation_id")
        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None:
                return ReservationResult(
                    ok=False,
                    error="reservation_not_found",
                    reservation_id=reservation_id,
                )

            cancelled = dict(reservation)
            cancelled["status"] = "cancelled"
            self.reservations[reservation_id] = cancelled
            return ReservationResult(
                ok=True,
                data=dict(cancelled),
                reservation_id=reservation_id,
            )


class GenericPMSAdapter:
    def __init__(self, backend: PMSBackend | None = None) -> None:
        self._lock = threading.RLock()
        self._backend: PMSBackend = backend or self._backend_from_env()

    @property
    def backend(self) -> PMSBackend:
        with self._lock:
            return self._backend

    def set_backend(self, backend: PMSBackend) -> None:
        if backend is None:
            raise PMSValidationError("backend is required")
        with self._lock:
            self._backend = backend

    def get_property(self, property_id: str) -> PropertyResult:
        with self._lock:
            return self._backend.get_property(property_id)

    def list_reservations(self, property_id: str) -> Result:
        with self._lock:
            return self._backend.list_reservations(property_id)

    def create_reservation(self, property_id: str, payload: dict[str, Any]) -> ReservationResult:
        with self._lock:
            return self._backend.create_reservation(property_id, payload)

    def get_reservation(self, reservation_id: str) -> ReservationResult:
        with self._lock:
            return self._backend.get_reservation(reservation_id)

    def update_reservation(self, reservation_id: str, payload: dict[str, Any]) -> ReservationResult:
        with self._lock:
            return self._backend.update_reservation(reservation_id, payload)

    def cancel_reservation(self, reservation_id: str) -> ReservationResult:
        with self._lock:
            return self._backend.cancel_reservation(reservation_id)

    @staticmethod
    def _backend_from_env() -> PMSBackend:
        mode = os.getenv("KMO_PMS_BACKEND", "mock").strip().lower()
        if mode in {"", "mock"}:
            return MockPMSBackend()
        raise PMSAdapterError(
            f"Unsupported PMS backend {mode!r}. MVP supports only mock backend."
        )


def _validate_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PMSValidationError(f"{field_name} must be a non-empty string")


def _validate_reservation_payload(payload: dict[str, Any], *, require_guest: bool) -> None:
    if not isinstance(payload, dict):
        raise PMSValidationError("payload must be a dict")

    required = ["arrival_date", "departure_date"]
    if require_guest:
        required.insert(0, "guest_name")

    for key in required:
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise PMSValidationError(f"{key} must be a non-empty string")

    arrival = payload.get("arrival_date")
    departure = payload.get("departure_date")
    if isinstance(arrival, str) and isinstance(departure, str) and arrival >= departure:
        raise PMSValidationError("arrival_date must be before departure_date")
