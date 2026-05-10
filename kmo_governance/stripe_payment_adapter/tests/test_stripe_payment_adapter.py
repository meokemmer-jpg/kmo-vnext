from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.stripe_payment_adapter import (
    ChargeResult,
    PaymentIntentResult,
    StripeAdapterError,
    StripeClient,
)


def sign(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def test_create_payment_intent_validates_amount() -> None:
    client = StripeClient()

    with pytest.raises(StripeAdapterError, match="amount"):
        client.create_payment_intent(amount=0, currency="usd")


def test_create_payment_intent_validates_currency() -> None:
    client = StripeClient()

    with pytest.raises(StripeAdapterError, match="currency"):
        client.create_payment_intent(amount=1000, currency="us")


def test_create_payment_intent_basic() -> None:
    client = StripeClient()

    intent = client.create_payment_intent(amount=1000, currency="USD", metadata={"order": "A1"})

    assert isinstance(intent, PaymentIntentResult)
    assert intent.id.startswith("pi_")
    assert intent.amount == 1000
    assert intent.currency == "usd"
    assert intent.status == "requires_capture"
    assert intent.metadata == {"order": "A1"}


def test_create_payment_intent_idempotency_key_returns_same_result() -> None:
    client = StripeClient()

    first = client.create_payment_intent(amount=1000, currency="usd", idempotency_key="same")
    second = client.create_payment_intent(amount=2000, currency="eur", idempotency_key="same")

    assert second == first


def test_capture_payment_basic() -> None:
    client = StripeClient()
    intent = client.create_payment_intent(amount=1200, currency="usd")

    charge = client.capture_payment(payment_intent_id=intent.id)

    assert isinstance(charge, ChargeResult)
    assert charge.id.startswith("ch_")
    assert charge.payment_intent_id == intent.id
    assert charge.amount == 1200
    assert charge.status == "succeeded"
    assert charge.captured is True


def test_capture_payment_rejects_missing_intent() -> None:
    client = StripeClient()

    with pytest.raises(StripeAdapterError, match="not found"):
        client.capture_payment(payment_intent_id="pi_missing")


def test_capture_payment_rejects_double_capture() -> None:
    client = StripeClient()
    intent = client.create_payment_intent(amount=1200, currency="usd")
    client.capture_payment(payment_intent_id=intent.id)

    with pytest.raises(StripeAdapterError, match="cannot be captured"):
        client.capture_payment(payment_intent_id=intent.id)


def test_refund_payment_basic() -> None:
    client = StripeClient()
    intent = client.create_payment_intent(amount=1200, currency="usd")
    charge = client.capture_payment(payment_intent_id=intent.id)

    refund = client.refund_payment(charge_id=charge.id, amount=500)

    assert refund.id.startswith("re_")
    assert refund.charge_id == charge.id
    assert refund.amount == 500
    assert refund.currency == "usd"
    assert refund.status == "succeeded"


def test_refund_payment_rejects_excess_amount() -> None:
    client = StripeClient()
    intent = client.create_payment_intent(amount=1200, currency="usd")
    charge = client.capture_payment(payment_intent_id=intent.id)

    with pytest.raises(StripeAdapterError, match="exceeds"):
        client.refund_payment(charge_id=charge.id, amount=1201)


def test_list_charges_filters_by_customer() -> None:
    client = StripeClient()
    customer = client.customer_management(action="create", email="user@example.com", name="User")
    other = client.customer_management(action="create", email="other@example.com")

    intent = client.create_payment_intent(amount=1200, currency="usd", customer_id=customer.id)
    other_intent = client.create_payment_intent(amount=1500, currency="usd", customer_id=other.id)
    charge = client.capture_payment(payment_intent_id=intent.id)
    client.capture_payment(payment_intent_id=other_intent.id)

    assert client.list_charges(customer_id=customer.id) == [charge]
    assert len(client.list_charges()) == 2


def test_webhook_handler_validates_hmac_signature() -> None:
    client = StripeClient(webhook_secret="secret")
    payload = json.dumps({"id": "evt_1", "type": "payment_intent.succeeded"}).encode("utf-8")

    result = client.webhook_handler(payload=payload, signature=sign("secret", payload))

    assert result.received is True
    assert result.event_type == "payment_intent.succeeded"
    assert result.event_id == "evt_1"

    with pytest.raises(StripeAdapterError, match="signature"):
        client.webhook_handler(payload=payload, signature="bad")


def test_result_dataclasses_are_frozen() -> None:
    client = StripeClient()
    intent = client.create_payment_intent(amount=1200, currency="usd")

    with pytest.raises(FrozenInstanceError):
        intent.status = "mutated"
