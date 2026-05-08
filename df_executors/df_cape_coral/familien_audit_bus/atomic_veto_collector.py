"""Atomic-Veto-Collector (All-Votes-In-Pattern) [CRUX-MK].

Welle-31 P-W31-2: Anti-Last-Veto-Wins-Patch fuer Familien-Audit-Bus.

Problem (V14 Codex+Gemini Konsens):
    Default ``FamilienAuditBus.process_pending`` aggregiert Filter-Resultate
    in einer Liste, sequentiell. Zwei zeitnahe gegensaetzliche Vetos koennen
    in seltenen Pfaden Last-Veto-Wins-Semantik erzeugen, wenn parallel
    mehrere Bus-Instanzen oder externe Veto-Kanaele in dieselbe Decision
    schreiben.

Loesung:
    Atomic-Veto-Collector mit Barrier-Synchronisation. Alle Stimmen MUESSEN
    eingehen bevor Aggregation stattfindet. Fehlende Stimmen werden als
    ABSTAIN gewertet. Aggregation ist deterministisch (sortiert nach
    member_id), nicht reihenfolgen-abhaengig.

Bio-Aequivalent (Lymphatic-Pattern):
    Lymph-Knoten sammeln ALLE Antikoerper-Signale bevor T-Zell-Aktivierung
    feuert. Kein einzelner Knoten entscheidet allein.

CRUX-Bindung:
    K_0: direkt zentral (Familien-Veto-Race ist K_0-Risiko)
    Q_0: epistemische Integritaet via deterministische Aggregation
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional


# Constants (no magic numbers)
DEFAULT_QUORUM_TIMEOUT_SEC: float = 5.0
ABSTAIN_FOR_MISSING: str = "abstain"


@dataclass(frozen=True)
class AtomicVoteRecord:
    """Immutable Vote-Record (Snapshot des Vote-States nach Quorum-Schliessung).

    Pre: decision_id non-empty, votes deterministic-sorted.
    Post: aggregated_state in {approved, vetoed} (final).
    """

    decision_id: str
    aggregated_state: str
    votes: tuple[tuple[str, str, str], ...]  # (member_id, action, rationale)
    veto_count: int
    approve_count: int
    abstain_count: int
    quorum_size: int
    closed_at: float


class AtomicVetoCollector:
    """Atomic-Veto-Collector mit All-Votes-In-Pattern.

    Sammelt Stimmen pro Decision, schliesst Quorum nach
    ``vote(...)``-Calls von ALLEN erwarteten Mitgliedern (oder Timeout).

    Aggregation:
        - Wenn EIN Veto eines Consent-Berechtigten existiert -> vetoed.
        - Sonst -> approved.
        - Reihenfolge der Vote-Eingaenge ist IRRELEVANT (deterministische
          Sortierung nach member_id vor Aggregation).

    Pre: ``register_decision`` wird VOR ``vote`` Calls aufgerufen.
    Post: ``close_quorum`` liefert immutable AtomicVoteRecord.
    """

    def __init__(
        self,
        clock: Optional[callable] = None,
    ) -> None:
        self._clock = clock if clock is not None else time.time
        self._lock = threading.RLock()
        # decision_id -> dict mit metadata
        self._decisions: dict[str, dict] = {}
        # decision_id -> threading.Event (set when quorum complete or timeout)
        self._quorum_events: dict[str, threading.Event] = {}

    def register_decision(
        self,
        decision_id: str,
        expected_members: list[str],
        consent_members: list[str],
    ) -> None:
        """Registriert Decision mit erwarteten Vote-Members.

        Pre: decision_id non-empty, expected_members non-empty.
        Post: Decision ready for ``vote`` calls.
        """
        if not decision_id:
            raise ValueError("decision_id must be non-empty")
        if not expected_members:
            raise ValueError("expected_members must be non-empty")

        with self._lock:
            if decision_id in self._decisions:
                raise ValueError(
                    f"decision_id {decision_id!r} already registered"
                )
            self._decisions[decision_id] = {
                "expected_members": frozenset(expected_members),
                "consent_members": frozenset(consent_members),
                "votes": {},  # member_id -> (action, rationale, timestamp)
                "closed": False,
                "result": None,
            }
            self._quorum_events[decision_id] = threading.Event()

    def vote(
        self,
        decision_id: str,
        member_id: str,
        action: str,
        rationale: str = "",
    ) -> bool:
        """Submit a vote (atomic-add, NOT aggregation-triggering).

        Pre: decision_id registered, member_id in expected_members,
             action in {approve, veto, info_acknowledged, abstain}.
        Post: Vote stored. Returns True if quorum now complete (caller can
              call ``close_quorum``).
        """
        if action == "veto" and not rationale:
            raise ValueError("veto action requires non-empty rationale")
        if action not in {"approve", "veto", "info_acknowledged", "abstain"}:
            raise ValueError(f"invalid action {action!r}")

        with self._lock:
            decision = self._decisions.get(decision_id)
            if decision is None:
                raise KeyError(f"decision_id {decision_id!r} not registered")
            if decision["closed"]:
                # Late-arriving vote after close - ignored (not an error,
                # but logged).
                return False
            if member_id not in decision["expected_members"]:
                raise ValueError(
                    f"member_id {member_id!r} not in expected_members"
                )

            # Idempotent: same member voting twice with same action is OK,
            # different actions raise (Byzantine vote-flip).
            existing = decision["votes"].get(member_id)
            if existing is not None:
                ex_action, ex_rationale, _ = existing
                if ex_action != action:
                    raise ValueError(
                        f"member {member_id!r} already voted "
                        f"{ex_action!r}, cannot change to {action!r}"
                    )
                # Same action, idempotent
                return len(decision["votes"]) == len(decision["expected_members"])

            decision["votes"][member_id] = (action, rationale, self._clock())

            quorum_complete = (
                len(decision["votes"]) == len(decision["expected_members"])
            )
            if quorum_complete:
                self._quorum_events[decision_id].set()
            return quorum_complete

    def wait_for_quorum(
        self,
        decision_id: str,
        timeout_sec: float = DEFAULT_QUORUM_TIMEOUT_SEC,
    ) -> bool:
        """Block until quorum complete OR timeout. Returns True if complete."""
        with self._lock:
            event = self._quorum_events.get(decision_id)
            if event is None:
                raise KeyError(f"decision_id {decision_id!r} not registered")
        # Release lock during wait to allow concurrent votes to complete.
        return event.wait(timeout=timeout_sec)

    def close_quorum(self, decision_id: str) -> AtomicVoteRecord:
        """Atomic close: Aggregate votes, return immutable record.

        Pre: decision_id registered. Missing votes -> ABSTAIN.
        Post: Record is final. Subsequent votes ignored.
        """
        with self._lock:
            decision = self._decisions.get(decision_id)
            if decision is None:
                raise KeyError(f"decision_id {decision_id!r} not registered")
            if decision["closed"]:
                cached = decision.get("result")
                if cached is not None:
                    return cached
                raise RuntimeError(
                    f"decision {decision_id!r} closed without result"
                )

            # Fill missing votes with ABSTAIN (deterministic).
            expected = decision["expected_members"]
            consent = decision["consent_members"]
            votes_dict = decision["votes"]
            now = self._clock()

            # Deterministic sort by member_id for reproducible aggregation.
            sorted_members = sorted(expected)
            vote_tuples: list[tuple[str, str, str]] = []
            for mid in sorted_members:
                cast = votes_dict.get(mid)
                if cast is None:
                    vote_tuples.append((mid, ABSTAIN_FOR_MISSING, "missing"))
                else:
                    action, rationale, _ = cast
                    vote_tuples.append((mid, action, rationale))

            # Aggregation: ANY veto from consent_member -> vetoed.
            veto_count = sum(
                1 for (mid, act, _) in vote_tuples
                if act == "veto" and mid in consent
            )
            approve_count = sum(
                1 for (_, act, _) in vote_tuples if act == "approve"
            )
            abstain_count = sum(
                1 for (_, act, _) in vote_tuples
                if act in (ABSTAIN_FOR_MISSING, "abstain")
            )
            aggregated = "vetoed" if veto_count > 0 else "approved"

            record = AtomicVoteRecord(
                decision_id=decision_id,
                aggregated_state=aggregated,
                votes=tuple(vote_tuples),
                veto_count=veto_count,
                approve_count=approve_count,
                abstain_count=abstain_count,
                quorum_size=len(expected),
                closed_at=now,
            )
            decision["closed"] = True
            decision["result"] = record
            return record

    def is_closed(self, decision_id: str) -> bool:
        with self._lock:
            decision = self._decisions.get(decision_id)
            return decision is not None and decision["closed"]

    def get_record(self, decision_id: str) -> Optional[AtomicVoteRecord]:
        with self._lock:
            decision = self._decisions.get(decision_id)
            if decision is None:
                return None
            return decision.get("result")


# [CRUX-MK]
