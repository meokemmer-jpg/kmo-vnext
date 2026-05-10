"""HeyLou hotel-room-allocation distributed lock module [CRUX-MK]."""

from __future__ import annotations

from .heylou_distributed_lock import (
    DEFAULT_TTL_SECONDS,
    HeyLouDistributedLock,
    LockRecord,
    LockState,
    RoomSlotKey,
)

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "HeyLouDistributedLock",
    "LockRecord",
    "LockState",
    "RoomSlotKey",
]

# CRUX-MK
