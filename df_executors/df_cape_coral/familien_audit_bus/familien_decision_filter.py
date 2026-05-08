"""Familien-Decision-Filter (Lymphatic-Knoten pro Familien-Mitglied) [CRUX-MK]

Pro Familien-Mitglied ein Filter-Layer mit consent_domains (Veto-Recht), info_domains
(nur informieren) + optional custom_filter_func. Bio: Lymphatic-Knoten + Antikoerper.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from familien_audit_bus import FamilienDecisionEnvelope


# Filter-Action-Konstanten (Trinity-Pattern)
ACTION_APPROVE = "approve"
ACTION_VETO = "veto"
ACTION_INFO_ACKNOWLEDGED = "info_acknowledged"
ACTION_ABSTAIN = "abstain"

VALID_ACTIONS = frozenset({
    ACTION_APPROVE, ACTION_VETO, ACTION_INFO_ACKNOWLEDGED, ACTION_ABSTAIN,
})


@dataclass
class FilterDecision:
    """Resultat eines Filter-Nodes pro Decision.

    Pre: action in VALID_ACTIONS. Post: rationale non-empty wenn action == veto.
    """

    member_id: str
    decision_id: str
    action: str
    rationale: str = ""
    timestamp: float = 0.0


class FamilienDecisionFilter:
    """Filter-Node fuer ein Familien-Mitglied (Lymphatic-Knoten).

    Default-Verhalten:
    - Mitglied = proposer -> info_acknowledged (eigene Initiative)
    - Mitglied in requires_consent + Domain in consent_domains -> approve
    - Mitglied in info_only oder Domain in info_domains -> info_acknowledged
    - Sonst: abstain

    custom_filter_func erlaubt mitglied-spezifische Logik (z.B. K_0-Schwellen).
    """

    def __init__(
        self,
        member_id: str,
        consent_domains: list | None = None,
        info_domains: list | None = None,
        custom_filter_func: Callable | None = None,
    ):
        if not member_id:
            raise ValueError("member_id must be non-empty")
        self.member_id = member_id
        self.consent_domains = set(consent_domains or [])
        self.info_domains = set(info_domains or [])
        self.custom_filter_func = custom_filter_func

    def evaluate(self, envelope) -> FilterDecision:
        """Evaluiert Decision gegen Mitglied-Kriterien.

        Pre: envelope valid (decision_id, domain, payload).
        Post: FilterDecision mit deterministischer action.
        """
        # 1. Custom-Filter hat Vorrang
        if self.custom_filter_func is not None:
            result = self.custom_filter_func(envelope)
            if result.action not in VALID_ACTIONS:
                raise ValueError(
                    f"custom_filter_func returned invalid action {result.action!r}"
                )
            if result.action == ACTION_VETO and not result.rationale:
                raise ValueError("veto requires non-empty rationale")
            if not result.member_id:
                result.member_id = self.member_id
            if not result.decision_id:
                result.decision_id = envelope.decision_id
            if result.timestamp == 0.0:
                result.timestamp = time.time()
            return result

        # 2. Eigener Vorschlag -> Acknowledged
        if self.member_id == envelope.proposer_member_id:
            return FilterDecision(
                member_id=self.member_id,
                decision_id=envelope.decision_id,
                action=ACTION_INFO_ACKNOWLEDGED,
                rationale="self-proposed",
                timestamp=time.time(),
            )

        # 3. Consent-Berechtigt + Domain passt -> default approve
        if (
            self.member_id in envelope.requires_consent
            and envelope.domain in self.consent_domains
        ):
            return FilterDecision(
                member_id=self.member_id,
                decision_id=envelope.decision_id,
                action=ACTION_APPROVE,
                rationale="consent-domain-default-approve",
                timestamp=time.time(),
            )

        # 4. Info-Only-Pfad
        if (
            self.member_id in envelope.info_only
            or envelope.domain in self.info_domains
        ):
            return FilterDecision(
                member_id=self.member_id,
                decision_id=envelope.decision_id,
                action=ACTION_INFO_ACKNOWLEDGED,
                rationale="info-only-pathway",
                timestamp=time.time(),
            )

        # 5. Fallback: abstain
        return FilterDecision(
            member_id=self.member_id,
            decision_id=envelope.decision_id,
            action=ACTION_ABSTAIN,
            rationale="no-applicable-filter-criterion",
            timestamp=time.time(),
        )


# [CRUX-MK]
