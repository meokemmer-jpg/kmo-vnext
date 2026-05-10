from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.mews_pms_adapter import (
    MewsClient,
    ReservationResult,
)


@pytest.fixture()
def client() -> MewsClient:
    return MewsClient(access_token="access", client_token="client")


def test_requires_access_token() -> None:
    with pytest.raises(ValueError, match="access_token"):
        MewsClient(access_token="", client_token="client")


def test_requires_client_token() -> None:
    with pytest.raises(ValueError, match="client_token"):
        MewsClient(access_token="access", client_token="")


def test_get_configuration_includes_pair_auth_body(client: MewsClient) -> None:
    result = client.get_configuration()

    assert result.ok is True
    assert result.configuration["backend"] == "mock"
    assert result.configuration["auth"] == {
        "AccessToken": "access",
        "ClientToken": "client",
    }


def test_list_rooms(client: MewsClient) -> None:
    result = client.list_rooms()

    assert result.ok is True
    assert [room["id"] for room in result.rooms] == ["room_1", "room_2"]


def test_list_rate_groups(client: MewsClient) -> None:
    result = client.list_rate_groups()

    assert result.ok is True
    assert [rate["id"] for rate in result.rate_groups] == ["rate_1", "rate_2"]


def test_create_and_list_reservation(client: MewsClient) -> None:
    created = client.create_reservation(
        customer_id="customer_1",
        room_id="room_1",
        rate_group_id="rate_1",
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-03T00:00:00Z",
        guest_count=2,
    )
    listed = client.list_reservations(customer_id="customer_1")

    assert created.ok is True
    assert created.reservation["id"] == "reservation_1"
    assert listed.ok is True
    assert listed.reservations == [created.reservation]


def test_create_reservation_rejects_unknown_room(client: MewsClient) -> None:
    result = client.create_reservation(
        customer_id="customer_1",
        room_id="missing",
        rate_group_id="rate_1",
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-03T00:00:00Z",
    )

    assert result.ok is False
    assert result.error == "room_id not found"


def test_create_reservation_rejects_invalid_date_range(client: MewsClient) -> None:
    result = client.create_reservation(
        customer_id="customer_1",
        room_id="room_1",
        rate_group_id="rate_1",
        start_utc="2026-06-03T00:00:00Z",
        end_utc="2026-06-01T00:00:00Z",
    )

    assert result.ok is False
    assert result.error == "start_utc must be before end_utc"


def test_availability_block_reports_conflict(client: MewsClient) -> None:
    client.create_reservation(
        customer_id="customer_1",
        room_id="room_1",
        rate_group_id="rate_1",
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-03T00:00:00Z",
    )

    result = client.get_availability_block(
        room_id="room_1",
        start_utc="2026-06-02T00:00:00Z",
        end_utc="2026-06-04T00:00:00Z",
    )

    assert result.ok is True
    assert result.availability["available"] is False
    assert result.availability["conflicting_reservation_ids"] == ["reservation_1"]


def test_post_charge_and_get_invoice(client: MewsClient) -> None:
    reservation = client.create_reservation(
        customer_id="customer_1",
        room_id="room_1",
        rate_group_id="rate_1",
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-03T00:00:00Z",
    )
    charge = client.post_charge(
        reservation_id=reservation.reservation["id"],
        amount=2500,
        description="Minibar",
    )
    invoice = client.get_invoice(reservation_id=reservation.reservation["id"])

    assert charge.ok is True
    assert invoice.ok is True
    assert invoice.invoice["total"] == 2500
    assert invoice.invoice["charges"] == [charge.charge]


def test_post_charge_rejects_negative_amount(client: MewsClient) -> None:
    reservation = client.create_reservation(
        customer_id="customer_1",
        room_id="room_1",
        rate_group_id="rate_1",
        start_utc="2026-06-01T00:00:00Z",
        end_utc="2026-06-03T00:00:00Z",
    )

    result = client.post_charge(
        reservation_id=reservation.reservation["id"],
        amount=-1,
        description="Invalid",
    )

    assert result.ok is False
    assert result.error == "amount must be positive"


def test_result_dataclass_is_frozen() -> None:
    result = ReservationResult(ok=True, reservation={"id": "reservation_1"})

    with pytest.raises(FrozenInstanceError):
        result.ok = False  # type: ignore[misc]
