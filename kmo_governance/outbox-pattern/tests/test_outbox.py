"""KMO Outbox Pattern Tests [CRUX-MK]

Pflicht-Tests:
1. Atomic-Write (kein partial-write bei Crash-Simulation)
2. Happy-Path 3 Events (publish + process + ack)
3. Idempotency (gleiche event_id = einmal verarbeitet)
4. DLQ nach 3 Fails
5. Cross-machine-simulation (2 Producer, 1 Consumer)

Spec: branch-hub/blueprints/SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30.md §P-KMO-A3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Pfad zum Modul
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kmo_outbox_consumer import OutboxConsumer  # noqa: E402
from kmo_outbox_producer import EventEnvelope, OutboxProducer, atomic_write_json  # noqa: E402


@pytest.fixture
def dirs(tmp_path):
    """Fresh outbox/ack/dlq dirs + state-db Pfade pro Test."""
    return {
        "outbox": tmp_path / "outbox",
        "ack": tmp_path / "ack",
        "dlq": tmp_path / "dlq",
        "producer_db": tmp_path / "producer.db",
        "consumer_db": tmp_path / "consumer.db",
    }


def test_atomic_write_no_partial_file(tmp_path):
    """Atomic-Write: targetfile existiert NUR fully written."""
    target = tmp_path / "atomic.json"
    atomic_write_json(target, {"key": "value", "n": 42})
    assert target.exists()
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"key": "value", "n": 42}
    # Keine .tmp-Files uebrig
    tmp_files = list(tmp_path.glob(".tmp-*"))
    assert tmp_files == []


def test_happy_path_3_events(dirs):
    """3 Events publish + consume + ack, alle erfolgreich."""
    producer = OutboxProducer(
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        machine_id="mac",
        state_db=dirs["producer_db"],
    )
    consumer = OutboxConsumer(
        consumer_id="test",
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        dlq_dir=dirs["dlq"],
        state_db=dirs["consumer_db"],
    )

    received: list[EventEnvelope] = []

    def handler(event: EventEnvelope) -> None:
        received.append(event)

    consumer.subscribe(["sync"], handler)

    e1 = producer.publish("mac", "sync", {"file": "a.md"})
    e2 = producer.publish("mac", "sync", {"file": "b.md"})
    e3 = producer.publish("mac", "sync", {"file": "c.md"})

    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3

    stats = consumer.poll_and_process()
    assert stats.polled == 3
    assert stats.processed == 3
    assert stats.failed == 0
    assert len(received) == 3

    # Ack-Files existieren
    ack_files = list(dirs["ack"].glob("*.ack.json"))
    assert len(ack_files) == 3


def test_idempotency_same_event_id_processed_once(dirs):
    """Doppel-Publish mit gleicher event_id: Consumer verarbeitet nur 1x."""
    producer = OutboxProducer(
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        machine_id="mac",
        state_db=dirs["producer_db"],
    )
    consumer = OutboxConsumer(
        consumer_id="test",
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        dlq_dir=dirs["dlq"],
        state_db=dirs["consumer_db"],
    )
    call_count = {"n": 0}

    def handler(event):
        call_count["n"] += 1

    consumer.subscribe(["sync"], handler)

    fixed_id = "11111111-2222-3333-4444-555555555555"
    producer.publish("mac", "sync", {"v": 1}, event_id=fixed_id)
    stats1 = consumer.poll_and_process()
    assert stats1.processed == 1
    assert call_count["n"] == 1

    # 2. Run: keine neuen Events; idempotency-Schutz greift fuer denselben File
    stats2 = consumer.poll_and_process()
    assert stats2.skipped_idempotent == 1
    assert stats2.processed == 0
    assert call_count["n"] == 1  # Handler nicht erneut aufgerufen


def test_dlq_after_3_failures(dirs):
    """Handler raised IMMER -> nach 3 Fails landet Event in DLQ."""
    producer = OutboxProducer(
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        machine_id="mac",
        state_db=dirs["producer_db"],
    )
    consumer = OutboxConsumer(
        consumer_id="test",
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        dlq_dir=dirs["dlq"],
        state_db=dirs["consumer_db"],
    )

    def failing_handler(event):
        raise RuntimeError("simulated failure")

    consumer.subscribe(["bad"], failing_handler)

    producer.publish("mac", "bad", {"x": 1})

    # Run 1: fail (retry=1)
    s1 = consumer.poll_and_process()
    assert s1.failed == 1
    assert s1.moved_to_dlq == 0

    # Run 2: fail (retry=2)
    s2 = consumer.poll_and_process()
    assert s2.failed == 1
    assert s2.moved_to_dlq == 0

    # Run 3: fail (retry=3) -> DLQ
    s3 = consumer.poll_and_process()
    assert s3.failed == 1
    assert s3.moved_to_dlq == 1

    dlq_files = list(dirs["dlq"].glob("*.dlq.json"))
    assert len(dlq_files) == 1
    with open(dlq_files[0], "r", encoding="utf-8") as f:
        dlq_data = json.load(f)
    assert dlq_data["retry_count"] == 3
    assert "simulated failure" in dlq_data["reason"]


def test_cross_machine_simulation(dirs, tmp_path):
    """2 Producer (mac+windows), 1 Consumer: alle 6 Events werden verarbeitet."""
    p_mac = OutboxProducer(
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        machine_id="mac",
        state_db=tmp_path / "p_mac.db",
    )
    p_win = OutboxProducer(
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        machine_id="windows",
        state_db=tmp_path / "p_win.db",
    )
    consumer = OutboxConsumer(
        consumer_id="kmo-central",
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        dlq_dir=dirs["dlq"],
        state_db=dirs["consumer_db"],
    )

    machines_seen = set()

    def handler(event):
        machines_seen.add(event.machine_id)

    consumer.subscribe(["sync"], handler)

    for i in range(3):
        p_mac.publish("mac", "sync", {"i": i})
        p_win.publish("windows", "sync", {"i": i})

    stats = consumer.poll_and_process()
    assert stats.polled == 6
    assert stats.processed == 6
    assert machines_seen == {"mac", "windows"}

    # Sequenzen pro Machine sind getrennt-monoton
    mac_files = sorted(dirs["outbox"].glob("mac-sync-*.json"))
    win_files = sorted(dirs["outbox"].glob("windows-sync-*.json"))
    assert len(mac_files) == 3
    assert len(win_files) == 3


def test_topic_filtering(dirs):
    """Consumer ignoriert Events von nicht-subscribed Topics."""
    producer = OutboxProducer(
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        machine_id="mac",
        state_db=dirs["producer_db"],
    )
    consumer = OutboxConsumer(
        consumer_id="test",
        outbox_dir=dirs["outbox"],
        ack_dir=dirs["ack"],
        dlq_dir=dirs["dlq"],
        state_db=dirs["consumer_db"],
    )
    received = []
    consumer.subscribe(["sync"], lambda e: received.append(e))

    producer.publish("mac", "sync", {"a": 1})
    producer.publish("mac", "metrics", {"b": 2})  # NICHT subscribed
    producer.publish("mac", "sync", {"c": 3})

    stats = consumer.poll_and_process()
    assert stats.processed == 2
    assert len(received) == 2
    assert all(e.topic == "sync" for e in received)


# [CRUX-MK]
