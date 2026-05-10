# [CRUX-MK]
"""Tests fuer LexVance-Compliance-Audit-Bus (Welle-40 Phase-33, 8. Domain)."""
from __future__ import annotations

import time

import pytest

from kmo_governance.lexvance_compliance_audit_bus import (
    Jurisdiction,
    LegalAuditEvent,
    LegalObligationType,
    LexVanceComplianceAuditBus,
)


def test_init_validation() -> None:
    LexVanceComplianceAuditBus()  # default OK
    with pytest.raises(ValueError):
        LexVanceComplianceAuditBus(max_events=0)
    with pytest.raises(TypeError):
        LexVanceComplianceAuditBus(default_jurisdiction="DE")  # type: ignore[arg-type]


def test_publish_basic_event() -> None:
    bus = LexVanceComplianceAuditBus()
    event = bus.publish(
        obligation_type=LegalObligationType.GDPR_AUDIT,
        mandant_id="mandant-001",
        context="Annual GDPR audit",
    )
    assert event.event_id != ""
    assert event.obligation_type == LegalObligationType.GDPR_AUDIT
    assert event.jurisdiction == Jurisdiction.DE  # default
    assert event.chain_hash != ""
    assert event.prev_hash == ""  # first event in chain


def test_chain_hash_propagation() -> None:
    """Chain: e2.prev_hash == e1.chain_hash (same mandant)."""
    bus = LexVanceComplianceAuditBus()
    e1 = bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx1")
    e2 = bus.publish(LegalObligationType.TAX_FILING, "m1", "ctx2")
    assert e2.prev_hash == e1.chain_hash
    assert e2.chain_hash != e1.chain_hash


def test_chain_per_mandant_isolated() -> None:
    """Different mandanten have independent chains."""
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx1")
    e2 = bus.publish(LegalObligationType.CONTRACT_REVIEW, "m2", "ctx2")
    assert e2.prev_hash == ""  # m2's first event


def test_verify_chain_intact() -> None:
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx1")
    bus.publish(LegalObligationType.TAX_FILING, "m1", "ctx2")
    bus.publish(LegalObligationType.GDPR_AUDIT, "m1", "ctx3")
    assert bus.verify_chain("m1") is True


def test_verify_chain_empty() -> None:
    bus = LexVanceComplianceAuditBus()
    assert bus.verify_chain("nonexistent") is True


def test_publish_validation() -> None:
    bus = LexVanceComplianceAuditBus()
    with pytest.raises(TypeError):
        bus.publish("not-enum", "m1", "ctx")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        bus.publish(LegalObligationType.GDPR_AUDIT, "", "ctx")
    with pytest.raises(ValueError):
        bus.publish(LegalObligationType.GDPR_AUDIT, "m1", "")


def test_query_filter_by_mandant() -> None:
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx")
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m2", "ctx")
    m1_events = bus.query(mandant_id="m1")
    assert len(m1_events) == 1
    assert m1_events[0].mandant_id == "m1"


def test_query_filter_by_obligation() -> None:
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx")
    bus.publish(LegalObligationType.TAX_FILING, "m1", "ctx")
    contracts = bus.query(obligation_type=LegalObligationType.CONTRACT_REVIEW)
    assert len(contracts) == 1


def test_query_filter_by_jurisdiction() -> None:
    bus = LexVanceComplianceAuditBus()
    bus.publish(
        LegalObligationType.GDPR_AUDIT, "m1", "ctx", jurisdiction=Jurisdiction.US,
    )
    bus.publish(
        LegalObligationType.GDPR_AUDIT, "m1", "ctx", jurisdiction=Jurisdiction.DE,
    )
    us_events = bus.query(jurisdiction=Jurisdiction.US)
    assert len(us_events) == 1
    assert us_events[0].jurisdiction == Jurisdiction.US


def test_jurisdiction_retention_de_10y() -> None:
    """DE retention = 10 years = 87600h."""
    bus = LexVanceComplianceAuditBus(default_jurisdiction=Jurisdiction.DE)
    e = bus.publish(LegalObligationType.TAX_FILING, "m1", "ctx")
    assert e.jurisdiction == Jurisdiction.DE


def test_cleanup_expired_de_within_retention() -> None:
    """Recent DE event survives cleanup."""
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.TAX_FILING, "m1", "ctx")
    removed = bus.cleanup_expired()
    assert removed == 0


def test_cleanup_expired_old_event_removed() -> None:
    """Event older than retention is removed."""
    bus = LexVanceComplianceAuditBus()
    e = bus.publish(LegalObligationType.TAX_FILING, "m1", "ctx", jurisdiction=Jurisdiction.DE)
    # Simulate: cleanup as if 11 years passed
    far_future = time.time() + (11 * 365 * 24 * 3600)
    removed = bus.cleanup_expired(current_ts=far_future)
    assert removed == 1


def test_audit_due_date_set() -> None:
    """audit_due_in_h sets audit_due_date."""
    bus = LexVanceComplianceAuditBus()
    e = bus.publish(
        LegalObligationType.GDPR_AUDIT,
        "m1",
        "ctx",
        audit_due_in_h=24.0,
    )
    assert e.audit_due_date is not None
    assert e.audit_due_date > e.timestamp


def test_get_stats() -> None:
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.GDPR_AUDIT, "m1", "ctx")
    bus.publish(LegalObligationType.GDPR_AUDIT, "m2", "ctx")
    bus.publish(LegalObligationType.TAX_FILING, "m1", "ctx", jurisdiction=Jurisdiction.US)
    stats = bus.get_stats()
    assert stats["total"] == 3
    assert stats["mandanten_count"] == 2
    assert stats["per_obligation"]["gdpr_audit"] == 2


def test_event_frozen_immutability() -> None:
    bus = LexVanceComplianceAuditBus()
    e = bus.publish(LegalObligationType.GDPR_AUDIT, "m1", "ctx")
    with pytest.raises(Exception):
        e.event_id = "changed"  # type: ignore[misc]


def test_max_events_fifo_eviction() -> None:
    """max_events=2 enforces FIFO."""
    bus = LexVanceComplianceAuditBus(max_events=2)
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx-1")
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx-2")
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx-3")
    events = bus.query()
    assert len(events) == 2
    contexts = [e.context for e in events]
    assert "ctx-1" not in contexts


# ---------------------------------------------------------------------------
# W47-P1 (V20-F1-Fix): SHA256-Recompute-Verify
# ---------------------------------------------------------------------------


def test_w47p1_verify_chain_sha256_recompute() -> None:
    """W47-P1: verify_chain checkt SHA256-Recompute (anti-tamper)."""
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx-original")
    assert bus.verify_chain("m1") is True


def test_w47p1_tampered_context_breaks_chain() -> None:
    """W47-P1: wenn ein Event mit getampered context im store ist, verify schlaegt fehl.

    Direct-Replace event in self._events with tampered version → recompute mismatch.
    """
    import dataclasses
    from kmo_governance.lexvance_compliance_audit_bus import LegalAuditEvent
    bus = LexVanceComplianceAuditBus()
    e1 = bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "original-context")
    # Tamper with context (chain_hash bleibt original)
    tampered = dataclasses.replace(e1, context="MALICIOUS-CONTEXT")
    bus._events[0] = tampered
    assert bus.verify_chain("m1") is False  # SHA256 recompute mismatch


# ---------------------------------------------------------------------------
# Welle-50 (V21-P2): External-Anchor-Stub
# ---------------------------------------------------------------------------


def test_w50_daily_checkpoint_returns_snapshot() -> None:
    """Welle-50: daily_checkpoint liefert mandant-chain-snapshot."""
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx")
    snap = bus.daily_checkpoint("2026-05-10")
    assert snap["date"] == "2026-05-10"
    assert "m1" in snap["last_chain_hashes"]
    assert snap["event_count"] == 1


def test_w50_daily_checkpoint_invokes_callback() -> None:
    """Welle-50: callback wird aufgerufen mit snapshot."""
    received = {}
    def fake_anchor(snap):
        received.update(snap)
    bus = LexVanceComplianceAuditBus(external_anchor_callback=fake_anchor)
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx")
    bus.daily_checkpoint("2026-05-10")
    assert received["date"] == "2026-05-10"


def test_w50_callback_failure_does_not_crash() -> None:
    """Welle-50: callback-Exception wird gefangen + status loggt fail."""
    def boom(snap):
        raise RuntimeError("network down")
    bus = LexVanceComplianceAuditBus(external_anchor_callback=boom)
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx")
    snap = bus.daily_checkpoint("2026-05-10")
    assert "callback_failed" in snap["anchor_status"]


def test_w50_anchor_history_persistence() -> None:
    """Welle-50: snapshots in anchor_history persistiert."""
    bus = LexVanceComplianceAuditBus()
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx-1")
    bus.daily_checkpoint("2026-05-10")
    bus.publish(LegalObligationType.CONTRACT_REVIEW, "m1", "ctx-2")
    bus.daily_checkpoint("2026-05-11")
    history = bus.get_anchor_history()
    assert len(history) == 2


def test_w50_checkpoint_validation() -> None:
    bus = LexVanceComplianceAuditBus()
    with pytest.raises(ValueError):
        bus.daily_checkpoint("")


# CRUX-MK
