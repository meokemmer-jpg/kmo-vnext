from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar


class MewsAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class ConfigurationResult(Result):
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReservationResult(Result):
    reservation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReservationsResult(Result):
    reservations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RoomsResult(Result):
    rooms: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RateGroupsResult(Result):
    rate_groups: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AvailabilityBlockResult(Result):
    availability: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChargeResult(Result):
    charge: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InvoiceResult(Result):
    invoice: dict[str, Any] = field(default_factory=dict)


class MewsClient:
    DEFAULT_ENV_FLAG: ClassVar[str] = "MEWS_PMS_ADAPTER_BACKEND"

    def __init__(
        self,
        *,
        access_token: str,
        client_token: str,
        enterprise_id: str = "enterprise_mock_1",
        backend: str | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        if not client_token:
            raise ValueError("client_token is required")

        self.access_token = access_token
        self.client_token = client_token
        self.enterprise_id = enterprise_id
        self.backend = (backend or os.getenv(self.DEFAULT_ENV_FLAG, "mock")).lower()
        self._lock = threading.RLock()
        self._state = self._initial_state()

    def get_configuration(self) -> ConfigurationResult:
        if self.backend != "mock":
            return ConfigurationResult(ok=False, error="real API backend is not implemented in MVP")
        with self._lock:
            return ConfigurationResult(
                ok=True,
                configuration={
                    "enterprise_id": self.enterprise_id,
                    "backend": "mock",
                    "auth": self._auth_body(),
                    "currency": self._state["configuration"]["currency"],
                    "timezone": self._state["configuration"]["timezone"],
                },
            )

    def list_reservations(self, *, customer_id: str | None = None) -> ReservationsResult:
        if self.backend != "mock":
            return ReservationsResult(ok=False, error="real API backend is not implemented in MVP")
        with self._lock:
            reservations = list(self._state["reservations"].values())
            if customer_id is not None:
                reservations = [item for item in reservations if item.get("customer_id") == customer_id]
            return ReservationsResult(ok=True, reservations=[dict(item) for item in reservations])

    def create_reservation(
        self,
        *,
        customer_id: str,
        room_id: str,
        rate_group_id: str,
        start_utc: str,
        end_utc: str,
        guest_count: int = 1,
    ) -> ReservationResult:
        if self.backend != "mock":
            return ReservationResult(ok=False, error="real API backend is not implemented in MVP")
        if not customer_id:
            return ReservationResult(ok=False, error="customer_id is required")
        if room_id not in self._state["rooms"]:
            return ReservationResult(ok=False, error="room_id not found")
        if rate_group_id not in self._state["rate_groups"]:
            return ReservationResult(ok=False, error="rate_group_id not found")
        if guest_count < 1:
            return ReservationResult(ok=False, error="guest_count must be at least 1")
        if not self._valid_date_range(start_utc, end_utc):
            return ReservationResult(ok=False, error="start_utc must be before end_utc")

        with self._lock:
            reservation_id = self._next_id("reservation")
            reservation = {
                "id": reservation_id,
                "customer_id": customer_id,
                "room_id": room_id,
                "rate_group_id": rate_group_id,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "guest_count": guest_count,
                "state": "Confirmed",
            }
            self._state["reservations"][reservation_id] = reservation
            self._state["invoices"][reservation_id] = {
                "id": self._next_id("invoice"),
                "reservation_id": reservation_id,
                "currency": self._state["configuration"]["currency"],
                "charges": [],
                "total": 0,
                "state": "Open",
            }
            return ReservationResult(ok=True, reservation=dict(reservation))

    def list_rooms(self) -> RoomsResult:
        if self.backend != "mock":
            return RoomsResult(ok=False, error="real API backend is not implemented in MVP")
        with self._lock:
            return RoomsResult(ok=True, rooms=[dict(item) for item in self._state["rooms"].values()])

    def list_rate_groups(self) -> RateGroupsResult:
        if self.backend != "mock":
            return RateGroupsResult(ok=False, error="real API backend is not implemented in MVP")
        with self._lock:
            return RateGroupsResult(ok=True, rate_groups=[dict(item) for item in self._state["rate_groups"].values()])

    def get_availability_block(self, *, room_id: str, start_utc: str, end_utc: str) -> AvailabilityBlockResult:
        if self.backend != "mock":
            return AvailabilityBlockResult(ok=False, error="real API backend is not implemented in MVP")
        if room_id not in self._state["rooms"]:
            return AvailabilityBlockResult(ok=False, error="room_id not found")
        if not self._valid_date_range(start_utc, end_utc):
            return AvailabilityBlockResult(ok=False, error="start_utc must be before end_utc")

        with self._lock:
            conflicting = [
                item
                for item in self._state["reservations"].values()
                if item["room_id"] == room_id
                and item["start_utc"] < end_utc
                and start_utc < item["end_utc"]
            ]
            return AvailabilityBlockResult(
                ok=True,
                availability={
                    "room_id": room_id,
                    "start_utc": start_utc,
                    "end_utc": end_utc,
                    "available": not conflicting,
                    "conflicting_reservation_ids": [item["id"] for item in conflicting],
                },
            )

    def post_charge(
        self,
        *,
        reservation_id: str,
        amount: int,
        description: str,
        currency: str | None = None,
    ) -> ChargeResult:
        if self.backend != "mock":
            return ChargeResult(ok=False, error="real API backend is not implemented in MVP")
        if reservation_id not in self._state["reservations"]:
            return ChargeResult(ok=False, error="reservation_id not found")
        if amount <= 0:
            return ChargeResult(ok=False, error="amount must be positive")
        if not description:
            return ChargeResult(ok=False, error="description is required")

        with self._lock:
            invoice = self._state["invoices"][reservation_id]
            charge = {
                "id": self._next_id("charge"),
                "reservation_id": reservation_id,
                "amount": amount,
                "currency": currency or invoice["currency"],
                "description": description,
            }
            invoice["charges"].append(charge)
            invoice["total"] += amount
            return ChargeResult(ok=True, charge=dict(charge))

    def get_invoice(self, *, reservation_id: str) -> InvoiceResult:
        if self.backend != "mock":
            return InvoiceResult(ok=False, error="real API backend is not implemented in MVP")
        with self._lock:
            invoice = self._state["invoices"].get(reservation_id)
            if invoice is None:
                return InvoiceResult(ok=False, error="invoice not found")
            copied = dict(invoice)
            copied["charges"] = [dict(item) for item in invoice["charges"]]
            return InvoiceResult(ok=True, invoice=copied)

    def _auth_body(self) -> dict[str, str]:
        return {
            "AccessToken": self.access_token,
            "ClientToken": self.client_token,
        }

    def _next_id(self, prefix: str) -> str:
        with self._lock:
            self._state["counters"][prefix] += 1
            return f"{prefix}_{self._state['counters'][prefix]}"

    def _valid_date_range(self, start_utc: str, end_utc: str) -> bool:
        try:
            return date.fromisoformat(start_utc[:10]) < date.fromisoformat(end_utc[:10])
        except ValueError:
            return False

    def _initial_state(self) -> dict[str, Any]:
        return {
            "configuration": {
                "currency": "EUR",
                "timezone": "Europe/Berlin",
            },
            "rooms": {
                "room_1": {"id": "room_1", "name": "101", "category": "Standard"},
                "room_2": {"id": "room_2", "name": "201", "category": "Deluxe"},
            },
            "rate_groups": {
                "rate_1": {"id": "rate_1", "name": "Best Available Rate", "currency": "EUR"},
                "rate_2": {"id": "rate_2", "name": "Non Refundable", "currency": "EUR"},
            },
            "reservations": {},
            "invoices": {},
            "counters": {
                "reservation": 0,
                "invoice": 0,
                "charge": 0,
            },
        }
