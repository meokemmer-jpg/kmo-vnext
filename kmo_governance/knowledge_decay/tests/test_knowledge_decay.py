"""Tests for knowledge_decay [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.4: FSRS + Synaptic-Plasticity (LTP/LTD).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.knowledge_decay import (  # noqa: E402
    KnowledgeDecayEngine,
    SECONDS_PER_DAY,
    STABILITY_FLOOR,
)


# ---------- Engine constructor validation ----------


def test_engine_validates_invalid_params():
    with pytest.raises(ValueError):
        KnowledgeDecayEngine(ltp_boost_factor=0)  # must be > 0
    with pytest.raises(ValueError):
        KnowledgeDecayEngine(ltd_decay_rate_per_day=1.5)  # must be in (0,1)
    with pytest.raises(ValueError):
        KnowledgeDecayEngine(pruning_confidence=1.5)  # must be in [0,1]
    with pytest.raises(ValueError):
        KnowledgeDecayEngine(pruning_min_age_days=-1)


# ---------- register / get / idempotence ----------


def test_register_creates_new_entry():
    eng = KnowledgeDecayEngine()
    e = eng.register("method-pareto-cut", initial_confidence=0.7, initial_stability=2.0)
    assert e.key == "method-pareto-cut"
    assert e.confidence == 0.7
    assert e.stability == 2.0
    assert e.use_count == 0


def test_register_idempotent_returns_existing():
    eng = KnowledgeDecayEngine()
    e1 = eng.register("k1", initial_confidence=0.5)
    e2 = eng.register("k1", initial_confidence=0.9)  # already exists
    assert e1 is e2  # same object
    assert e1.confidence == 0.5  # original unchanged


def test_register_validates_inputs():
    eng = KnowledgeDecayEngine()
    with pytest.raises(ValueError):
        eng.register("k1", initial_confidence=1.5)
    with pytest.raises(ValueError):
        eng.register("k2", initial_stability=0)


# ---------- LTP / use ----------


def test_use_unknown_key_returns_none():
    eng = KnowledgeDecayEngine()
    assert eng.use("nonexistent") is None


def test_use_increases_confidence_and_stability():
    eng = KnowledgeDecayEngine(ltp_boost_factor=0.3)
    eng.register("k1", initial_confidence=0.5, initial_stability=1.0)
    e = eng.use("k1", performance=1.0)
    # confidence approaches 1 via (1-conf)*boost: 0.5 + (0.5*0.3) = 0.65
    assert e.confidence == pytest.approx(0.65)
    # stability * (1 + 0.3*1.0) = 1.3
    assert e.stability == pytest.approx(1.3)
    assert e.use_count == 1


def test_use_validates_performance():
    eng = KnowledgeDecayEngine()
    eng.register("k1")
    with pytest.raises(ValueError):
        eng.use("k1", performance=1.5)


def test_use_partial_performance_smaller_boost():
    eng = KnowledgeDecayEngine(ltp_boost_factor=0.5)
    eng.register("k1", initial_confidence=0.5, initial_stability=1.0)
    e = eng.use("k1", performance=0.5)  # half-boost
    boost = 0.5 * 0.5  # = 0.25
    expected_conf = 0.5 + (1.0 - 0.5) * boost
    assert e.confidence == pytest.approx(expected_conf)
    assert e.stability == pytest.approx(1.0 * 1.25)


# ---------- LTD / decay ----------


def test_decay_reduces_confidence_and_stability_over_time():
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(
        clock=lambda: fake_now["t"],
        ltd_decay_rate_per_day=0.1,
    )
    eng.register("k1", initial_confidence=0.8, initial_stability=2.0)
    # advance 5 days
    fake_now["t"] += 5 * SECONDS_PER_DAY
    decayed_count = eng.decay()
    assert decayed_count == 1
    e = eng.get("k1")
    # conf decayed by (0.1*0.5) * 5 = 0.25 -> 0.8 - 0.25 = 0.55
    assert e.confidence == pytest.approx(0.55)
    # stability * (1 - 0.1*5) = 0.5x
    assert e.stability == pytest.approx(2.0 * 0.5)


def test_decay_clamps_at_zero():
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(
        clock=lambda: fake_now["t"],
        ltd_decay_rate_per_day=0.5,
    )
    eng.register("k1", initial_confidence=0.1, initial_stability=1.0)
    fake_now["t"] += 100 * SECONDS_PER_DAY  # massive decay
    eng.decay()
    e = eng.get("k1")
    assert e.confidence >= 0.0
    assert e.stability >= 0.001


# ---------- Pruning ----------


def test_prune_removes_low_confidence_old_entries():
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(
        clock=lambda: fake_now["t"],
        pruning_confidence=0.2,
        pruning_min_age_days=7.0,
    )
    eng.register("k_old_lowconf", initial_confidence=0.1)   # WILL be pruned
    eng.register("k_old_highconf", initial_confidence=0.9)  # NOT pruned (high conf)
    eng.register("k_new_lowconf", initial_confidence=0.1)   # NOT pruned (too young)

    # Age all by 10 days for first 2; advance fake_now and re-register new one fresh
    fake_now["t"] += 10 * SECONDS_PER_DAY
    eng.register("k_new_now", initial_confidence=0.1)  # created at t=1000+10d, fresh

    pruned = eng.prune()
    assert "k_old_lowconf" in pruned
    assert "k_old_highconf" not in pruned
    assert "k_new_now" not in pruned


def test_prune_returns_empty_if_nothing_due():
    eng = KnowledgeDecayEngine()
    eng.register("k1", initial_confidence=0.9)
    assert eng.prune() == []


# ---------- Retrievability + Forgetting-Curve ----------


def test_retrievability_decreases_over_time():
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(clock=lambda: fake_now["t"])
    e = eng.register("k1", initial_stability=2.0)
    # immediately: R ≈ 1.0
    assert e.retrievability(fake_now["t"]) == pytest.approx(1.0)
    # 2 days later: R = exp(-2/2) = exp(-1) ≈ 0.368
    fake_now["t"] += 2 * SECONDS_PER_DAY
    assert e.retrievability(fake_now["t"]) == pytest.approx(math.exp(-1.0))


def test_get_due_for_review_orders_by_urgency():
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(clock=lambda: fake_now["t"])
    eng.register("low_stab", initial_stability=0.5)   # decays fast
    eng.register("high_stab", initial_stability=10.0) # decays slow
    eng.register("never_decays", initial_stability=100.0)

    fake_now["t"] += 1 * SECONDS_PER_DAY
    due = eng.get_due_for_review(retrievability_threshold=0.9)
    keys = [e.key for e in due]
    # low_stab should be MOST urgent (lowest R)
    assert keys[0] == "low_stab"


def test_get_due_for_review_validates_threshold():
    eng = KnowledgeDecayEngine()
    with pytest.raises(ValueError):
        eng.get_due_for_review(retrievability_threshold=0)
    with pytest.raises(ValueError):
        eng.get_due_for_review(retrievability_threshold=1.0)


def test_optimal_next_review_returns_future_timestamp():
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(clock=lambda: fake_now["t"])
    e = eng.register("k1", initial_stability=10.0)
    next_t = eng.optimal_next_review("k1")
    # Should be in the future (last_use + S*ln(1/0.9))
    assert next_t > fake_now["t"]
    expected_offset = 10.0 * math.log(1.0 / 0.9) * SECONDS_PER_DAY
    assert next_t == pytest.approx(fake_now["t"] + expected_offset)


def test_optimal_next_review_returns_none_for_unknown():
    eng = KnowledgeDecayEngine()
    assert eng.optimal_next_review("nonexistent") is None


# ---------- Integration: use boostet, decay erodes, prune cleans ----------


# ---------- Patch F1: Stability-Floor (Welle-9-delta Cross-LLM 3/3 Finding) ----------


def test_f1_stability_floor_enforced_on_registration():
    """Patch F1: Even if user requests tiny stability, floor is applied."""
    eng = KnowledgeDecayEngine()
    e = eng.register("k1", initial_stability=0.0001)  # below floor 0.001
    assert e.stability >= STABILITY_FLOOR


def test_f1_stability_floor_prevents_decay_to_zero():
    """Patch F1: massive decay does not push stability below floor."""
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(
        clock=lambda: fake_now["t"],
        ltd_decay_rate_per_day=0.99,  # extreme decay
    )
    eng.register("k1", initial_stability=0.5)
    fake_now["t"] += 100 * SECONDS_PER_DAY  # 100 days
    eng.decay()
    e = eng.get("k1")
    assert e.stability >= STABILITY_FLOOR


def test_f1_optimal_next_review_safe_with_floor():
    """Patch F1: optimal_next_review computable even after extreme decay."""
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(
        clock=lambda: fake_now["t"],
        ltd_decay_rate_per_day=0.99,
    )
    eng.register("k1", initial_stability=0.5)
    fake_now["t"] += 1000 * SECONDS_PER_DAY  # extreme age
    eng.decay()
    next_t = eng.optimal_next_review("k1")
    assert next_t is not None
    assert next_t > 0  # finite, valid timestamp


def test_full_lifecycle_use_decay_prune():
    fake_now = {"t": 1000.0}
    eng = KnowledgeDecayEngine(
        clock=lambda: fake_now["t"],
        ltp_boost_factor=0.5,
        ltd_decay_rate_per_day=0.2,
        pruning_confidence=0.3,
        pruning_min_age_days=5.0,
    )
    eng.register("active", initial_confidence=0.5, initial_stability=1.0)
    eng.register("forgotten", initial_confidence=0.5, initial_stability=1.0)

    # User uses "active" daily for 10 days
    for day in range(10):
        fake_now["t"] += SECONDS_PER_DAY
        eng.use("active", performance=1.0)

    # Decay both
    eng.decay()

    # "active" should still have high conf (was boosted), "forgotten" should be low
    active = eng.get("active")
    forgotten = eng.get("forgotten")
    assert active.confidence > forgotten.confidence

    # Prune (forgotten should be candidates if conf low + old enough)
    fake_now["t"] += 5 * SECONDS_PER_DAY  # age past pruning_min_age
    eng.decay()
    pruned = eng.prune()
    # forgotten should be in pruned since confidence eroded below 0.3
    assert "forgotten" in pruned or eng.get("forgotten").confidence < eng.pruning_confidence
