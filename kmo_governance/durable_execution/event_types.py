"""Event-Type Definitions for KMO Durable-Execution-State-Machine.

Implements P-KMO-A7 per SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30 §P-KMO-A7.

Defines the 4 event-classes for the immutable event-sourcing log:
- RoutingDecision   -- which DF/agent picked up a phase
- DFStatusChange    -- a Dark-Factory transitioned status
- StopFlagTransition -- a STOP.flag was raised/cleared
- ApprovalState     -- approval-gate response (Gerdi/Martin/auto)

CRUX-MK: Q_0 erhoeht durch immutable Audit-Trail; W_0 by replayability.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    """Discriminator for the 4 KMO event-classes."""

    ROUTING_DECISION = "ROUTING_DECISION"
    DF_STATUS_CHANGE = "DF_STATUS_CHANGE"
    STOP_FLAG_TRANSITION = "STOP_FLAG_TRANSITION"
    APPROVAL_STATE = "APPROVAL_STATE"
    # System-events for state-machine itself (not in spec but required for replay):
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    STATE_TRANSITION = "STATE_TRANSITION"
    SNAPSHOT_TAKEN = "SNAPSHOT_TAKEN"


@dataclass(frozen=True)
class Event:
    """Immutable event in the workflow event-log.

    Frozen dataclass to prevent mutation after append.
    """

    event_id: str
    workflow_id: str
    event_type: EventType
    timestamp: float
    sequence: int
    payload: dict
    actor: Optional[str] = None  # who/what produced this event
    correlation_id: Optional[str] = None  # link to upstream cause

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            event_id=d["event_id"],
            workflow_id=d["workflow_id"],
            event_type=EventType(d["event_type"]),
            timestamp=d["timestamp"],
            sequence=d["sequence"],
            payload=d.get("payload", {}),
            actor=d.get("actor"),
            correlation_id=d.get("correlation_id"),
        )


# ----- Payload schemas (documented as dict-shape) -----
# We use plain dicts in payload for serialization stability, but the helper
# constructors below enforce the schema at write-time.


def make_routing_decision(
    workflow_id: str,
    sequence: int,
    phase: str,
    chosen_target: str,
    candidates: list[str],
    rationale: str,
    actor: Optional[str] = "router",
    correlation_id: Optional[str] = None,
) -> Event:
    """Build a ROUTING_DECISION event."""
    return Event(
        event_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        event_type=EventType.ROUTING_DECISION,
        timestamp=time.time(),
        sequence=sequence,
        payload={
            "phase": phase,
            "chosen_target": chosen_target,
            "candidates": list(candidates),
            "rationale": rationale,
        },
        actor=actor,
        correlation_id=correlation_id,
    )


def make_df_status_change(
    workflow_id: str,
    sequence: int,
    df_id: str,
    from_status: str,
    to_status: str,
    reason: Optional[str] = None,
    actor: Optional[str] = "df-engine",
    correlation_id: Optional[str] = None,
) -> Event:
    """Build a DF_STATUS_CHANGE event."""
    return Event(
        event_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        event_type=EventType.DF_STATUS_CHANGE,
        timestamp=time.time(),
        sequence=sequence,
        payload={
            "df_id": df_id,
            "from_status": from_status,
            "to_status": to_status,
            "reason": reason,
        },
        actor=actor,
        correlation_id=correlation_id,
    )


def make_stop_flag_transition(
    workflow_id: str,
    sequence: int,
    flag_id: str,
    raised: bool,
    reason: Optional[str] = None,
    actor: Optional[str] = "operator",
    correlation_id: Optional[str] = None,
) -> Event:
    """Build a STOP_FLAG_TRANSITION event. raised=True if set, False if cleared."""
    return Event(
        event_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        event_type=EventType.STOP_FLAG_TRANSITION,
        timestamp=time.time(),
        sequence=sequence,
        payload={
            "flag_id": flag_id,
            "raised": bool(raised),
            "reason": reason,
        },
        actor=actor,
        correlation_id=correlation_id,
    )


def make_approval_state(
    workflow_id: str,
    sequence: int,
    gate_id: str,
    decision: str,  # "APPROVED" | "REJECTED" | "PENDING"
    approver: str,
    notes: Optional[str] = None,
    actor: Optional[str] = "approval-gate",
    correlation_id: Optional[str] = None,
) -> Event:
    """Build an APPROVAL_STATE event."""
    return Event(
        event_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        event_type=EventType.APPROVAL_STATE,
        timestamp=time.time(),
        sequence=sequence,
        payload={
            "gate_id": gate_id,
            "decision": decision,
            "approver": approver,
            "notes": notes,
        },
        actor=actor,
        correlation_id=correlation_id,
    )


def make_state_transition(
    workflow_id: str,
    sequence: int,
    from_phase: str,
    to_phase: str,
    state_patch: dict,
    actor: Optional[str] = "state-machine",
    correlation_id: Optional[str] = None,
) -> Event:
    """Build a generic STATE_TRANSITION event for arbitrary phase moves."""
    return Event(
        event_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        event_type=EventType.STATE_TRANSITION,
        timestamp=time.time(),
        sequence=sequence,
        payload={
            "from_phase": from_phase,
            "to_phase": to_phase,
            "state_patch": state_patch,
        },
        actor=actor,
        correlation_id=correlation_id,
    )
