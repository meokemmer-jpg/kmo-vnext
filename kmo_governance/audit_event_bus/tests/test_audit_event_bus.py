# [CRUX-MK]
"""Audit-Event-Bus Tests."""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.audit_event_bus import (
    AuditEvent,
    AuditEventBus,
    AuditEventLevel,
    AuditQuery,
    RetentionPolicy,
)


def test_audit_event_frozen():
    e = AuditEvent(
        event_id="e1",
        source="s",
        level=AuditEventLevel.INFO,
        payload=(("k", "v"),),
        timestamp=1.0,
    )
    with pytest.raises(Exception):
        e.event_id = "modified"


def test_audit_event_invalid_source_raises():
    with pytest.raises(ValueError):
        AuditEvent(
            event_id="e1",
            source="",
            level=AuditEventLevel.INFO,
            payload=(),
            timestamp=1.0,
        )


def test_audit_event_invalid_level_type_raises():
    with pytest.raises(TypeError):
        AuditEvent(
            event_id="e1",
            source="s",
            level="info",  # str instead of enum
            payload=(),
            timestamp=1.0,
        )


def test_retention_policy_validation():
    with pytest.raises(ValueError):
        RetentionPolicy(ttl_s=0)
    with pytest.raises(ValueError):
        RetentionPolicy(max_size=-1)


def test_event_bus_publish_returns_event():
    bus = AuditEventBus()
    event = bus.publish("svc", AuditEventLevel.INFO, {"key": "val"})
    assert event.source == "svc"
    assert event.level == AuditEventLevel.INFO
    assert event.get_payload_dict() == {"key": "val"}


def test_event_bus_subscribe_receives_publish():
    bus = AuditEventBus()
    received = []
    bus.subscribe("sub-1", lambda e: received.append(e))
    bus.publish("svc", AuditEventLevel.WARN, {})
    assert len(received) == 1


def test_event_bus_unsubscribe_stops_notifications():
    bus = AuditEventBus()
    received = []
    bus.subscribe("sub-1", lambda e: received.append(e))
    bus.unsubscribe("sub-1")
    bus.publish("svc", AuditEventLevel.INFO, {})
    assert received == []


def test_event_bus_count_tracks_events():
    bus = AuditEventBus()
    for i in range(10):
        bus.publish("svc", AuditEventLevel.INFO, {"i": i})
    assert bus.count() == 10


def test_event_bus_query_by_level():
    bus = AuditEventBus()
    bus.publish("svc", AuditEventLevel.INFO, {})
    bus.publish("svc", AuditEventLevel.ERROR, {})
    bus.publish("svc", AuditEventLevel.CRITICAL, {})
    q = AuditQuery(levels=(AuditEventLevel.ERROR, AuditEventLevel.CRITICAL))
    results = bus.query(q)
    assert len(results) == 2


def test_event_bus_query_by_source():
    bus = AuditEventBus()
    bus.publish("svc-A", AuditEventLevel.INFO, {})
    bus.publish("svc-B", AuditEventLevel.INFO, {})
    q = AuditQuery(sources=("svc-A",))
    results = bus.query(q)
    assert len(results) == 1
    assert results[0].source == "svc-A"


def test_event_bus_query_by_payload_match():
    bus = AuditEventBus()
    bus.publish("svc", AuditEventLevel.INFO, {"hotel_id": "h1"})
    bus.publish("svc", AuditEventLevel.INFO, {"hotel_id": "h2"})
    q = AuditQuery(payload_contains=(("hotel_id", "h1"),))
    results = bus.query(q)
    assert len(results) == 1


def test_event_bus_max_size_enforced():
    bus = AuditEventBus(RetentionPolicy(ttl_s=10.0, max_size=5))
    for i in range(20):
        bus.publish("svc", AuditEventLevel.INFO, {"i": i})
    assert bus.count() == 5  # only last 5


def test_event_bus_prune_expired():
    bus = AuditEventBus(RetentionPolicy(ttl_s=0.01, max_size=100))
    for _ in range(5):
        bus.publish("svc", AuditEventLevel.INFO, {})
    time.sleep(0.05)
    removed = bus.prune_expired()
    assert removed == 5
    assert bus.count() == 0


def test_event_bus_concurrent_publish_50_threads():
    bus = AuditEventBus()

    def worker():
        for _ in range(20):
            bus.publish("svc", AuditEventLevel.INFO, {"thread": "x"})

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert bus.count() == 1000


def test_event_bus_subscriber_exception_isolated():
    bus = AuditEventBus()
    received_good = []
    bus.subscribe("good", lambda e: received_good.append(e))

    def broken(e):
        raise RuntimeError("subscriber broken")

    bus.subscribe("broken", broken)
    bus.publish("svc", AuditEventLevel.INFO, {})
    # Good subscriber still receives
    assert len(received_good) == 1
