"""Familien-Audit-Bus (Domain-Adapter ueber Lymphatic-Core) [CRUX-MK]

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

The Bus is a **Domain-Adapter** combining:
- `lymphatic_core.evaluate_envelope` + `aggregate_veto`  (Pattern-Core)
- 5-Domain-Whitelist (Cape-Coral)                        (Extension)
- SQLite-backed seq-counter + finalized-set              (Extension)
- Audit-Persister attach (Cape-Coral-Vault PARA)         (Extension)
- Proposer/Consent/Info-Only relevance axes              (Extension)

Pattern-Reuse aus kmo_governance/outbox-pattern: atomic_write_json,
EventEnvelope-Style.

Spec: Welle-30 W-30-1 (Hotel/Trading -> Cape-Coral-Vault Familien-Verwaltung).
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from lymphatic_core import (
    FINAL_VETOED,
    aggregate_veto,
    evaluate_envelope,
)

if TYPE_CHECKING:
    from familien_decision_filter import FamilienDecisionFilter, FilterDecision
    from familien_audit_persister import FamilienAuditPersister


# Familien-Decision-Domains (Domain-Extension: 5-Domain-Whitelist)
DOMAIN_RELOCATION = "relocation"  # Cape-Coral-Move, Wegzugssteuer, E-2 Visa
DOMAIN_HEALTH = "health"          # Gesundheits-Decision
DOMAIN_EDUCATION = "education"    # Schule, Ausbildung
DOMAIN_FINANCE = "finance"        # Familien-Kapital (K_0)
DOMAIN_RELATIONS = "relations"    # Brueder/Eltern (Q_0)

VALID_DOMAINS = frozenset({
    DOMAIN_RELOCATION, DOMAIN_HEALTH, DOMAIN_EDUCATION,
    DOMAIN_FINANCE, DOMAIN_RELATIONS,
})


@dataclass
class FamilienDecisionEnvelope:
    """Domain-Envelope (Cape-Coral-spezifisch)."""

    decision_id: str
    proposer_member_id: str
    domain: str
    seq: int
    timestamp: float
    title: str
    payload: dict
    requires_consent: list = field(default_factory=list)
    info_only: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FamilienDecisionEnvelope":
        return cls(**d)

    def filename(self) -> str:
        short_id = self.decision_id.split("-")[0]
        return f"{self.domain}-{self.seq:08d}-{short_id}.json"


def atomic_write_json(target: Path, data: dict) -> None:
    """Atomic-Write: tempfile + os.replace. Reuse aus outbox-pattern."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent), prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


class FamilienAuditBus:
    """Lymphatic-Bus Domain-Adapter (Cape-Coral).

    Pattern-Core ist `lymphatic_core` (evaluate_envelope + aggregate_veto).
    Diese Klasse fuegt Cape-Coral-spezifische Logik hinzu: 5-Domain-Whitelist,
    Multi-Axis-Relevance (proposer/consent/info-only), SQLite-State,
    Persister-Attach.
    """

    def __init__(
        self,
        bus_dir: Path,
        audit_dir: Path,
        state_db: Path | None = None,
    ):
        self.bus_dir = Path(bus_dir)
        self.audit_dir = Path(audit_dir)
        self.bus_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        if state_db is None:
            state_db = (
                Path.home() / "Library" / "Application Support"
                / "kmo-cape-coral" / "familien-audit-bus.db"
            )
        self.state_db = Path(state_db)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        self._filters: dict = {}
        self._persister = None

    def _init_db(self) -> None:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS seq_counter (
                    domain TEXT NOT NULL PRIMARY KEY,
                    last_seq INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS processed_decisions (
                    decision_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    finalized_at REAL NOT NULL,
                    final_state TEXT NOT NULL,
                    filter_count INTEGER NOT NULL,
                    veto_count INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain ON processed_decisions(domain)"
            )
            conn.commit()

    def _next_seq(self, domain: str) -> int:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seq_counter (domain, last_seq) VALUES (?, 0)",
                (domain,),
            )
            conn.execute(
                "UPDATE seq_counter SET last_seq = last_seq + 1 WHERE domain = ?",
                (domain,),
            )
            cur = conn.execute(
                "SELECT last_seq FROM seq_counter WHERE domain = ?", (domain,)
            )
            row = cur.fetchone()
            conn.commit()
            return int(row[0])

    def register_filter(self, member_filter) -> None:
        """Registriert Lymphatic-Knoten (Filter pro Familien-Mitglied)."""
        if not member_filter.member_id:
            raise ValueError("member_filter.member_id must be non-empty")
        self._filters[member_filter.member_id] = member_filter

    def attach_persister(self, persister) -> None:
        """Haengt Audit-Trail-Persister an (JSONL + Markdown)."""
        self._persister = persister

    def submit_decision(
        self,
        proposer_member_id: str,
        domain: str,
        title: str,
        payload: dict,
        requires_consent: list | None = None,
        info_only: list | None = None,
        decision_id: str | None = None,
    ) -> FamilienDecisionEnvelope:
        """Reicht Familien-Decision in Bus ein (atomar persistiert)."""
        if domain not in VALID_DOMAINS:
            raise ValueError(f"domain {domain!r} not in {VALID_DOMAINS}")
        if not title:
            raise ValueError("title must be non-empty")
        if not proposer_member_id:
            raise ValueError("proposer_member_id must be non-empty")

        envelope = FamilienDecisionEnvelope(
            decision_id=decision_id or str(uuid.uuid4()),
            proposer_member_id=proposer_member_id,
            domain=domain,
            seq=self._next_seq(domain),
            timestamp=time.time(),
            title=title,
            payload=payload,
            requires_consent=list(requires_consent or []),
            info_only=list(info_only or []),
        )
        atomic_write_json(self.bus_dir / envelope.filename(), envelope.to_dict())
        return envelope

    def _is_finalized(self, decision_id: str) -> bool:
        with sqlite3.connect(self.state_db) as conn:
            cur = conn.execute(
                "SELECT 1 FROM processed_decisions WHERE decision_id = ?",
                (decision_id,),
            )
            return cur.fetchone() is not None

    def _record_finalized(self, envelope, final_state, filter_count, veto_count) -> None:
        with sqlite3.connect(self.state_db) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO processed_decisions
                   (decision_id, domain, seq, finalized_at, final_state, filter_count, veto_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    envelope.decision_id, envelope.domain, envelope.seq,
                    time.time(), final_state, filter_count, veto_count,
                ),
            )
            conn.commit()

    # --- Domain-Extension: relevance + veto-eligibility callbacks ---

    @staticmethod
    def _relevance(node_id: str, envelope) -> bool:
        """Cape-Coral Multi-Axis-Relevance (Domain-Extension)."""
        return (
            node_id == envelope.proposer_member_id
            or node_id in envelope.requires_consent
            or node_id in envelope.info_only
        )

    @staticmethod
    def _make_veto_eligibility(envelope):
        """Cape-Coral Veto-Eligibility: only consent-required nodes can veto."""
        consent_set = set(envelope.requires_consent)
        return lambda node_id: node_id in consent_set

    # --- Bus-Loop: Pattern-Core dispatch + Cape-Coral state mgmt ---

    def process_pending(self) -> dict:
        """Laeuft Pending-Decisions durch Pattern-Core + persistiert.

        Pattern-Core: lymphatic_core.evaluate_envelope + aggregate_veto.
        Domain-Adapter: SQLite-Idempotency, Multi-Axis-Relevance, Persister.
        """
        stats = {
            "polled": 0, "processed": 0, "skipped_finalized": 0,
            "vetoed_count": 0, "approved_count": 0, "errors": [],
        }
        if not self.bus_dir.exists():
            return stats

        # Build node_id -> filter-fn map (domain-side)
        filter_fns = {
            mid: lambda env, f=f: f.evaluate(env).to_filter_result()
            for mid, f in self._filters.items()
        }

        for bus_file in sorted(self.bus_dir.glob("*.json")):
            if bus_file.name.startswith(".tmp-"):
                continue
            stats["polled"] += 1
            try:
                with open(bus_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                envelope = FamilienDecisionEnvelope.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                stats["errors"].append(f"parse-error {bus_file.name}: {e}")
                continue

            if self._is_finalized(envelope.decision_id):
                stats["skipped_finalized"] += 1
                continue

            # Pattern-Core: fan-out + aggregate
            results, errors = evaluate_envelope(
                envelope=envelope,
                envelope_id=envelope.decision_id,
                filter_nodes=filter_fns,
                relevance_fn=self._relevance,
                veto_eligibility_fn=lambda nid, env: nid in set(env.requires_consent),
            )
            stats["errors"].extend(errors)
            final_state, veto_count = aggregate_veto(
                results, self._make_veto_eligibility(envelope)
            )

            if final_state == FINAL_VETOED:
                stats["vetoed_count"] += 1
            else:
                stats["approved_count"] += 1

            # Persister expects legacy FilterDecision shape; rebuild from
            # FilterResult-Frozen-Type for backwards-compat.
            from familien_decision_filter import FilterDecision
            legacy_results = [
                FilterDecision(
                    member_id=r.node_id,
                    decision_id=r.envelope_id,
                    action=r.action,
                    rationale=r.rationale,
                    timestamp=r.timestamp,
                )
                for r in results
            ]

            if self._persister is not None:
                try:
                    self._persister.persist(envelope, legacy_results, final_state)
                except Exception as e:
                    stats["errors"].append(f"persist-error {envelope.decision_id}: {e}")

            self._record_finalized(
                envelope, final_state,
                filter_count=len(results),
                veto_count=veto_count,
            )
            stats["processed"] += 1

        return stats


# [CRUX-MK]
