from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.twilio_messaging_adapter import (
    HistoryResult,
    LookupResult,
    MessageRecord,
    RateLimitError,
    SendResult,
    StatusCallbackResult,
    TwilioAdapterError,
    TwilioClient,
    ValidationError,
)


def test_send_sms_creates_mock_message() -> None:
    client = TwilioClient()

    result = client.send_sms(to="+15551234567", body="hello")

    assert result.ok is True
    assert result.sid is not None
    assert result.status == "queued"
    assert result.channel == "sms"


def test_send_whatsapp_creates_mock_message_with_normalized_addresses() -> None:
    client = TwilioClient()

    result = client.send_whatsapp(to="+15551234567", body="hello")

    assert result.ok is True
    history = client.message_history(channel="whatsapp")
    assert history.messages[0].to == "whatsapp:+15551234567"
    assert history.messages[0].from_ == "whatsapp:+15550000002"


def test_lookup_number_valid() -> None:
    client = TwilioClient()

    result = client.lookup_number("+15551234567")

    assert result == LookupResult(
        ok=True,
        phone_number="+15551234567",
        valid=True,
        country_code="US",
        carrier="mock-carrier",
        error=None,
    )


def test_lookup_number_invalid_returns_error_result() -> None:
    client = TwilioClient()

    result = client.lookup_number("5551234567")

    assert result.ok is False
    assert result.valid is False
    assert result.error == "phone number must be E.164 formatted"


def test_status_callback_updates_existing_message() -> None:
    client = TwilioClient()
    sent = client.send_sms(to="+15551234567", body="hello")

    result = client.status_callback(sid=sent.sid or "", status="delivered")

    assert result == StatusCallbackResult(ok=True, sid=sent.sid, status="delivered", error=None)
    assert client.message_history().messages[0].status == "delivered"


def test_status_callback_unknown_sid_returns_error() -> None:
    client = TwilioClient()

    result = client.status_callback(sid="SMmissing", status="delivered")

    assert result.ok is False
    assert result.error == "message not found"


def test_message_history_filters_by_channel_and_limit() -> None:
    client = TwilioClient()
    client.send_sms(to="+15551234567", body="sms")
    client.send_whatsapp(to="+15551234567", body="wa")
    client.send_sms(to="+15557654321", body="sms2")

    result = client.message_history(channel="sms", limit=1)

    assert result.ok is True
    assert len(result.messages) == 1
    assert result.messages[0].channel == "sms"


def test_message_history_filters_by_recipient() -> None:
    client = TwilioClient()
    client.send_sms(to="+15551234567", body="one")
    client.send_sms(to="+15557654321", body="two")

    result = client.message_history(to="+15557654321")

    assert len(result.messages) == 1
    assert result.messages[0].body == "two"


def test_validation_rejects_bad_sms_number() -> None:
    client = TwilioClient()

    with pytest.raises(ValidationError, match="E.164"):
        client.send_sms(to="bad", body="hello")


def test_validation_rejects_empty_body() -> None:
    client = TwilioClient()

    with pytest.raises(ValidationError, match="body is required"):
        client.send_sms(to="+15551234567", body=" ")


def test_rate_limit_returns_error_result() -> None:
    client = TwilioClient(rate_limit_per_minute=1)

    first = client.send_sms(to="+15551234567", body="one")
    second = client.send_sms(to="+15551234567", body="two")

    assert first.ok is True
    assert second.ok is False
    assert second.error == "rate limit exceeded"


def test_frozen_result_dataclasses_are_immutable() -> None:
    send_result = SendResult(ok=True, sid="SM1", status="queued", channel="sms")
    lookup_result = LookupResult(ok=True, phone_number="+15551234567", valid=True)
    status_result = StatusCallbackResult(ok=True, sid="SM1", status="queued")
    history_result = HistoryResult(ok=True, messages=())
    record = MessageRecord(
        sid="SM1",
        channel="sms",
        to="+15551234567",
        from_="+15550000001",
        body="hello",
        status="queued",
        created_at=1.0,
        updated_at=1.0,
    )

    for instance in (send_result, lookup_result, status_result, history_result, record):
        with pytest.raises(FrozenInstanceError):
            instance.ok = False  # type: ignore[attr-defined]
