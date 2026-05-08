# [CRUX-MK]
"""Cape-Familien-Audit-Bus Tests (Welle-30 Phase-23 KMO-vNext Wild-Code-Blindtest 1/3).

Q_0-PFLICHT: KEINE Real-Familien-Daten -- alle Tests nutzen ausschliesslich
dummy-Daten ("test_member_x", "test_decision_y", "test_context_z").

Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).
2. Lift:        kmo_governance.kpm_audit_event_bus (Welle-26 Phase-19, KPM-Trading).
3. Lift (HIER): Cape-Coral-Vault Familien-Decision-Verwaltung.

12+ Tests:
  test_init_validation
  test_publish_creates_event
  test_publish_increments_stats
  test_query_by_decision_type
  test_query_by_family_member
  test_query_by_time_range
  test_query_by_compliance_tag
  test_validate_event_compliance_required
  test_cleanup_old_purges
  test_get_stats_correct
  test_concurrent_publish_50_threads
  test_event_frozen_immutability
  test_event_unique_uuid
  + Pre-Cond-Validation Tests
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.cape_familien_audit_bus import (
    CapeFamilienAuditBus,
    ComplianceTag,
    FamilienAuditEvent,
    FamilienDecisionType,
)


# ---------------------------------------------------------------------- Init
def test_init_validation():
    """Pre-Conditions am Konstruktor werden geprueft."""
    with pytest.raises(ValueError):
        CapeFamilienAuditBus(retention_window_h=0)
    with pytest.raises(ValueError):
        CapeFamilienAuditBus(retention_window_h=-1.0)
    with pytest.raises(TypeError):
        CapeFamilienAuditBus(compliance_required={"not-an-enum"})

    # Default OK -- GDPR 1-Jahr-Retention
    bus = CapeFamilienAuditBus()
    assert bus.retention_window_h == 8760.0  # 1 Jahr GDPR-Default
    assert bus.compliance_required == frozenset()

    # Mit compliance_required OK
    bus2 = CapeFamilienAuditBus(
        retention_window_h=24.0,
        compliance_required={ComplianceTag.GDPR, ComplianceTag.PERSONAL_DATA},
    )
    assert ComplianceTag.GDPR in bus2.compliance_required
    assert ComplianceTag.PERSONAL_DATA in bus2.compliance_required


# ------------------------------------------------------------------- publish
def test_publish_creates_event():
    """publish() liefert vollstaendiges FamilienAuditEvent zurueck."""
    bus = CapeFamilienAuditBus()
    event = bus.publish(
        decision_type=FamilienDecisionType.DECISION_VISA,
        family_member_role="test_member_a",
        context="test_context_e2_visa_review",
        compliance_tags=frozenset(
            {ComplianceTag.LEGAL, ComplianceTag.US_RELOCATION}
        ),
        metadata=(
            ("test_meta_key", "test_meta_value"),
            ("test_decision_id", "test_decision_dummy_001"),
        ),
    )
    assert isinstance(event, FamilienAuditEvent)
    assert event.decision_type == FamilienDecisionType.DECISION_VISA
    assert event.family_member_role == "test_member_a"
    assert event.context == "test_context_e2_visa_review"
    assert ComplianceTag.LEGAL in event.compliance_tags
    assert ComplianceTag.US_RELOCATION in event.compliance_tags
    assert event.get_metadata_dict() == {
        "test_meta_key": "test_meta_value",
        "test_decision_id": "test_decision_dummy_001",
    }
    assert event.timestamp > 0
    assert event.event_id  # uuid4 string non-empty


def test_publish_increments_stats():
    """publish() inkrementiert total_published + by_decision_type + by_compliance_tag + by_family_member_role."""
    bus = CapeFamilienAuditBus()
    bus.publish(
        decision_type=FamilienDecisionType.DECISION_FAMILIAL,
        family_member_role="test_member_a",
        context="test_context_1",
        compliance_tags=frozenset({ComplianceTag.FAMILIAL}),
    )
    bus.publish(
        decision_type=FamilienDecisionType.DECISION_TAX,
        family_member_role="test_member_a",
        context="test_context_2",
        compliance_tags=frozenset(
            {ComplianceTag.LEGAL, ComplianceTag.FINANCIAL_K0}
        ),
    )
    bus.publish(
        decision_type=FamilienDecisionType.DECISION_FAMILIAL,
        family_member_role="test_member_b",
        context="test_context_3",
    )

    stats = bus.get_stats()
    assert stats["total_published"] == 3
    assert stats["by_decision_type"]["decision_familial"] == 2
    assert stats["by_decision_type"]["decision_tax"] == 1
    assert stats["by_compliance_tag"]["familial"] == 1
    assert stats["by_compliance_tag"]["legal"] == 1
    assert stats["by_compliance_tag"]["financial_k0"] == 1
    assert stats["by_family_member_role"]["test_member_a"] == 2
    assert stats["by_family_member_role"]["test_member_b"] == 1
    assert stats["current_count"] == 3


# --------------------------------------------------------------------- query
def test_query_by_decision_type():
    """Filter nach decision_type liefert nur Events vom Typ."""
    bus = CapeFamilienAuditBus()
    bus.publish(
        FamilienDecisionType.DECISION_VISA,
        "test_member_a",
        "test_ctx_1",
    )
    bus.publish(
        FamilienDecisionType.DECISION_TAX,
        "test_member_a",
        "test_ctx_2",
    )
    bus.publish(
        FamilienDecisionType.DECISION_VISA,
        "test_member_b",
        "test_ctx_3",
    )
    bus.publish(
        FamilienDecisionType.DECISION_MEDICAL,
        "test_member_a",
        "test_ctx_4",
    )

    visas = bus.query(decision_type=FamilienDecisionType.DECISION_VISA)
    assert len(visas) == 2
    assert all(e.decision_type == FamilienDecisionType.DECISION_VISA for e in visas)

    medicals = bus.query(decision_type=FamilienDecisionType.DECISION_MEDICAL)
    assert len(medicals) == 1


def test_query_by_family_member():
    """Filter nach family_member_role liefert nur passende Events."""
    bus = CapeFamilienAuditBus()
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx_1",
    )
    bus.publish(
        FamilienDecisionType.DECISION_PROCEDURAL,
        "test_member_b",
        "test_ctx_2",
    )
    bus.publish(
        FamilienDecisionType.DECISION_TAX,
        "test_member_a",
        "test_ctx_3",
    )

    role_a = bus.query(family_member_role="test_member_a")
    assert len(role_a) == 2
    assert all(e.family_member_role == "test_member_a" for e in role_a)

    role_b = bus.query(family_member_role="test_member_b")
    assert len(role_b) == 1


def test_query_by_time_range():
    """Filter nach since/until liefert Events innerhalb Zeit-Range."""
    bus = CapeFamilienAuditBus()
    t0 = time.time()
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx_1",
    )
    time.sleep(0.02)
    t1 = time.time()
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx_2",
    )
    time.sleep(0.02)
    t2 = time.time()
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx_3",
    )

    after_t1 = bus.query(since=t1)
    assert 1 <= len(after_t1) <= 2

    before_t1 = bus.query(until=t1)
    assert 1 <= len(before_t1) <= 2

    in_range = bus.query(since=t0, until=t2 + 1.0)
    assert len(in_range) == 3


def test_query_by_compliance_tag():
    """Filter nach compliance_tag liefert nur Events mit diesem Tag."""
    bus = CapeFamilienAuditBus()
    bus.publish(
        FamilienDecisionType.DECISION_TAX,
        "test_member_a",
        "test_ctx_1",
        compliance_tags=frozenset({ComplianceTag.GDPR, ComplianceTag.LEGAL}),
    )
    bus.publish(
        FamilienDecisionType.DECISION_MEDICAL,
        "test_member_a",
        "test_ctx_2",
        compliance_tags=frozenset({ComplianceTag.MEDICAL_PRIVACY}),
    )
    bus.publish(
        FamilienDecisionType.DECISION_FINANCIAL,
        "test_member_b",
        "test_ctx_3",
        compliance_tags=frozenset({ComplianceTag.FINANCIAL_K0, ComplianceTag.GDPR}),
    )

    gdpr_events = bus.query(compliance_tag=ComplianceTag.GDPR)
    assert len(gdpr_events) == 2
    assert all(ComplianceTag.GDPR in e.compliance_tags for e in gdpr_events)

    medical_events = bus.query(compliance_tag=ComplianceTag.MEDICAL_PRIVACY)
    assert len(medical_events) == 1


# ------------------------------------------------------------------- validate
def test_validate_event_compliance_required():
    """validate_event prueft compliance_required als Subset."""
    bus = CapeFamilienAuditBus(
        compliance_required={ComplianceTag.GDPR, ComplianceTag.PERSONAL_DATA},
    )

    # Event mit allen erforderlichen Tags - VALID
    ev_full = bus.publish(
        FamilienDecisionType.DECISION_PROCEDURAL,
        "test_member_a",
        "test_ctx_full",
        compliance_tags=frozenset(
            {
                ComplianceTag.GDPR,
                ComplianceTag.PERSONAL_DATA,
                ComplianceTag.LEGAL,
            }
        ),
    )
    is_valid, missing = bus.validate_event(ev_full)
    assert is_valid is True
    assert missing == []

    # Event mit fehlenden Tags - INVALID
    ev_partial = bus.publish(
        FamilienDecisionType.DECISION_PROCEDURAL,
        "test_member_a",
        "test_ctx_partial",
        compliance_tags=frozenset({ComplianceTag.GDPR}),
    )
    is_valid, missing = bus.validate_event(ev_partial)
    assert is_valid is False
    assert "personal_data" in missing

    # Bus ohne compliance_required: jedes Event valid
    bus_open = CapeFamilienAuditBus()
    ev_open = bus_open.publish(
        FamilienDecisionType.DECISION_PROCEDURAL,
        "test_member_a",
        "test_ctx_open",
    )
    is_valid, missing = bus_open.validate_event(ev_open)
    assert is_valid is True
    assert missing == []


# --------------------------------------------------------------- cleanup_old
def test_cleanup_old_purges():
    """cleanup_old() entfernt Events aelter als retention_window_h.

    Trick: retention_window_h=0.05/3600 = 0.00001388h ≈ 0.05s sodass cleanup_old
    nach time.sleep(0.1) ALLE Events purgt.
    """
    bus = CapeFamilienAuditBus(retention_window_h=0.05 / 3600.0)  # 0.05s
    for i in range(5):
        bus.publish(
            FamilienDecisionType.DECISION_PROCEDURAL,
            "test_member_a",
            f"test_ctx_{i}",
        )
    assert bus.get_stats()["current_count"] == 5

    time.sleep(0.1)
    removed = bus.cleanup_old()
    assert removed == 5
    assert bus.get_stats()["current_count"] == 0
    assert bus.get_stats()["total_purged"] == 5


# ---------------------------------------------------------------- get_stats
def test_get_stats_correct():
    """get_stats() liefert korrekte Snapshots; Aenderungen am Returnwert wirken nicht zurueck."""
    bus = CapeFamilienAuditBus(retention_window_h=24.0)
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx_1",
        compliance_tags=frozenset({ComplianceTag.FAMILIAL}),
    )
    bus.publish(
        FamilienDecisionType.DECISION_VISA,
        "test_member_b",
        "test_ctx_2",
        compliance_tags=frozenset(
            {ComplianceTag.LEGAL, ComplianceTag.US_RELOCATION}
        ),
    )

    stats = bus.get_stats()
    assert stats["total_published"] == 2
    assert stats["total_purged"] == 0
    assert stats["by_decision_type"]["decision_familial"] == 1
    assert stats["by_decision_type"]["decision_visa"] == 1
    assert stats["by_compliance_tag"]["familial"] == 1
    assert stats["by_compliance_tag"]["legal"] == 1
    assert stats["by_compliance_tag"]["us_relocation"] == 1
    assert stats["by_family_member_role"]["test_member_a"] == 1
    assert stats["by_family_member_role"]["test_member_b"] == 1
    assert stats["current_count"] == 2
    assert stats["retention_window_h"] == 24.0

    # Mutation des Returnwerts wirkt nicht auf Bus
    stats["total_published"] = 999
    stats["by_decision_type"]["decision_familial"] = 999
    stats["by_family_member_role"]["test_member_a"] = 999
    stats2 = bus.get_stats()
    assert stats2["total_published"] == 2
    assert stats2["by_decision_type"]["decision_familial"] == 1
    assert stats2["by_family_member_role"]["test_member_a"] == 1


# ----------------------------------------------------------- thread-safety
def test_concurrent_publish_50_threads():
    """50 Threads x 20 Publishes = 1000 Events ohne Race-Condition."""
    bus = CapeFamilienAuditBus()

    def worker(role: str):
        for i in range(20):
            bus.publish(
                decision_type=FamilienDecisionType.DECISION_PROCEDURAL,
                family_member_role=role,
                context=f"test_ctx_{i}",
                compliance_tags=frozenset({ComplianceTag.GDPR}),
            )

    threads = [
        threading.Thread(target=worker, args=(f"test_member_{i}",))
        for i in range(50)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = bus.get_stats()
    # NB: DEFAULT_MAX_SIZE=1000 -> deque-cap erreicht aber total_published muss exakt sein
    assert stats["total_published"] == 1000
    # current_count by deque-cap (1000) == total_published wenn keine Eviction
    assert stats["current_count"] == 1000
    assert stats["by_decision_type"]["decision_procedural"] == 1000
    assert stats["by_compliance_tag"]["gdpr"] == 1000
    # 50 different family-roles, each with 20 publishes
    assert len(stats["by_family_member_role"]) == 50
    for i in range(50):
        assert stats["by_family_member_role"][f"test_member_{i}"] == 20


# ------------------------------------------------------- frozen-immutability
def test_event_frozen_immutability():
    """FamilienAuditEvent ist frozen Dataclass; Mutation wirft Exception."""
    bus = CapeFamilienAuditBus()
    event = bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx_immut",
    )
    with pytest.raises(Exception):
        event.family_member_role = "modified"  # type: ignore
    with pytest.raises(Exception):
        event.context = "tampered_context"  # type: ignore


# ------------------------------------------------------------ unique-event-id
def test_event_unique_uuid():
    """Jedes Event hat eindeutige uuid4 event_id."""
    bus = CapeFamilienAuditBus()
    event_ids = set()
    for i in range(500):
        ev = bus.publish(
            FamilienDecisionType.DECISION_PROCEDURAL,
            "test_member_a",
            f"test_ctx_{i}",
        )
        assert ev.event_id not in event_ids, "duplicate event_id detected"
        event_ids.add(ev.event_id)
    assert len(event_ids) == 500


# ------------------------------------------------- additional Pre-Cond-Tests
def test_publish_invalid_decision_type_raises():
    """decision_type muss FamilienDecisionType sein, nicht string."""
    bus = CapeFamilienAuditBus()
    with pytest.raises(TypeError):
        bus.publish(
            "decision_familial",  # type: ignore
            "test_member_a",
            "test_ctx",
        )


def test_publish_empty_role_raises():
    """family_member_role darf nicht leer sein."""
    bus = CapeFamilienAuditBus()
    with pytest.raises(ValueError):
        bus.publish(
            FamilienDecisionType.DECISION_FAMILIAL,
            "",
            "test_ctx",
        )


def test_publish_empty_context_raises():
    """context darf nicht leer sein."""
    bus = CapeFamilienAuditBus()
    with pytest.raises(ValueError):
        bus.publish(
            FamilienDecisionType.DECISION_FAMILIAL,
            "test_member_a",
            "",
        )


def test_query_invalid_filter_types():
    """Falsche Filter-Typen werfen TypeError."""
    bus = CapeFamilienAuditBus()
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx",
    )
    with pytest.raises(TypeError):
        bus.query(decision_type="decision_familial")  # type: ignore
    with pytest.raises(TypeError):
        bus.query(compliance_tag="gdpr")  # type: ignore


# ---------------------------------------------------------------------------
# P-V15-3: Anti-Stats-Leak Tests (Cross-LLM-V15 Konsens-Patch)
# ---------------------------------------------------------------------------


def test_metadata_size_limit_enforced():
    """P-V15-3: metadata > max_metadata_bytes -> ValueError."""
    bus = CapeFamilienAuditBus(max_metadata_bytes=200)
    # kleines metadata -> OK
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "test_member_a",
        "test_ctx",
        metadata=(("k", "v"),),
    )
    # grosses metadata -> raise
    big_metadata = tuple(
        (f"key_{i}", "x" * 100) for i in range(20)
    )
    with pytest.raises(ValueError, match="metadata exceeds max_metadata_bytes"):
        bus.publish(
            FamilienDecisionType.DECISION_FAMILIAL,
            "test_member_a",
            "test_ctx",
            metadata=big_metadata,
        )


def test_role_cardinality_bounded():
    """P-V15-3: by_family_member_role waechst nur bis max_role_cardinality."""
    bus = CapeFamilienAuditBus(max_role_cardinality=5)
    # 5 distinct roles -> alle drin
    for i in range(5):
        bus.publish(
            FamilienDecisionType.DECISION_FAMILIAL,
            f"member_{i}",
            "ctx",
        )
    stats = bus.get_stats()
    assert len(stats["by_family_member_role"]) == 5
    assert stats["silent_drops_count"] == 0

    # 5 weitere distinct roles -> alle silent dropped
    for i in range(5, 10):
        bus.publish(
            FamilienDecisionType.DECISION_FAMILIAL,
            f"member_{i}",
            "ctx",
        )
    stats = bus.get_stats()
    # by_family_member_role bleibt bei 5 (NEUE roles dropped)
    assert len(stats["by_family_member_role"]) == 5
    # silent_drops_count = 5 (member_5 .. member_9)
    assert stats["silent_drops_count"] == 5

    # Re-publish einer EXISTIERENDEN role -> count++ (kein drop)
    bus.publish(
        FamilienDecisionType.DECISION_FAMILIAL,
        "member_0",
        "ctx",
    )
    stats = bus.get_stats()
    assert stats["by_family_member_role"]["member_0"] == 2
    assert stats["silent_drops_count"] == 5  # unveraendert


def test_silent_drops_count_increments_on_role_overflow():
    """P-V15-3: silent_drops_count wird bei jedem unique-role-overflow inkrementiert."""
    bus = CapeFamilienAuditBus(max_role_cardinality=2)
    bus.publish(FamilienDecisionType.DECISION_FAMILIAL, "alice", "ctx")
    bus.publish(FamilienDecisionType.DECISION_FAMILIAL, "bob", "ctx")
    # 3. distinct role -> dropped
    bus.publish(FamilienDecisionType.DECISION_FAMILIAL, "carol", "ctx")
    # 4. distinct role -> dropped
    bus.publish(FamilienDecisionType.DECISION_FAMILIAL, "dave", "ctx")
    # 5. distinct role -> dropped
    bus.publish(FamilienDecisionType.DECISION_FAMILIAL, "eve", "ctx")
    stats = bus.get_stats()
    assert stats["silent_drops_count"] == 3
    # by_family_member_role hat nur alice, bob
    assert set(stats["by_family_member_role"].keys()) == {"alice", "bob"}
    # Events selbst werden weiterhin gespeichert (nicht gedropped)
    assert stats["total_published"] == 5
    assert stats["current_count"] == 5


# CRUX-MK
