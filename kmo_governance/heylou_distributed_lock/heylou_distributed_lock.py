"""HeyLou distributed lock for hotel-room-allocation across OTA channels.

Domain:
  - Key: (hotel_id, room_id, time_slot)
  - Holder: ota_channel_id
  - States: AVAILABLE, RESERVED, BOOKED, CONFLICT
  - Default TTL: 900 seconds for RESERVED allocations

The implementation is intentionally in-memory and thread-safe. It models the
coordination primitive used before a persistent or networked lock backend is
introduced.
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional


DEFAULT_TTL_SECONDS = 900.0


class LockState(str, enum.Enum):
    """Allocation state for one hotel room time slot."""

    AVAILABLE = "available"
    RESERVED = "reserved"
    BOOKED = "booked"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class RoomSlotKey:
    """Unique allocation key for a hotel room time slot."""

    hotel_id: str
    room_id: str
    time_slot: str

    def __post_init__(self) -> None:
        if not self.hotel_id:
            raise ValueError("hotel_id must be non-empty")
        if not self.room_id:
            raise ValueError("room_id must be non-empty")
        if not self.time_slot:
            raise ValueError("time_slot must be non-empty")


@dataclass(frozen=True)
class LockRecord:
    """Snapshot of one room-slot lock."""

    key: RoomSlotKey
    state: LockState
    holder: Optional[str] = None
    expires_at: Optional[float] = None
    conflicting_holder: Optional[str] = None
    version: int = 0
    updated_at: float = 0.0

    @property
    def is_terminal(self) -> bool:
        return self.state == LockState.BOOKED


class HeyLouDistributedLock:
    """Thread-safe in-memory lock manager for OTA room allocation.

    RESERVED records expire via TTL. BOOKED records are terminal and do not
    expire automatically. A competing OTA attempting to reserve or book an
    already-held slot records CONFLICT with the original holder preserved.
    """

    def __init__(
        self,
        default_ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be > 0")
        self._default_ttl_seconds = float(default_ttl_seconds)
        self._clock = clock
        self._lock = threading.RLock()
        self._records: dict[RoomSlotKey, LockRecord] = {}
        self._audit: list[LockRecord] = []

    @property
    def default_ttl_seconds(self) -> float:
        return self._default_ttl_seconds

    def reserve(
        self,
        hotel_id: str,
        room_id: str,
        time_slot: str,
        ota_channel_id: str,
        ttl_seconds: Optional[float] = None,
    ) -> LockRecord:
        """Reserve a room slot for an OTA channel."""

        key = RoomSlotKey(hotel_id=hotel_id, room_id=room_id, time_slot=time_slot)
        holder = self._validate_holder(ota_channel_id)
        ttl = self._resolve_ttl(ttl_seconds)

        with self._lock:
            now = self._clock()
            current = self._current_record(key, now)
            if current.state in {LockState.AVAILABLE, LockState.RESERVED} and (
                current.holder in {None, holder}
            ):
                return self._store(
                    replace(
                        current,
                        state=LockState.RESERVED,
                        holder=holder,
                        expires_at=now + ttl,
                        conflicting_holder=None,
                        version=current.version + 1,
                        updated_at=now,
                    )
                )

            return self._conflict(current, holder, now)

    def book(
        self,
        hotel_id: str,
        room_id: str,
        time_slot: str,
        ota_channel_id: str,
    ) -> LockRecord:
        """Promote an available or self-held reserved slot to BOOKED."""

        key = RoomSlotKey(hotel_id=hotel_id, room_id=room_id, time_slot=time_slot)
        holder = self._validate_holder(ota_channel_id)

        with self._lock:
            now = self._clock()
            current = self._current_record(key, now)
            if current.state in {LockState.AVAILABLE, LockState.RESERVED} and (
                current.holder in {None, holder}
            ):
                return self._store(
                    replace(
                        current,
                        state=LockState.BOOKED,
                        holder=holder,
                        expires_at=None,
                        conflicting_holder=None,
                        version=current.version + 1,
                        updated_at=now,
                    )
                )

            if current.state == LockState.BOOKED and current.holder == holder:
                return current

            return self._conflict(current, holder, now)

    def release(
        self,
        hotel_id: str,
        room_id: str,
        time_slot: str,
        ota_channel_id: str,
    ) -> LockRecord:
        """Release a RESERVED or CONFLICT slot when called by the owning OTA."""

        key = RoomSlotKey(hotel_id=hotel_id, room_id=room_id, time_slot=time_slot)
        holder = self._validate_holder(ota_channel_id)

        with self._lock:
            now = self._clock()
            current = self._current_record(key, now)
            if current.state == LockState.AVAILABLE:
                return current
            if current.state == LockState.BOOKED:
                raise ValueError("booked slots cannot be released by lock release")
            if current.holder != holder:
                raise PermissionError("only the current holder can release the slot")

            return self._store(
                replace(
                    current,
                    state=LockState.AVAILABLE,
                    holder=None,
                    expires_at=None,
                    conflicting_holder=None,
                    version=current.version + 1,
                    updated_at=now,
                )
            )

    def get(
        self,
        hotel_id: str,
        room_id: str,
        time_slot: str,
    ) -> LockRecord:
        """Return the current lock snapshot for a room slot."""

        key = RoomSlotKey(hotel_id=hotel_id, room_id=room_id, time_slot=time_slot)
        with self._lock:
            return self._current_record(key, self._clock())

    def is_available(self, hotel_id: str, room_id: str, time_slot: str) -> bool:
        return self.get(hotel_id, room_id, time_slot).state == LockState.AVAILABLE

    def sweep_expired(self) -> int:
        """Expire all stale RESERVED records and return the number changed."""

        expired = 0
        with self._lock:
            now = self._clock()
            for key in list(self._records):
                before = self._records[key]
                after = self._expire_if_needed(before, now)
                if after is not before:
                    self._store(after)
                    expired += 1
        return expired

    def audit_trail(self) -> tuple[LockRecord, ...]:
        with self._lock:
            return tuple(self._audit)

    def records(self) -> tuple[LockRecord, ...]:
        with self._lock:
            now = self._clock()
            return tuple(self._current_record(key, now) for key in sorted(
                self._records,
                key=lambda item: (item.hotel_id, item.room_id, item.time_slot),
            ))

    def _current_record(self, key: RoomSlotKey, now: float) -> LockRecord:
        current = self._records.get(key)
        if current is None:
            return LockRecord(
                key=key,
                state=LockState.AVAILABLE,
                version=0,
                updated_at=now,
            )

        expired = self._expire_if_needed(current, now)
        if expired is not current:
            return self._store(expired)
        return current

    def _expire_if_needed(self, record: LockRecord, now: float) -> LockRecord:
        if (
            record.state == LockState.RESERVED
            and record.expires_at is not None
            and record.expires_at <= now
        ):
            return replace(
                record,
                state=LockState.AVAILABLE,
                holder=None,
                expires_at=None,
                conflicting_holder=None,
                version=record.version + 1,
                updated_at=now,
            )
        return record

    def _conflict(
        self,
        current: LockRecord,
        conflicting_holder: str,
        now: float,
    ) -> LockRecord:
        return self._store(
            replace(
                current,
                state=LockState.CONFLICT,
                expires_at=None,
                conflicting_holder=conflicting_holder,
                version=current.version + 1,
                updated_at=now,
            )
        )

    def _store(self, record: LockRecord) -> LockRecord:
        self._records[record.key] = record
        self._audit.append(record)
        return record

    def _resolve_ttl(self, ttl_seconds: Optional[float]) -> float:
        ttl = self._default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        if ttl <= 0:
            raise ValueError("ttl_seconds must be > 0")
        return ttl

    @staticmethod
    def _validate_holder(ota_channel_id: str) -> str:
        if not ota_channel_id:
            raise ValueError("ota_channel_id must be non-empty")
        return ota_channel_id
