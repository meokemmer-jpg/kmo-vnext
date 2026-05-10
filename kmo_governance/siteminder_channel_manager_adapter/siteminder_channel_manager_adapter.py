from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ChannelResult:
    ok: bool
    channels: tuple[str, ...]
    message: str = ""


@dataclass(frozen=True)
class PushResult:
    ok: bool
    channel: str
    rate: float
    inventory: int
    message: str = ""


@dataclass(frozen=True)
class BookingResult:
    ok: bool
    booking_id: str
    channel: str
    payload: dict[str, Any]
    message: str = ""


@dataclass(frozen=True)
class DistributionResult:
    ok: bool
    pushed: tuple[PushResult, ...]
    failed: tuple[PushResult, ...]
    message: str = ""


@dataclass(frozen=True)
class ChannelHealthResult:
    ok: bool
    channel: str
    status: str
    message: str = ""


class SiteMinderClient:
    ENV_VAR = "KMO_SITEMINDER_BACKEND"

    def __init__(self, channels: tuple[str, ...] | list[str] | None = None) -> None:
        self._lock = threading.RLock()
        self._backend_mode = os.getenv(self.ENV_VAR, "mock").strip().lower()
        self._channels: dict[str, dict[str, Any]] = {}
        self._bookings: dict[str, dict[str, Any]] = {}

        initial_channels = channels or ("booking.com", "expedia", "airbnb")
        for channel in initial_channels:
            self._channels[self._normalize_channel(channel)] = {
                "rate": None,
                "inventory": None,
                "healthy": True,
                "updated_at": None,
            }

    @property
    def backend_mode(self) -> str:
        return self._backend_mode

    def list_channels(self) -> ChannelResult:
        with self._lock:
            return ChannelResult(
                ok=True,
                channels=tuple(sorted(self._channels.keys())),
                message=f"{self._backend_mode} backend",
            )

    def push_to_channel(self, channel: str, rate: float, inventory: int) -> PushResult:
        normalized = self._normalize_channel(channel)
        validation_error = self._validate_ari(normalized, rate, inventory)
        if validation_error:
            return PushResult(False, normalized, rate, inventory, validation_error)

        if self._backend_mode != "mock":
            return PushResult(
                False,
                normalized,
                rate,
                inventory,
                "real SiteMinder API backend is not implemented in MVP",
            )

        with self._lock:
            if normalized not in self._channels:
                return PushResult(False, normalized, rate, inventory, "unknown channel")

            self._channels[normalized]["rate"] = float(rate)
            self._channels[normalized]["inventory"] = int(inventory)
            self._channels[normalized]["updated_at"] = self._utc_now()

        return PushResult(True, normalized, float(rate), int(inventory), "pushed")

    def distribute_ari(
        self,
        rate: float,
        inventory: int,
        channels: tuple[str, ...] | list[str] | None = None,
    ) -> DistributionResult:
        target_channels = channels or self.list_channels().channels
        pushed: list[PushResult] = []
        failed: list[PushResult] = []

        for channel in target_channels:
            result = self.push_to_channel(channel, rate, inventory)
            if result.ok:
                pushed.append(result)
            else:
                failed.append(result)

        return DistributionResult(
            ok=not failed,
            pushed=tuple(pushed),
            failed=tuple(failed),
            message="distributed" if not failed else "partially distributed",
        )

    def receive_booking_from_channel(
        self,
        channel: str,
        payload: dict[str, Any],
    ) -> BookingResult:
        normalized = self._normalize_channel(channel)
        if not normalized:
            return BookingResult(False, "", normalized, dict(payload), "channel is required")

        if not isinstance(payload, dict):
            return BookingResult(False, "", normalized, {}, "payload must be a dict")

        with self._lock:
            if normalized not in self._channels:
                return BookingResult(False, "", normalized, dict(payload), "unknown channel")

            guest_name = payload.get("guest_name")
            if not guest_name:
                return BookingResult(False, "", normalized, dict(payload), "guest_name is required")

            booking_id = str(payload.get("booking_id") or uuid.uuid4())
            booking = {
                **payload,
                "booking_id": booking_id,
                "channel": normalized,
                "received_at": self._utc_now(),
            }
            self._bookings[booking_id] = booking

        return BookingResult(True, booking_id, normalized, dict(booking), "received")

    def channel_health_check(self, channel: str) -> ChannelHealthResult:
        normalized = self._normalize_channel(channel)
        if not normalized:
            return ChannelHealthResult(False, normalized, "invalid", "channel is required")

        with self._lock:
            state = self._channels.get(normalized)
            if state is None:
                return ChannelHealthResult(False, normalized, "unknown", "unknown channel")

            if not state.get("healthy", False):
                return ChannelHealthResult(False, normalized, "unhealthy", "channel unhealthy")

        return ChannelHealthResult(True, normalized, "healthy", "channel healthy")

    def set_channel_health(self, channel: str, healthy: bool) -> None:
        normalized = self._normalize_channel(channel)
        with self._lock:
            if normalized not in self._channels:
                raise ValueError("unknown channel")
            self._channels[normalized]["healthy"] = bool(healthy)

    def get_channel_state(self, channel: str) -> dict[str, Any]:
        normalized = self._normalize_channel(channel)
        with self._lock:
            if normalized not in self._channels:
                raise ValueError("unknown channel")
            return dict(self._channels[normalized])

    def get_booking(self, booking_id: str) -> dict[str, Any]:
        with self._lock:
            if booking_id not in self._bookings:
                raise ValueError("unknown booking")
            return dict(self._bookings[booking_id])

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        if not isinstance(channel, str):
            return ""
        return channel.strip().lower()

    def _validate_ari(self, channel: str, rate: float, inventory: int) -> str:
        if not channel:
            return "channel is required"
        if not isinstance(rate, int | float):
            return "rate must be numeric"
        if rate < 0:
            return "rate must be non-negative"
        if not isinstance(inventory, int):
            return "inventory must be an integer"
        if inventory < 0:
            return "inventory must be non-negative"
        return ""

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
