from __future__ import annotations

from dataclasses import FrozenInstanceError
import os

import pytest

from kmo_governance.hubspot_crm_adapter import (
    ActivityResult,
    ContactResult,
    DealResult,
    HubSpotClient,
    OAuth2Mock,
)


def test_oauth2_mock_returns_access_token() -> None:
    oauth = OAuth2Mock(access_token="token-123")

    assert oauth.authorize() == "token-123"


def test_default_backend_is_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HUBSPOT_CRM_BACKEND", raising=False)

    client = HubSpotClient()

    assert client.backend == "mock"


def test_real_backend_switch_is_env_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_CRM_BACKEND", "real")

    with pytest.raises(NotImplementedError):
        HubSpotClient()


def test_create_contact_validation_requires_email() -> None:
    client = HubSpotClient()

    result = client.create_contact({"first_name": "Ada", "last_name": "Lovelace"})

    assert result == ContactResult(ok=False, error="email is required")


def test_create_and_list_contacts() -> None:
    client = HubSpotClient()

    created = client.create_contact(
        {
            "email": "ada@example.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "guest_status": "returning",
        }
    )
    listed = client.list_contacts()

    assert created.ok is True
    assert created.id == "contact_1"
    assert created.contact is not None
    assert created.contact["email"] == "ada@example.com"
    assert listed.ok is True
    assert len(listed.contacts) == 1
    assert listed.contacts[0]["guest_status"] == "returning"


def test_create_contact_rejects_duplicate_email() -> None:
    client = HubSpotClient()
    payload = {"email": "ada@example.com", "first_name": "Ada", "last_name": "Lovelace"}

    assert client.create_contact(payload).ok is True
    duplicate = client.create_contact(payload)

    assert duplicate.ok is False
    assert duplicate.error == "email already exists"


def test_update_contact_changes_allowed_fields() -> None:
    client = HubSpotClient()
    created = client.create_contact(
        {"email": "ada@example.com", "first_name": "Ada", "last_name": "Lovelace"}
    )

    updated = client.update_contact(
        created.id or "",
        {"phone": "+49 30 123", "guest_status": "vip", "unknown": "ignored"},
    )

    assert updated.ok is True
    assert updated.contact is not None
    assert updated.contact["phone"] == "+49 30 123"
    assert updated.contact["guest_status"] == "vip"
    assert "unknown" not in updated.contact


def test_update_contact_not_found() -> None:
    client = HubSpotClient()

    result = client.update_contact("missing", {"phone": "+49 30 123"})

    assert result.ok is False
    assert result.error == "contact not found"


def test_create_deal_requires_existing_contact() -> None:
    client = HubSpotClient()

    result = client.create_deal({"name": "Weekend Stay", "contact_id": "missing", "amount": 199})

    assert result == DealResult(ok=False, error="contact not found")


def test_create_and_list_deals() -> None:
    client = HubSpotClient()
    contact = client.create_contact(
        {"email": "guest@example.com", "first_name": "Grace", "last_name": "Hopper"}
    )

    created = client.create_deal(
        {
            "name": "Suite Booking",
            "contact_id": contact.id,
            "amount": 499.5,
            "stage": "reserved",
        }
    )
    listed = client.list_deals()

    assert created.ok is True
    assert created.id == "deal_1"
    assert created.deal is not None
    assert created.deal["stage"] == "reserved"
    assert listed.ok is True
    assert len(listed.deals) == 1
    assert listed.deals[0]["amount"] == 499.5


def test_log_activity_for_contact() -> None:
    client = HubSpotClient()
    contact = client.create_contact(
        {"email": "guest@example.com", "first_name": "Grace", "last_name": "Hopper"}
    )

    result = client.log_activity(
        {
            "contact_id": contact.id,
            "activity_type": "email",
            "note": "Sent pre-arrival message",
        }
    )

    assert result.ok is True
    assert result.id == "activity_1"
    assert result.activity is not None
    assert result.activity["note"] == "Sent pre-arrival message"


def test_list_companies_and_result_immutability() -> None:
    client = HubSpotClient()

    companies = client.list_companies()
    frozen = ActivityResult(ok=True, id="activity_1")

    assert companies.ok is True
    assert len(companies.companies) == 1
    assert companies.companies[0]["name"] == "Hotel Demo GmbH"

    with pytest.raises(FrozenInstanceError):
        frozen.ok = False  # type: ignore[misc]
