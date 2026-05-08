# [CRUX-MK]
"""9dots-PMO-Audit-Bus Tests (Welle-32 Phase-25 KMO-vNext Bio-Pattern-Lift 6/6).

Q_0-PFLICHT: KEINE Real-9dots-Production-Daten -- alle Tests nutzen ausschliesslich
dummy-Daten ("test_agent_x", "test_slot_y", "test_context_z").

Pattern-Quelle: kmo_governance.audit_event_bus (Welle-9, Hotel-Domain).
2. Lift:        kmo_governance.kpm_audit_event_bus (Welle-26 Phase-19, KPM-Trading).
3. Lift:        kmo_governance.cape_familien_audit_bus (Welle-30 Phase-23, Cape-Familien).
4./5. Lifts:    weitere KMO-Sublayer-Lifts.
6. Lift (HIER): 9dots-PMO-Compliance-Audit-Trail.

15 Tests:
  test_init_validation
  test_publish_creates_event
  test_publish_increments_stats
  test_query_by_decision_type
  test_query_by_agent_class
  test_query_by_slot_id
  test_query_by_governance_tier
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

from kmo_governance.ninedots_pmo_audit_bus import (
    ComplianceTag,
    NineDotsPMOAuditBus,
    PMOAuditEvent,
    PMODecisionType,
)


# ---------------------------------------------------------------------- Init
def test_init_validation():
    """Pre-Conditions am Konstruktor werden geprueft."""
    with pytest.raises(ValueError):
        NineDotsPMOAuditBus(retention_window_h=0)
    with pytest.raises(ValueError):
        NineDotsPMOAuditBus(retention_window_h=-1.0)
    with pytest.raises(TypeError):
        NineDotsPMOAuditBus(compliance_required={"not-an-enum"})

    # Default OK -- SAE-Audit 6-Monats-Retention
    bus = NineDotsPMOAuditBus()
    assert bus.retention_window_h == 4380.0  # 6 Monate SAE-Default
    assert bus.compliance_required == frozenset()

    # Mit compliance_required OK
    bus2 = NineDotsPMOAuditBus(
        retention_window_h=24.0,
        compliance_required={ComplianceTag.COSMOS, ComplianceTag.SAE_GOVERNANCE},
    )
    assert ComplianceTag.COSMOS in bus2.compliance_required
    assert ComplianceTag.SAE_GOVERNANCE in bus2.compliance_required


# ------------------------------------------------------------------- publish
def test_publish_creates_event():
    """publish() liefert vollstaendiges PMOAuditEvent zurueck."""
    bus = NineDotsPMOAuditBus()
    event = bus.publish(
        decision_type=PMODecisionType.AGENT_PROMOTION,
        agent_class="test_agent_revenue",
        slot_id="test_slot_42",
        governance_tier=1,
        context="test_ctx_promotion_aggressive_to_active",
        compliance_tags=frozenset(
            {ComplianceTag.SAE_GOVERNANCE, ComplianceTag.COSMOS}
        ),
        metadata=(
            ("test_meta_key", "test_meta_value"),
            ("test_decision_id", "test_decision_dummy_001"),
        ),
    )
    assert isinstance(event, PMOAuditEvent)
    assert event.decision_type == PMODecisionType.AGENT_PROMOTION
    assert event.agent_class == "test_agent_revenue"
    assert event.slot_id == "test_slot_42"
    assert event.governance_tier == 1
    assert event.context == "test_ctx_promotion_aggressive_to_active"
    assert ComplianceTag.SAE_GOVERNANCE in event.compliance_tags
    assert ComplianceTag.COSMOS in event.compliance_tags
    assert event.get_metadata_dict() == {
        "test_meta_key": "test_meta_value",
        "test_decision_id": "test_decision_dummy_001",
    }
    assert event.timestamp > 0
    assert event.event_id  # uuid4 string non-empty


def test_publish_increments_stats():
    """publish() inkrementiert total_published + by_decision_type + by_compliance_tag +
    by_agent_class + by_governance_tier."""
    bus = NineDotsPMOAuditBus()
    bus.publish(
        decision_type=PMODecisionType.SLOT_ALLOCATION,
        agent_class="test_agent_revenue",
        slot_id="test_slot_1",
        governance_tier=0,
        context="test_ctx_1",
        compliance_tags=frozenset({ComplianceTag.SAE_GOVERNANCE}),
    )
    bus.publish(
        decision_type=PMODecisionType.HAMILTON_PIVOT,
        agent_class="test_agent_revenue",
        slot_id="test_slot_2",
        governance_tier=2,
        context="test_ctx_2",
        compliance_tags=frozenset(
            {ComplianceTag.CRUX_BINDING, ComplianceTag.K0_RELEVANT}
        ),
    )
    bus.publish(
        decision_type=PMODecisionType.SLOT_ALLOCATION,
        agent_class="test_agent_housekeeping",
        slot_id="test_slot_3",
        governance_tier=0,
        context="test_ctx_3",
    )

    stats = bus.get_stats()
    assert stats["total_published"] == 3
    assert stats["by_decision_type"]["slot_allocation"] == 2
    assert stats["by_decision_type"]["hamilton_pivot"] == 1
    assert stats["by_compliance_tag"]["sae_governance"] == 1
    assert stats["by_compliance_tag"]["crux_binding"] == 1
    assert stats["by_compliance_tag"]["k0_relevant"] == 1
    assert stats["by_agent_class"]["test_agent_revenue"] == 2
    assert stats["by_agent_class"]["test_agent_housekeeping"] == 1
    assert stats["by_governance_tier"][0] == 2
    assert stats["by_governance_tier"][2] == 1
    assert stats["current_count"] == 3


# --------------------------------------------------------------------- query
def test_query_by_decision_type():
    """Filter nach decision_type liefert nur Events vom Typ."""
    bus = NineDotsPMOAuditBus()
    bus.publish(
        PMODecisionType.AGENT_PROMOTION,
        "test_agent_a",
        "test_slot_1",
        1,
        "test_ctx_1",
    )
    bus.publish(
        PMODecisionType.AGENT_RELEGATION,
        "test_agent_a",
        "test_slot_2",
        -1,
        "test_ctx_2",
    )
    bus.publish(
        PMODecisionType.AGENT_PROMOTION,
        "test_agent_b",
        "test_slot_3",
        1,
        "test_ctx_3",
    )
    bus.publish(
        PMODecisionType.TRINITY_VOTE,
        "test_agent_a",
        "test_slot_4",
        0,
        "test_ctx_4",
    )

    promotions = bus.query(decision_type=PMODecisionType.AGENT_PROMOTION)
    assert len(promotions) == 2
    assert all(
        e.decision_type == PMODecisionType.AGENT_PROMOTION for e in promotions
    )

    votes = bus.query(decision_type=PMODecisionType.TRINITY_VOTE)
    assert len(votes) == 1


def test_query_by_agent_class():
    """Filter nach agent_class liefert nur passende Events."""
    bus = NineDotsPMOAuditBus()
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_1",
        0,
        "test_ctx_1",
    )
    bus.publish(
        PMODecisionType.BUDGET_ADJUSTMENT,
        "test_agent_b",
        "test_slot_2",
        1,
        "test_ctx_2",
    )
    bus.publish(
        PMODecisionType.HAMILTON_PIVOT,
        "test_agent_a",
        "test_slot_3",
        2,
        "test_ctx_3",
    )

    cls_a = bus.query(agent_class="test_agent_a")
    assert len(cls_a) == 2
    assert all(e.agent_class == "test_agent_a" for e in cls_a)

    cls_b = bus.query(agent_class="test_agent_b")
    assert len(cls_b) == 1


def test_query_by_slot_id():
    """Filter nach slot_id liefert nur passende Events."""
    bus = NineDotsPMOAuditBus()
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_42",
        0,
        "test_ctx_1",
    )
    bus.publish(
        PMODecisionType.AGENT_PROMOTION,
        "test_agent_a",
        "test_slot_42",
        1,
        "test_ctx_2",
    )
    bus.publish(
        PMODecisionType.AGENT_RELEGATION,
        "test_agent_b",
        "test_slot_99",
        -1,
        "test_ctx_3",
    )

    slot_42 = bus.query(slot_id="test_slot_42")
    assert len(slot_42) == 2
    assert all(e.slot_id == "test_slot_42" for e in slot_42)

    slot_99 = bus.query(slot_id="test_slot_99")
    assert len(slot_99) == 1


def test_query_by_governance_tier():
    """Filter nach governance_tier liefert nur passende Events."""
    bus = NineDotsPMOAuditBus()
    bus.publish(
        PMODecisionType.GOVERNANCE_TIER_CHANGE,
        "test_agent_a",
        "test_slot_1",
        2,  # high tier
        "test_ctx_1",
    )
    bus.publish(
        PMODecisionType.GOVERNANCE_TIER_CHANGE,
        "test_agent_b",
        "test_slot_2",
        -1,  # negative tier
        "test_ctx_2",
    )
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_c",
        "test_slot_3",
        2,  # high tier (same as first)
        "test_ctx_3",
    )

    tier_2 = bus.query(governance_tier=2)
    assert len(tier_2) == 2
    assert all(e.governance_tier == 2 for e in tier_2)

    tier_minus_1 = bus.query(governance_tier=-1)
    assert len(tier_minus_1) == 1


def test_query_by_time_range():
    """Filter nach since/until liefert Events innerhalb Zeit-Range."""
    bus = NineDotsPMOAuditBus()
    t0 = time.time()
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_1",
        0,
        "test_ctx_1",
    )
    time.sleep(0.02)
    t1 = time.time()
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_2",
        0,
        "test_ctx_2",
    )
    time.sleep(0.02)
    t2 = time.time()
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_3",
        0,
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
    bus = NineDotsPMOAuditBus()
    bus.publish(
        PMODecisionType.HAMILTON_PIVOT,
        "test_agent_a",
        "test_slot_1",
        1,
        "test_ctx_1",
        compliance_tags=frozenset(
            {ComplianceTag.CRUX_BINDING, ComplianceTag.SAE_GOVERNANCE}
        ),
    )
    bus.publish(
        PMODecisionType.BUDGET_ADJUSTMENT,
        "test_agent_a",
        "test_slot_2",
        0,
        "test_ctx_2",
        compliance_tags=frozenset({ComplianceTag.K0_RELEVANT}),
    )
    bus.publish(
        PMODecisionType.GOVERNANCE_TIER_CHANGE,
        "test_agent_b",
        "test_slot_3",
        2,
        "test_ctx_3",
        compliance_tags=frozenset(
            {ComplianceTag.COSMOS, ComplianceTag.SAE_GOVERNANCE}
        ),
    )

    sae_events = bus.query(compliance_tag=ComplianceTag.SAE_GOVERNANCE)
    assert len(sae_events) == 2
    assert all(ComplianceTag.SAE_GOVERNANCE in e.compliance_tags for e in sae_events)

    k0_events = bus.query(compliance_tag=ComplianceTag.K0_RELEVANT)
    assert len(k0_events) == 1


# ------------------------------------------------------------------- validate
def test_validate_event_compliance_required():
    """validate_event prueft compliance_required als Subset."""
    bus = NineDotsPMOAuditBus(
        compliance_required={ComplianceTag.COSMOS, ComplianceTag.SAE_GOVERNANCE},
    )

    # Event mit allen erforderlichen Tags - VALID
    ev_full = bus.publish(
        PMODecisionType.AGENT_PROMOTION,
        "test_agent_a",
        "test_slot_1",
        1,
        "test_ctx_full",
        compliance_tags=frozenset(
            {
                ComplianceTag.COSMOS,
                ComplianceTag.SAE_GOVERNANCE,
                ComplianceTag.MYZ_LAYER,
            }
        ),
    )
    is_valid, missing = bus.validate_event(ev_full)
    assert is_valid is True
    assert missing == []

    # Event mit fehlenden Tags - INVALID
    ev_partial = bus.publish(
        PMODecisionType.AGENT_PROMOTION,
        "test_agent_a",
        "test_slot_2",
        1,
        "test_ctx_partial",
        compliance_tags=frozenset({ComplianceTag.COSMOS}),
    )
    is_valid, missing = bus.validate_event(ev_partial)
    assert is_valid is False
    assert "sae_governance" in missing

    # Bus ohne compliance_required: jedes Event valid
    bus_open = NineDotsPMOAuditBus()
    ev_open = bus_open.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_1",
        0,
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
    bus = NineDotsPMOAuditBus(retention_window_h=0.05 / 3600.0)  # 0.05s
    for i in range(5):
        bus.publish(
            PMODecisionType.SLOT_ALLOCATION,
            "test_agent_a",
            f"test_slot_{i}",
            0,
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
    bus = NineDotsPMOAuditBus(retention_window_h=24.0)
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_1",
        0,
        "test_ctx_1",
        compliance_tags=frozenset({ComplianceTag.SAE_GOVERNANCE}),
    )
    bus.publish(
        PMODecisionType.AGENT_PROMOTION,
        "test_agent_b",
        "test_slot_2",
        1,
        "test_ctx_2",
        compliance_tags=frozenset(
            {ComplianceTag.COSMOS, ComplianceTag.MYZ_LAYER}
        ),
    )

    stats = bus.get_stats()
    assert stats["total_published"] == 2
    assert stats["total_purged"] == 0
    assert stats["by_decision_type"]["slot_allocation"] == 1
    assert stats["by_decision_type"]["agent_promotion"] == 1
    assert stats["by_compliance_tag"]["sae_governance"] == 1
    assert stats["by_compliance_tag"]["cosmos"] == 1
    assert stats["by_compliance_tag"]["myz_layer"] == 1
    assert stats["by_agent_class"]["test_agent_a"] == 1
    assert stats["by_agent_class"]["test_agent_b"] == 1
    assert stats["by_governance_tier"][0] == 1
    assert stats["by_governance_tier"][1] == 1
    assert stats["current_count"] == 2
    assert stats["retention_window_h"] == 24.0

    # Mutation des Returnwerts wirkt nicht auf Bus
    stats["total_published"] = 999
    stats["by_decision_type"]["slot_allocation"] = 999
    stats["by_agent_class"]["test_agent_a"] = 999
    stats["by_governance_tier"][0] = 999
    stats2 = bus.get_stats()
    assert stats2["total_published"] == 2
    assert stats2["by_decision_type"]["slot_allocation"] == 1
    assert stats2["by_agent_class"]["test_agent_a"] == 1
    assert stats2["by_governance_tier"][0] == 1


# ----------------------------------------------------------- thread-safety
def test_concurrent_publish_50_threads():
    """50 Threads x 20 Publishes = 1000 Events ohne Race-Condition."""
    bus = NineDotsPMOAuditBus()

    def worker(agent_idx: int):
        for i in range(20):
            bus.publish(
                decision_type=PMODecisionType.SLOT_ALLOCATION,
                agent_class=f"test_agent_{agent_idx}",
                slot_id=f"test_slot_{agent_idx}_{i}",
                governance_tier=0,
                context=f"test_ctx_{i}",
                compliance_tags=frozenset({ComplianceTag.SAE_GOVERNANCE}),
            )

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(50)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = bus.get_stats()
    # NB: DEFAULT_MAX_SIZE=1000 -> deque-cap erreicht, total_published muss exakt sein
    assert stats["total_published"] == 1000
    # current_count by deque-cap (1000) == total_published wenn keine Eviction
    assert stats["current_count"] == 1000
    assert stats["by_decision_type"]["slot_allocation"] == 1000
    assert stats["by_compliance_tag"]["sae_governance"] == 1000
    # 50 different agent-classes, each with 20 publishes
    assert len(stats["by_agent_class"]) == 50
    for i in range(50):
        assert stats["by_agent_class"][f"test_agent_{i}"] == 20
    # Alle Events governance_tier=0 -> exakt 1000 in tier 0
    assert stats["by_governance_tier"][0] == 1000


# ------------------------------------------------------- frozen-immutability
def test_event_frozen_immutability():
    """PMOAuditEvent ist frozen Dataclass; Mutation wirft Exception."""
    bus = NineDotsPMOAuditBus()
    event = bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_1",
        0,
        "test_ctx_immut",
    )
    with pytest.raises(Exception):
        event.agent_class = "modified"  # type: ignore
    with pytest.raises(Exception):
        event.slot_id = "tampered_slot"  # type: ignore
    with pytest.raises(Exception):
        event.governance_tier = 99  # type: ignore


# ------------------------------------------------------------ unique-event-id
def test_event_unique_uuid():
    """Jedes Event hat eindeutige uuid4 event_id."""
    bus = NineDotsPMOAuditBus()
    event_ids = set()
    for i in range(500):
        ev = bus.publish(
            PMODecisionType.SLOT_ALLOCATION,
            "test_agent_a",
            f"test_slot_{i}",
            0,
            f"test_ctx_{i}",
        )
        assert ev.event_id not in event_ids, "duplicate event_id detected"
        event_ids.add(ev.event_id)
    assert len(event_ids) == 500


# ------------------------------------------------- additional Pre-Cond-Tests
def test_publish_invalid_decision_type_raises():
    """decision_type muss PMODecisionType sein, nicht string."""
    bus = NineDotsPMOAuditBus()
    with pytest.raises(TypeError):
        bus.publish(
            "slot_allocation",  # type: ignore
            "test_agent_a",
            "test_slot_1",
            0,
            "test_ctx",
        )


def test_publish_empty_agent_class_raises():
    """agent_class darf nicht leer sein."""
    bus = NineDotsPMOAuditBus()
    with pytest.raises(ValueError):
        bus.publish(
            PMODecisionType.SLOT_ALLOCATION,
            "",
            "test_slot_1",
            0,
            "test_ctx",
        )


def test_publish_empty_slot_id_raises():
    """slot_id darf nicht leer sein."""
    bus = NineDotsPMOAuditBus()
    with pytest.raises(ValueError):
        bus.publish(
            PMODecisionType.SLOT_ALLOCATION,
            "test_agent_a",
            "",
            0,
            "test_ctx",
        )


def test_publish_invalid_governance_tier_raises():
    """governance_tier muss int sein, nicht string oder bool."""
    bus = NineDotsPMOAuditBus()
    with pytest.raises(TypeError):
        bus.publish(
            PMODecisionType.SLOT_ALLOCATION,
            "test_agent_a",
            "test_slot_1",
            "0",  # type: ignore -- string statt int
            "test_ctx",
        )
    with pytest.raises(TypeError):
        bus.publish(
            PMODecisionType.SLOT_ALLOCATION,
            "test_agent_a",
            "test_slot_1",
            True,  # type: ignore -- bool statt int (subtype-Falle)
            "test_ctx",
        )


def test_publish_empty_context_raises():
    """context darf nicht leer sein."""
    bus = NineDotsPMOAuditBus()
    with pytest.raises(ValueError):
        bus.publish(
            PMODecisionType.SLOT_ALLOCATION,
            "test_agent_a",
            "test_slot_1",
            0,
            "",
        )


def test_query_invalid_filter_types():
    """Falsche Filter-Typen werfen TypeError."""
    bus = NineDotsPMOAuditBus()
    bus.publish(
        PMODecisionType.SLOT_ALLOCATION,
        "test_agent_a",
        "test_slot_1",
        0,
        "test_ctx",
    )
    with pytest.raises(TypeError):
        bus.query(decision_type="slot_allocation")  # type: ignore
    with pytest.raises(TypeError):
        bus.query(compliance_tag="cosmos")  # type: ignore
    with pytest.raises(TypeError):
        bus.query(governance_tier="0")  # type: ignore


# CRUX-MK
