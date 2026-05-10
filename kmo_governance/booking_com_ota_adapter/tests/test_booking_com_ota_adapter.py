from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.booking_com_ota_adapter import (
    AvailabilityPushResult,
    BookingComClient,
    BookingComError,
    CancellationResult,
    ContentManagementResult,
    PropertyResult,
    ReservationResult,
)


def test_get_property_json_success() -> None:
    client = BookingComClient()
    result = client.get_property()

    assert isinstance(result, PropertyResult)
    assert result.ok is True
    assert result.property_id == "demo-property"
    assert result.data["name"] == "Demo Hotel"


def test_get_property_missing_returns_error_result() -> None:
    client = BookingComClient()

    result = client.get_property("missing")

    assert result.ok is False
    assert result.message == "property not found"


def test_push_availability_updates_rates_restrictions_inventory() -> None:
    client = BookingComClient()

    result = client.push_availability(
        rates={"STD": {"2026-01-01": "120.00"}},
        restrictions={"STD": {"min_stay": 2}},
        inventory={"STD": {"2026-01-01": 5}},
    )

    assert isinstance(result, AvailabilityPushResult)
    assert result.ok is True
    assert result.updated["rates"]["STD"]["2026-01-01"] == "120.00"
    assert result.notification_id == "mock-notification-1"


def test_push_availability_xml_format() -> None:
    client = BookingComClient()

    result = client.push_availability(
        rates={"STD": {"date": "2026-01-01", "price": "120.00"}},
        restrictions={"STD": {"closed": "false"}},
        inventory={"STD": {"count": "5"}},
        format="xml",
    )

    assert result.ok is True
    assert result.format == "xml"
    assert result.updated["inventory"]["STD"]["count"] == "5"


def test_confirm_reservation_creates_record_and_notification() -> None:
    client = BookingComClient()

    result = client.confirm_reservation(
        {
            "reservation_id": "R1",
            "guest_name": "Ada Lovelace",
            "room_type": "STD",
            "arrival": "2026-02-01",
            "departure": "2026-02-03",
        }
    )

    assert isinstance(result, ReservationResult)
    assert result.ok is True
    assert result.data["status"] == "confirmed"
    assert client.notifications[-1]["event"] == "reservation_confirmed"


def test_confirm_reservation_duplicate_returns_error() -> None:
    client = BookingComClient()
    payload = {"reservation_id": "R1", "guest_name": "Ada"}

    first = client.confirm_reservation(payload)
    second = client.confirm_reservation(payload)

    assert first.ok is True
    assert second.ok is False
    assert second.message == "reservation already exists"


def test_modify_reservation_updates_existing_record() -> None:
    client = BookingComClient()
    client.confirm_reservation({"reservation_id": "R1", "guest_name": "Ada", "total": "100.00"})

    result = client.modify_reservation("R1", {"total": "125.00"})

    assert result.ok is True
    assert result.data["status"] == "modified"
    assert result.data["total"] == "125.00"


def test_modify_reservation_missing_returns_error() -> None:
    client = BookingComClient()

    result = client.modify_reservation("missing", {"total": "125.00"})

    assert result.ok is False
    assert result.message == "reservation not found"


def test_cancel_reservation_marks_cancelled() -> None:
    client = BookingComClient()
    client.confirm_reservation({"reservation_id": "R1", "guest_name": "Ada"})

    result = client.cancel_reservation("R1", reason="guest request")

    assert isinstance(result, CancellationResult)
    assert result.ok is True
    assert result.cancelled is True
    assert client.modify_reservation("R1", {"guest_name": "Grace"}).message == "reservation already cancelled"


def test_content_management_updates_property_content() -> None:
    client = BookingComClient()

    result = client.content_management(
        {
            "title": "Demo Hotel Berlin",
            "description": "Central test property",
            "amenities": ["wifi", "parking"],
        }
    )

    assert isinstance(result, ContentManagementResult)
    assert result.ok is True
    assert result.content["title"] == "Demo Hotel Berlin"
    assert result.content["notification_id"] == "mock-notification-1"


def test_validation_errors() -> None:
    client = BookingComClient()

    with pytest.raises(BookingComError):
        client.get_property(format="yaml")

    with pytest.raises(BookingComError):
        client.push_availability({}, {"STD": {}}, {"STD": {}})

    with pytest.raises(BookingComError):
        client.confirm_reservation({"guest_name": "Ada"})


def test_result_dataclasses_are_frozen() -> None:
    result = ReservationResult(True, "R1", {"status": "confirmed"}, "json")

    with pytest.raises(FrozenInstanceError):
        result.ok = False  # type: ignore[misc]
