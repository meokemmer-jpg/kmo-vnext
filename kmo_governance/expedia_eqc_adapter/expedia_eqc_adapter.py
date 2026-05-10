from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal


BackendMode = Literal["mock", "live"]


@dataclass(frozen=True)
class Result:
    ok: bool
    status: str
    message: str = ""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class PropertyResult(Result):
    properties: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RateAvailabilityResult(Result):
    property_id: str = ""
    room_type_id: str = ""
    rate_plan_id: str = ""


@dataclass(frozen=True)
class BookingResult(Result):
    booking_id: str = ""
    property_id: str = ""
    state: str = ""


@dataclass(frozen=True)
class RefundResult(Result):
    booking_id: str = ""
    refund_id: str = ""
    amount: float = 0.0


class ExpediaEQCClient:
    """EQC v3-shaped MVP adapter with an in-memory mock backend.

    Real API support is intentionally gated. Set EXPEDIA_EQC_BACKEND=live to
    fail fast until transport/auth implementation is added.
    """

    ENV_BACKEND = "EXPEDIA_EQC_BACKEND"

    def __init__(
        self,
        *,
        backend: BackendMode | None = None,
        seed_properties: list[dict[str, Any]] | None = None,
    ) -> None:
        self.backend: BackendMode = backend or os.getenv(self.ENV_BACKEND, "mock").lower()  # type: ignore[assignment]
        if self.backend not in {"mock", "live"}:
            raise ValueError("backend must be 'mock' or 'live'")
        if self.backend == "live":
            raise NotImplementedError("live Expedia EQC transport is not implemented in MVP")

        self._lock = threading.RLock()
        self._properties: dict[str, dict[str, Any]] = {}
        self._inventory: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._bookings: dict[str, dict[str, Any]] = {}
        self._refunds: dict[str, dict[str, Any]] = {}

        for prop in seed_properties or self._default_properties():
            property_id = self._require_text(prop.get("property_id"), "property_id")
            self._properties[property_id] = dict(prop)

    def list_properties(self) -> PropertyResult:
        with self._lock:
            properties = tuple(dict(item) for item in self._properties.values())
        return PropertyResult(ok=True, status="success", properties=properties)

    def push_rate_availability(
        self,
        *,
        property_id: str,
        room_type_id: str,
        rate_plan_id: str,
        stay_date: str,
        rate: float,
        available: int,
        currency: str = "USD",
    ) -> RateAvailabilityResult:
        error = self._validate_rate_availability(
            property_id=property_id,
            room_type_id=room_type_id,
            rate_plan_id=rate_plan_id,
            stay_date=stay_date,
            rate=rate,
            available=available,
            currency=currency,
        )
        if error:
            return RateAvailabilityResult(ok=False, status="validation_error", message=error)

        with self._lock:
            if property_id not in self._properties:
                return RateAvailabilityResult(
                    ok=False,
                    status="not_found",
                    message="property_id does not exist",
                    property_id=property_id,
                    room_type_id=room_type_id,
                    rate_plan_id=rate_plan_id,
                )
            key = (property_id, room_type_id, rate_plan_id, stay_date)
            self._inventory[key] = {
                "property_id": property_id,
                "room_type_id": room_type_id,
                "rate_plan_id": rate_plan_id,
                "stay_date": stay_date,
                "rate": float(rate),
                "available": int(available),
                "currency": currency.upper(),
            }

        return RateAvailabilityResult(
            ok=True,
            status="success",
            property_id=property_id,
            room_type_id=room_type_id,
            rate_plan_id=rate_plan_id,
        )

    def confirm_booking(
        self,
        *,
        property_id: str,
        room_type_id: str,
        rate_plan_id: str,
        stay_date: str,
        guest_name: str,
        amount: float,
        currency: str = "USD",
        booking_id: str | None = None,
    ) -> BookingResult:
        error = self._validate_booking_input(
            property_id=property_id,
            room_type_id=room_type_id,
            rate_plan_id=rate_plan_id,
            stay_date=stay_date,
            guest_name=guest_name,
            amount=amount,
            currency=currency,
        )
        if error:
            return BookingResult(ok=False, status="validation_error", message=error)

        with self._lock:
            if property_id not in self._properties:
                return BookingResult(ok=False, status="not_found", message="property_id does not exist")

            inventory_key = (property_id, room_type_id, rate_plan_id, stay_date)
            inventory = self._inventory.get(inventory_key)
            if not inventory or inventory["available"] <= 0:
                return BookingResult(ok=False, status="sold_out", message="no availability for requested stay")

            resolved_booking_id = booking_id or f"EQC-{uuid.uuid4().hex[:12].upper()}"
            if resolved_booking_id in self._bookings:
                return BookingResult(
                    ok=False,
                    status="conflict",
                    message="booking_id already exists",
                    booking_id=resolved_booking_id,
                    property_id=property_id,
                    state=self._bookings[resolved_booking_id]["state"],
                )

            inventory["available"] -= 1
            self._bookings[resolved_booking_id] = {
                "booking_id": resolved_booking_id,
                "property_id": property_id,
                "room_type_id": room_type_id,
                "rate_plan_id": rate_plan_id,
                "stay_date": stay_date,
                "guest_name": guest_name,
                "amount": float(amount),
                "currency": currency.upper(),
                "state": "confirmed",
            }

        return BookingResult(
            ok=True,
            status="success",
            booking_id=resolved_booking_id,
            property_id=property_id,
            state="confirmed",
        )

    def modify_booking(self, *, booking_id: str, **changes: Any) -> BookingResult:
        if not self._is_text(booking_id):
            return BookingResult(ok=False, status="validation_error", message="booking_id is required")
        allowed = {"guest_name", "stay_date", "amount"}
        invalid = set(changes) - allowed
        if invalid:
            return BookingResult(
                ok=False,
                status="validation_error",
                message=f"unsupported change fields: {', '.join(sorted(invalid))}",
                booking_id=booking_id,
            )

        with self._lock:
            booking = self._bookings.get(booking_id)
            if not booking:
                return BookingResult(ok=False, status="not_found", message="booking_id does not exist", booking_id=booking_id)
            if booking["state"] == "refunded":
                return BookingResult(ok=False, status="invalid_state", message="refunded booking cannot be modified", booking_id=booking_id)
            if booking["state"] == "cancelled":
                return BookingResult(ok=False, status="invalid_state", message="cancelled booking cannot be modified", booking_id=booking_id)

            if "guest_name" in changes and not self._is_text(changes["guest_name"]):
                return BookingResult(ok=False, status="validation_error", message="guest_name must be non-empty", booking_id=booking_id)
            if "stay_date" in changes and not self._is_iso_date(changes["stay_date"]):
                return BookingResult(ok=False, status="validation_error", message="stay_date must be YYYY-MM-DD", booking_id=booking_id)
            if "amount" in changes and float(changes["amount"]) < 0:
                return BookingResult(ok=False, status="validation_error", message="amount must be non-negative", booking_id=booking_id)

            booking.update(changes)

        return BookingResult(
            ok=True,
            status="success",
            booking_id=booking_id,
            property_id=booking["property_id"],
            state=booking["state"],
        )

    def refund_booking(self, *, booking_id: str, amount: float | None = None) -> RefundResult:
        if not self._is_text(booking_id):
            return RefundResult(ok=False, status="validation_error", message="booking_id is required")
        if amount is not None and amount <= 0:
            return RefundResult(ok=False, status="validation_error", message="amount must be positive", booking_id=booking_id)

        with self._lock:
            booking = self._bookings.get(booking_id)
            if not booking:
                return RefundResult(ok=False, status="not_found", message="booking_id does not exist", booking_id=booking_id)
            if booking["state"] == "refunded":
                return RefundResult(ok=False, status="invalid_state", message="booking already refunded", booking_id=booking_id)

            refund_amount = float(amount if amount is not None else booking["amount"])
            if refund_amount > float(booking["amount"]):
                return RefundResult(ok=False, status="validation_error", message="refund exceeds booking amount", booking_id=booking_id)

            refund_id = f"REF-{uuid.uuid4().hex[:12].upper()}"
            booking["state"] = "refunded"
            self._refunds[refund_id] = {
                "refund_id": refund_id,
                "booking_id": booking_id,
                "amount": refund_amount,
                "currency": booking["currency"],
            }

        return RefundResult(
            ok=True,
            status="success",
            booking_id=booking_id,
            refund_id=refund_id,
            amount=refund_amount,
        )

    def _validate_rate_availability(
        self,
        *,
        property_id: str,
        room_type_id: str,
        rate_plan_id: str,
        stay_date: str,
        rate: float,
        available: int,
        currency: str,
    ) -> str:
        if not all(self._is_text(value) for value in [property_id, room_type_id, rate_plan_id, currency]):
            return "property_id, room_type_id, rate_plan_id, and currency are required"
        if not self._is_iso_date(stay_date):
            return "stay_date must be YYYY-MM-DD"
        if rate < 0:
            return "rate must be non-negative"
        if available < 0:
            return "available must be non-negative"
        return ""

    def _validate_booking_input(
        self,
        *,
        property_id: str,
        room_type_id: str,
        rate_plan_id: str,
        stay_date: str,
        guest_name: str,
        amount: float,
        currency: str,
    ) -> str:
        if not all(self._is_text(value) for value in [property_id, room_type_id, rate_plan_id, guest_name, currency]):
            return "property_id, room_type_id, rate_plan_id, guest_name, and currency are required"
        if not self._is_iso_date(stay_date):
            return "stay_date must be YYYY-MM-DD"
        if amount < 0:
            return "amount must be non-negative"
        return ""

    @staticmethod
    def _default_properties() -> list[dict[str, Any]]:
        return [
            {
                "property_id": "P-100",
                "name": "Mock EQC Hotel",
                "market": "SEA",
                "status": "active",
            }
        ]

    @staticmethod
    def _is_text(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @classmethod
    def _require_text(cls, value: Any, name: str) -> str:
        if not cls._is_text(value):
            raise ValueError(f"{name} is required")
        return value

    @staticmethod
    def _is_iso_date(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
