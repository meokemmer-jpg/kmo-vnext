from __future__ import annotations

import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Literal


Channel = Literal["sms", "whatsapp"]
MessageStatus = Literal["queued", "sent", "delivered", "failed", "undelivered"]


class TwilioAdapterError(Exception):
    """Base error for the MVP adapter."""


class ValidationError(TwilioAdapterError):
    """Raised when adapter input is invalid."""


class RateLimitError(TwilioAdapterError):
    """Raised when the local mock rate limit is exceeded."""


@dataclass(frozen=True)
class MessageRecord:
    sid: str
    channel: Channel
    to: str
    from_: str
    body: str
    status: MessageStatus
    created_at: float
    updated_at: float
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class SendResult:
    ok: bool
    sid: str | None
    status: MessageStatus | None
    channel: Channel
    error: str | None = None


@dataclass(frozen=True)
class LookupResult:
    ok: bool
    phone_number: str | None
    valid: bool
    country_code: str | None = None
    carrier: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class StatusCallbackResult:
    ok: bool
    sid: str | None
    status: MessageStatus | None
    error: str | None = None


@dataclass(frozen=True)
class HistoryResult:
    ok: bool
    messages: tuple[MessageRecord, ...]
    error: str | None = None


class TwilioClient:
    """Twilio SMS/WhatsApp MVP adapter with an in-memory mock backend."""

    _PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
    _STATUSES: set[str] = {"queued", "sent", "delivered", "failed", "undelivered"}

    def __init__(
        self,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        default_from_sms: str = "+15550000001",
        default_from_whatsapp: str = "whatsapp:+15550000002",
        rate_limit_per_minute: int = 60,
        backend: str | None = None,
    ) -> None:
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN")
        self.default_from_sms = default_from_sms
        self.default_from_whatsapp = default_from_whatsapp
        self.rate_limit_per_minute = rate_limit_per_minute
        self.backend = backend or os.getenv("KMO_TWILIO_BACKEND", "mock").lower()

        self._lock = threading.RLock()
        self._messages: dict[str, MessageRecord] = {}
        self._request_times: list[float] = []

        if self.rate_limit_per_minute <= 0:
            raise ValidationError("rate_limit_per_minute must be greater than zero")

    def send_sms(self, *, to: str, body: str, from_: str | None = None) -> SendResult:
        self._ensure_mock_backend()
        self._validate_phone(to)
        sender = from_ or self.default_from_sms
        self._validate_phone(sender)
        self._validate_body(body)
        return self._send(channel="sms", to=to, body=body, from_=sender)

    def send_whatsapp(self, *, to: str, body: str, from_: str | None = None) -> SendResult:
        self._ensure_mock_backend()
        normalized_to = self._normalize_whatsapp(to)
        sender = from_ or self.default_from_whatsapp
        normalized_from = self._normalize_whatsapp(sender)
        self._validate_body(body)
        return self._send(channel="whatsapp", to=normalized_to, body=body, from_=normalized_from)

    def lookup_number(self, phone_number: str) -> LookupResult:
        self._ensure_mock_backend()
        try:
            self._validate_phone(phone_number)
        except ValidationError as exc:
            return LookupResult(ok=False, phone_number=phone_number, valid=False, error=str(exc))

        return LookupResult(
            ok=True,
            phone_number=phone_number,
            valid=True,
            country_code=self._country_code(phone_number),
            carrier="mock-carrier",
        )

    def status_callback(
        self,
        *,
        sid: str,
        status: MessageStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> StatusCallbackResult:
        self._ensure_mock_backend()
        if status not in self._STATUSES:
            return StatusCallbackResult(ok=False, sid=sid, status=None, error="invalid status")

        with self._lock:
            current = self._messages.get(sid)
            if current is None:
                return StatusCallbackResult(ok=False, sid=sid, status=None, error="message not found")

            updated = MessageRecord(
                sid=current.sid,
                channel=current.channel,
                to=current.to,
                from_=current.from_,
                body=current.body,
                status=status,
                created_at=current.created_at,
                updated_at=time.time(),
                error_code=error_code,
                error_message=error_message,
            )
            self._messages[sid] = updated

        return StatusCallbackResult(ok=True, sid=sid, status=status)

    def message_history(
        self,
        *,
        to: str | None = None,
        channel: Channel | None = None,
        limit: int | None = None,
    ) -> HistoryResult:
        self._ensure_mock_backend()
        if channel is not None and channel not in {"sms", "whatsapp"}:
            return HistoryResult(ok=False, messages=(), error="invalid channel")
        if limit is not None and limit < 0:
            return HistoryResult(ok=False, messages=(), error="limit must be non-negative")

        with self._lock:
            messages = list(self._messages.values())

        if to is not None:
            messages = [message for message in messages if message.to == to]
        if channel is not None:
            messages = [message for message in messages if message.channel == channel]

        messages.sort(key=lambda message: message.created_at, reverse=True)
        if limit is not None:
            messages = messages[:limit]

        return HistoryResult(ok=True, messages=tuple(messages))

    def _send(self, *, channel: Channel, to: str, body: str, from_: str) -> SendResult:
        try:
            self._check_rate_limit()
        except RateLimitError as exc:
            return SendResult(ok=False, sid=None, status=None, channel=channel, error=str(exc))

        now = time.time()
        sid = f"SM{uuid.uuid4().hex}"
        record = MessageRecord(
            sid=sid,
            channel=channel,
            to=to,
            from_=from_,
            body=body,
            status="queued",
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            self._messages[sid] = record

        return SendResult(ok=True, sid=sid, status="queued", channel=channel)

    def _check_rate_limit(self) -> None:
        now = time.time()
        window_start = now - 60

        with self._lock:
            self._request_times = [stamp for stamp in self._request_times if stamp >= window_start]
            if len(self._request_times) >= self.rate_limit_per_minute:
                raise RateLimitError("rate limit exceeded")
            self._request_times.append(now)

    def _ensure_mock_backend(self) -> None:
        if self.backend != "mock":
            raise TwilioAdapterError("real Twilio backend is gated and not implemented in this MVP")

    def _validate_phone(self, value: str) -> None:
        if not isinstance(value, str) or not self._PHONE_RE.match(value):
            raise ValidationError("phone number must be E.164 formatted")

    def _validate_body(self, body: str) -> None:
        if not isinstance(body, str) or not body.strip():
            raise ValidationError("message body is required")
        if len(body) > 1600:
            raise ValidationError("message body exceeds 1600 characters")

    def _normalize_whatsapp(self, value: str) -> str:
        if value.startswith("whatsapp:"):
            phone = value.removeprefix("whatsapp:")
        else:
            phone = value
        self._validate_phone(phone)
        return f"whatsapp:{phone}"

    def _country_code(self, phone_number: str) -> str:
        if phone_number.startswith("+1"):
            return "US"
        if phone_number.startswith("+49"):
            return "DE"
        return "ZZ"
