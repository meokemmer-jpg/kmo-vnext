from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.sendgrid_email_adapter import (
    EmailResult,
    ListResult,
    SendGridClient,
    SuppressionResult,
    TemplateResult,
)


def test_send_email_success_returns_message_id() -> None:
    client = SendGridClient()

    result = client.send_email(
        to_email="recipient@example.com",
        from_email="sender@example.com",
        subject="Hello",
        content="Body",
    )

    assert result.ok is True
    assert result.message_id is not None
    assert result.status == "mocked"


def test_send_email_validation_rejects_invalid_to_email() -> None:
    client = SendGridClient()

    result = client.send_email(
        to_email="invalid",
        from_email="sender@example.com",
        subject="Hello",
        content="Body",
    )

    assert result == EmailResult(ok=False, error="valid email is required")


def test_send_email_validation_rejects_empty_subject() -> None:
    client = SendGridClient()

    result = client.send_email(
        to_email="recipient@example.com",
        from_email="sender@example.com",
        subject=" ",
        content="Body",
    )

    assert result.ok is False
    assert result.error == "subject is required"


def test_send_template_success_stores_template_message() -> None:
    client = SendGridClient()

    result = client.send_template(
        to_email="recipient@example.com",
        from_email="sender@example.com",
        template_id="d-template",
        dynamic_data={"name": "Ada"},
    )

    assert result.ok is True
    assert result.template_id == "d-template"
    assert result.message_id is not None


def test_send_template_rejects_blank_template_id() -> None:
    client = SendGridClient()

    result = client.send_template(
        to_email="recipient@example.com",
        from_email="sender@example.com",
        template_id=" ",
    )

    assert result.ok is False
    assert result.error == "template_id is required"


def test_manage_lists_create_and_get() -> None:
    client = SendGridClient()

    created = client.manage_lists(
        action="create",
        name="Customers",
        contacts=["a@example.com", "b@example.com"],
    )
    fetched = client.manage_lists(action="get", list_id=created.list_id)

    assert created.ok is True
    assert fetched.ok is True
    assert fetched.list_data == {
        "id": created.list_id,
        "name": "Customers",
        "contacts": ["a@example.com", "b@example.com"],
    }


def test_manage_lists_update() -> None:
    client = SendGridClient()
    created = client.manage_lists(action="create", name="Old")

    updated = client.manage_lists(
        action="update",
        list_id=created.list_id,
        name="New",
        contacts=["new@example.com"],
    )

    assert updated.ok is True
    assert updated.list_data == {
        "id": created.list_id,
        "name": "New",
        "contacts": ["new@example.com"],
    }


def test_manage_lists_delete() -> None:
    client = SendGridClient()
    created = client.manage_lists(action="create", name="Delete Me")

    deleted = client.manage_lists(action="delete", list_id=created.list_id)
    fetched = client.manage_lists(action="get", list_id=created.list_id)

    assert deleted.ok is True
    assert fetched.ok is False
    assert fetched.error == "list not found"


def test_manage_lists_rejects_unknown_action() -> None:
    client = SendGridClient()

    result = client.manage_lists(action="archive", list_id="list_1")

    assert result == ListResult(ok=False, action="archive", error="unsupported list action")


def test_suppression_handling_add_check_remove() -> None:
    client = SendGridClient()

    added = client.suppression_handling(action="add", email="blocked@example.com")
    checked = client.suppression_handling(action="check", email="blocked@example.com")
    removed = client.suppression_handling(action="remove", email="blocked@example.com")
    checked_again = client.suppression_handling(action="check", email="blocked@example.com")

    assert added.suppressed is True
    assert checked.suppressed is True
    assert removed.suppressed is False
    assert checked_again.suppressed is False


def test_real_api_switch_is_env_var_gated_but_not_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KMO_SENDGRID_USE_REAL_API", "true")
    client = SendGridClient()

    result = client.send_email(
        to_email="recipient@example.com",
        from_email="sender@example.com",
        subject="Hello",
        content="Body",
    )

    assert result.ok is False
    assert result.status == "real_api_disabled"
    assert result.error == "real API is not implemented in MVP"


def test_result_dataclasses_are_frozen() -> None:
    results = [
        EmailResult(ok=True),
        TemplateResult(ok=True),
        ListResult(ok=True, action="get"),
        SuppressionResult(ok=True, email="a@example.com"),
    ]

    for result in results:
        with pytest.raises(FrozenInstanceError):
            result.ok = False  # type: ignore[misc]
