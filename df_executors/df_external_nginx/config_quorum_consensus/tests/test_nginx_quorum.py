"""Tests fuer NGINX Config Quorum-Consensus Module [CRUX-MK].

Coverage-Klassen:
- Validator: Parsing, Syntax-Errors, Normalisierung, Hash-Determinismus
- Quorum-Engine: 3-of-5 Threshold, TTL-Window, Equivocation-Detection, Race-Conditions
- Distributor: Atomic-Deploy, Rollback bei Failure, Healthcheck-Integration
- Threading: 50 parallele Validators, Concurrent-Vote-Submission

Pflicht: 15+ Tests inkl. threading.Thread fuer Race-Condition-Coverage.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from df_executors.df_external_nginx.config_quorum_consensus import (
    ConfigParseError,
    ConfigProposal,
    DistributionResult,
    NginxConfigDistributor,
    NginxConfigValidator,
    NginxQuorumEngine,
    QuorumDecision,
    RollbackReason,
    ValidatorVote,
)
from df_executors.df_external_nginx.config_quorum_consensus.nginx_config_validator import (
    FindingSeverity,
)
from df_executors.df_external_nginx.config_quorum_consensus.nginx_quorum_engine import (
    QuorumOutcome,
    ValidatorVerdict,
)


# ---------- Fixtures ----------


VALID_NGINX_CONFIG = """
events {
    worker_connections 1024;
}
http {
    upstream backend {
        server 10.0.0.1:8080;
        server 10.0.0.2:8080;
    }
    server {
        listen 80;
        server_name example.com;
        location / {
            proxy_pass http://backend;
        }
    }
}
"""

VALID_NGINX_CONFIG_2 = """
events {
    worker_connections 2048;
}
http {
    server {
        listen 443;
        location /api {
            proxy_pass https://api.example.com;
        }
    }
}
"""

INVALID_NGINX_NO_EVENTS = """
http {
    server {
        listen 80;
    }
}
"""

INVALID_NGINX_BAD_PROXY = """
events { worker_connections 1024; }
http {
    server {
        listen 80;
        location / { proxy_pass not-a-url; }
    }
}
"""

INVALID_NGINX_UNCLOSED = """
events {
    worker_connections 1024;
http {
    server {
        listen 80;
    }
}
"""


@pytest.fixture
def validator():
    return NginxConfigValidator()


@pytest.fixture
def fake_clock():
    """Mutable clock fuer deterministische TTL-Tests."""
    state = {"t": 1000.0}

    def now() -> float:
        return state["t"]

    def advance(dt: float) -> None:
        state["t"] += dt

    now.advance = advance  # type: ignore[attr-defined]
    return now


@pytest.fixture
def quorum_engine(fake_clock):
    return NginxQuorumEngine(
        cluster_size=5,
        quorum_threshold=3,
        vote_ttl_sec=30.0,
        clock=fake_clock,
    )


@pytest.fixture
def distributor(quorum_engine, fake_clock):
    deploy_log = []
    health_log = []

    def deploy_func(instance_id: str, config_source: str) -> bool:
        deploy_log.append((instance_id, config_source))
        return True

    def healthcheck_func(instance_id: str) -> bool:
        health_log.append(instance_id)
        return True

    dist = NginxConfigDistributor(
        quorum_engine=quorum_engine,
        instance_ids=["nginx-1", "nginx-2", "nginx-3", "nginx-4", "nginx-5"],
        deploy_func=deploy_func,
        healthcheck_func=healthcheck_func,
        clock=fake_clock,
    )
    dist._deploy_log = deploy_log  # type: ignore[attr-defined]
    dist._health_log = health_log  # type: ignore[attr-defined]
    return dist


# ---------- Validator Tests (5) ----------


def test_validator_parses_valid_config(validator):
    ast = validator.parse(VALID_NGINX_CONFIG)
    assert ast.name == "__root__"
    block_names = [b.name for b in ast.children]
    assert "events" in block_names
    assert "http" in block_names


def test_validator_rejects_unclosed_block(validator):
    with pytest.raises(ConfigParseError):
        validator.parse(INVALID_NGINX_UNCLOSED)


def test_validator_finds_missing_required_block(validator):
    findings = validator.validate(INVALID_NGINX_NO_EVENTS)
    blocking = [f for f in findings if f.is_blocking()]
    assert any("events" in f.message for f in blocking)


def test_validator_finds_invalid_proxy_pass(validator):
    findings = validator.validate(INVALID_NGINX_BAD_PROXY)
    blocking = [f for f in findings if f.is_blocking()]
    assert any("proxy_pass" in f.message for f in blocking)


def test_validator_hash_is_deterministic(validator):
    h1 = validator.config_hash(VALID_NGINX_CONFIG)
    # Add comments + extra whitespace -> same hash after normalization.
    altered = VALID_NGINX_CONFIG.replace("listen 80;", "# port comment\n        listen 80;")
    h2 = validator.config_hash(altered)
    assert h1 == h2
    h3 = validator.config_hash(VALID_NGINX_CONFIG_2)
    assert h1 != h3


# ---------- Quorum-Engine Tests (6) ----------


def test_quorum_engine_rejects_too_small_cluster():
    with pytest.raises(ValueError):
        NginxQuorumEngine(cluster_size=2, quorum_threshold=2)


def test_quorum_engine_rejects_non_majority_threshold():
    with pytest.raises(ValueError):
        NginxQuorumEngine(cluster_size=5, quorum_threshold=2)  # not strict-majority


def test_quorum_approves_at_threshold(quorum_engine):
    quorum_engine.submit_proposal("hash-A", "config-A")
    quorum_engine.submit_vote("hash-A", "v1", ValidatorVerdict.ACCEPT)
    quorum_engine.submit_vote("hash-A", "v2", ValidatorVerdict.ACCEPT)
    decision = quorum_engine.resolve("hash-A")
    assert decision.outcome == QuorumOutcome.PENDING
    quorum_engine.submit_vote("hash-A", "v3", ValidatorVerdict.ACCEPT)
    decision = quorum_engine.resolve("hash-A")
    assert decision.outcome == QuorumOutcome.APPROVED
    assert decision.accept_count == 3


def test_quorum_rejects_when_blocking_majority(quorum_engine):
    quorum_engine.submit_proposal("hash-B", "config-B")
    quorum_engine.submit_vote("hash-B", "v1", ValidatorVerdict.REJECT)
    quorum_engine.submit_vote("hash-B", "v2", ValidatorVerdict.REJECT)
    quorum_engine.submit_vote("hash-B", "v3", ValidatorVerdict.REJECT)
    decision = quorum_engine.resolve("hash-B")
    # 3 REJECTs > (5 - 3) = 2 -> blocking quorum.
    assert decision.outcome == QuorumOutcome.REJECTED


def test_quorum_last_vote_wins(quorum_engine):
    quorum_engine.submit_proposal("hash-C", "config-C")
    quorum_engine.submit_vote("hash-C", "v1", ValidatorVerdict.ACCEPT)
    quorum_engine.submit_vote("hash-C", "v1", ValidatorVerdict.REJECT)  # override
    proposal = quorum_engine._proposals["hash-C"]
    assert proposal.votes["v1"].verdict == ValidatorVerdict.REJECT


def test_quorum_ttl_expires_stale_votes(quorum_engine, fake_clock):
    quorum_engine.submit_proposal("hash-D", "config-D")
    quorum_engine.submit_vote("hash-D", "v1", ValidatorVerdict.ACCEPT)
    quorum_engine.submit_vote("hash-D", "v2", ValidatorVerdict.ACCEPT)
    fake_clock.advance(31.0)  # past TTL
    quorum_engine.submit_vote("hash-D", "v3", ValidatorVerdict.ACCEPT)
    decision = quorum_engine.resolve("hash-D")
    # v1+v2 stale, only v3 fresh -> 1 ACCEPT.
    assert decision.accept_count == 1
    # Proposal submitted at t=1000, now t>1031, total_active=1 < threshold=3 -> TIMEOUT.
    assert decision.outcome == QuorumOutcome.TIMEOUT


def test_quorum_detects_equivocation(quorum_engine):
    quorum_engine.submit_proposal("hash-E1", "configE1")
    quorum_engine.submit_proposal("hash-E2", "configE2")
    quorum_engine.submit_vote("hash-E1", "byzantine", ValidatorVerdict.ACCEPT)
    quorum_engine.submit_vote("hash-E2", "byzantine", ValidatorVerdict.ACCEPT)
    conflicting = quorum_engine.detect_equivocation("byzantine")
    assert len(conflicting) == 2
    assert "hash-E1" in conflicting
    assert "hash-E2" in conflicting


# ---------- Distributor Tests (3) ----------


def test_distributor_deploys_on_approved(distributor, quorum_engine):
    quorum_engine.submit_proposal("hash-X", "config-X")
    for v in ["v1", "v2", "v3"]:
        quorum_engine.submit_vote("hash-X", v, ValidatorVerdict.ACCEPT)
    result = distributor.distribute("hash-X", "config-X")
    assert result.success is True
    assert len(result.instances_deployed) == 5
    assert result.rollback_reason is None


def test_distributor_rolls_back_on_quorum_reject(distributor, quorum_engine):
    quorum_engine.submit_proposal("hash-Y", "config-Y")
    for v in ["v1", "v2", "v3"]:
        quorum_engine.submit_vote("hash-Y", v, ValidatorVerdict.REJECT)
    result = distributor.distribute("hash-Y", "config-Y")
    assert result.success is False
    assert result.rollback_reason == RollbackReason.QUORUM_REJECTED


def test_distributor_rolls_back_on_healthcheck_failure(quorum_engine, fake_clock):
    failing_hosts = {"nginx-3"}

    def deploy_func(iid, src):
        return True

    def healthcheck_func(iid):
        return iid not in failing_hosts

    dist = NginxConfigDistributor(
        quorum_engine=quorum_engine,
        instance_ids=["nginx-1", "nginx-2", "nginx-3", "nginx-4", "nginx-5"],
        deploy_func=deploy_func,
        healthcheck_func=healthcheck_func,
        clock=fake_clock,
    )
    quorum_engine.submit_proposal("hash-Z", "config-Z")
    for v in ["v1", "v2", "v3"]:
        quorum_engine.submit_vote("hash-Z", v, ValidatorVerdict.ACCEPT)
    result = dist.distribute("hash-Z", "config-Z")
    assert result.success is False
    assert result.rollback_reason == RollbackReason.POST_DEPLOY_HEALTHCHECK_FAILED


# ---------- Threading / Race-Condition Tests (3) ----------


def test_concurrent_vote_submission_no_lost_updates():
    """50 Threads voten parallel; jeder Vote muss ankommen."""
    engine = NginxQuorumEngine(cluster_size=51, quorum_threshold=26, vote_ttl_sec=60.0)
    engine.submit_proposal("hash-T", "config-T")
    n_threads = 50
    barrier = threading.Barrier(n_threads)
    errors: list[str] = []

    def vote(idx: int) -> None:
        try:
            barrier.wait(timeout=5.0)
            engine.submit_vote(
                "hash-T",
                f"validator-{idx}",
                ValidatorVerdict.ACCEPT,
            )
        except Exception as exc:  # pragma: no cover -- defensive
            errors.append(repr(exc))

    threads = [threading.Thread(target=vote, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    assert errors == []
    decision = engine.resolve("hash-T")
    assert decision.accept_count == n_threads


def test_concurrent_proposal_submission_idempotent():
    """Mehrere Threads submitten gleichen config_hash -> nur 1 Proposal angelegt."""
    engine = NginxQuorumEngine()
    n_threads = 20
    barrier = threading.Barrier(n_threads)
    proposals: list[ConfigProposal] = []
    proposals_lock = threading.Lock()

    def submit_proposal_thread(idx: int) -> None:
        barrier.wait(timeout=5.0)
        p = engine.submit_proposal("hash-shared", "shared-config")
        with proposals_lock:
            proposals.append(p)

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        futs = [ex.submit(submit_proposal_thread, i) for i in range(n_threads)]
        for f in futs:
            f.result(timeout=10.0)
    # All threads got the *same* proposal-instance (idempotent).
    first = proposals[0]
    assert all(p is first for p in proposals)


def test_byzantine_validator_blocked_by_threshold():
    """1 Byzantine-Validator (REJECT) kann 4 ACCEPT-Validators nicht blocken (3-of-5 ACCEPT win)."""
    engine = NginxQuorumEngine(cluster_size=5, quorum_threshold=3, vote_ttl_sec=60.0)
    engine.submit_proposal("hash-B-attack", "config")
    n_acceptors = 4
    barrier = threading.Barrier(n_acceptors + 1)
    errors: list[str] = []

    def acceptor_vote(idx: int) -> None:
        try:
            barrier.wait(timeout=5.0)
            engine.submit_vote(
                "hash-B-attack",
                f"honest-{idx}",
                ValidatorVerdict.ACCEPT,
            )
        except Exception as exc:  # pragma: no cover
            errors.append(repr(exc))

    def byzantine_vote() -> None:
        try:
            barrier.wait(timeout=5.0)
            engine.submit_vote(
                "hash-B-attack",
                "byzantine-1",
                ValidatorVerdict.REJECT,
            )
        except Exception as exc:  # pragma: no cover
            errors.append(repr(exc))

    threads = [
        threading.Thread(target=acceptor_vote, args=(i,))
        for i in range(n_acceptors)
    ] + [threading.Thread(target=byzantine_vote)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    assert errors == []
    decision = engine.resolve("hash-B-attack")
    assert decision.accept_count == n_acceptors
    assert decision.reject_count == 1
    assert decision.outcome == QuorumOutcome.APPROVED  # 4 ACCEPT >= 3 threshold wins


# ---------- Integration Test (1) ----------


def test_end_to_end_validate_quorum_distribute(validator, distributor, quorum_engine):
    """Vollstaendiger Pfad: parse -> validate -> hash -> quorum-vote -> distribute."""
    findings = validator.validate(VALID_NGINX_CONFIG)
    blocking = [f for f in findings if f.severity == FindingSeverity.ERROR]
    assert blocking == []
    cfg_hash = validator.config_hash(VALID_NGINX_CONFIG)
    quorum_engine.submit_proposal(cfg_hash, VALID_NGINX_CONFIG)
    for v in ["nginx-validator-1", "nginx-validator-2", "nginx-validator-3"]:
        quorum_engine.submit_vote(cfg_hash, v, ValidatorVerdict.ACCEPT)
    decision = quorum_engine.resolve(cfg_hash)
    assert decision.outcome == QuorumOutcome.APPROVED
    result = distributor.distribute(cfg_hash, VALID_NGINX_CONFIG)
    assert result.success is True
    assert len(result.instances_deployed) == 5


# CRUX-MK
