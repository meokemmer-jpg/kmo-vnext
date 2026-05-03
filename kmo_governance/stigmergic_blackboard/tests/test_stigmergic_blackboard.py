"""KMO Stigmergic-Blackboard Tests [CRUX-MK].

Spec: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-2.2.

Pflicht (8):
- test_blackboard_append_only_no_updates
- test_blackboard_cross_machine_consistency
- test_stigmergy_path_strength_decay
- test_stigmergy_reinforcement_compound_effect
- test_sandpile_redistribution_4_neighbors
- test_sandpile_avalanche_self_organized_critical
- test_subscriber_long_poll_efficiency
- test_blackboard_ttl_garbage_collection
"""

from __future__ import annotations

import time

import pytest

from kmo_governance.stigmergic_blackboard import (
    AvalancheEvent,
    BlackboardStore,
    SandpileLoadDistributor,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def store(tmp_path):
    return BlackboardStore(
        db_path=tmp_path / "blackboard.db",
        machine_id="test-host-1",
        decay_lambda=0.1,
    )


# ---------------- Blackboard Pflicht-Tests ----------------


def test_blackboard_append_only_no_updates(store):
    """append_only: each call creates a new event_id; no in-place mutation."""
    e1 = store.append("t1", "alarm", "df-A", payload={"x": 1})
    e2 = store.append("t1", "alarm", "df-B", payload={"x": 2})
    assert e1 != e2
    events = store.read_since("t1")
    assert len(events) == 2
    # Monotonic-seq strictly increasing
    seqs = [e.monotonic_seq for e in events]
    assert seqs == sorted(seqs)
    assert seqs[1] > seqs[0]


def test_blackboard_cross_machine_consistency(tmp_path):
    """Two stores with different machine_ids share the SQLite-WAL DB consistently."""
    db = tmp_path / "shared.db"
    s1 = BlackboardStore(db_path=db, machine_id="machine-A")
    s2 = BlackboardStore(db_path=db, machine_id="machine-B")
    s1.append("t1", "alarm", "df-on-A", payload={"src": "A"})
    s2.append("t1", "alarm", "df-on-B", payload={"src": "B"})
    events_seen_by_s1 = s1.read_since("t1")
    events_seen_by_s2 = s2.read_since("t1")
    assert len(events_seen_by_s1) == 2
    assert len(events_seen_by_s2) == 2
    machine_ids = {e.machine_id for e in events_seen_by_s1}
    assert machine_ids == {"machine-A", "machine-B"}


def test_stigmergy_path_strength_decay(store):
    """Single trail strength decays exponentially over time."""
    store.append("t1", "path-X", "df-A", payload={})
    s_now = store.stigmergy_strength("t1", "path-X")
    assert s_now == pytest.approx(1.0, rel=0.01)
    # Compute strength as if 50 seconds elapsed
    later = time.time() + 50.0
    s_later = store.stigmergy_strength("t1", "path-X", now=later)
    # decay = exp(-0.1 * 50) = exp(-5) ≈ 0.0067
    assert s_later < 0.05
    assert s_later > 0.0


def test_stigmergy_reinforcement_compound_effect(store):
    """Reinforcement appends new event -> total strength compounds."""
    e1 = store.append("t1", "path-X", "df-A", payload={"step": "init"})
    s1 = store.stigmergy_strength("t1", "path-X")
    store.reinforce("t1", "path-X", "df-B", original_event_id=e1)
    s2 = store.stigmergy_strength("t1", "path-X")
    assert s2 > s1
    assert s2 == pytest.approx(2.0, rel=0.05)  # 2 fresh events ≈ 2.0
    # Both events visible
    assert len(store.read_since("t1", topic="path-X")) == 2


def test_blackboard_ttl_garbage_collection(store):
    """gc_expired removes events whose ttl_until is in the past."""
    store.append("t1", "alarm", "df-A", ttl_sec=0.001)  # expires almost immediately
    store.append("t1", "alarm", "df-A", ttl_sec=600)    # long-lived
    store.append("t1", "alarm", "df-A", ttl_sec=None)   # no expiry
    time.sleep(0.05)
    deleted = store.gc_expired()
    assert deleted == 1
    remaining = store.read_since("t1")
    assert len(remaining) == 2


def test_blackboard_purge_tissue_gdpr(store):
    """purge_tissue cascade-deletes all events for that tissue."""
    store.append("t1", "alarm", "df-A")
    store.append("t1", "demand", "df-A")
    store.append("t2", "alarm", "df-A")
    deleted = store.purge_tissue("t1")
    assert deleted == 2
    assert store.count_for_tissue("t1") == 0
    assert store.count_for_tissue("t2") == 1


def test_blackboard_subscriber_long_poll_efficiency(store):
    """read_since with since_seq returns only NEW events (subscriber long-poll pattern)."""
    store.append("t1", "alarm", "df-A")
    store.append("t1", "alarm", "df-A")
    initial = store.read_since("t1")
    last_seen = initial[-1].monotonic_seq

    # No new events: empty result
    assert store.read_since("t1", since_seq=last_seen) == []

    # New event: only new returned
    store.append("t1", "alarm", "df-B")
    new_only = store.read_since("t1", since_seq=last_seen)
    assert len(new_only) == 1
    assert new_only[0].monotonic_seq > last_seen


def test_blackboard_topic_filter(store):
    """read_since with topic returns only matching topic events."""
    store.append("t1", "alarm", "df-A")
    store.append("t1", "demand", "df-A")
    store.append("t1", "alarm", "df-B")
    alarm_only = store.read_since("t1", topic="alarm")
    assert len(alarm_only) == 2
    assert all(e.topic == "alarm" for e in alarm_only)


# ---------------- Sandpile Pflicht-Tests ----------------


def test_sandpile_redistribution_4_neighbors():
    """4-neighbor topology: load > z_crit redistributes equally to 4 neighbors."""
    topology = {
        "center": ["n1", "n2", "n3", "n4"],
        "n1": [], "n2": [], "n3": [], "n4": [],  # boundary nodes
    }
    sp = SandpileLoadDistributor(topology, z_crit=4.0)
    # load 5 > 4 -> avalanche fires
    events = sp.increment_load("center", amount=5.0)
    assert len(events) == 1
    assert events[0].df_id == "center"
    assert events[0].redistribute_amount == pytest.approx(1.25)  # 5/4
    assert sp.get_load("center") == 0.0
    for n in ["n1", "n2", "n3", "n4"]:
        assert sp.get_load(n) == pytest.approx(1.25)


def test_sandpile_avalanche_self_organized_critical():
    """Cascade avalanche: redistribution can trigger neighbor over threshold."""
    topology = {
        "A": ["B"],
        "B": ["C"],
        "C": [],  # boundary
    }
    sp = SandpileLoadDistributor(topology, z_crit=2.0)
    # Pre-load B near threshold
    sp.increment_load("B", amount=1.5)  # B = 1.5, no avalanche (under 2)
    # A's avalanche pushes B over threshold -> chain
    events = sp.increment_load("A", amount=3.0)  # A = 3 > 2, redistributes 3 to B
    assert len(events) >= 2  # at least A then B
    assert events[0].df_id == "A"
    assert any(e.df_id == "B" for e in events)


def test_sandpile_no_avalanche_below_threshold():
    """Loads below z_crit do not trigger avalanche."""
    topology = {"A": ["B"], "B": []}
    sp = SandpileLoadDistributor(topology, z_crit=10.0)
    events = sp.increment_load("A", amount=5.0)
    assert events == []
    assert sp.get_load("A") == 5.0


def test_sandpile_constructor_validation():
    with pytest.raises(ValueError):
        SandpileLoadDistributor({"A": []}, z_crit=0)
    sp = SandpileLoadDistributor({"A": []})
    with pytest.raises(KeyError):
        sp.increment_load("UNKNOWN", amount=1)
    with pytest.raises(ValueError):
        sp.increment_load("A", amount=-1)


# ---------------- Patch C2: Blackboard atomar BEGIN IMMEDIATE (Welle-9β.5) ----------------


def test_blackboard_concurrent_writers_unique_seq_constraint(tmp_path):
    """Two stores writing same tissue concurrently: UNIQUE-Constraint enforced.

    Verifies BEGIN IMMEDIATE Lock prevents seq-collision; UNIQUE-Index would
    raise IntegrityError as safety-net (caught + retried in append()).
    """
    db = tmp_path / "concurrent.db"
    s1 = BlackboardStore(db_path=db, machine_id="m1")
    s2 = BlackboardStore(db_path=db, machine_id="m2")
    # Sequential writes from 2 stores: seqs MUST be unique (1, 2, 3, 4, ...)
    s1.append("t1", "alarm", "df-A")
    s2.append("t1", "alarm", "df-B")
    s1.append("t1", "alarm", "df-C")
    s2.append("t1", "alarm", "df-D")
    events = s1.read_since("t1")
    seqs = [e.monotonic_seq for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # all unique
    assert seqs == [1, 2, 3, 4]


# ---------------- Patch C3: Sandpile-Persistence (Welle-9β.5) ----------------


def test_sandpile_persistence_via_blackboard(tmp_path):
    """Sandpile-Avalanches are checkpointed to BlackboardStore + restorable."""
    db = tmp_path / "sandpile_bb.db"
    bb = BlackboardStore(db_path=db, machine_id="test")
    topology = {"A": ["B", "C", "D", "E"], "B": [], "C": [], "D": [], "E": []}
    sp = SandpileLoadDistributor(
        topology, z_crit=4.0,
        blackboard=bb, tissue_id="tissue-pricing", df_id_self="sp-controller",
    )
    sp.increment_load("A", amount=5.0)  # avalanche fires
    # Avalanche persisted in blackboard
    events = bb.read_since("tissue-pricing")
    avalanche_events = [e for e in events if e.topic.startswith("sandpile-avalanche:")]
    assert len(avalanche_events) == 1
    payload = avalanche_events[0].payload
    assert payload["df_id"] == "A"
    assert payload["redistribute_amount"] == pytest.approx(1.25)

    # Simulate restart: new SandpileLoadDistributor, replay from blackboard
    sp_new = SandpileLoadDistributor(
        topology, z_crit=4.0,
        blackboard=bb, tissue_id="tissue-pricing", df_id_self="sp-controller",
    )
    restored = sp_new.restore_state_from_blackboard()
    assert restored == 1
    assert len(sp_new.avalanche_log) == 1
    assert sp_new.avalanche_log[0].df_id == "A"


def test_sandpile_persistence_requires_tissue_id_and_df_id_self():
    """blackboard checkpointing requires tissue_id + df_id_self."""
    bb = BlackboardStore(db_path=":memory:")
    with pytest.raises(ValueError):
        SandpileLoadDistributor({"A": []}, blackboard=bb)
    with pytest.raises(ValueError):
        SandpileLoadDistributor({"A": []}, blackboard=bb, tissue_id="t1")
