from __future__ import annotations

import os
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any


_REAL_API_ENV_VAR = "HOTELFRIEND_USE_REAL_API"


@dataclass(frozen=True)
class PropertyListResult:
    success: bool
    properties: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class BookingResult:
    success: bool
    booking: dict[str, Any] | None = None
    bookings: list[dict[str, Any]] | None = None
    error: str | None = None


@dataclass(frozen=True)
class CancelBookingResult:
    success: bool
    booking_id: str | None = None
    status: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RoomTypesResult:
    success: bool
    room_types: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class InventoryResult:
    success: bool
    property_id: str | None = None
    room_type_id: str | None = None
    inventory: dict[str, int] | None = None
    error: str | None = None


class HotelFriendClient:
    """MVP HotelFriend PMS adapter with a mock backend by default."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.use_real_api = os.getenv(_REAL_API_ENV_VAR, "").lower() in {"1", "true", "yes"}
        self._lock = threading.RLock()
        self._state = self._build_mock_state()

    def get_property_list(self) -> PropertyListResult:
        if self.use_real_api:
            return PropertyListResult(False, [], "real API mode is not implemented in MVP")

        with self._lock:
            return PropertyListResult(True, deepcopy(list(self._state["properties"].values())))

    def list_bookings(self, property_id: str) -> BookingResult:
        if self.use_real_api:
            return BookingResult(False, error="real API mode is not implemented in MVP")

        error = self._validate_property_id(property_id)
        if error:
            return BookingResult(False, error=error)

        with self._lock:
            bookings = [
                deepcopy(booking)
                for booking in self._state["bookings"].values()
                if booking["property_id"] == property_id
            ]
            return BookingResult(True, bookings=bookings)

    def create_booking(
        self,
        property_id: str,
        room_type_id: str,
        guest_name: str,
        check_in: str,
        check_out: str,
        rooms: int = 1,
    ) -> BookingResult:
        if self.use_real_api:
            return BookingResult(False, error="real API mode is not implemented in MVP")

        error = self._validate_booking_payload(
            property_id=property_id,
            room_type_id=room_type_id,
            guest_name=guest_name,
            check_in=check_in,
            check_out=check_out,
            rooms=rooms,
        )
        if error:
            return BookingResult(False, error=error)

        with self._lock:
            inventory = self._state["inventory"][property_id][room_type_id]
            for stay_date in self._stay_dates(check_in, check_out):
                if inventory.get(stay_date, 0) < rooms:
                    return BookingResult(False, error=f"insufficient inventory for {stay_date}")

            for stay_date in self._stay_dates(check_in, check_out):
                inventory[stay_date] -= rooms

            booking_id = f"bk_{uuid.uuid4().hex[:12]}"
            booking = {
                "id": booking_id,
                "property_id": property_id,
                "room_type_id": room_type_id,
                "guest_name": guest_name,
                "check_in": check_in,
                "check_out": check_out,
                "rooms": rooms,
                "status": "confirmed",
            }
            self._state["bookings"][booking_id] = booking
            return BookingResult(True, booking=deepcopy(booking))

    def cancel_booking(self, booking_id: str) -> CancelBookingResult:
        if self.use_real_api:
            return CancelBookingResult(False, error="real API mode is not implemented in MVP")

        if not booking_id:
            return CancelBookingResult(False, error="booking_id is required")

        with self._lock:
            booking = self._state["bookings"].get(booking_id)
            if booking is None:
                return CancelBookingResult(False, booking_id=booking_id, error="booking not found")
            if booking["status"] == "cancelled":
                return CancelBookingResult(False, booking_id=booking_id, error="booking already cancelled")

            inventory = self._state["inventory"][booking["property_id"]][booking["room_type_id"]]
            for stay_date in self._stay_dates(booking["check_in"], booking["check_out"]):
                inventory[stay_date] = inventory.get(stay_date, 0) + booking["rooms"]

            booking["status"] = "cancelled"
            return CancelBookingResult(True, booking_id=booking_id, status="cancelled")

    def list_room_types(self, property_id: str) -> RoomTypesResult:
        if self.use_real_api:
            return RoomTypesResult(False, [], "real API mode is not implemented in MVP")

        error = self._validate_property_id(property_id)
        if error:
            return RoomTypesResult(False, [], error)

        with self._lock:
            return RoomTypesResult(True, deepcopy(self._state["room_types"][property_id]))

    def push_inventory(
        self,
        property_id: str,
        room_type_id: str,
        inventory: dict[str, int],
    ) -> InventoryResult:
        if self.use_real_api:
            return InventoryResult(False, error="real API mode is not implemented in MVP")

        error = self._validate_inventory_payload(property_id, room_type_id, inventory)
        if error:
            return InventoryResult(False, property_id, room_type_id, error=error)

        with self._lock:
            self._state["inventory"][property_id][room_type_id].update(inventory)
            return InventoryResult(
                True,
                property_id,
                room_type_id,
                deepcopy(self._state["inventory"][property_id][room_type_id]),
            )

    def _validate_property_id(self, property_id: str) -> str | None:
        if not property_id:
            return "property_id is required"
        with self._lock:
            if property_id not in self._state["properties"]:
                return "property not found"
        return None

    def _validate_room_type_id(self, property_id: str, room_type_id: str) -> str | None:
        if not room_type_id:
            return "room_type_id is required"
        with self._lock:
            if room_type_id not in {room["id"] for room in self._state["room_types"].get(property_id, [])}:
                return "room type not found"
        return None

    def _validate_booking_payload(
        self,
        property_id: str,
        room_type_id: str,
        guest_name: str,
        check_in: str,
        check_out: str,
        rooms: int,
    ) -> str | None:
        property_error = self._validate_property_id(property_id)
        if property_error:
            return property_error

        room_error = self._validate_room_type_id(property_id, room_type_id)
        if room_error:
            return room_error

        if not guest_name:
            return "guest_name is required"
        if rooms < 1:
            return "rooms must be greater than zero"

        try:
            check_in_date = date.fromisoformat(check_in)
            check_out_date = date.fromisoformat(check_out)
        except ValueError:
            return "check_in and check_out must be ISO dates"

        if check_out_date <= check_in_date:
            return "check_out must be after check_in"

        return None

    def _validate_inventory_payload(
        self,
        property_id: str,
        room_type_id: str,
        inventory: dict[str, int],
    ) -> str | None:
        property_error = self._validate_property_id(property_id)
        if property_error:
            return property_error

        room_error = self._validate_room_type_id(property_id, room_type_id)
        if room_error:
            return room_error

        if not inventory:
            return "inventory is required"

        for inventory_date, quantity in inventory.items():
            try:
                date.fromisoformat(inventory_date)
            except ValueError:
                return f"invalid inventory date: {inventory_date}"
            if not isinstance(quantity, int) or quantity < 0:
                return "inventory values must be non-negative integers"

        return None

    @staticmethod
    def _stay_dates(check_in: str, check_out: str) -> list[str]:
        start = date.fromisoformat(check_in)
        end = date.fromisoformat(check_out)
        return [
            date.fromordinal(day).isoformat()
            for day in range(start.toordinal(), end.toordinal())
        ]

    @staticmethod
    def _build_mock_state() -> dict[str, Any]:
        property_id = "prop_berlin_001"
        room_type_id = "rt_standard"
        deluxe_room_type_id = "rt_deluxe"

        return {
            "properties": {
                property_id: {
                    "id": property_id,
                    "name": "KMO Berlin Hotel",
                    "currency": "EUR",
                    "timezone": "Europe/Berlin",
                }
            },
            "room_types": {
                property_id: [
                    {"id": room_type_id, "name": "Standard Room", "max_occupancy": 2},
                    {"id": deluxe_room_type_id, "name": "Deluxe Room", "max_occupancy": 3},
                ]
            },
            "inventory": {
                property_id: {
                    room_type_id: {
                        "2026-06-01": 5,
                        "2026-06-02": 5,
                        "2026-06-03": 5,
                    },
                    deluxe_room_type_id: {
                        "2026-06-01": 2,
                        "2026-06-02": 2,
                        "2026-06-03": 2,
                    },
                }
            },
            "bookings": {},
        }
