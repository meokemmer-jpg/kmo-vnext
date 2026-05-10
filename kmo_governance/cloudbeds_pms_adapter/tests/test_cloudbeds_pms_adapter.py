from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.cloudbeds_pms_adapter import (
    CloudbedsClient,
    ErrorResult,
    GuestHistoryResult,
    HotelDetailsResult,
    HotelsResult,
    PaymentResult,
    ReservationResult,
    ReservationsResult,
    RoomTypesResult,
)


def test_authenticate_returns_mock_oauth2_token() -> None:
    client = CloudbedsClient()

    token = client.authenticate()

    assert token.startswith("mock-oauth2-token-")
    assert client.access_token == token


def test_list_hotels_returns_seed_hotels() -> None:
    client = CloudbedsClient()

    result = client.list_hotels()

    assert isinstance(result, HotelsResult)
    assert result.ok is True
    assert len(result.hotels) == 2
    assert {hotel["id"] for hotel in result.hotels} == {"hotel_berlin", "hotel_hamburg"}


def test_get_hotel_details_returns_hotel() -> None:
    client = CloudbedsClient()

    result = client.get_hotel_details("hotel_berlin")

    assert isinstance(result, HotelDetailsResult)
    assert result.ok is True
    assert result.hotel["name"] == "KMO Berlin Mitte"


def test_get_hotel_details_unknown_hotel_returns_404() -> None:
    client = CloudbedsClient()

    result = client.get_hotel_details("missing")

    assert isinstance(result, ErrorResult)
    assert result.ok is False
    assert result.status_code == 404
    assert result.error == "hotel not found"


def test_list_room_types_filters_by_hotel() -> None:
    client = CloudbedsClient()

    result = client.list_room_types("hotel_berlin")

    assert isinstance(result, RoomTypesResult)
    assert result.ok is True
    assert {room["id"] for room in result.room_types} == {"rt_single_berlin", "rt_double_berlin"}


def test_post_reservation_creates_reservation() -> None:
    client = CloudbedsClient()

    result = client.post_reservation(
        hotel_id="hotel_berlin",
        guest_id="guest_002",
        room_type_id="rt_double_berlin",
        check_in="2026-07-10",
        check_out="2026-07-12",
    )

    assert isinstance(result, ReservationResult)
    assert result.ok is True
    assert result.reservation["id"].startswith("res_")
    assert result.reservation["guest_id"] == "guest_002"


def test_list_reservations_filters_created_reservation_by_guest() -> None:
    client = CloudbedsClient()
    created = client.post_reservation(
        hotel_id="hotel_berlin",
        guest_id="guest_003",
        room_type_id="rt_single_berlin",
        check_in="2026-08-01",
        check_out="2026-08-02",
    )
    assert isinstance(created, ReservationResult)

    result = client.list_reservations(guest_id="guest_003")

    assert isinstance(result, ReservationsResult)
    assert len(result.reservations) == 1
    assert result.reservations[0]["id"] == created.reservation["id"]


def test_post_reservation_missing_required_field_returns_validation_error() -> None:
    client = CloudbedsClient()

    result = client.post_reservation(
        hotel_id="hotel_berlin",
        guest_id="",
        room_type_id="rt_single_berlin",
        check_in="2026-08-01",
        check_out="2026-08-02",
    )

    assert isinstance(result, ErrorResult)
    assert result.status_code == 400
    assert "guest_id" in result.error


def test_post_payment_creates_payment_for_reservation() -> None:
    client = CloudbedsClient()

    result = client.post_payment(
        reservation_id="res_seed_001",
        amount=50,
        currency="eur",
        method="card",
    )

    assert isinstance(result, PaymentResult)
    assert result.ok is True
    assert result.payment["id"].startswith("pay_")
    assert result.payment["amount"] == 50.0
    assert result.payment["currency"] == "EUR"


def test_post_payment_rejects_negative_amount() -> None:
    client = CloudbedsClient()

    result = client.post_payment(
        reservation_id="res_seed_001",
        amount=-1,
        currency="EUR",
        method="card",
    )

    assert isinstance(result, ErrorResult)
    assert result.status_code == 400
    assert result.error == "amount must be positive"


def test_get_guest_history_returns_reservations_and_payments() -> None:
    client = CloudbedsClient()

    result = client.get_guest_history("guest_001")

    assert isinstance(result, GuestHistoryResult)
    assert result.ok is True
    assert result.guest_id == "guest_001"
    assert len(result.reservations) == 1
    assert len(result.payments) == 1


def test_result_dataclasses_are_frozen() -> None:
    result = HotelsResult(ok=True, hotels=())

    with pytest.raises(FrozenInstanceError):
        result.ok = False  # type: ignore[misc]
