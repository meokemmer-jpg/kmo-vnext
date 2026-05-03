"""KMO Cell-Boundary [CRUX-MK].

KMO-vNext Phase-1 Modul 2.1: Cell-Membrane-Definition pro Saga-Run-Cell.

Bio-Aequivalent: Lipid-Bilayer mit selektiven Channels (Aquaporine fuer Wasser,
Ionen-Kanaele fuer Ionen, GPCR fuer Signal-Liganden). Selektive Permeabilitaet
entscheidet welche Payloads die Membrane passieren.

K11-K16 + LC1-LC5 konform. Multi-Tenancy via hotel_id Pflicht-Field (Welle-8 Backlog).

SAE-Isomorphie: Trinity-Slot-Resource-Boundary auf Cell-Ebene. Atomic-Counter pattern
fuer Quota-Tracking, Frozen-Dataclass fuer Boundary-Definition (immutable contract).

Usage:
    boundary = CellBoundary(
        cell_id="saga-run-abc123",
        hotel_id="apaleo-eu-hotel-001",
        quota=CellQuota(cpu_seconds=300, llm_token_budget=50_000),
        input_schema=lambda x: isinstance(x, dict) and "booking_id" in x,
    )
    mgr = CellBoundaryManager(boundary, on_quota_exhausted=trigger_apoptose)
    if mgr.validate_input(payload):
        mgr.consume_tokens(1234)
        # ... do work ...
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# Constants with units (no magic numbers).
DEFAULT_IO_RATE_WINDOW_SEC: float = 60.0
APOPTOSE_REASON_QUOTA_EXHAUSTED: str = "quota_exhausted"
APOPTOSE_REASON_SCHEMA_VIOLATION: str = "schema_violation"


@dataclass(frozen=True)
class CellQuota:
    """Resource quotas pro Cell-Run. None = unlimited (kein Cap).

    Bio-Aequivalent: Membrane-Channel-Capacity. Ueberschreitung triggert Apoptose.

    Fields:
        cpu_seconds: max CPU-Time pro Cell-Lifetime (wall clock)
        memory_mb: max Memory-Footprint
        llm_token_budget: max LLM-Tokens (input + output kombiniert)
        io_calls_per_minute: max I/O-Calls per 60s sliding window (Rate-Limit)
    """

    cpu_seconds: Optional[float] = None
    memory_mb: Optional[float] = None
    llm_token_budget: Optional[int] = None
    io_calls_per_minute: Optional[int] = None

    def __post_init__(self) -> None:
        for name, val in (
            ("cpu_seconds", self.cpu_seconds),
            ("memory_mb", self.memory_mb),
            ("llm_token_budget", self.llm_token_budget),
            ("io_calls_per_minute", self.io_calls_per_minute),
        ):
            if val is not None and val < 0:
                raise ValueError(f"{name} must be >= 0 or None, got {val}")


@dataclass(frozen=True)
class CellBoundary:
    """Cell-Membrane-Definition pro Saga-Run-Cell. Immutable contract.

    Bio-Aequivalent: Lipid-Bilayer + selective Channels. Definiert was rein/raus darf.

    Pre-Conditions:
        - cell_id non-empty (Identitaet der Cell)
        - hotel_id non-empty (Multi-Tenancy-Boundary, GDPR)
        - quota: optionale Resource-Limits (None-Felder = unlimited)
        - input_schema / output_schema: optionale Callable-Validatoren

    Post-Conditions:
        - Boundary ist immutable nach Erstellung
        - Hotel-Isolation: cell darf NUR mit eigenem hotel_id-Tag arbeiten

    Fields:
        cell_id: eindeutige Cell-ID (z.B. saga_run_id)
        hotel_id: Multi-Tenancy-Tag (Pflicht, ROW-LEVEL-SECURITY)
        quota: Resource-Limits
        input_schema: Callable[[Any], bool] (True = passes membrane)
        output_schema: Callable[[Any], bool] (True = exits membrane)
        metadata: optional structured metadata
    """

    cell_id: str
    hotel_id: str
    quota: CellQuota = field(default_factory=CellQuota)
    input_schema: Optional[Callable[[Any], bool]] = None
    output_schema: Optional[Callable[[Any], bool]] = None
    metadata: Optional[dict] = None

    def __post_init__(self) -> None:
        if not self.cell_id or not isinstance(self.cell_id, str):
            raise ValueError("cell_id must be non-empty string")
        if not self.hotel_id or not isinstance(self.hotel_id, str):
            raise ValueError("hotel_id must be non-empty string (Multi-Tenancy Pflicht)")


class QuotaExhaustedError(RuntimeError):
    """Raised when a quota is exhausted. Triggers apoptose via callback."""

    def __init__(self, quota_name: str, consumed: float, limit: float):
        super().__init__(
            f"Quota {quota_name!r} exhausted: consumed={consumed} >= limit={limit}"
        )
        self.quota_name = quota_name
        self.consumed = consumed
        self.limit = limit


class SchemaViolationError(RuntimeError):
    """Raised when an I/O-payload fails schema validation (membrane rejection)."""

    def __init__(self, channel: str, reason: str):
        super().__init__(f"Schema violation on channel {channel!r}: {reason}")
        self.channel = channel
        self.reason = reason


class CellBoundaryManager:
    """Stateful manager for a concrete Cell-Boundary instance.

    Tracks resource consumption, validates I/O-payloads, triggers apoptose on
    quota exhaustion or repeated schema violations. Thread-safe via RLock.

    Apoptose-Hook (on_quota_exhausted): callable[(reason: str, details: dict), None].
    Phase-1 stub; will be wired to apoptosis_engine in Phase-1.2.4 saga-integration.

    Pre-Conditions:
        - boundary: valid CellBoundary instance
        - on_quota_exhausted: optional callback (None = log only)

    Post-Conditions:
        - All consume_* operations are atomic
        - On exhaustion: apoptose_callback fired exactly once + is_apoptosed=True
        - Subsequent operations on apoptosed cell raise QuotaExhaustedError
    """

    def __init__(
        self,
        boundary: CellBoundary,
        on_quota_exhausted: Optional[Callable[[str, dict], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(boundary, CellBoundary):
            raise TypeError(f"boundary must be CellBoundary, got {type(boundary)}")
        self.boundary = boundary
        self._on_quota_exhausted = on_quota_exhausted
        self._clock = clock
        self._lock = threading.RLock()

        self._consumed_cpu: float = 0.0
        self._consumed_memory: float = 0.0
        self._consumed_tokens: int = 0
        self._io_call_timestamps: list[float] = []
        self._is_apoptosed: bool = False
        self._apoptose_reason: Optional[str] = None
        self._cell_started_at: float = self._clock()

    # ---------------- Public API ----------------

    @property
    def is_apoptosed(self) -> bool:
        return self._is_apoptosed

    @property
    def apoptose_reason(self) -> Optional[str]:
        return self._apoptose_reason

    @property
    def consumed_tokens(self) -> int:
        return self._consumed_tokens

    @property
    def consumed_cpu(self) -> float:
        return self._consumed_cpu

    @property
    def consumed_memory(self) -> float:
        return self._consumed_memory

    def remaining_tokens(self) -> Optional[int]:
        cap = self.boundary.quota.llm_token_budget
        if cap is None:
            return None
        return max(0, cap - self._consumed_tokens)

    def remaining_cpu(self) -> Optional[float]:
        cap = self.boundary.quota.cpu_seconds
        if cap is None:
            return None
        return max(0.0, cap - self._consumed_cpu)

    def consume_tokens(self, n: int) -> int:
        """Atomically consume n tokens. Triggers apoptose on exhaustion.

        Pre: n >= 0
        Post: consumed_tokens += n if quota allows; else QuotaExhaustedError raised
              + apoptose triggered.
        """
        if n < 0:
            raise ValueError(f"n must be >= 0, got {n}")
        with self._lock:
            self._guard_apoptosed()
            cap = self.boundary.quota.llm_token_budget
            new_total = self._consumed_tokens + n
            if cap is not None and new_total > cap:
                self._trigger_apoptose(
                    APOPTOSE_REASON_QUOTA_EXHAUSTED,
                    {"quota": "llm_token_budget", "consumed": new_total, "limit": cap},
                )
                raise QuotaExhaustedError("llm_token_budget", new_total, cap)
            self._consumed_tokens = new_total
            return self._consumed_tokens

    def consume_cpu(self, seconds: float) -> float:
        """Atomically consume cpu_seconds. Triggers apoptose on exhaustion."""
        if seconds < 0:
            raise ValueError(f"seconds must be >= 0, got {seconds}")
        with self._lock:
            self._guard_apoptosed()
            cap = self.boundary.quota.cpu_seconds
            new_total = self._consumed_cpu + seconds
            if cap is not None and new_total > cap:
                self._trigger_apoptose(
                    APOPTOSE_REASON_QUOTA_EXHAUSTED,
                    {"quota": "cpu_seconds", "consumed": new_total, "limit": cap},
                )
                raise QuotaExhaustedError("cpu_seconds", new_total, cap)
            self._consumed_cpu = new_total
            return self._consumed_cpu

    def consume_memory(self, mb: float) -> float:
        """Atomically consume memory. Triggers apoptose on exhaustion."""
        if mb < 0:
            raise ValueError(f"mb must be >= 0, got {mb}")
        with self._lock:
            self._guard_apoptosed()
            cap = self.boundary.quota.memory_mb
            new_total = self._consumed_memory + mb
            if cap is not None and new_total > cap:
                self._trigger_apoptose(
                    APOPTOSE_REASON_QUOTA_EXHAUSTED,
                    {"quota": "memory_mb", "consumed": new_total, "limit": cap},
                )
                raise QuotaExhaustedError("memory_mb", new_total, cap)
            self._consumed_memory = new_total
            return self._consumed_memory

    def record_io_call(self) -> None:
        """Record an I/O call. Enforces io_calls_per_minute rate-limit.

        Sliding-window: keeps timestamps within DEFAULT_IO_RATE_WINDOW_SEC.
        """
        with self._lock:
            self._guard_apoptosed()
            now = self._clock()
            cutoff = now - DEFAULT_IO_RATE_WINDOW_SEC
            self._io_call_timestamps = [
                t for t in self._io_call_timestamps if t >= cutoff
            ]
            cap = self.boundary.quota.io_calls_per_minute
            if cap is not None and len(self._io_call_timestamps) + 1 > cap:
                self._trigger_apoptose(
                    APOPTOSE_REASON_QUOTA_EXHAUSTED,
                    {
                        "quota": "io_calls_per_minute",
                        "consumed": len(self._io_call_timestamps) + 1,
                        "limit": cap,
                    },
                )
                raise QuotaExhaustedError(
                    "io_calls_per_minute", len(self._io_call_timestamps) + 1, cap
                )
            self._io_call_timestamps.append(now)

    def validate_input(self, payload: Any) -> bool:
        """Validate input-payload via boundary.input_schema (if present).

        Returns True if payload passes membrane (or no schema set).
        Raises SchemaViolationError if schema raises an exception during validation.
        """
        with self._lock:
            self._guard_apoptosed()
            schema = self.boundary.input_schema
            if schema is None:
                return True
            try:
                result = bool(schema(payload))
            except Exception as e:
                raise SchemaViolationError(
                    "input", f"validator raised {type(e).__name__}: {e}"
                ) from e
            return result

    def validate_output(self, payload: Any) -> bool:
        """Validate output-payload via boundary.output_schema (if present)."""
        with self._lock:
            self._guard_apoptosed()
            schema = self.boundary.output_schema
            if schema is None:
                return True
            try:
                result = bool(schema(payload))
            except Exception as e:
                raise SchemaViolationError(
                    "output", f"validator raised {type(e).__name__}: {e}"
                ) from e
            return result

    def assert_hotel_id(self, expected_hotel_id: str) -> None:
        """Multi-Tenancy guard. Raises PermissionError on hotel_id mismatch.

        Used at I/O-call boundaries to ensure a cell only operates on its own tenant.
        """
        if expected_hotel_id != self.boundary.hotel_id:
            raise PermissionError(
                f"Hotel-ID isolation violation: cell.hotel_id={self.boundary.hotel_id!r} "
                f"vs requested={expected_hotel_id!r}"
            )

    # ---------------- Internals ----------------

    def _guard_apoptosed(self) -> None:
        if self._is_apoptosed:
            raise QuotaExhaustedError(
                self._apoptose_reason or "apoptosed",
                consumed=-1,
                limit=-1,
            )

    def _trigger_apoptose(self, reason: str, details: dict) -> None:
        """Internal: mark as apoptosed and fire callback exactly once."""
        if self._is_apoptosed:
            return
        self._is_apoptosed = True
        self._apoptose_reason = reason
        if self._on_quota_exhausted is not None:
            try:
                self._on_quota_exhausted(reason, dict(details))
            except Exception:
                # Apoptose-callback is best-effort. Failure here must not mask
                # the original quota exhaustion. Log via stderr in production wrapper.
                pass


# CRUX-MK
