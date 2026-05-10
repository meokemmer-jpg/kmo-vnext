from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any


class StripeAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class PaymentIntentResult:
    id: str
    amount: int
    currency: str
    status: str
    customer_id: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChargeResult:
    id: str
    payment_intent_id: str
    amount: int
    currency: str
    status: str
    captured: bool


@dataclass(frozen=True)
class RefundResult:
    id: str
    charge_id: str
    amount: int
    currency: str
    status: str


@dataclass(frozen=True)
class CustomerResult:
    id: str
    email: str
    name: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class WebhookResult:
    received: bool
    event_type: str
    event_id: str | None


class StripeClient:
    def __init__(
        self,
        *,
        webhook_secret: str = "test_secret",
        use_real_api: bool | None = None,
    ) -> None:
        self.use_real_api = (
            os.getenv("STRIPE_PAYMENT_ADAPTER_BACKEND", "mock").lower() == "real"
            if use_real_api is None
            else use_real_api
        )
        if self.use_real_api:
            raise NotImplementedError("Real Stripe API backend is intentionally disabled for MVP.")

        self.webhook_secret = webhook_secret
        self._lock = threading.RLock()
        self._payment_intents: dict[str, PaymentIntentResult] = {}
        self._charges: dict[str, ChargeResult] = {}
        self._refunds: dict[str, RefundResult] = {}
        self._customers: dict[str, CustomerResult] = {}
        self._idempotency: dict[str, Any] = {}

    def create_payment_intent(
        self,
        *,
        amount: int,
        currency: str,
        customer_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentIntentResult:
        self._validate_amount(amount)
        self._validate_currency(currency)
        metadata = dict(metadata or {})

        with self._lock:
            cached = self._get_idempotent(idempotency_key)
            if cached is not None:
                return cached

            if customer_id is not None and customer_id not in self._customers:
                raise StripeAdapterError("customer_id does not exist")

            intent = PaymentIntentResult(
                id=self._new_id("pi"),
                amount=amount,
                currency=currency.lower(),
                status="requires_capture",
                customer_id=customer_id,
                metadata=metadata,
            )
            self._payment_intents[intent.id] = intent
            self._set_idempotent(idempotency_key, intent)
            return intent

    def capture_payment(
        self,
        *,
        payment_intent_id: str,
        idempotency_key: str | None = None,
    ) -> ChargeResult:
        with self._lock:
            cached = self._get_idempotent(idempotency_key)
            if cached is not None:
                return cached

            intent = self._payment_intents.get(payment_intent_id)
            if intent is None:
                raise StripeAdapterError("payment intent not found")
            if intent.status != "requires_capture":
                raise StripeAdapterError("payment intent cannot be captured")

            captured_intent = PaymentIntentResult(
                id=intent.id,
                amount=intent.amount,
                currency=intent.currency,
                status="succeeded",
                customer_id=intent.customer_id,
                metadata=dict(intent.metadata),
            )
            charge = ChargeResult(
                id=self._new_id("ch"),
                payment_intent_id=intent.id,
                amount=intent.amount,
                currency=intent.currency,
                status="succeeded",
                captured=True,
            )
            self._payment_intents[intent.id] = captured_intent
            self._charges[charge.id] = charge
            self._set_idempotent(idempotency_key, charge)
            return charge

    def refund_payment(
        self,
        *,
        charge_id: str,
        amount: int | None = None,
        idempotency_key: str | None = None,
    ) -> RefundResult:
        with self._lock:
            cached = self._get_idempotent(idempotency_key)
            if cached is not None:
                return cached

            charge = self._charges.get(charge_id)
            if charge is None:
                raise StripeAdapterError("charge not found")

            refund_amount = charge.amount if amount is None else amount
            self._validate_amount(refund_amount)
            if refund_amount > charge.amount:
                raise StripeAdapterError("refund amount exceeds charge amount")

            refund = RefundResult(
                id=self._new_id("re"),
                charge_id=charge.id,
                amount=refund_amount,
                currency=charge.currency,
                status="succeeded",
            )
            self._refunds[refund.id] = refund
            self._set_idempotent(idempotency_key, refund)
            return refund

    def list_charges(self, *, customer_id: str | None = None) -> list[ChargeResult]:
        with self._lock:
            charges = list(self._charges.values())
            if customer_id is None:
                return charges

            return [
                charge
                for charge in charges
                if self._payment_intents[charge.payment_intent_id].customer_id == customer_id
            ]

    def webhook_handler(self, *, payload: bytes | str, signature: str) -> WebhookResult:
        payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            raise StripeAdapterError("invalid webhook signature")

        try:
            event = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise StripeAdapterError("invalid webhook payload") from exc

        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise StripeAdapterError("webhook event type is required")

        event_id = event.get("id")
        if event_id is not None and not isinstance(event_id, str):
            raise StripeAdapterError("webhook event id must be a string")

        return WebhookResult(received=True, event_type=event_type, event_id=event_id)

    def customer_management(
        self,
        *,
        action: str,
        customer_id: str | None = None,
        email: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> CustomerResult | None:
        action = action.lower()
        metadata = dict(metadata or {})

        with self._lock:
            cached = self._get_idempotent(idempotency_key)
            if cached is not None:
                return cached

            if action == "create":
                if not email or "@" not in email:
                    raise StripeAdapterError("valid email is required")
                customer = CustomerResult(
                    id=self._new_id("cus"),
                    email=email,
                    name=name,
                    metadata=metadata,
                )
                self._customers[customer.id] = customer
                self._set_idempotent(idempotency_key, customer)
                return customer

            if action == "retrieve":
                if not customer_id:
                    raise StripeAdapterError("customer_id is required")
                customer = self._customers.get(customer_id)
                if customer is None:
                    raise StripeAdapterError("customer not found")
                return customer

            if action == "update":
                if not customer_id:
                    raise StripeAdapterError("customer_id is required")
                existing = self._customers.get(customer_id)
                if existing is None:
                    raise StripeAdapterError("customer not found")
                updated = CustomerResult(
                    id=existing.id,
                    email=email or existing.email,
                    name=name if name is not None else existing.name,
                    metadata=metadata or dict(existing.metadata),
                )
                self._customers[updated.id] = updated
                self._set_idempotent(idempotency_key, updated)
                return updated

            if action == "delete":
                if not customer_id:
                    raise StripeAdapterError("customer_id is required")
                if customer_id not in self._customers:
                    raise StripeAdapterError("customer not found")
                del self._customers[customer_id]
                return None

            raise StripeAdapterError("unsupported customer action")

    def _get_idempotent(self, key: str | None) -> Any | None:
        if key is None:
            return None
        return self._idempotency.get(key)

    def _set_idempotent(self, key: str | None, value: Any) -> None:
        if key is not None:
            self._idempotency[key] = value

    @staticmethod
    def _validate_amount(amount: int) -> None:
        if not isinstance(amount, int) or amount <= 0:
            raise StripeAdapterError("amount must be a positive integer")

    @staticmethod
    def _validate_currency(currency: str) -> None:
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            raise StripeAdapterError("currency must be a 3-letter ISO code")

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:12]}"
