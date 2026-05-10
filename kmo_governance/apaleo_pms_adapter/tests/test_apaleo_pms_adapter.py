from __future__ import annotations

from dataclasses import FrozenInstanceError
import os

import pytest

from kmo_governance.apaleo_pms_adapter import (
    ApaleoClient,
    ApaleoError,
    InventoryUpdated,
    PropertyResult,
    ReservationCancelled,
    ReservationCreated,
    TokenResult,
)


def test_refresh_token_returns_mock_token() -> None:
    client = ApaleoClient()

    result = client.refresh_token()

    assert isinstance(result, TokenResult)
    assert result.ok is True
    assert result.access_token.startswith("mock-token-")
    assert result.expires_at is not None


def test_list_properties_returns_seeded_properties() -> None:
    client = ApaleoClient()

    result = client.list_properties()

    assert result.ok is True
    assert len(result.properties) == 2
    assert {item["id"] for item in result.properties} == {"BER001", "MUC001"}


def test_get_property_returns_property_by_id() -> None:
    client = ApaleoClient()

    result = client.get_property("BER001")

    assert isinstance(result, PropertyResult)
    assert result.ok is True
    assert result.property is not None
    assert result.property["name"] == "KMO Berlin Mitte"


def test_get_property_missing_returns_error_result() -> None:
    client = ApaleoClient()

    result = client.get_property("NOPE")

    assert result.ok is False
    assert "Property not found" in result.message


def test_list_rate_plans_returns_property_rate_plans() -> None:
    client = ApaleoClient()

    result = client.list_rate_plans("BER001")

    assert result.ok is True
    assert {item["id"] for item in result.rate_plans} == {"BAR", "NRF"}


def test_create_reservation_creates_event_and_listable_reservation() -> None:
    client = ApaleoClient()

    event = client.create_reservation(
        "BER001",
        {"firstName": "Ada", "lastName": "Lovelace"},
        {"from": "2026-06-01", "to": "2026-06-03"},
        "BAR",
    )
    listed = client.list_reservations("BER001", "2026-06-01", "2026-06-04")

    assert isinstance(event, ReservationCreated)
    assert event.ok is True
    assert event.reservation_id.startswith("RES-")
    assert len(listed.reservations) == 1
    assert listed.reservations[0]["id"] == event.reservation_id


def test_cancel_reservation_updates_status() -> None:
    client = ApaleoClient()
    created = client.create_reservation(
        "BER001",
        {"firstName": "Grace", "lastName": "Hopper"},
        {"from": "2026-07-01", "to": "2026-07-02"},
        "BAR",
    )

    cancelled = client.cancel_reservation(created.reservation_id)
    listed = client.list_reservations("BER001", "2026-07-01", "2026-07-02")

    assert isinstance(cancelled, ReservationCancelled)
    assert cancelled.ok is True
    assert listed.reservations[0]["status"] == "cancelled"


def test_cancel_missing_reservation_returns_error_result() -> None:
    client = ApaleoClient()

    result = client.cancel_reservation("RES-MISSING")

    assert result.ok is False
    assert result.reservation_id == "RES-MISSING"
    assert "Reservation not found" in result.message


def test_update_inventory_stores_count() -> None:
    client = ApaleoClient()

    result = client.update_inventory("BER001", "BAR", "2026-08-01", 7)

    assert isinstance(result, InventoryUpdated)
    assert result.ok is True
    assert result.count == 7
    assert client.get_inventory_count("BER001", "BAR", "2026-08-01") == 7


def test_validation_rejects_bad_guest() -> None:
    client = ApaleoClient()

    with pytest.raises(ApaleoError, match="guest.firstName"):
        client.create_reservation(
            "BER001",
            {"lastName": "Only"},
            {"from": "2026-06-01", "to": "2026-06-02"},
            "BAR",
        )


def test_validation_rejects_invalid_inventory_count() -> None:
    client = ApaleoClient()

    with pytest.raises(ApaleoError, match="count"):
        client.update_inventory("BER001", "BAR", "2026-08-01", -1)


def test_results_are_frozen() -> None:
    result = ReservationCreated(
        ok=True,
        reservation_id="RES-1",
        property_id="BER001",
        guest={"firstName": "Ada", "lastName": "Lovelace"},
        dates={"from": "2026-06-01", "to": "2026-06-02"},
        rate_plan_id="BAR",
    )

    with pytest.raises(FrozenInstanceError):
        result.ok = False


def test_real_api_switch_is_env_var_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APALEO_USE_REAL_API", "true")
    client = ApaleoClient()

    with pytest.raises(NotImplementedError):
        client.list_properties()

    monkeypatch.delenv("APALEO_USE_REAL_API")
    assert os.getenv("APALEO_USE_REAL_API") is None
