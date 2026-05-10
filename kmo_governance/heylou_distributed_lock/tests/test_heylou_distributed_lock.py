"""Tests for HeyLou hotel-room-allocation distributed lock [CRUX-MK]."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.heylou_distributed_lock import (  # noqa: E402
    DEFAULT_TTL_SECONDS,
    HeyLouDistributedLock,
    LockState,
    RoomSlotKey,
)


def test_room_slot_key_validates_required_parts():
    RoomSlotKey("hotel-1", "room-101", "2026-05-10T20:00Z")
    with pytest.raises(ValueError):
        RoomSlotKey("", "room-101", "2026-05-10T20:00Z")
    with pytest.raises(ValueError):
        RoomSlotKey("hotel-1", "", "2026-05-10T20:00Z")
    with pytest.raises(ValueError):
        RoomSlotKey("hotel-1", "room-101", "")


def test_default_ttl_is_900_seconds():
    manager = HeyLouDistributedLock()
    assert manager.default_ttl_seconds == DEFAULT_TTL_SECONDS == 900.0


def test_new_slot_is_available():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    record = manager.get("hotel-1", "room-101", "slot-a")
    assert record.state == LockState.AVAILABLE
    assert record.holder is None
    assert manager.is_available("hotel-1", "room-101", "slot-a") is True


def test_reserve_sets_holder_and_expiry():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    record = manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    assert record.state == LockState.RESERVED
    assert record.holder == "booking-com"
    assert record.expires_at == 100.0 + DEFAULT_TTL_SECONDS


def test_reserve_same_holder_extends_ttl_and_version():
    now = {"value": 100.0}
    manager = HeyLouDistributedLock(clock=lambda: now["value"])
    first = manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    now["value"] = 200.0
    second = manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    assert second.state == LockState.RESERVED
    assert second.holder == "booking-com"
    assert second.expires_at == 1100.0
    assert second.version == first.version + 1


def test_competing_reserve_records_conflict():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    conflict = manager.reserve("hotel-1", "room-101", "slot-a", "expedia")
    assert conflict.state == LockState.CONFLICT
    assert conflict.holder == "booking-com"
    assert conflict.conflicting_holder == "expedia"


def test_book_promotes_self_reserved_slot():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    booked = manager.book("hotel-1", "room-101", "slot-a", "booking-com")
    assert booked.state == LockState.BOOKED
    assert booked.holder == "booking-com"
    assert booked.expires_at is None
    assert booked.is_terminal is True


def test_book_available_slot_directly():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    booked = manager.book("hotel-1", "room-101", "slot-a", "direct-ota")
    assert booked.state == LockState.BOOKED
    assert booked.holder == "direct-ota"


def test_competing_book_against_reserved_slot_records_conflict():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    conflict = manager.book("hotel-1", "room-101", "slot-a", "expedia")
    assert conflict.state == LockState.CONFLICT
    assert conflict.holder == "booking-com"
    assert conflict.conflicting_holder == "expedia"


def test_reserved_slot_expires_to_available():
    now = {"value": 100.0}
    manager = HeyLouDistributedLock(default_ttl_seconds=10, clock=lambda: now["value"])
    manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    now["value"] = 111.0
    record = manager.get("hotel-1", "room-101", "slot-a")
    assert record.state == LockState.AVAILABLE
    assert record.holder is None
    assert record.expires_at is None


def test_release_requires_current_holder_and_does_not_release_booked():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    manager.reserve("hotel-1", "room-101", "slot-a", "booking-com")
    with pytest.raises(PermissionError):
        manager.release("hotel-1", "room-101", "slot-a", "expedia")

    released = manager.release("hotel-1", "room-101", "slot-a", "booking-com")
    assert released.state == LockState.AVAILABLE

    manager.book("hotel-1", "room-101", "slot-a", "booking-com")
    with pytest.raises(ValueError):
        manager.release("hotel-1", "room-101", "slot-a", "booking-com")


def test_threaded_reserve_allows_one_holder_or_conflict():
    manager = HeyLouDistributedLock(clock=lambda: 100.0)
    barrier = threading.Barrier(2)
    results = []

    def reserve(ota_channel_id: str) -> None:
        barrier.wait()
        results.append(
            manager.reserve("hotel-1", "room-101", "slot-a", ota_channel_id)
        )

    first = threading.Thread(target=reserve, args=("booking-com",))
    second = threading.Thread(target=reserve, args=("expedia",))
    first.start()
    second.start()
    first.join()
    second.join()

    states = {record.state for record in results}
    final = manager.get("hotel-1", "room-101", "slot-a")
    assert LockState.RESERVED in states
    assert LockState.CONFLICT in states
    assert final.state == LockState.CONFLICT
    assert final.holder in {"booking-com", "expedia"}
    assert final.conflicting_holder in {"booking-com", "expedia"}
