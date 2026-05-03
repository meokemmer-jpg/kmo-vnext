"""KMO Cell-Boundary Tests [CRUX-MK].

Spec-Section: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-1.2.1 Tests-Block.

Pflicht-Tests:
- test_cell_boundary_schema_validation
- test_cell_boundary_quota_enforcement
- test_cell_boundary_io_audit_trail
- test_cell_boundary_hotel_id_isolation
- test_cell_boundary_quota_exhaustion_apoptose_trigger

Plus Edge-Case-Tests fuer Constructor-Validation und Apoptose-Lifecycle.
"""

from __future__ import annotations

import threading

import pytest

from kmo_governance.cell_boundary import (
    APOPTOSE_REASON_QUOTA_EXHAUSTED,
    BoundaryAuditLog,
    CellBoundary,
    CellBoundaryManager,
    CellQuota,
    QuotaEnforcer,
    QuotaExhaustedError,
    SchemaViolationError,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def audit_db(tmp_path):
    """Isolated audit DB per test."""
    return tmp_path / "boundary_audit.db"


@pytest.fixture
def audit_log(audit_db):
    return BoundaryAuditLog(db_path=audit_db, machine_id="test-host")


@pytest.fixture
def fixed_clock():
    """Manual-tick clock for deterministic rate-limit tests."""
    state = {"t": 1_000_000.0}

    def clock() -> float:
        return state["t"]

    def tick(dt: float) -> None:
        state["t"] += dt

    clock.tick = tick  # type: ignore[attr-defined]
    return clock


# ---------------- Pflicht-Test 1: Schema-Validation ----------------


def test_cell_boundary_schema_validation():
    """Input/Output-Schema validators block non-conforming payloads (membrane-permeability)."""
    boundary = CellBoundary(
        cell_id="cell-1",
        hotel_id="hotel-A",
        input_schema=lambda x: isinstance(x, dict) and "booking_id" in x,
        output_schema=lambda x: isinstance(x, dict) and x.get("status") == "ok",
    )
    mgr = CellBoundaryManager(boundary)

    # Pass: matching schema
    assert mgr.validate_input({"booking_id": "abc"}) is True
    assert mgr.validate_output({"status": "ok"}) is True

    # Reject: non-matching
    assert mgr.validate_input({"foo": "bar"}) is False
    assert mgr.validate_input("not-a-dict") is False
    assert mgr.validate_output({"status": "fail"}) is False

    # Schema raising propagates as SchemaViolationError
    def bad_validator(x):
        raise RuntimeError("internal validator bug")

    boundary2 = CellBoundary(
        cell_id="cell-2", hotel_id="hotel-A", input_schema=bad_validator
    )
    mgr2 = CellBoundaryManager(boundary2)
    with pytest.raises(SchemaViolationError) as exc:
        mgr2.validate_input({"x": 1})
    assert exc.value.channel == "input"

    # No schema -> always passes
    boundary3 = CellBoundary(cell_id="cell-3", hotel_id="hotel-A")
    mgr3 = CellBoundaryManager(boundary3)
    assert mgr3.validate_input(None) is True
    assert mgr3.validate_output(object()) is True


# ---------------- Pflicht-Test 2: Quota-Enforcement ----------------


def test_cell_boundary_quota_enforcement():
    """Token/CPU/Memory caps enforced atomically. Over-limit raises QuotaExhaustedError."""
    boundary = CellBoundary(
        cell_id="cell-1",
        hotel_id="hotel-A",
        quota=CellQuota(cpu_seconds=10.0, memory_mb=128.0, llm_token_budget=1000),
    )
    mgr = CellBoundaryManager(boundary)

    # Within-budget consume succeeds
    assert mgr.consume_tokens(500) == 500
    assert mgr.consume_tokens(400) == 900
    assert mgr.remaining_tokens() == 100

    # Going over-budget raises and apoptosis is set
    with pytest.raises(QuotaExhaustedError) as exc:
        mgr.consume_tokens(200)  # would be 1100 > 1000
    assert exc.value.quota_name == "llm_token_budget"
    assert exc.value.limit == 1000
    assert mgr.is_apoptosed is True
    assert mgr.apoptose_reason == APOPTOSE_REASON_QUOTA_EXHAUSTED

    # Subsequent operations on apoptosed cell also raise
    with pytest.raises(QuotaExhaustedError):
        mgr.consume_tokens(0)

    # Independent quota: CPU separate from tokens
    boundary2 = CellBoundary(
        cell_id="cell-2",
        hotel_id="hotel-A",
        quota=CellQuota(cpu_seconds=5.0),
    )
    mgr2 = CellBoundaryManager(boundary2)
    mgr2.consume_cpu(3.0)
    mgr2.consume_cpu(2.0)
    with pytest.raises(QuotaExhaustedError) as exc:
        mgr2.consume_cpu(0.01)  # 5.01 > 5.0
    assert exc.value.quota_name == "cpu_seconds"

    # Memory quota
    boundary3 = CellBoundary(
        cell_id="cell-3",
        hotel_id="hotel-A",
        quota=CellQuota(memory_mb=64.0),
    )
    mgr3 = CellBoundaryManager(boundary3)
    mgr3.consume_memory(64.0)
    with pytest.raises(QuotaExhaustedError):
        mgr3.consume_memory(0.1)

    # Negative input rejected
    with pytest.raises(ValueError):
        CellBoundaryManager(
            CellBoundary(cell_id="cell-x", hotel_id="hotel-A")
        ).consume_tokens(-1)


# ---------------- Pflicht-Test 3: I/O-Audit-Trail ----------------


def test_cell_boundary_io_audit_trail(audit_log):
    """Boundary-events are appended to audit log with hotel-id row-level-security."""
    boundary = CellBoundary(
        cell_id="cell-A1",
        hotel_id="hotel-A",
        quota=CellQuota(llm_token_budget=10_000),
        input_schema=lambda x: True,
    )
    mgr = CellBoundaryManager(boundary)
    enforcer = QuotaEnforcer(mgr, audit_log)

    enforcer.charge_tokens(100, payload={"prompt": "hi"})
    enforcer.charge_tokens(200, payload={"prompt": "hi2"})
    enforcer.validate_input({"booking_id": "X"})
    enforcer.charge_io_call(payload={"endpoint": "/api/x"})

    events = audit_log.read_for_cell("cell-A1", "hotel-A")
    assert len(events) == 4
    types = [e.event_type for e in events]
    assert types == ["consume", "consume", "validate", "io_call"]
    # Token-event payload-hash present (provenance)
    assert events[0].payload_hash is not None
    # Cell-id and hotel-id consistency
    for e in events:
        assert e.cell_id == "cell-A1"
        assert e.hotel_id == "hotel-A"
    # Counter-API
    assert audit_log.count_for_cell("cell-A1", "hotel-A") == 4


# ---------------- Pflicht-Test 4: Hotel-ID-Isolation ----------------


def test_cell_boundary_hotel_id_isolation(audit_log):
    """Multi-Tenancy: events for hotel-A are NOT visible to hotel-B queries."""
    bA = CellBoundary(cell_id="cellA", hotel_id="hotel-A")
    bB = CellBoundary(cell_id="cellB", hotel_id="hotel-B")
    mA = CellBoundaryManager(bA)
    mB = CellBoundaryManager(bB)
    eA = QuotaEnforcer(mA, audit_log)
    eB = QuotaEnforcer(mB, audit_log)

    eA.charge_tokens(50, payload={"x": 1})
    eA.charge_tokens(50, payload={"x": 2})
    eB.charge_tokens(99, payload={"y": 1})

    # Hotel-A sees only its own events
    a_events = audit_log.read_for_hotel("hotel-A")
    assert len(a_events) == 2
    assert all(e.hotel_id == "hotel-A" for e in a_events)

    # Hotel-B sees only its own
    b_events = audit_log.read_for_hotel("hotel-B")
    assert len(b_events) == 1
    assert b_events[0].hotel_id == "hotel-B"

    # Cross-tenant query for cellA in hotel-B yields zero (RLS)
    assert audit_log.read_for_cell("cellA", "hotel-B") == []
    assert audit_log.read_for_cell("cellB", "hotel-A") == []

    # Manager-level assert_hotel_id guard
    mA.assert_hotel_id("hotel-A")  # no raise
    with pytest.raises(PermissionError):
        mA.assert_hotel_id("hotel-B")

    # GDPR cascade-delete: purge hotel-A
    deleted = audit_log.purge_hotel("hotel-A")
    assert deleted == 2
    assert audit_log.read_for_hotel("hotel-A") == []
    # Hotel-B unaffected
    assert len(audit_log.read_for_hotel("hotel-B")) == 1


# ---------------- Pflicht-Test 5: Quota-Exhaustion Apoptose-Trigger ----------------


def test_cell_boundary_quota_exhaustion_apoptose_trigger(audit_log):
    """Quota exhaustion fires the apoptose-callback exactly once + logs apoptose-event."""
    fired: list[tuple[str, dict]] = []

    def apoptose_cb(reason: str, details: dict) -> None:
        fired.append((reason, details))

    boundary = CellBoundary(
        cell_id="cell-doomed",
        hotel_id="hotel-A",
        quota=CellQuota(llm_token_budget=100),
    )
    mgr = CellBoundaryManager(boundary, on_quota_exhausted=apoptose_cb)
    enforcer = QuotaEnforcer(mgr, audit_log)

    enforcer.charge_tokens(50)  # 50/100
    with pytest.raises(QuotaExhaustedError):
        enforcer.charge_tokens(60)  # would be 110 -> exhaust

    # Callback fired exactly once
    assert len(fired) == 1
    reason, details = fired[0]
    assert reason == APOPTOSE_REASON_QUOTA_EXHAUSTED
    assert details["quota"] == "llm_token_budget"
    assert details["limit"] == 100

    # Apoptose-event in audit log
    apop_events = [
        e for e in audit_log.read_for_cell("cell-doomed", "hotel-A")
        if e.event_type == "apoptose"
    ]
    assert len(apop_events) == 1
    assert apop_events[0].event_subtype == APOPTOSE_REASON_QUOTA_EXHAUSTED

    # Subsequent charge re-raises but does NOT re-fire callback
    with pytest.raises(QuotaExhaustedError):
        enforcer.charge_tokens(1)
    assert len(fired) == 1  # still exactly one


# ---------------- Edge: Constructor validation ----------------


def test_cell_boundary_requires_cell_id():
    with pytest.raises(ValueError):
        CellBoundary(cell_id="", hotel_id="hotel-A")


def test_cell_boundary_requires_hotel_id_multi_tenancy_pflicht():
    with pytest.raises(ValueError):
        CellBoundary(cell_id="cell-1", hotel_id="")


def test_cell_quota_negative_rejected():
    with pytest.raises(ValueError):
        CellQuota(cpu_seconds=-1)
    with pytest.raises(ValueError):
        CellQuota(llm_token_budget=-5)


# ---------------- Edge: I/O Rate-Limit (sliding-window) ----------------


def test_io_calls_per_minute_rate_limit(fixed_clock):
    boundary = CellBoundary(
        cell_id="cell-1",
        hotel_id="hotel-A",
        quota=CellQuota(io_calls_per_minute=3),
    )
    mgr = CellBoundaryManager(boundary, clock=fixed_clock)

    # 3 calls within window: ok
    mgr.record_io_call()
    mgr.record_io_call()
    mgr.record_io_call()
    # 4th call: exhaust
    with pytest.raises(QuotaExhaustedError):
        mgr.record_io_call()

    # Apoptosed cell stays apoptosed even if window slides forward
    fixed_clock.tick(120.0)
    with pytest.raises(QuotaExhaustedError):
        mgr.record_io_call()


# ---------------- Edge: Thread-safety of consume_tokens ----------------


def test_consume_tokens_thread_safety():
    """Concurrent consume_tokens calls do not double-count or corrupt counter."""
    boundary = CellBoundary(
        cell_id="cell-1",
        hotel_id="hotel-A",
        quota=CellQuota(llm_token_budget=10_000),
    )
    mgr = CellBoundaryManager(boundary)

    # 100 threads each consume 1 token
    def worker():
        try:
            mgr.consume_tokens(1)
        except QuotaExhaustedError:
            pass

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert mgr.consumed_tokens == 100
    assert mgr.is_apoptosed is False


# ---------------- Edge: Apoptose-callback exception is suppressed ----------------


def test_apoptose_callback_exception_suppressed(audit_log):
    """If the apoptose-callback raises, the original QuotaExhaustedError still propagates."""

    def bad_cb(reason: str, details: dict) -> None:
        raise RuntimeError("callback boom")

    boundary = CellBoundary(
        cell_id="cell-1",
        hotel_id="hotel-A",
        quota=CellQuota(llm_token_budget=10),
    )
    mgr = CellBoundaryManager(boundary, on_quota_exhausted=bad_cb)
    with pytest.raises(QuotaExhaustedError):
        mgr.consume_tokens(11)
    # Apoptose still recorded internally even though callback raised
    assert mgr.is_apoptosed is True


# ---------------- Edge: Frozen-Dataclass immutability ----------------


def test_cell_boundary_immutable():
    boundary = CellBoundary(cell_id="cell-1", hotel_id="hotel-A")
    with pytest.raises((AttributeError, Exception)):
        boundary.cell_id = "cell-2"  # type: ignore[misc]
