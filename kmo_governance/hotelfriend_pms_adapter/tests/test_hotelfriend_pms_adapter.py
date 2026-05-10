from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.hotelfriend_pms_adapter import (
    BookingResult,
    HotelFriendClient,
    InventoryResult,
    PropertyListResult,
)


def test_get_property_list_returns_mock_properties() -> None:
    client = HotelFriendClient()

    result = client.get_property_list()

    assert result.success is True
    assert result.properties[0]["id"] == "prop_berlin_001"


def test_list_room_types_returns_mock_room_types() -> None:
    client = HotelFriendClient()

    result = client.list_room_types("prop_berlin_001")

    assert result.success is True
    assert {room["id"] for room in result.room_types} == {"rt_standard", "rt_deluxe"}


def test_push_inventory_updates_mock_backend() -> None:
    client = HotelFriendClient()

    result = client.push_inventory("prop_berlin_001", "rt_standard", {"2026-06-04": 7})

    assert result.success is True
    assert result.inventory is not None
    assert result.inventory["2026-06-04"] == 7


def test_create_booking_creates_confirmed_booking() -> None:
    client = HotelFriendClient()

    result = client.create_booking(
        "prop_berlin_001",
        "rt_standard",
        "Ada Lovelace",
        "2026-06-01",
        "2026-06-03",
        1,
    )

    assert result.success is True
    assert result.booking is not None
    assert result.booking["status"] == "confirmed"
    assert result.booking["guest_name"] == "Ada Lovelace"


def test_list_bookings_returns_created_booking() -> None:
    client = HotelFriendClient()
    created = client.create_booking(
        "prop_berlin_001",
        "rt_standard",
        "Grace Hopper",
        "2026-06-01",
        "2026-06-02",
        1,
    )

    result = client.list_bookings("prop_berlin_001")

    assert result.success is True
    assert result.bookings is not None
    assert created.booking is not None
    assert created.booking["id"] in {booking["id"] for booking in result.bookings}


def test_cancel_booking_marks_booking_cancelled() -> None:
    client = HotelFriendClient()
    created = client.create_booking(
        "prop_berlin_001",
        "rt_standard",
        "Linus Torvalds",
        "2026-06-01",
        "2026-06-02",
        1,
    )
    assert created.booking is not None

    result = client.cancel_booking(created.booking["id"])

    assert result.success is True
    assert result.booking_id == created.booking["id"]
    assert result.status == "cancelled"


def test_create_booking_rejects_missing_guest_name() -> None:
    client = HotelFriendClient()

    result = client.create_booking(
        "prop_berlin_001",
        "rt_standard",
        "",
        "2026-06-01",
        "2026-06-02",
        1,
    )

    assert result.success is False
    assert result.error == "guest_name is required"


def test_create_booking_rejects_invalid_date_order() -> None:
    client = HotelFriendClient()

    result = client.create_booking(
        "prop_berlin_001",
        "rt_standard",
        "Bad Dates",
        "2026-06-03",
        "2026-06-01",
        1,
    )

    assert result.success is False
    assert result.error == "check_out must be after check_in"


def test_create_booking_rejects_unknown_room_type() -> None:
    client = HotelFriendClient()

    result = client.create_booking(
        "prop_berlin_001",
        "rt_missing",
        "Unknown Room",
        "2026-06-01",
        "2026-06-02",
        1,
    )

    assert result.success is False
    assert result.error == "room type not found"


def test_cancel_booking_rejects_unknown_booking() -> None:
    client = HotelFriendClient()

    result = client.cancel_booking("bk_missing")

    assert result.success is False
    assert result.booking_id == "bk_missing"
    assert result.error == "booking not found"


def test_real_api_switch_is_env_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOTELFRIEND_USE_REAL_API", "true")
    client = HotelFriendClient()

    result = client.get_property_list()

    assert result.success is False
    assert result.error == "real API mode is not implemented in MVP"


def test_result_dataclasses_are_frozen() -> None:
    property_result = PropertyListResult(True, [])
    booking_result = BookingResult(True)
    inventory_result = InventoryResult(True, "prop_berlin_001", "rt_standard", {})

    with pytest.raises(FrozenInstanceError):
        property_result.success = False  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        booking_result.error = "changed"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        inventory_result.property_id = "changed"  # type: ignore[misc]
