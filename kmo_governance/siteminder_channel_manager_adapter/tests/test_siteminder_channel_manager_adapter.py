from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.siteminder_channel_manager_adapter import (
    BookingResult,
    ChannelHealthResult,
    ChannelResult,
    DistributionResult,
    PushResult,
    SiteMinderClient,
)


def test_list_channels_returns_default_mock_channels() -> None:
    client = SiteMinderClient()
    result = client.list_channels()

    assert isinstance(result, ChannelResult)
    assert result.ok is True
    assert result.channels == ("airbnb", "booking.com", "expedia")


def test_push_to_channel_updates_mock_backend_state() -> None:
    client = SiteMinderClient()

    result = client.push_to_channel("booking.com", 149.5, 7)
    state = client.get_channel_state("booking.com")

    assert result == PushResult(True, "booking.com", 149.5, 7, "pushed")
    assert state["rate"] == 149.5
    assert state["inventory"] == 7
    assert state["updated_at"] is not None


def test_push_to_channel_normalizes_channel_name() -> None:
    client = SiteMinderClient()

    result = client.push_to_channel(" Booking.Com ", 120, 3)

    assert result.ok is True
    assert result.channel == "booking.com"


def test_push_to_unknown_channel_fails() -> None:
    client = SiteMinderClient()

    result = client.push_to_channel("unknown", 100, 1)

    assert result.ok is False
    assert result.message == "unknown channel"


def test_push_negative_rate_fails_validation() -> None:
    client = SiteMinderClient()

    result = client.push_to_channel("booking.com", -1, 1)

    assert result.ok is False
    assert result.message == "rate must be non-negative"


def test_push_negative_inventory_fails_validation() -> None:
    client = SiteMinderClient()

    result = client.push_to_channel("booking.com", 100, -1)

    assert result.ok is False
    assert result.message == "inventory must be non-negative"


def test_distribute_ari_pushes_to_all_channels() -> None:
    client = SiteMinderClient()

    result = client.distribute_ari(199, 4)

    assert isinstance(result, DistributionResult)
    assert result.ok is True
    assert len(result.pushed) == 3
    assert result.failed == ()
    assert {push.channel for push in result.pushed} == {"airbnb", "booking.com", "expedia"}


def test_distribute_ari_reports_partial_failure() -> None:
    client = SiteMinderClient()

    result = client.distribute_ari(199, 4, channels=("booking.com", "unknown"))

    assert result.ok is False
    assert len(result.pushed) == 1
    assert len(result.failed) == 1
    assert result.failed[0].message == "unknown channel"


def test_receive_booking_from_channel_stores_booking() -> None:
    client = SiteMinderClient()
    payload = {"booking_id": "B-1", "guest_name": "Ada Lovelace", "nights": 2}

    result = client.receive_booking_from_channel("airbnb", payload)
    booking = client.get_booking("B-1")

    assert isinstance(result, BookingResult)
    assert result.ok is True
    assert result.booking_id == "B-1"
    assert booking["guest_name"] == "Ada Lovelace"
    assert booking["channel"] == "airbnb"


def test_receive_booking_requires_guest_name() -> None:
    client = SiteMinderClient()

    result = client.receive_booking_from_channel("airbnb", {"booking_id": "B-2"})

    assert result.ok is False
    assert result.message == "guest_name is required"


def test_channel_health_check_reports_healthy_and_unhealthy() -> None:
    client = SiteMinderClient()

    healthy = client.channel_health_check("expedia")
    client.set_channel_health("expedia", False)
    unhealthy = client.channel_health_check("expedia")

    assert healthy == ChannelHealthResult(True, "expedia", "healthy", "channel healthy")
    assert unhealthy == ChannelHealthResult(False, "expedia", "unhealthy", "channel unhealthy")


def test_result_dataclasses_are_frozen() -> None:
    result = PushResult(True, "booking.com", 100.0, 1, "pushed")

    with pytest.raises(FrozenInstanceError):
        result.ok = False
