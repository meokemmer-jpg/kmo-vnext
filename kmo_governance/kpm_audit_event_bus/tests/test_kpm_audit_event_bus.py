# [CRUX-MK]
"""KPM-Audit-Event-Bus Tests (Welle-26 Phase-19 Bio-Pattern-Lift)."""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.kpm_audit_event_bus import (
    ComplianceTag,
    KPMAuditEventBus,
    TradeAuditEvent,
    TradeEventType,
)


# ---------------------------------------------------------------------- Init
def test_init_validation():
    """Pre-Conditions am Konstruktor werden geprueft."""
    with pytest.raises(ValueError):
        KPMAuditEventBus(retention_window_h=0)
    with pytest.raises(ValueError):
        KPMAuditEventBus(retention_window_h=-1.0)
    with pytest.raises(TypeError):
        KPMAuditEventBus(compliance_required={"not-an-enum"})

    # Default OK
    bus = KPMAuditEventBus()
    assert bus.retention_window_h == 168.0  # MiFID-RTS-25 Default
    assert bus.compliance_required == frozenset()

    # Mit compliance_required OK
    bus2 = KPMAuditEventBus(
        retention_window_h=200.0,
        compliance_required={ComplianceTag.KYC, ComplianceTag.AML},
    )
    assert ComplianceTag.KYC in bus2.compliance_required
    assert ComplianceTag.AML in bus2.compliance_required


# ------------------------------------------------------------------- publish
def test_publish_creates_event():
    """publish() liefert vollstaendiges TradeAuditEvent zurueck."""
    bus = KPMAuditEventBus()
    event = bus.publish(
        strategy_id="strat-aggressive-001",
        event_type=TradeEventType.BUY,
        instrument_id="DE0007100000",
        quantity=100.0,
        price=50.25,
        compliance_tags=frozenset({ComplianceTag.KYC, ComplianceTag.MIFID_BEST_EXEC}),
        metadata=(("venue", "XETRA"), ("client_id", "kemmer-family")),
    )
    assert isinstance(event, TradeAuditEvent)
    assert event.strategy_id == "strat-aggressive-001"
    assert event.event_type == TradeEventType.BUY
    assert event.instrument_id == "DE0007100000"
    assert event.quantity == 100.0
    assert event.price == 50.25
    assert ComplianceTag.KYC in event.compliance_tags
    assert ComplianceTag.MIFID_BEST_EXEC in event.compliance_tags
    assert event.get_metadata_dict() == {
        "venue": "XETRA",
        "client_id": "kemmer-family",
    }
    assert event.timestamp > 0
    assert event.event_id  # uuid4 string non-empty


def test_publish_increments_stats():
    """publish() inkrementiert total_published + by_event_type + by_compliance_tag."""
    bus = KPMAuditEventBus()
    bus.publish(
        strategy_id="s1",
        event_type=TradeEventType.BUY,
        instrument_id="ISIN1",
        quantity=10,
        price=100,
        compliance_tags=frozenset({ComplianceTag.KYC}),
    )
    bus.publish(
        strategy_id="s1",
        event_type=TradeEventType.SELL,
        instrument_id="ISIN1",
        quantity=5,
        price=110,
        compliance_tags=frozenset({ComplianceTag.KYC, ComplianceTag.AML}),
    )
    bus.publish(
        strategy_id="s2",
        event_type=TradeEventType.BUY,
        instrument_id="ISIN2",
        quantity=20,
        price=50,
    )

    stats = bus.get_stats()
    assert stats["total_published"] == 3
    assert stats["by_event_type"]["buy"] == 2
    assert stats["by_event_type"]["sell"] == 1
    assert stats["by_compliance_tag"]["kyc"] == 2
    assert stats["by_compliance_tag"]["aml"] == 1
    assert stats["current_count"] == 3


# --------------------------------------------------------------------- query
def test_query_by_strategy_id():
    """Filter nach strategy_id liefert nur passende Events."""
    bus = KPMAuditEventBus()
    bus.publish("strat-A", TradeEventType.BUY, "I1", 10, 100)
    bus.publish("strat-B", TradeEventType.BUY, "I1", 20, 100)
    bus.publish("strat-A", TradeEventType.SELL, "I1", 5, 110)

    results = bus.query(strategy_id="strat-A")
    assert len(results) == 2
    assert all(e.strategy_id == "strat-A" for e in results)


def test_query_by_event_type():
    """Filter nach event_type liefert nur Events vom Typ."""
    bus = KPMAuditEventBus()
    bus.publish("s", TradeEventType.BUY, "I1", 10, 100)
    bus.publish("s", TradeEventType.SELL, "I1", 5, 110)
    bus.publish("s", TradeEventType.CANCEL, "I1", 5, 110)
    bus.publish("s", TradeEventType.PARTIAL_FILL, "I1", 3, 105)

    sells = bus.query(event_type=TradeEventType.SELL)
    assert len(sells) == 1
    assert sells[0].event_type == TradeEventType.SELL

    fills = bus.query(event_type=TradeEventType.PARTIAL_FILL)
    assert len(fills) == 1


def test_query_by_time_range():
    """Filter nach since/until liefert Events innerhalb Zeit-Range."""
    bus = KPMAuditEventBus()
    t0 = time.time()
    bus.publish("s", TradeEventType.BUY, "I1", 10, 100)
    time.sleep(0.02)
    t1 = time.time()
    bus.publish("s", TradeEventType.BUY, "I1", 10, 100)
    time.sleep(0.02)
    t2 = time.time()
    bus.publish("s", TradeEventType.BUY, "I1", 10, 100)

    # Nur Events nach t1 (sollten 1-2 sein, je nach genauer Insertion-Zeit)
    after_t1 = bus.query(since=t1)
    assert 1 <= len(after_t1) <= 2

    # Nur Events vor t1
    before_t1 = bus.query(until=t1)
    assert 1 <= len(before_t1) <= 2

    # Range [t0, t2] sollte alle 3 enthalten
    in_range = bus.query(since=t0, until=t2 + 1.0)
    assert len(in_range) == 3


def test_query_by_compliance_tag():
    """Filter nach compliance_tag liefert nur Events mit diesem Tag."""
    bus = KPMAuditEventBus()
    bus.publish(
        "s",
        TradeEventType.BUY,
        "I1",
        10,
        100,
        compliance_tags=frozenset({ComplianceTag.KYC, ComplianceTag.AML}),
    )
    bus.publish(
        "s",
        TradeEventType.SELL,
        "I1",
        5,
        110,
        compliance_tags=frozenset({ComplianceTag.MIFID_BEST_EXEC}),
    )
    bus.publish(
        "s",
        TradeEventType.BUY,
        "I2",
        20,
        50,
        compliance_tags=frozenset({ComplianceTag.AML}),
    )

    aml_events = bus.query(compliance_tag=ComplianceTag.AML)
    assert len(aml_events) == 2
    assert all(ComplianceTag.AML in e.compliance_tags for e in aml_events)

    mifid_events = bus.query(compliance_tag=ComplianceTag.MIFID_BEST_EXEC)
    assert len(mifid_events) == 1


# ------------------------------------------------------------------- validate
def test_validate_event_with_compliance_required():
    """validate_event prueft compliance_required als Subset."""
    bus = KPMAuditEventBus(
        compliance_required={ComplianceTag.KYC, ComplianceTag.AML},
    )

    # Event mit allen erforderlichen Tags - VALID
    ev_full = bus.publish(
        "s",
        TradeEventType.BUY,
        "I1",
        10,
        100,
        compliance_tags=frozenset(
            {ComplianceTag.KYC, ComplianceTag.AML, ComplianceTag.MIFID_BEST_EXEC}
        ),
    )
    is_valid, missing = bus.validate_event(ev_full)
    assert is_valid is True
    assert missing == []

    # Event mit fehlenden Tags - INVALID
    ev_partial = bus.publish(
        "s",
        TradeEventType.BUY,
        "I1",
        10,
        100,
        compliance_tags=frozenset({ComplianceTag.KYC}),
    )
    is_valid, missing = bus.validate_event(ev_partial)
    assert is_valid is False
    assert "aml" in missing

    # Bus ohne compliance_required: jedes Event valid
    bus_open = KPMAuditEventBus()
    ev_open = bus_open.publish("s", TradeEventType.BUY, "I1", 10, 100)
    is_valid, missing = bus_open.validate_event(ev_open)
    assert is_valid is True
    assert missing == []


# --------------------------------------------------------------- cleanup_old
def test_cleanup_old_purges_expired():
    """cleanup_old() entfernt Events aelter als retention_window_h.

    Trick: retention_window_h=0.05/3600 = 0.00001388h ≈ 0.05s sodass cleanup_old
    nach time.sleep(0.1) ALLE Events purgt.
    """
    bus = KPMAuditEventBus(retention_window_h=0.05 / 3600.0)  # 0.05s
    for _ in range(5):
        bus.publish("s", TradeEventType.BUY, "I1", 10, 100)
    assert bus.get_stats()["current_count"] == 5

    time.sleep(0.1)
    removed = bus.cleanup_old()
    assert removed == 5
    assert bus.get_stats()["current_count"] == 0
    assert bus.get_stats()["total_purged"] == 5


# ---------------------------------------------------------------- get_stats
def test_get_stats_correct_counts():
    """get_stats() liefert korrekte Snapshots; Aenderungen am Returnwert wirken nicht zurueck."""
    bus = KPMAuditEventBus(retention_window_h=24.0)
    bus.publish(
        "s1",
        TradeEventType.BUY,
        "I1",
        10,
        100,
        compliance_tags=frozenset({ComplianceTag.POSITION_LIMIT}),
    )
    bus.publish(
        "s2",
        TradeEventType.REJECT,
        "I2",
        5,
        50,
        compliance_tags=frozenset({ComplianceTag.RISK_BUDGET, ComplianceTag.LATE_TRADING}),
    )

    stats = bus.get_stats()
    assert stats["total_published"] == 2
    assert stats["total_purged"] == 0
    assert stats["by_event_type"]["buy"] == 1
    assert stats["by_event_type"]["reject"] == 1
    assert stats["by_compliance_tag"]["position_limit"] == 1
    assert stats["by_compliance_tag"]["risk_budget"] == 1
    assert stats["by_compliance_tag"]["late_trading"] == 1
    assert stats["current_count"] == 2
    assert stats["retention_window_h"] == 24.0

    # Mutation des Returnwerts wirkt nicht auf Bus
    stats["total_published"] = 999
    stats["by_event_type"]["buy"] = 999
    stats2 = bus.get_stats()
    assert stats2["total_published"] == 2
    assert stats2["by_event_type"]["buy"] == 1


# ----------------------------------------------------------- thread-safety
def test_concurrent_publish_50_threads():
    """50 Threads x 20 Publishes = 1000 Events ohne Race-Condition."""
    bus = KPMAuditEventBus()

    def worker(strategy_id: str):
        for i in range(20):
            bus.publish(
                strategy_id=strategy_id,
                event_type=TradeEventType.BUY,
                instrument_id=f"INST-{i}",
                quantity=1.0,
                price=100.0,
                compliance_tags=frozenset({ComplianceTag.KYC}),
            )

    threads = [
        threading.Thread(target=worker, args=(f"strat-{i}",))
        for i in range(50)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = bus.get_stats()
    assert stats["total_published"] == 1000
    assert stats["current_count"] == 1000
    assert stats["by_event_type"]["buy"] == 1000
    assert stats["by_compliance_tag"]["kyc"] == 1000


# ------------------------------------------------------- frozen-immutability
def test_event_frozen_immutability():
    """TradeAuditEvent ist frozen Dataclass; Mutation wirft Exception."""
    bus = KPMAuditEventBus()
    event = bus.publish("s", TradeEventType.BUY, "I1", 10, 100)
    with pytest.raises(Exception):
        event.strategy_id = "modified"  # type: ignore
    with pytest.raises(Exception):
        event.quantity = 999  # type: ignore


# ------------------------------------------------------------ unique-event-id
def test_event_unique_uuid():
    """Jedes Event hat eindeutige uuid4 event_id."""
    bus = KPMAuditEventBus()
    event_ids = set()
    for _ in range(500):
        ev = bus.publish("s", TradeEventType.BUY, "I1", 10, 100)
        assert ev.event_id not in event_ids, "duplicate event_id detected"
        event_ids.add(ev.event_id)
    assert len(event_ids) == 500


# ------------------------------------------------- additional Pre-Cond-Tests
def test_publish_invalid_quantity_raises():
    """quantity <= 0 wird abgelehnt."""
    bus = KPMAuditEventBus()
    with pytest.raises(ValueError):
        bus.publish("s", TradeEventType.BUY, "I1", 0, 100)
    with pytest.raises(ValueError):
        bus.publish("s", TradeEventType.BUY, "I1", -10, 100)


def test_publish_invalid_price_raises():
    """price <= 0 wird abgelehnt."""
    bus = KPMAuditEventBus()
    with pytest.raises(ValueError):
        bus.publish("s", TradeEventType.BUY, "I1", 10, 0)
    with pytest.raises(ValueError):
        bus.publish("s", TradeEventType.BUY, "I1", 10, -100)


def test_publish_invalid_event_type_raises():
    """event_type muss TradeEventType sein, nicht string."""
    bus = KPMAuditEventBus()
    with pytest.raises(TypeError):
        bus.publish("s", "buy", "I1", 10, 100)  # type: ignore


def test_query_invalid_filter_types():
    """Falsche Filter-Typen werfen TypeError."""
    bus = KPMAuditEventBus()
    bus.publish("s", TradeEventType.BUY, "I1", 10, 100)
    with pytest.raises(TypeError):
        bus.query(event_type="buy")  # type: ignore
    with pytest.raises(TypeError):
        bus.query(compliance_tag="kyc")  # type: ignore


# -------------- P-V13-4: Metadata-Cap + Silent-Drops-Counter --------------


def test_metadata_size_limit_enforced():
    """V13-4: metadata > max_metadata_bytes raises ValueError."""
    bus = KPMAuditEventBus(max_metadata_bytes=64)

    # Small metadata OK
    small_meta = (("k", "v"),)
    bus.publish("s", TradeEventType.BUY, "I1", 10, 100, metadata=small_meta)

    # Big metadata > 64 bytes -> ValueError
    huge_value = "x" * 200
    big_meta = (("key", huge_value),)
    with pytest.raises(ValueError, match="metadata size.*exceeds"):
        bus.publish(
            "s", TradeEventType.BUY, "I1", 10, 100, metadata=big_meta
        )

    # max_metadata_bytes pre-condition < 1
    with pytest.raises(ValueError, match="max_metadata_bytes"):
        KPMAuditEventBus(max_metadata_bytes=0)
    with pytest.raises(ValueError, match="max_metadata_bytes"):
        KPMAuditEventBus(max_metadata_bytes=-5)


def test_silent_drops_counter_increments():
    """V13-4: silent_drops_count incrementiert bei deque-maxlen-eviction."""
    # Mock DEFAULT_MAX_SIZE for testbarkeit via class-monkey-patch
    bus = KPMAuditEventBus()
    # Set deque maxlen to 3 fuer determinitistischen Test
    from collections import deque as _deque

    bus._events = _deque(maxlen=3)

    # Initial: keine drops
    assert bus.get_stats()["silent_drops_count"] == 0

    # 3 events -> deque voll, aber NOCH keine drops
    for i in range(3):
        bus.publish("s", TradeEventType.BUY, f"I{i}", 10, 100)
    assert bus.get_stats()["silent_drops_count"] == 0
    assert bus.get_stats()["current_count"] == 3

    # 4. event -> deque schon voll vor append -> 1 silent drop
    bus.publish("s", TradeEventType.BUY, "I4", 10, 100)
    assert bus.get_stats()["silent_drops_count"] == 1
    assert bus.get_stats()["current_count"] == 3

    # 5. + 6. event -> 3 drops total
    bus.publish("s", TradeEventType.BUY, "I5", 10, 100)
    bus.publish("s", TradeEventType.BUY, "I6", 10, 100)
    assert bus.get_stats()["silent_drops_count"] == 3
    assert bus.get_stats()["current_count"] == 3


def test_silent_drops_in_stats():
    """V13-4: silent_drops_count erscheint in get_stats()-Snapshot."""
    bus = KPMAuditEventBus()
    stats = bus.get_stats()
    # Pflicht-Feld vorhanden
    assert "silent_drops_count" in stats
    assert stats["silent_drops_count"] == 0
    assert isinstance(stats["silent_drops_count"], int)

    # Snapshot-Isolation: dict-Mutation veraendert Bus-Internal nicht
    stats["silent_drops_count"] = 999
    assert bus.get_stats()["silent_drops_count"] == 0


# CRUX-MK
