from __future__ import annotations

from dataclasses import dataclass
import os
import threading
from typing import Any


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class HotelResult:
    ok: bool
    hotel: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class ReservationResult:
    ok: bool
    reservations: list[dict[str, Any]] | None = None
    error: str | None = None


@dataclass(frozen=True)
class CheckInResult:
    ok: bool
    reservation_id: str | None = None
    status: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class CheckOutResult:
    ok: bool
    reservation_id: str | None = None
    status: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RoomStatusResult:
    ok: bool
    room_id: str | None = None
    status: str | None = None
    error: str | None = None


class StayNTouchClient:
    def __init__(self, *, hotel_id: str = "hotel_001", api_key: str | None = None) -> None:
        self.hotel_id = hotel_id
        self.api_key = api_key
        self.use_real_api = os.getenv("STAYNTOUCH_USE_REAL_API", "").lower() in {"1", "true", "yes"}
        self._lock = threading.RLock()
        self._state = {
            "hotel": {
                "id": hotel_id,
                "name": "Mock StayNTouch Hotel",
                "timezone": "Europe/Berlin",
            },
            "reservations": {
                "res_001": {
                    "id": "res_001",
                    "guest_name": "Ada Lovelace",
                    "room_id": "101",
                    "status": "reserved",
                },
                "res_002": {
                    "id": "res_002",
                    "guest_name": "Grace Hopper",
                    "room_id": "102",
                    "status": "reserved",
                },
            },
            "rooms": {
                "101": "clean",
                "102": "dirty",
            },
        }

    def get_hotel(self, hotel_id: str | None = None) -> HotelResult:
        if self.use_real_api:
            raise AdapterError("Real StayNTouch API mode is not implemented in MVP adapter")

        requested = hotel_id or self.hotel_id
        with self._lock:
            hotel = self._state["hotel"]
            if requested != hotel["id"]:
                return HotelResult(ok=False, error="hotel_not_found")
            return HotelResult(ok=True, hotel=dict(hotel))

    def list_reservations(self, *, status: str | None = None) -> ReservationResult:
        if self.use_real_api:
            raise AdapterError("Real StayNTouch API mode is not implemented in MVP adapter")

        with self._lock:
            reservations = [dict(item) for item in self._state["reservations"].values()]
            if status is not None:
                reservations = [item for item in reservations if item["status"] == status]
            return ReservationResult(ok=True, reservations=reservations)

    def mobile_checkin(self, reservation_id: str) -> CheckInResult:
        if self.use_real_api:
            raise AdapterError("Real StayNTouch API mode is not implemented in MVP adapter")
        if not reservation_id:
            return CheckInResult(ok=False, error="reservation_id_required")

        with self._lock:
            reservation = self._state["reservations"].get(reservation_id)
            if reservation is None:
                return CheckInResult(ok=False, reservation_id=reservation_id, error="reservation_not_found")
            if reservation["status"] == "checked_in":
                return CheckInResult(ok=False, reservation_id=reservation_id, status="checked_in", error="already_checked_in")
            if reservation["status"] == "checked_out":
                return CheckInResult(ok=False, reservation_id=reservation_id, status="checked_out", error="already_checked_out")

            reservation["status"] = "checked_in"
            return CheckInResult(ok=True, reservation_id=reservation_id, status="checked_in")

    def mobile_checkout(self, reservation_id: str) -> CheckOutResult:
        if self.use_real_api:
            raise AdapterError("Real StayNTouch API mode is not implemented in MVP adapter")
        if not reservation_id:
            return CheckOutResult(ok=False, error="reservation_id_required")

        with self._lock:
            reservation = self._state["reservations"].get(reservation_id)
            if reservation is None:
                return CheckOutResult(ok=False, reservation_id=reservation_id, error="reservation_not_found")
            if reservation["status"] != "checked_in":
                return CheckOutResult(ok=False, reservation_id=reservation_id, status=reservation["status"], error="not_checked_in")

            reservation["status"] = "checked_out"
            return CheckOutResult(ok=True, reservation_id=reservation_id, status="checked_out")

    def push_room_status(self, room_id: str, status: str) -> RoomStatusResult:
        if self.use_real_api:
            raise AdapterError("Real StayNTouch API mode is not implemented in MVP adapter")
        if not room_id:
            return RoomStatusResult(ok=False, error="room_id_required")
        if status not in {"clean", "dirty", "inspected", "out_of_order"}:
            return RoomStatusResult(ok=False, room_id=room_id, error="invalid_room_status")

        with self._lock:
            if room_id not in self._state["rooms"]:
                return RoomStatusResult(ok=False, room_id=room_id, error="room_not_found")
            self._state["rooms"][room_id] = status
            return RoomStatusResult(ok=True, room_id=room_id, status=status)
