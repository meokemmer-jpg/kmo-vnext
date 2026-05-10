# [CRUX-MK]
"""Tests fuer Graphity-Homeostasis-Pricing (Welle-44 Phase-37)."""
from __future__ import annotations

import pytest

from kmo_governance.graphity_homeostasis_pricing import (
    GraphityHomeostasisPricing,
    RoyaltyDecision,
    RoyaltySample,
    RoyaltyState,
)


def _smp(royalty_pct: float = 0.10, book: str = "book-1") -> RoyaltySample:
    return RoyaltySample(
        sample_id="s",
        book_id=book,
        author_id="author-A",
        royalty_pct=royalty_pct,
        timestamp=0.0,
    )


def test_init_validation() -> None:
    GraphityHomeostasisPricing()
    with pytest.raises(ValueError):
        GraphityHomeostasisPricing(setpoint=1.5)
    with pytest.raises(ValueError):
        GraphityHomeostasisPricing(history_window=0)
    with pytest.raises(ValueError):
        GraphityHomeostasisPricing(mild_threshold_pct=20, critical_threshold_pct=10)


def test_sample_validation() -> None:
    with pytest.raises(ValueError):
        RoyaltySample(sample_id="", book_id="b", author_id="a", royalty_pct=0.1, timestamp=0)
    with pytest.raises(ValueError):
        RoyaltySample(sample_id="s", book_id="b", author_id="a", royalty_pct=1.5, timestamp=0)


def test_normal_at_setpoint() -> None:
    h = GraphityHomeostasisPricing(setpoint=0.10)
    d = h.record_sample(_smp(0.10))
    assert d.state == RoyaltyState.NORMAL
    assert d.recommendation == "ok"


def test_under_royalty_triggers_renegotiate_up() -> None:
    h = GraphityHomeostasisPricing(setpoint=0.10, mild_threshold_pct=5)
    d = h.record_sample(_smp(0.085))  # 15% below setpoint
    assert d.state in (RoyaltyState.UNDER_ROYALTY, RoyaltyState.CRITICAL)


def test_over_royalty_triggers_renegotiate_down() -> None:
    h = GraphityHomeostasisPricing(setpoint=0.10, mild_threshold_pct=5)
    d = h.record_sample(_smp(0.115))  # 15% above setpoint
    assert d.state in (RoyaltyState.OVER_ROYALTY, RoyaltyState.CRITICAL)


def test_critical_state() -> None:
    h = GraphityHomeostasisPricing(setpoint=0.10, critical_threshold_pct=15)
    d = h.record_sample(_smp(0.15))  # 50% deviation
    assert d.state == RoyaltyState.CRITICAL
    assert d.recommendation == "critical_legal_review_required"


def test_per_book_history_isolated() -> None:
    h = GraphityHomeostasisPricing()
    h.record_sample(_smp(0.10, book="book-1"))
    h.record_sample(_smp(0.05, book="book-2"))
    hist1 = h.get_book_history("book-1")
    hist2 = h.get_book_history("book-2")
    assert len(hist1) == 1
    assert len(hist2) == 1
    assert hist1[0].royalty_pct == 0.10
    assert hist2[0].royalty_pct == 0.05


def test_decision_frozen() -> None:
    h = GraphityHomeostasisPricing()
    d = h.record_sample(_smp(0.10))
    with pytest.raises(Exception):
        d.state = RoyaltyState.CRITICAL  # type: ignore[misc]


def test_get_book_history_empty() -> None:
    h = GraphityHomeostasisPricing()
    assert h.get_book_history("nonexistent") == ()


def test_rolling_avg_smooths() -> None:
    """Multiple samples averaged to smooth single spikes."""
    h = GraphityHomeostasisPricing(setpoint=0.10, critical_threshold_pct=50)
    h.record_sample(_smp(0.10))
    h.record_sample(_smp(0.10))
    h.record_sample(_smp(0.10))
    d = h.record_sample(_smp(0.20))  # spike
    # avg: (0.10*3 + 0.20)/4 = 0.125, deviation 25% < 50% (critical)
    assert d.state != RoyaltyState.CRITICAL


# CRUX-MK
