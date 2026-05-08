"""Lymphatic-Core (Pattern-Core, domain-agnostic) [CRUX-MK]

Welle-31 P-W31-1 Pattern-Core-vs-Domain-Extension-Trennung.

This module hosts the **pure Pattern-Core** for the lymphatic-distribution
pattern: a broadcast-bus that fans an envelope to a set of filter-nodes,
each of which returns a decision in {approve, veto, info_acknowledged,
abstain}, and an aggregation rule that turns N decisions into a final
state.

Pattern-Core is domain-agnostic: NO references to "familie", "cape-coral",
"K_0", or any of the 5 Cape-Coral-Domains. Tests should be writable
against this module alone (no Cape-Coral context needed).

Domain-Extensions live in:
- familien_decision_filter.py (5-Domain-Whitelist + custom_filter_func)
- familien_audit_persister.py (Cape-Coral-Vault PARA layout)

Pattern-Zustandsmaschine:
    PENDING --(broadcast to relevant filters)--> EVALUATED
    EVALUATED --(aggregate veto-rule)----------> FINALIZED(approved|vetoed)

Invariants:
    I-LC-1: A finalized envelope_id is never re-evaluated (idempotent).
    I-LC-2: A filter is invoked at most once per envelope.
    I-LC-3: Aggregation is deterministic given the same filter results.
    I-LC-4: A veto from any consent-required filter blocks; otherwise approve.

Failure-Model:
    F-LC-1: Filter raises -> recorded as filter-error, envelope NOT finalized.
    F-LC-2: Filter returns invalid action -> filter-error.
    F-LC-3: Filter returns veto without rationale -> filter-error.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional


# Pattern-Core Action-Constants (Trinity-Pattern, domain-agnostic)
ACTION_APPROVE = "approve"
ACTION_VETO = "veto"
ACTION_INFO_ACKNOWLEDGED = "info_acknowledged"
ACTION_ABSTAIN = "abstain"

VALID_ACTIONS = frozenset({
    ACTION_APPROVE, ACTION_VETO, ACTION_INFO_ACKNOWLEDGED, ACTION_ABSTAIN,
})

# Pattern-Core Final-States
FINAL_APPROVED = "approved"
FINAL_VETOED = "vetoed"


@dataclass(frozen=True)
class FilterResult:
    """Decision of a single filter-node (Pattern-Core type, frozen).

    Pre: action in VALID_ACTIONS; if action == VETO then rationale non-empty.
    Post: immutable; safe to share across aggregation.
    """

    node_id: str
    envelope_id: str
    action: str
    rationale: str = ""
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(
                f"action must be in {VALID_ACTIONS}, got {self.action!r}"
            )
        if self.action == ACTION_VETO and not self.rationale:
            raise ValueError("VETO requires non-empty rationale")
        if not self.node_id:
            raise ValueError("node_id must be non-empty")


# Type alias: a filter-node is anything callable on an envelope returning
# FilterResult. The envelope is opaque to the core; relevance and address
# resolution are responsibilities of the caller (or relevance_fn).
FilterFn = Callable[[object], FilterResult]
RelevanceFn = Callable[[str, object], bool]
VetoEligibilityFn = Callable[[str, object], bool]


def evaluate_envelope(
    envelope: object,
    envelope_id: str,
    filter_nodes: dict[str, FilterFn],
    relevance_fn: RelevanceFn,
    veto_eligibility_fn: VetoEligibilityFn,
) -> tuple[list[FilterResult], list[str]]:
    """Pattern-Core fan-out: broadcast envelope to relevant filter-nodes.

    Pre:
        envelope_id non-empty; filter_nodes maps node_id -> FilterFn;
        relevance_fn(node_id, envelope) -> bool;
        veto_eligibility_fn(node_id, envelope) -> bool (only used by aggregator).

    Post:
        Returns (results, errors). Each filter is invoked at most once.
        Filters whose relevance_fn returns False are skipped silently.

    Failure-Model:
        F-LC-1, F-LC-2, F-LC-3 - all caught and recorded as errors.
    """
    if not envelope_id:
        raise ValueError("envelope_id must be non-empty")

    results: list[FilterResult] = []
    errors: list[str] = []
    for node_id, fn in filter_nodes.items():
        try:
            if not relevance_fn(node_id, envelope):
                continue
            result = fn(envelope)
            if not isinstance(result, FilterResult):
                errors.append(
                    f"filter-error {node_id}/{envelope_id}: "
                    f"expected FilterResult, got {type(result).__name__}"
                )
                continue
            results.append(result)
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            # F-LC-2/F-LC-3: invalid action / missing rationale raise in
            # FilterResult.__post_init__; F-LC-1: any other filter exception.
            errors.append(f"filter-error {node_id}/{envelope_id}: {e}")
        except Exception as e:  # noqa: BLE001 - boundary, recorded
            errors.append(f"filter-error {node_id}/{envelope_id}: {e}")
    return results, errors


def aggregate_veto(
    results: Iterable[FilterResult],
    is_veto_eligible: Callable[[str], bool],
) -> tuple[str, int]:
    """Pattern-Core aggregation: any veto from a veto-eligible node blocks.

    Pre:
        results iterable of FilterResult; is_veto_eligible(node_id) -> bool.

    Post:
        Returns (final_state, veto_count). Deterministic given input.
        I-LC-4: at least one veto-eligible veto -> FINAL_VETOED, else FINAL_APPROVED.
    """
    veto_count = sum(
        1 for r in results
        if r.action == ACTION_VETO and is_veto_eligible(r.node_id)
    )
    final_state = FINAL_VETOED if veto_count > 0 else FINAL_APPROVED
    return final_state, veto_count


# [CRUX-MK]
