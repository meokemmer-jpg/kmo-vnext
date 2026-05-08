"""Familien-Audit-Bus Tests (Cape-Coral-Vault Lymphatic-Pattern) [CRUX-MK]

Pflicht-Tests (12+):
1. Atomic-Write
2. Happy-Path approved
3. Veto durch Consent-Berechtigte
4. Info-Only-Mitglied (kein Veto)
5. Idempotency
6. Custom-Filter-Func (K_0-Schwelle)
7. JSONL-Append (rules/audit-trail.md §1)
8. Markdown-Card mit Frontmatter
9. Multi-Domain Sequenzen monoton
10. Lymphatic-Verteilung (nur relevante Filter)
11. Ungueltige Domain abgewiesen
12. Sequenz-Counter persistent
13. Empty title rejected
14. Filter-empty-member-id rejected
15. Custom-Filter-Veto ohne Rationale = Filter-Error
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from familien_audit_bus import (  # noqa: E402
    FamilienAuditBus, FamilienDecisionEnvelope,
    DOMAIN_RELOCATION, DOMAIN_FINANCE, DOMAIN_HEALTH, DOMAIN_RELATIONS,
    atomic_write_json,
)
from familien_decision_filter import (  # noqa: E402
    FamilienDecisionFilter, FilterDecision,
    ACTION_APPROVE, ACTION_VETO, ACTION_INFO_ACKNOWLEDGED,
)
from familien_audit_persister import FamilienAuditPersister  # noqa: E402


@pytest.fixture
def dirs(tmp_path):
    return {
        "bus": tmp_path / "bus",
        "audit": tmp_path / "audit",
        "vault": tmp_path / "vault",
        "state_db": tmp_path / "bus_state.db",
    }


def _make_bus(dirs):
    return FamilienAuditBus(
        bus_dir=dirs["bus"], audit_dir=dirs["audit"], state_db=dirs["state_db"],
    )


def test_atomic_write_no_partial_file(tmp_path):
    """Test 1: Atomic-Write -> kein partial-write."""
    target = tmp_path / "atomic.json"
    atomic_write_json(target, {"key": "value", "n": 42})
    assert target.exists()
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"key": "value", "n": 42}
    assert list(tmp_path.glob(".tmp-*")) == []


def test_happy_path_decision_approved(dirs):
    """Test 2: Decision von Martin, Gerdi consent, default approve."""
    bus = _make_bus(dirs)
    bus.attach_persister(FamilienAuditPersister(vault_root=dirs["vault"]))
    bus.register_filter(FamilienDecisionFilter(
        member_id="martin", consent_domains=[DOMAIN_RELOCATION, DOMAIN_FINANCE],
    ))
    bus.register_filter(FamilienDecisionFilter(
        member_id="gerdi", consent_domains=[DOMAIN_RELOCATION, DOMAIN_FINANCE],
    ))
    envelope = bus.submit_decision(
        proposer_member_id="martin", domain=DOMAIN_RELOCATION,
        title="Cape-Coral-Move-2027", payload={"timeline": "2027-Q2", "rho": 250000},
        requires_consent=["gerdi"],
    )
    assert envelope.seq == 1 and envelope.domain == DOMAIN_RELOCATION

    stats = bus.process_pending()
    assert stats["polled"] == 1
    assert stats["processed"] == 1
    assert stats["approved_count"] == 1
    assert stats["vetoed_count"] == 0


def test_veto_by_consent_member_blocks_decision(dirs):
    """Test 3: Gerdi vetoes -> final_state == vetoed."""
    bus = _make_bus(dirs)
    bus.attach_persister(FamilienAuditPersister(vault_root=dirs["vault"]))

    def gerdi_veto(envelope):
        return FilterDecision(
            member_id="gerdi", decision_id=envelope.decision_id,
            action=ACTION_VETO, rationale="Q_0-Risiko-zu-hoch-Brueder-Beziehung",
        )

    bus.register_filter(FamilienDecisionFilter(member_id="martin"))
    bus.register_filter(FamilienDecisionFilter(
        member_id="gerdi", consent_domains=[DOMAIN_RELOCATION],
        custom_filter_func=gerdi_veto,
    ))
    bus.submit_decision(
        "martin", DOMAIN_RELOCATION, "Cape-Coral-Move-Now",
        {"timeline": "2026-Q3"}, requires_consent=["gerdi"],
    )

    stats = bus.process_pending()
    assert stats["processed"] == 1
    assert stats["vetoed_count"] == 1
    assert stats["approved_count"] == 0


def test_info_only_member_acknowledged(dirs):
    """Test 4: Sebastian info-only, kein Veto-Recht."""
    bus = _make_bus(dirs)
    bus.attach_persister(FamilienAuditPersister(vault_root=dirs["vault"]))
    bus.register_filter(FamilienDecisionFilter(member_id="martin"))
    bus.register_filter(FamilienDecisionFilter(
        member_id="sebastian", info_domains=[DOMAIN_RELOCATION, DOMAIN_RELATIONS],
    ))
    bus.submit_decision(
        "martin", DOMAIN_RELOCATION, "Cape-Coral-Move-Info",
        {}, info_only=["sebastian"],
    )
    stats = bus.process_pending()
    assert stats["processed"] == 1
    assert stats["approved_count"] == 1


def test_idempotent_double_process(dirs):
    """Test 5: process_pending() 2x: 2. Run skippt finalisierte."""
    bus = _make_bus(dirs)
    bus.register_filter(FamilienDecisionFilter(member_id="martin"))
    bus.submit_decision("martin", DOMAIN_HEALTH, "Routine-Bluttest", {})

    s1 = bus.process_pending()
    s2 = bus.process_pending()
    assert s1["processed"] == 1
    assert s2["processed"] == 0
    assert s2["skipped_finalized"] == 1


def test_custom_filter_func_k0_threshold(dirs):
    """Test 6: Martin custom-filter K_0-Schwelle 100k."""
    bus = _make_bus(dirs)

    def k0_filter(envelope):
        rho = envelope.payload.get("rho", 0)
        if rho > 100_000:
            return FilterDecision(
                member_id="martin", decision_id=envelope.decision_id,
                action=ACTION_VETO, rationale=f"K_0-Schwelle: rho={rho}",
            )
        return FilterDecision(
            member_id="martin", decision_id=envelope.decision_id,
            action=ACTION_APPROVE, rationale="K_0-eingehalten",
        )

    bus.register_filter(FamilienDecisionFilter(
        member_id="martin", consent_domains=[DOMAIN_FINANCE],
        custom_filter_func=k0_filter,
    ))
    bus.submit_decision("gerdi", DOMAIN_FINANCE, "kleiner",
                       {"rho": 50_000}, requires_consent=["martin"])
    bus.submit_decision("gerdi", DOMAIN_FINANCE, "grosser",
                       {"rho": 200_000}, requires_consent=["martin"])

    stats = bus.process_pending()
    assert stats["processed"] == 2
    assert stats["approved_count"] == 1
    assert stats["vetoed_count"] == 1


def test_audit_trail_jsonl_append(dirs):
    """Test 7: JSONL-Append, mehrere Decisions = mehrere Lines."""
    bus = _make_bus(dirs)
    bus.attach_persister(FamilienAuditPersister(vault_root=dirs["vault"]))
    bus.register_filter(FamilienDecisionFilter(member_id="martin"))
    for i in range(3):
        bus.submit_decision("martin", DOMAIN_HEALTH, f"Test-{i}", {})
    bus.process_pending()

    log_path = dirs["vault"] / "branch-hub/audit/familien-audit-log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    for line in lines:
        record = json.loads(line)
        assert record["action"] == "FAMILIEN-DECISION-FINALIZED"
        assert "decision_id" in record
        assert record["branch"] == "cape-coral-familien-audit-bus"


def test_markdown_decision_card_frontmatter(dirs):
    """Test 8: Markdown-Card mit Cape-Coral-Vault PARA-Frontmatter."""
    bus = _make_bus(dirs)
    bus.attach_persister(FamilienAuditPersister(vault_root=dirs["vault"]))
    bus.register_filter(FamilienDecisionFilter(
        member_id="martin", consent_domains=[DOMAIN_RELOCATION],
    ))
    bus.submit_decision("martin", DOMAIN_RELOCATION, "Cape-Coral-Move-Q3", {})
    bus.process_pending()

    dc_dir = dirs["vault"] / "projects/cape-coral-relocation/decision-cards"
    md_files = list(dc_dir.glob("DC-FAM-RELOCATION-*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "type: decision" in content
    assert "domain: cape-coral" in content
    assert "sub-domain: relocation" in content
    assert "crux-mk: true" in content
    assert "Cape-Coral-Move-Q3" in content
    assert "[CRUX-MK]" in content


def test_multi_domain_sequences_monotonic(dirs):
    """Test 9: Sequenzen pro Domain getrennt-monoton."""
    bus = _make_bus(dirs)
    bus.register_filter(FamilienDecisionFilter(member_id="martin"))
    e1 = bus.submit_decision("martin", DOMAIN_RELOCATION, "R1", {})
    e2 = bus.submit_decision("martin", DOMAIN_HEALTH, "H1", {})
    e3 = bus.submit_decision("martin", DOMAIN_RELOCATION, "R2", {})
    e4 = bus.submit_decision("martin", DOMAIN_HEALTH, "H2", {})
    assert e1.seq == 1 and e2.seq == 1
    assert e3.seq == 2 and e4.seq == 2


def test_lymphatic_distribution_only_relevant(dirs):
    """Test 10: Filter wird nur fuer relevante Decisions gerufen."""
    bus = _make_bus(dirs)
    seen = []

    def eltern_filter(envelope):
        seen.append(envelope.decision_id)
        return FilterDecision(
            member_id="eltern", decision_id=envelope.decision_id,
            action=ACTION_INFO_ACKNOWLEDGED,
        )

    bus.register_filter(FamilienDecisionFilter(member_id="martin"))
    bus.register_filter(FamilienDecisionFilter(
        member_id="eltern", custom_filter_func=eltern_filter,
    ))
    bus.submit_decision(
        "martin", DOMAIN_RELATIONS, "Familienfeier", {}, info_only=["eltern"]
    )
    bus.submit_decision("martin", DOMAIN_FINANCE, "Trade", {})
    bus.process_pending()
    assert len(seen) == 1


def test_invalid_domain_rejected(dirs):
    """Test 11: Ungueltige Domain raises ValueError."""
    bus = _make_bus(dirs)
    with pytest.raises(ValueError, match="domain"):
        bus.submit_decision("martin", "invalid-domain", "x", {})


def test_seq_counter_persistent_across_restart(dirs):
    """Test 12: Counter persistiert ueber Bus-Restart."""
    bus1 = _make_bus(dirs)
    bus1.register_filter(FamilienDecisionFilter(member_id="martin"))
    e1 = bus1.submit_decision("martin", DOMAIN_HEALTH, "H1", {})
    e2 = bus1.submit_decision("martin", DOMAIN_HEALTH, "H2", {})
    assert e1.seq == 1 and e2.seq == 2

    bus2 = _make_bus(dirs)
    bus2.register_filter(FamilienDecisionFilter(member_id="martin"))
    e3 = bus2.submit_decision("martin", DOMAIN_HEALTH, "H3", {})
    assert e3.seq == 3


def test_empty_title_rejected(dirs):
    """Test 13: Empty title raises ValueError."""
    bus = _make_bus(dirs)
    with pytest.raises(ValueError, match="title"):
        bus.submit_decision("martin", DOMAIN_HEALTH, "", {})


def test_filter_without_member_id_rejected():
    """Test 14: Filter mit empty member_id raises ValueError."""
    with pytest.raises(ValueError, match="member_id"):
        FamilienDecisionFilter(member_id="")


def test_custom_filter_veto_without_rationale(dirs):
    """Test 15: Custom-Filter mit veto+empty rationale = Filter-Error."""
    bus = _make_bus(dirs)

    def bad_veto(envelope):
        return FilterDecision(
            member_id="gerdi", decision_id=envelope.decision_id,
            action=ACTION_VETO, rationale="",
        )

    bus.register_filter(FamilienDecisionFilter(member_id="martin"))
    bus.register_filter(FamilienDecisionFilter(
        member_id="gerdi", consent_domains=[DOMAIN_RELOCATION],
        custom_filter_func=bad_veto,
    ))
    bus.submit_decision("martin", DOMAIN_RELOCATION, "Test", {},
                       requires_consent=["gerdi"])
    stats = bus.process_pending()
    assert any("filter-error" in e for e in stats["errors"])


# [CRUX-MK]
