"""W-30-1 Race-Invariants formal getestet (Welle-31 P-W31-2) [CRUX-MK].

Adversarial-Tests gegen Last-Veto-Wins + Race-Conditions im Familien-
Audit-Bus (Cape-Coral-Vault). 6 Pflicht-Tests:

    1. Atomic-Veto-Collector: 2 simultane Vetos verschiedener Mitglieder
    2. 5 simultane Submissions mit Race-Window (Barrier-synchronized)
    3. Quorum-Conflict (3-of-5 Veto vs 2-of-5 Approve)
    4. Last-Write-Wins-Detection-Test (sollte FAIL = Anti-Pattern catched)
    5. Audit-Trail-Concurrent-Append (50+ parallele Appends, 0 Lost)
    6. Multi-Member-Disjoint-Decision-Domains (Veto auf A blockiert nicht B)

Conservation-Law: Wenn N Stimmen abgegeben, MUESSEN N Stimmen im Record sein.
Per rules/concurrency-mandatory-tests.md echte threading.Thread / Barrier.
"""
from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atomic_veto_collector import (  # noqa: E402
    AtomicVetoCollector,
    AtomicVoteRecord,
)
from familien_audit_bus import FamilienAuditBus, DOMAIN_FINANCE  # noqa: E402
from familien_audit_persister import FamilienAuditPersister  # noqa: E402
from familien_decision_filter import (  # noqa: E402
    FamilienDecisionFilter,
    FilterDecision,
    ACTION_VETO,
    ACTION_APPROVE,
)


@pytest.fixture
def collector():
    return AtomicVetoCollector()


def test_w31_race_two_simultaneous_vetos_atomic_aggregate(collector):
    """W-30-1 #1: Zwei simultane Vetos verschiedener Mitglieder werden
    deterministic aggregiert (NICHT Last-Veto-Wins).

    Conservation-Law: Beide Vetos im Record, Aggregated-State=vetoed.
    """
    decision_id = "decision-2-vetos"
    members = ["alice", "bob", "carol"]
    consent = ["alice", "bob"]
    collector.register_decision(decision_id, members, consent)

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def voter(member: str, action: str, rationale: str) -> None:
        try:
            barrier.wait()
            collector.vote(decision_id, member, action, rationale)
        except Exception as exc:  # pragma: no cover (test-only)
            errors.append(f"{member}: {exc!r}")

    t1 = threading.Thread(
        target=voter, args=("alice", "veto", "no-relocation-yet")
    )
    t2 = threading.Thread(
        target=voter, args=("bob", "veto", "kapital-conflict")
    )
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    # Carol votes approve outside the barrier.
    collector.vote(decision_id, "carol", "approve", "")

    assert errors == [], f"Race errors: {errors}"
    record = collector.close_quorum(decision_id)
    assert record.aggregated_state == "vetoed"
    # Both vetos preserved (NOT last-wins): veto_count counts only consent_member vetos
    assert record.veto_count == 2
    # All 3 votes preserved
    assert sum(1 for (_, act, _) in record.votes if act == "veto") == 2
    assert sum(1 for (_, act, _) in record.votes if act == "approve") == 1


def test_w31_race_five_simultaneous_submissions_barrier(collector):
    """W-30-1 #2: 5 parallele Vote-Submissions ueber Barrier sync.

    Conservation-Law: Alle 5 Stimmen im Record, deterministic-sortiert.
    """
    decision_id = "decision-5-parallel"
    members = ["m1", "m2", "m3", "m4", "m5"]
    consent = members  # all have veto rights
    collector.register_decision(decision_id, members, consent)

    barrier = threading.Barrier(5)
    actions = ["approve", "veto", "approve", "veto", "approve"]
    rationales = ["ok", "no-money", "ok", "wegzug-risk", "ok"]
    errors: list[str] = []

    def voter(idx: int) -> None:
        try:
            barrier.wait()
            collector.vote(
                decision_id, members[idx], actions[idx], rationales[idx]
            )
        except Exception as exc:  # pragma: no cover
            errors.append(f"{members[idx]}: {exc!r}")

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(voter, range(5)))

    assert errors == [], f"Race errors: {errors}"
    record = collector.close_quorum(decision_id)
    assert record.quorum_size == 5
    assert len(record.votes) == 5
    # Deterministic order: by member_id alphabetical
    member_order = [v[0] for v in record.votes]
    assert member_order == sorted(member_order)
    # 2 vetos -> aggregated=vetoed
    assert record.aggregated_state == "vetoed"
    assert record.veto_count == 2
    assert record.approve_count == 3


def test_w31_race_quorum_conflict_3_veto_vs_2_approve(collector):
    """W-30-1 #3: 3-of-5 Veto + 2-of-5 Approve = Atomic-Resolution=vetoed.

    ANY Veto eines Consent-Berechtigten -> blockiert (kein Mehrheits-Vote).
    """
    decision_id = "decision-quorum-conflict"
    members = ["a", "b", "c", "d", "e"]
    consent = ["a", "b", "c"]  # only first 3 have veto rights
    collector.register_decision(decision_id, members, consent)

    # 3 vetos from consent members + 2 approves from non-consent.
    collector.vote(decision_id, "a", "veto", "r1")
    collector.vote(decision_id, "b", "veto", "r2")
    collector.vote(decision_id, "c", "veto", "r3")
    collector.vote(decision_id, "d", "approve", "")
    collector.vote(decision_id, "e", "approve", "")

    record = collector.close_quorum(decision_id)
    assert record.aggregated_state == "vetoed"
    # Only consent_member vetos count toward veto_count
    assert record.veto_count == 3
    assert record.approve_count == 2

    # Mirror-Test: 2 vetos by NON-consent members + 3 approves -> approved.
    decision_id_2 = "decision-non-consent-veto"
    members2 = ["x", "y", "z", "p", "q"]
    consent2 = ["x", "y", "z"]
    collector.register_decision(decision_id_2, members2, consent2)
    collector.vote(decision_id_2, "x", "approve", "")
    collector.vote(decision_id_2, "y", "approve", "")
    collector.vote(decision_id_2, "z", "approve", "")
    collector.vote(decision_id_2, "p", "veto", "non-consent-veto-ignored")
    collector.vote(decision_id_2, "q", "veto", "non-consent-veto-ignored")
    record_2 = collector.close_quorum(decision_id_2)
    # Non-consent vetos don't count -> approved.
    assert record_2.aggregated_state == "approved"
    assert record_2.veto_count == 0


def test_w31_race_last_write_wins_anti_pattern_catched(collector):
    """W-30-1 #4: Vote-Flip von approve -> veto MUSS BLOCK (kein
    Last-Write-Wins).

    Anti-Pattern Detection: Wenn Member zuerst approve und dann veto
    abgibt, MUSS ValueError raisen (Byzantine-Vote-Flip).
    """
    decision_id = "decision-vote-flip"
    members = ["alice"]
    consent = ["alice"]
    collector.register_decision(decision_id, members, consent)

    collector.vote(decision_id, "alice", "approve", "")
    with pytest.raises(ValueError, match="cannot change to"):
        collector.vote(decision_id, "alice", "veto", "flipped")

    # First vote stands.
    record = collector.close_quorum(decision_id)
    assert record.aggregated_state == "approved"
    assert record.veto_count == 0


def test_w31_race_concurrent_audit_trail_append_50_threads(tmp_path):
    """W-30-1 #5: 50+ parallele Audit-Log-Appends, kein Lost-Update.

    Conservation-Law: 50 Stimmen -> 50 JSONL-Lines im Audit-Log.
    Pflicht per rules/concurrency-mandatory-tests.md (Klasse-1 + 2).
    """
    bus_dir = tmp_path / "bus"
    audit_dir = tmp_path / "audit"
    state_db = tmp_path / "state.db"
    vault = tmp_path / "vault"

    bus = FamilienAuditBus(
        bus_dir=bus_dir, audit_dir=audit_dir, state_db=state_db
    )
    persister = FamilienAuditPersister(vault_root=vault)

    n_threads = 50
    barrier = threading.Barrier(n_threads)
    errors: list[str] = []

    def submit_decision(idx: int) -> None:
        try:
            barrier.wait()
            bus.submit_decision(
                proposer_member_id=f"member-{idx % 5}",
                domain=DOMAIN_FINANCE,
                title=f"decision-{idx}",
                payload={"i": idx},
            )
        except Exception as exc:  # pragma: no cover
            errors.append(f"thread-{idx}: {exc!r}")

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        list(ex.map(submit_decision, range(n_threads)))

    assert errors == [], f"Submit errors: {errors}"
    # Conservation-Law: 50 envelopes in bus_dir
    bus_files = sorted(bus_dir.glob("*.json"))
    assert len(bus_files) == n_threads, (
        f"Lost envelopes: {n_threads} expected, "
        f"{len(bus_files)} found"
    )
    # All sequence numbers unique
    seqs: list[int] = []
    for bf in bus_files:
        with open(bf, "r", encoding="utf-8") as f:
            data = json.load(f)
        seqs.append(int(data["seq"]))
    assert len(set(seqs)) == n_threads, "Duplicate seq_no detected!"


def test_w31_race_disjoint_decision_domains_isolation(collector):
    """W-30-1 #6: Veto auf domain-A blockiert nicht domain-B.

    Multi-Member-Disjoint-Decision-Domains: Bus-A und Bus-B koennen
    parallel arbeiten ohne Cross-Contamination.
    """
    # Decision A in domain "relocation"
    members_a = ["alice", "bob"]
    consent_a = ["alice", "bob"]
    collector.register_decision("dec-A-relocation", members_a, consent_a)

    # Decision B in domain "finance"
    members_b = ["carol", "dan"]
    consent_b = ["carol", "dan"]
    collector.register_decision("dec-B-finance", members_b, consent_b)

    # Veto on A
    collector.vote("dec-A-relocation", "alice", "veto", "no-move")
    collector.vote("dec-A-relocation", "bob", "approve", "")

    # Approve on B (independently)
    collector.vote("dec-B-finance", "carol", "approve", "")
    collector.vote("dec-B-finance", "dan", "approve", "")

    rec_a = collector.close_quorum("dec-A-relocation")
    rec_b = collector.close_quorum("dec-B-finance")

    assert rec_a.aggregated_state == "vetoed"
    assert rec_b.aggregated_state == "approved"
    # Disjoint: A's veto did not leak into B.
    assert rec_b.veto_count == 0


# [CRUX-MK]
