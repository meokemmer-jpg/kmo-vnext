from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.expedia_eqc_adapter import (
    BookingResult,
    ExpediaEQCClient,
    PropertyResult,
    RateAvailabilityResult,
    RefundResult,
)


def client() -> ExpediaEQCClient:
    return ExpediaEQCClient(
        seed_properties=[
            {
                "property_id": "P-1",
                "name": "Test Hotel",
                "market": "BER",
                "status": "active",
            }
        ]
    )


def push_inventory(c: ExpediaEQCClient, *, available: int = 1) -> RateAvailabilityResult:
    return c.push_rate_availability(
        property_id="P-1",
        room_type_id="ROOM-1",
        rate_plan_id="BAR",
        stay_date="2026-06-01",
        rate=129.5,
        available=available,
        currency="EUR",
    )


def confirm(c: ExpediaEQCClient, *, booking_id: str = "B-1") -> BookingResult:
    return c.confirm_booking(
        property_id="P-1",
        room_type_id="ROOM-1",
        rate_plan_id="BAR",
        stay_date="2026-06-01",
        guest_name="Ada Lovelace",
        amount=129.5,
        currency="EUR",
        booking_id=booking_id,
    )


def test_list_properties_returns_seeded_properties() -> None:
    result = client().list_properties()

    assert isinstance(result, PropertyResult)
    assert result.ok is True
    assert result.status == "success"
    assert result.properties[0]["property_id"] == "P-1"


def test_push_rate_availability_success() -> None:
    result = push_inventory(client(), available=3)

    assert result.ok is True
    assert result.status == "success"
    assert result.property_id == "P-1"
    assert result.room_type_id == "ROOM-1"
    assert result.rate_plan_id == "BAR"


def test_push_rate_availability_rejects_invalid_date() -> None:
    result = client().push_rate_availability(
        property_id="P-1",
        room_type_id="ROOM-1",
        rate_plan_id="BAR",
        stay_date="01-06-2026",
        rate=129.5,
        available=1,
    )

    assert result.ok is False
    assert result.status == "validation_error"
    assert "stay_date" in result.message


def test_push_rate_availability_rejects_unknown_property() -> None:
    result = client().push_rate_availability(
        property_id="MISSING",
        room_type_id="ROOM-1",
        rate_plan_id="BAR",
        stay_date="2026-06-01",
        rate=129.5,
        available=1,
    )

    assert result.ok is False
    assert result.status == "not_found"


def test_confirm_booking_success_consumes_inventory() -> None:
    c = client()
    push_inventory(c, available=1)

    result = confirm(c)

    assert result.ok is True
    assert result.status == "success"
    assert result.booking_id == "B-1"
    assert result.state == "confirmed"


def test_confirm_booking_rejects_sold_out() -> None:
    c = client()
    push_inventory(c, available=0)

    result = confirm(c)

    assert result.ok is False
    assert result.status == "sold_out"


def test_confirm_booking_rejects_duplicate_booking_id() -> None:
    c = client()
    push_inventory(c, available=2)
    first = confirm(c, booking_id="B-DUP")
    second = confirm(c, booking_id="B-DUP")

    assert first.ok is True
    assert second.ok is False
    assert second.status == "conflict"


def test_modify_booking_success() -> None:
    c = client()
    push_inventory(c)
    confirm(c)

    result = c.modify_booking(booking_id="B-1", guest_name="Grace Hopper", amount=99.0)

    assert result.ok is True
    assert result.status == "success"
    assert result.booking_id == "B-1"
    assert result.state == "confirmed"


def test_modify_booking_rejects_missing_booking() -> None:
    result = client().modify_booking(booking_id="NOPE", guest_name="Grace Hopper")

    assert result.ok is False
    assert result.status == "not_found"


def test_refund_booking_success() -> None:
    c = client()
    push_inventory(c)
    confirm(c)

    result = c.refund_booking(booking_id="B-1", amount=25.0)

    assert isinstance(result, RefundResult)
    assert result.ok is True
    assert result.status == "success"
    assert result.booking_id == "B-1"
    assert result.amount == 25.0
    assert result.refund_id.startswith("REF-")


def test_refund_booking_rejects_double_refund() -> None:
    c = client()
    push_inventory(c)
    confirm(c)
    first = c.refund_booking(booking_id="B-1")
    second = c.refund_booking(booking_id="B-1")

    assert first.ok is True
    assert second.ok is False
    assert second.status == "invalid_state"


def test_result_dataclasses_are_frozen() -> None:
    result = BookingResult(ok=True, status="success", booking_id="B-1", property_id="P-1", state="confirmed")

    with pytest.raises(FrozenInstanceError):
        result.status = "changed"  # type: ignore[misc]
