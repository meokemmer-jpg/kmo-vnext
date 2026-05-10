from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.staynstouch_pms_adapter import (
    AdapterError,
    CheckInResult,
    HotelResult,
    ReservationResult,
    RoomStatusResult,
    StayNTouchClient,
)


def test_get_hotel_returns_mock_hotel() -> None:
    result = StayNTouchClient().get_hotel()

    assert result.ok is True
    assert result.hotel["id"] == "hotel_001"


def test_get_hotel_unknown_id_returns_error() -> None:
    result = StayNTouchClient().get_hotel("missing")

    assert result.ok is False
    assert result.error == "hotel_not_found"


def test_list_reservations_returns_mock_data() -> None:
    result = StayNTouchClient().list_reservations()

    assert result.ok is True
    assert len(result.reservations) == 2


def test_list_reservations_filters_by_status() -> None:
    client = StayNTouchClient()
    client.mobile_checkin("res_001")

    result = client.list_reservations(status="checked_in")

    assert result.ok is True
    assert [item["id"] for item in result.reservations] == ["res_001"]


def test_mobile_checkin_updates_reservation() -> None:
    client = StayNTouchClient()

    result = client.mobile_checkin("res_001")

    assert result.ok is True
    assert result.status == "checked_in"


def test_mobile_checkin_requires_reservation_id() -> None:
    result = StayNTouchClient().mobile_checkin("")

    assert result.ok is False
    assert result.error == "reservation_id_required"


def test_mobile_checkin_unknown_reservation() -> None:
    result = StayNTouchClient().mobile_checkin("missing")

    assert result.ok is False
    assert result.error == "reservation_not_found"


def test_mobile_checkout_requires_checked_in_reservation() -> None:
    result = StayNTouchClient().mobile_checkout("res_001")

    assert result.ok is False
    assert result.error == "not_checked_in"


def test_mobile_checkout_updates_reservation() -> None:
    client = StayNTouchClient()
    client.mobile_checkin("res_001")

    result = client.mobile_checkout("res_001")

    assert result.ok is True
    assert result.status == "checked_out"


def test_push_room_status_updates_room() -> None:
    result = StayNTouchClient().push_room_status("101", "inspected")

    assert result.ok is True
    assert result.room_id == "101"
    assert result.status == "inspected"


def test_push_room_status_rejects_invalid_status() -> None:
    result = StayNTouchClient().push_room_status("101", "sparkly")

    assert result.ok is False
    assert result.error == "invalid_room_status"


def test_result_dataclasses_are_frozen() -> None:
    result = HotelResult(ok=True, hotel={"id": "hotel_001"})

    with pytest.raises(FrozenInstanceError):
        result.ok = False


def test_real_api_mode_is_env_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAYNTOUCH_USE_REAL_API", "true")
    client = StayNTouchClient()

    with pytest.raises(AdapterError):
        client.get_hotel()


def test_public_result_types_importable() -> None:
    assert ReservationResult(ok=True, reservations=[]).ok is True
    assert CheckInResult(ok=True, reservation_id="res_001", status="checked_in").status == "checked_in"
    assert RoomStatusResult(ok=True, room_id="101", status="clean").status == "clean"
