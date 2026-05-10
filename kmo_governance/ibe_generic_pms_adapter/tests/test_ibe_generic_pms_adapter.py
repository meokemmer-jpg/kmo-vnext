from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.ibe_generic_pms_adapter import (
    GenericPMSAdapter,
    MockPMSBackend,
    PMSAdapterError,
    PMSValidationError,
    PropertyResult,
    ReservationResult,
)


def valid_payload(**overrides):
    payload = {
        "guest_name": "Ada Lovelace",
        "arrival_date": "2026-06-01",
        "departure_date": "2026-06-03",
        "room_type": "suite",
    }
    payload.update(overrides)
    return payload


def test_default_adapter_uses_mock_backend(monkeypatch):
    monkeypatch.delenv("KMO_PMS_BACKEND", raising=False)

    adapter = GenericPMSAdapter()

    assert isinstance(adapter.backend, MockPMSBackend)


def test_env_mock_backend_is_supported(monkeypatch):
    monkeypatch.setenv("KMO_PMS_BACKEND", "mock")

    adapter = GenericPMSAdapter()

    assert isinstance(adapter.backend, MockPMSBackend)


def test_env_real_backend_switch_is_gated(monkeypatch):
    monkeypatch.setenv("KMO_PMS_BACKEND", "real")

    with pytest.raises(PMSAdapterError, match="Unsupported PMS backend"):
        GenericPMSAdapter()


def test_get_property_returns_property_result():
    adapter = GenericPMSAdapter()

    result = adapter.get_property("prop_1")

    assert isinstance(result, PropertyResult)
    assert result.ok is True
    assert result.property_id == "prop_1"
    assert result.data["name"] == "Mock Hotel"


def test_get_missing_property_returns_error_result():
    adapter = GenericPMSAdapter()

    result = adapter.get_property("missing")

    assert result.ok is False
    assert result.error == "property_not_found"


def test_create_reservation_and_get_reservation():
    adapter = GenericPMSAdapter()

    created = adapter.create_reservation("prop_1", valid_payload())
    fetched = adapter.get_reservation(created.reservation_id)

    assert isinstance(created, ReservationResult)
    assert created.ok is True
    assert fetched.ok is True
    assert fetched.data["guest_name"] == "Ada Lovelace"
    assert fetched.data["status"] == "confirmed"


def test_list_reservations_filters_by_property():
    backend = MockPMSBackend(
        properties={
            "prop_1": {"id": "prop_1", "name": "One"},
            "prop_2": {"id": "prop_2", "name": "Two"},
        }
    )
    adapter = GenericPMSAdapter(backend)

    adapter.create_reservation("prop_1", valid_payload(guest_name="Guest One"))
    adapter.create_reservation("prop_2", valid_payload(guest_name="Guest Two"))
    result = adapter.list_reservations("prop_1")

    assert result.ok is True
    assert len(result.data) == 1
    assert result.data[0]["guest_name"] == "Guest One"


def test_update_reservation_changes_allowed_fields():
    adapter = GenericPMSAdapter()
    created = adapter.create_reservation("prop_1", valid_payload())

    updated = adapter.update_reservation(
        created.reservation_id,
        {
            "guest_name": "Grace Hopper",
            "arrival_date": "2026-06-02",
            "departure_date": "2026-06-04",
            "room_type": "deluxe",
        },
    )

    assert updated.ok is True
    assert updated.data["guest_name"] == "Grace Hopper"
    assert updated.data["room_type"] == "deluxe"


def test_cancel_reservation_sets_cancelled_status():
    adapter = GenericPMSAdapter()
    created = adapter.create_reservation("prop_1", valid_payload())

    cancelled = adapter.cancel_reservation(created.reservation_id)

    assert cancelled.ok is True
    assert cancelled.data["status"] == "cancelled"


def test_create_reservation_validates_required_fields():
    adapter = GenericPMSAdapter()

    with pytest.raises(PMSValidationError, match="guest_name"):
        adapter.create_reservation("prop_1", valid_payload(guest_name=""))


def test_create_reservation_validates_date_order():
    adapter = GenericPMSAdapter()

    with pytest.raises(PMSValidationError, match="arrival_date must be before departure_date"):
        adapter.create_reservation(
            "prop_1",
            valid_payload(arrival_date="2026-06-03", departure_date="2026-06-01"),
        )


def test_result_dataclasses_are_frozen():
    result = ReservationResult(ok=True, reservation_id="res_1")

    with pytest.raises(FrozenInstanceError):
        result.ok = False
