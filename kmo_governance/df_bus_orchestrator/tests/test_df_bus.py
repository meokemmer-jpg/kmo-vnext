"""KMO DF-Bus-Orchestrator Tests [CRUX-MK].

Welle-10 Phase-6.4 Subagent-F. 12 Pflicht-Tests fuer DFMessageBus + DFRoutingTable +
DFCircuitBreakerPool + DFOrchestrator + DFConsensusVoter.
"""

from __future__ import annotations

import dataclasses

import pytest

from kmo_governance.apaleo_adapter.apaleo_adapter import ApaleoCircuitBreaker
from kmo_governance.df_bus_orchestrator import (
    DFCircuitBreakerPool,
    DFConsensusVoter,
    DFMessage,
    DFMessageBus,
    DFMessageType,
    DFOrchestrator,
    DFRoutingTable,
    DFVoteRecord,
)
from kmo_governance.df_bus_orchestrator.df_bus_orchestrator import make_df_message


# ---------------- Fixtures ----------------


@pytest.fixture
def fixed_clock():
    """Mutable clock for deterministic TTL/heartbeat testing."""
    state = {"t": 1_000_000.0}

    def clock():
        return state["t"]

    def tick(dt):
        state["t"] += dt

    clock.tick = tick  # type: ignore[attr-defined]
    return clock


# ---------------- 1) DFMessage frozen-dataclass ----------------


def test_df_message_frozen_dataclass():
    """DFMessage ist frozen-dataclass (immutable, deterministischer provenance_hash)."""
    msg1 = make_df_message(
        df_id="df-A",
        msg_type=DFMessageType.HEARTBEAT,
        payload={"k": "v"},
        ttl_s=60.0,
        clock=lambda: 1000.0,
    )
    msg2 = make_df_message(
        df_id="df-A",
        msg_type=DFMessageType.HEARTBEAT,
        payload={"k": "v"},
        ttl_s=60.0,
        clock=lambda: 1000.0,
    )
    # Frozen: cannot mutate
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg1.df_id = "df-B"  # type: ignore[misc]
    # Determinismus: gleiche Inputs -> gleicher Hash
    assert msg1.provenance_hash == msg2.provenance_hash
    assert len(msg1.provenance_hash) == 64  # SHA256 hex
    # is_expired Logik
    assert not msg1.is_expired(now=1030.0)
    assert msg1.is_expired(now=1100.0)


# ---------------- 2) DFMessageBus publish/subscribe ----------------


def test_message_bus_publish_subscribe(fixed_clock):
    """Subscribe + publish liefert Message via Callback + get_pending."""
    bus = DFMessageBus(clock=fixed_clock)
    received = []

    def cb(msg: DFMessage):
        received.append(msg)

    sub_id = bus.subscribe("df-A", cb)
    assert isinstance(sub_id, str) and len(sub_id) == 32

    msg = make_df_message(
        df_id="orchestrator",
        msg_type=DFMessageType.DISPATCH,
        payload={"task": "x"},
        ttl_s=60.0,
        clock=fixed_clock,
    )
    assert bus.publish(msg, target_df_id="df-A") is True
    assert len(received) == 1
    assert received[0].provenance_hash == msg.provenance_hash

    pending = bus.get_pending("df-A")
    assert len(pending) == 1
    assert pending[0].payload == {"task": "x"}

    # unsubscribe -> kein neuer Callback
    assert bus.unsubscribe(sub_id) is True
    bus.publish(msg, target_df_id="df-A")
    assert len(received) == 1  # unchanged


# ---------------- 3) DFMessageBus TTL-expiry ----------------


def test_message_bus_ttl_expiry(fixed_clock):
    """get_pending filtert expired Messages; prune_expired entfernt sie endgueltig."""
    bus = DFMessageBus(clock=fixed_clock)
    msg = make_df_message(
        df_id="o",
        msg_type=DFMessageType.HEARTBEAT,
        payload={},
        ttl_s=10.0,
        clock=fixed_clock,
    )
    bus.publish(msg, target_df_id="df-A")
    assert len(bus.get_pending("df-A")) == 1

    # Vor TTL: still present
    fixed_clock.tick(5)
    assert len(bus.get_pending("df-A")) == 1

    # Nach TTL: filtered
    fixed_clock.tick(10)
    assert len(bus.get_pending("df-A")) == 0

    # prune entfernt physisch
    removed = bus.prune_expired()
    assert removed == 1
    # auch wenn wir den Clock zurueckdrehen wuerden -- prune hat geloescht
    assert len(bus.get_pending("df-A")) == 0


# ---------------- 4) DFRoutingTable capability lookup ----------------


def test_routing_table_capability_lookup(fixed_clock):
    """find_by_capability liefert alle DFs mit gegebener capability."""
    rt = DFRoutingTable(clock=fixed_clock)
    rt.register_df("df-A", ["pricing", "audit"])
    rt.register_df("df-B", ["pricing"])
    rt.register_df("df-C", ["audit"])

    pricing = sorted(rt.find_by_capability("pricing"))
    assert pricing == ["df-A", "df-B"]

    audit = sorted(rt.find_by_capability("audit"))
    assert audit == ["df-A", "df-C"]

    # Unknown capability
    assert rt.find_by_capability("nonexistent") == []

    # all_dfs
    assert sorted(rt.all_dfs()) == ["df-A", "df-B", "df-C"]


# ---------------- 5) DFRoutingTable heartbeat alive ----------------


def test_routing_table_heartbeat_alive_check(fixed_clock):
    """is_alive prueft Heartbeat innerhalb timeout_s."""
    rt = DFRoutingTable(clock=fixed_clock)
    rt.register_df("df-A", ["x"])

    # Frisch registriert -> alive
    assert rt.is_alive("df-A", timeout_s=60) is True

    # Nach 30s ohne Heartbeat -> noch alive (timeout 60)
    fixed_clock.tick(30)
    assert rt.is_alive("df-A", timeout_s=60) is True

    # Nach 70s ohne Heartbeat -> NICHT alive
    fixed_clock.tick(40)  # cumulative 70s
    assert rt.is_alive("df-A", timeout_s=60) is False

    # Heartbeat refresht
    assert rt.heartbeat("df-A") is True
    assert rt.is_alive("df-A", timeout_s=60) is True

    # Unbekannte DF
    assert rt.is_alive("df-UNKNOWN", timeout_s=60) is False
    assert rt.heartbeat("df-UNKNOWN") is False


# ---------------- 6) DFCircuitBreakerPool per-DF isolation ----------------


def test_circuit_breaker_pool_per_df_isolation():
    """Jede DF hat eigenen Breaker; ein Open beeinflusst andere nicht."""
    pool = DFCircuitBreakerPool(failure_threshold=2, reset_timeout_s=30.0)
    breaker_a = pool.get_breaker("df-A")
    breaker_b = pool.get_breaker("df-B")
    assert breaker_a is not breaker_b
    # Idempotenz
    assert pool.get_breaker("df-A") is breaker_a

    # Trip df-A
    def fail():
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker_a.call(fail)
    # df-A jetzt OPEN
    assert breaker_a.get_state()["state"] == ApaleoCircuitBreaker.STATE_OPEN
    # df-B unverandert CLOSED
    assert breaker_b.get_state()["state"] == ApaleoCircuitBreaker.STATE_CLOSED

    # get_failed_dfs zeigt nur df-A
    assert pool.get_failed_dfs() == ["df-A"]

    # reset_all setzt beide zurueck
    assert pool.reset_all() == 2
    assert breaker_a.get_state()["state"] == ApaleoCircuitBreaker.STATE_CLOSED


# ---------------- 7) DFOrchestrator dispatch to capability ----------------


def test_orchestrator_dispatch_to_capability(fixed_clock):
    """dispatch routet an erste alive-DF mit target_capability; skips dead/failed."""
    orch = DFOrchestrator(clock=fixed_clock)
    received_a, received_b = [], []
    orch.register_df("df-A", ["pricing"], lambda m: received_a.append(m))
    orch.register_df("df-B", ["pricing"], lambda m: received_b.append(m))

    delivered = orch.dispatch(
        DFMessageType.DISPATCH,
        {"job": 1},
        target_capability="pricing",
        sender_df_id="orchestrator",
    )
    # Eine DF bekommt es (erste alive)
    assert len(delivered) == 1
    assert delivered[0] in {"df-A", "df-B"}
    total_received = len(received_a) + len(received_b)
    assert total_received == 1

    # Wenn df-A's breaker OPEN: dispatch geht zu df-B
    breaker_a = orch.breakers.get_breaker("df-A")
    for _ in range(5):
        try:
            breaker_a.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        except RuntimeError:
            pass
    assert breaker_a.get_state()["state"] == ApaleoCircuitBreaker.STATE_OPEN

    received_b.clear()
    received_a.clear()
    delivered2 = orch.dispatch(
        DFMessageType.DISPATCH,
        {"job": 2},
        target_capability="pricing",
        sender_df_id="orchestrator",
    )
    assert delivered2 == ["df-B"]
    assert len(received_b) == 1
    assert len(received_a) == 0

    # Keine alive-DF -> empty list
    fixed_clock.tick(120)  # alle DFs jetzt dead
    delivered3 = orch.dispatch(
        DFMessageType.DISPATCH,
        {"job": 3},
        target_capability="pricing",
        sender_df_id="orchestrator",
    )
    assert delivered3 == []


# ---------------- 8) DFOrchestrator broadcast to all ----------------


def test_orchestrator_broadcast_to_all(fixed_clock):
    """broadcast erreicht alle alive-DFs."""
    orch = DFOrchestrator(clock=fixed_clock)
    inbox = {"df-A": [], "df-B": [], "df-C": []}
    orch.register_df("df-A", ["x"], lambda m: inbox["df-A"].append(m))
    orch.register_df("df-B", ["y"], lambda m: inbox["df-B"].append(m))
    orch.register_df("df-C", ["z"], lambda m: inbox["df-C"].append(m))

    delivered = orch.broadcast(DFMessageType.BROADCAST, {"announce": True})
    assert sorted(delivered) == ["df-A", "df-B", "df-C"]
    assert len(inbox["df-A"]) == 1
    assert len(inbox["df-B"]) == 1
    assert len(inbox["df-C"]) == 1


# ---------------- 9) DFOrchestrator health summary ----------------


def test_orchestrator_health_summary(fixed_clock):
    """get_health_summary aggregiert alive/dead/failed/pending pro DF."""
    orch = DFOrchestrator(clock=fixed_clock)
    orch.register_df("df-A", ["x"], lambda m: None)
    orch.register_df("df-B", ["x"], lambda m: None)
    orch.register_df("df-C", ["y"], lambda m: None)

    # Pending: dispatch broadcast
    orch.broadcast(DFMessageType.HEARTBEAT, {"ping": True})

    # Open breaker on df-B
    breaker_b = orch.breakers.get_breaker("df-B")
    for _ in range(5):
        try:
            breaker_b.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        except RuntimeError:
            pass

    # Make df-C dead
    fixed_clock.tick(30)
    orch.routing.heartbeat("df-A")
    orch.routing.heartbeat("df-B")
    fixed_clock.tick(40)  # df-C now ~70s old, df-A/B ~40s
    orch.routing.heartbeat("df-A")
    orch.routing.heartbeat("df-B")
    # df-C now dead (last heartbeat was at registration ~70s ago)

    summary = orch.get_health_summary()
    assert summary["total_dfs"] == 3
    assert "df-A" in summary["alive_dfs"]
    assert "df-B" in summary["alive_dfs"]
    assert "df-C" in summary["dead_dfs"]
    assert "df-B" in summary["failed_dfs"]
    assert summary["pending_per_df"]["df-A"] >= 1
    assert summary["pending_per_df"]["df-B"] >= 1
    assert summary["pending_per_df"]["df-C"] >= 1
    assert "timestamp" in summary


# ---------------- 10) DFConsensusVoter threshold reached ----------------


def test_consensus_voter_threshold_reached(fixed_clock):
    """is_consensus_reached -> True wenn yes-votes Threshold erfuellen."""
    voter = DFConsensusVoter(timeout_after_s=60.0, clock=fixed_clock)
    df_ids = ["df-1", "df-2", "df-3", "df-4"]
    assert voter.request_vote("prop-A", df_ids, threshold=0.5) is True
    # Doppelte request_vote -> False
    assert voter.request_vote("prop-A", df_ids, threshold=0.5) is False

    # Initial: outstanding > 0 -> None
    assert voter.is_consensus_reached("prop-A") is None

    voter.record_vote("prop-A", "df-1", True)
    voter.record_vote("prop-A", "df-2", True)
    # 2 yes von 4 = 50% -> reached (>=)
    assert voter.is_consensus_reached("prop-A") is True

    counts = voter.get_vote_count("prop-A")
    assert counts == {"yes": 2, "no": 0, "outstanding": 2, "total": 4}


# ---------------- 11) DFConsensusVoter threshold not reached ----------------


def test_consensus_voter_threshold_not_reached(fixed_clock):
    """is_consensus_reached -> False wenn zu viele No-Votes Threshold unmoeglich machen."""
    voter = DFConsensusVoter(timeout_after_s=60.0, clock=fixed_clock)
    df_ids = ["df-1", "df-2", "df-3", "df-4"]
    voter.request_vote("prop-B", df_ids, threshold=0.75)  # need 3 yes

    voter.record_vote("prop-B", "df-1", False)
    voter.record_vote("prop-B", "df-2", False)
    # 2 no, 2 outstanding -> max yes = 2 < need 3 -> definitiv False
    assert voter.is_consensus_reached("prop-B") is False

    # Idempotenz: redundanter Vote ignoriert
    assert voter.record_vote("prop-B", "df-1", True) is False
    counts = voter.get_vote_count("prop-B")
    assert counts == {"yes": 0, "no": 2, "outstanding": 2, "total": 4}

    # Unbekannter df_id im Vote -> False
    assert voter.record_vote("prop-B", "df-UNKNOWN", True) is False
    # Unbekannte proposal -> False / None
    assert voter.record_vote("prop-UNKNOWN", "df-1", True) is False
    assert voter.is_consensus_reached("prop-UNKNOWN") is None


# ---------------- 12) DFConsensusVoter timeout handling ----------------


def test_consensus_voter_timeout_handling(fixed_clock):
    """Timeout setzt is_consensus_reached auf False auch wenn outstanding > 0."""
    voter = DFConsensusVoter(timeout_after_s=10.0, clock=fixed_clock)
    df_ids = ["df-1", "df-2", "df-3"]
    voter.request_vote("prop-T", df_ids, threshold=0.66)  # need 2 yes

    voter.record_vote("prop-T", "df-1", True)
    # 1 yes, 0 no, 2 outstanding -> noch unentschieden
    assert voter.is_consensus_reached("prop-T") is None

    # Timeout
    fixed_clock.tick(15)
    # Outstanding aber expired -> False
    assert voter.is_consensus_reached("prop-T") is False

    # DFVoteRecord ist frozen
    record = voter._votes["prop-T"][0]
    assert isinstance(record, DFVoteRecord)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.vote = False  # type: ignore[misc]


# CRUX-MK
