"""KMO Cell-Boundary Quota Enforcer [CRUX-MK].

Pre-Action-Quota-Check fuer Cell-Boundary-Operations. Wrapper um
CellBoundaryManager der Audit-Logging + Quota-Enforcement kombiniert
und an Apoptose-Engine-Callback weiterleitet.

K11.b Pipeline-Cost-Estimate: Pre-Action-Check vor jeder kostenrelevanten Operation.
K13 Pre-Action-Verification: Hotel-ID + Quota werden VOR Action geprueft.

Bio-Aequivalent: Active-Transport-Pump (Na/K-ATPase). Energie-pflichtige
Membrane-Passage mit ATP-Verbrauch (= Quota-Cost) pro Channel-Open-Event.

Usage:
    enforcer = QuotaEnforcer(manager, audit_log)
    enforcer.charge_tokens(1500, payload={"prompt": "..."})  # logs + consumes
    enforcer.charge_io_call(payload={"booking_id": "abc"})
"""

from __future__ import annotations

from typing import Any, Optional

from .boundary_audit import BoundaryAuditLog
from .cell_boundary import (
    APOPTOSE_REASON_QUOTA_EXHAUSTED,
    CellBoundaryManager,
    QuotaExhaustedError,
    SchemaViolationError,
)


class QuotaEnforcer:
    """Composes CellBoundaryManager + BoundaryAuditLog for atomic
    pre-action quota-checks with audit-trail.

    Pre-Conditions:
        - manager: live CellBoundaryManager
        - audit_log: live BoundaryAuditLog (or None to skip auditing)

    Post-Conditions:
        - Every charge_* call logs an audit event AND consumes from quota
        - On quota exhaustion: apoptose-event logged, QuotaExhaustedError raised
        - On schema violation: violation event logged, SchemaViolationError raised
    """

    def __init__(
        self,
        manager: CellBoundaryManager,
        audit_log: Optional[BoundaryAuditLog] = None,
    ) -> None:
        self.manager = manager
        self.audit_log = audit_log

    # ---------------- Charge operations (consume + audit) ----------------

    def charge_tokens(self, n: int, payload: Any = None) -> int:
        """Consume tokens with audit-log entry. Raises QuotaExhaustedError on cap.

        Pre: n >= 0
        Post: audit log has 1 new event (consume/tokens) on success,
              or 1 event (apoptose) + raise on exhaustion.
        """
        try:
            new_total = self.manager.consume_tokens(n)
        except QuotaExhaustedError as e:
            self._log_apoptose(e)
            raise
        self._log("consume", "tokens", payload, {"n": n, "total": new_total})
        return new_total

    def charge_cpu(self, seconds: float, payload: Any = None) -> float:
        try:
            new_total = self.manager.consume_cpu(seconds)
        except QuotaExhaustedError as e:
            self._log_apoptose(e)
            raise
        self._log("consume", "cpu", payload, {"seconds": seconds, "total": new_total})
        return new_total

    def charge_memory(self, mb: float, payload: Any = None) -> float:
        try:
            new_total = self.manager.consume_memory(mb)
        except QuotaExhaustedError as e:
            self._log_apoptose(e)
            raise
        self._log("consume", "memory", payload, {"mb": mb, "total": new_total})
        return new_total

    def charge_io_call(self, payload: Any = None) -> None:
        """Record an I/O-call (rate-limited per io_calls_per_minute)."""
        try:
            self.manager.record_io_call()
        except QuotaExhaustedError as e:
            self._log_apoptose(e)
            raise
        self._log("io_call", None, payload, None)

    # ---------------- Validate operations (schema + audit) ----------------

    def validate_input(self, payload: Any) -> bool:
        """Validate input via boundary.input_schema. Logs validation event.

        Returns True on pass, False on fail. Raises SchemaViolationError if
        validator throws.
        """
        try:
            ok = self.manager.validate_input(payload)
        except SchemaViolationError as e:
            self._log("validate", "input", payload, {"violation": str(e)})
            raise
        self._log("validate", "input", payload, {"passed": ok})
        return ok

    def validate_output(self, payload: Any) -> bool:
        try:
            ok = self.manager.validate_output(payload)
        except SchemaViolationError as e:
            self._log("validate", "output", payload, {"violation": str(e)})
            raise
        self._log("validate", "output", payload, {"passed": ok})
        return ok

    # ---------------- Internals ----------------

    def _log(
        self,
        event_type: str,
        event_subtype: Optional[str],
        payload: Any,
        details: Optional[dict],
    ) -> None:
        if self.audit_log is None:
            return
        self.audit_log.append(
            cell_id=self.manager.boundary.cell_id,
            hotel_id=self.manager.boundary.hotel_id,
            event_type=event_type,
            event_subtype=event_subtype,
            payload=payload,
            details=details,
        )

    def _log_apoptose(self, err: QuotaExhaustedError) -> None:
        if self.audit_log is None:
            return
        self.audit_log.append(
            cell_id=self.manager.boundary.cell_id,
            hotel_id=self.manager.boundary.hotel_id,
            event_type="apoptose",
            event_subtype=APOPTOSE_REASON_QUOTA_EXHAUSTED,
            payload=None,
            details={
                "quota_name": err.quota_name,
                "consumed": err.consumed,
                "limit": err.limit,
            },
        )


# CRUX-MK
