"""Familien-Decision-Filter (Domain-Extension-Adapter) [CRUX-MK]

Welle-31 P-W31-1 Pattern-Core-vs-Extension-Trennung.

This module is a **Domain-Extension-Adapter** over `lymphatic_core`:
it adapts the generic `FilterResult` to a Cape-Coral-Familien view via
the legacy `FilterDecision` mutable type, the 5-Domain-Whitelist, the
proposer/consent/info-only relevance axes, and the `custom_filter_func`
hook.

The Pattern-Core (lymphatic_core.py) does NOT depend on any of this.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from lymphatic_core import (
    ACTION_APPROVE,
    ACTION_VETO,
    ACTION_INFO_ACKNOWLEDGED,
    ACTION_ABSTAIN,
    VALID_ACTIONS,
    FilterResult,
)

if TYPE_CHECKING:
    from familien_audit_bus import FamilienDecisionEnvelope


@dataclass
class FilterDecision:
    """Mutable Domain-Adapter for a filter-node decision.

    Backwards-compatible mutable shape (custom_filter_func expects to be able
    to construct + adjust). The Pattern-Core uses the immutable FilterResult.
    `to_filter_result()` bridges the two.
    """

    member_id: str
    decision_id: str
    action: str
    rationale: str = ""
    timestamp: float = 0.0

    def to_filter_result(self) -> FilterResult:
        return FilterResult(
            node_id=self.member_id,
            envelope_id=self.decision_id,
            action=self.action,
            rationale=self.rationale,
            timestamp=self.timestamp,
        )


class FamilienDecisionFilter:
    """Lymphatic-Knoten Domain-Adapter for one Familien-Mitglied.

    Domain-Extensions:
    - 5-Domain-Whitelist via `consent_domains` / `info_domains`
    - Proposer-self-relevance (member == proposer -> info_acknowledged)
    - `custom_filter_func` hook for member-specific Logik (z.B. K_0-Schwellen)

    The Pattern-Core stays agnostic to all of these; it only knows
    "node_id -> FilterFn".
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
        """Evaluiert Decision gegen Mitglied-Kriterien (domain-spezifisch).

        Pre: envelope valid (decision_id, domain, payload).
        Post: FilterDecision mit deterministischer action.
        """
        # 1. Custom-Filter (Domain-Extension) hat Vorrang
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

        # 2. Eigener Vorschlag -> Acknowledged (Domain-Extension)
        if self.member_id == envelope.proposer_member_id:
            return FilterDecision(
                member_id=self.member_id,
                decision_id=envelope.decision_id,
                action=ACTION_INFO_ACKNOWLEDGED,
                rationale="self-proposed",
                timestamp=time.time(),
            )

        # 3. Consent-Berechtigt + Domain-Whitelist (Domain-Extension)
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

        # 4. Info-Only-Pfad (Domain-Extension)
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
