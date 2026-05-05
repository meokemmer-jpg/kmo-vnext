"""Tests for feature_flag_engine SKELETON [CRUX-MK]."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.feature_flag_engine import (  # noqa: E402
    ABTestVariantSelector,
    ContextualRule,
    FeatureFlagEngine,
    FlagAuditLog,
    FlagContext,
    FlagRule,
    FlagRuleType,
    PercentageRollout,
)


# ---------- 1. Boolean Flag ----------


def test_flag_engine_register_and_evaluate_boolean():
    """Register Boolean-Flag + is_enabled liefert konsistent True/False."""
    engine = FeatureFlagEngine()
    engine.register_flag("feat-A", FlagRule.boolean("feat-A", True))
    engine.register_flag("feat-B", FlagRule.boolean("feat-B", False))

    ctx = FlagContext.from_dict(user_id="u-1")
    assert engine.is_enabled("feat-A", ctx) is True
    assert engine.is_enabled("feat-B", ctx) is False

    # Idempotent: gleicher Aufruf, gleiches Ergebnis
    assert engine.is_enabled("feat-A", ctx) is True
    assert engine.is_enabled("feat-B", ctx) is False


# ---------- 2. PercentageRollout deterministic ----------


def test_flag_engine_percentage_rollout_deterministic():
    """Gleiche (flag_id, user_id) liefern gleichen Bucket / Result."""
    rollout = PercentageRollout("flag-X", 50.0)
    user_id = "user-42"

    bucket_first = rollout.bucket_for(user_id)
    enabled_first = rollout.is_enabled(user_id)
    bucket_second = rollout.bucket_for(user_id)
    enabled_second = rollout.is_enabled(user_id)

    assert bucket_first == bucket_second
    assert enabled_first == enabled_second
    assert 0 <= bucket_first < 100

    # Verschiedene user_ids fuehren oft zu verschiedenen Ergebnissen
    other = rollout.bucket_for("user-999")
    assert 0 <= other < 100


# ---------- 3. Percentage-Distribution ----------


def test_flag_engine_percentage_distribution_within_5pct():
    """10000 user_ids @ 30% Rollout -> Anteil enabled in [25%, 35%]."""
    rollout = PercentageRollout("flag-Y", 30.0)
    n = 10_000
    enabled_count = sum(1 for i in range(n) if rollout.is_enabled(f"user-{i}"))
    fraction = enabled_count / n
    assert 0.25 <= fraction <= 0.35, (
        f"fraction {fraction:.4f} outside [0.25, 0.35]"
    )


# ---------- 4. ContextualRule eq match ----------


def test_flag_engine_contextual_rule_eq_match():
    """Contextual eq operation: hotel_id muss matchen."""
    rule = FlagRule.contextual(
        "feat-by-hotel",
        conditions=[("hotel_id", "eq", "hotel-1")],
    )
    engine = FeatureFlagEngine()
    engine.register_flag("feat-by-hotel", rule)

    ctx_match = FlagContext.from_dict(user_id="u", hotel_id="hotel-1")
    ctx_no = FlagContext.from_dict(user_id="u", hotel_id="hotel-2")

    assert engine.is_enabled("feat-by-hotel", ctx_match) is True
    assert engine.is_enabled("feat-by-hotel", ctx_no) is False


# ---------- 5. ContextualRule in list ----------


def test_flag_engine_contextual_rule_in_list():
    """Contextual 'in' operation: environment in list."""
    rule = FlagRule.contextual(
        "feat-env",
        conditions=[("environment", "in", ["staging", "dev"])],
    )
    engine = FeatureFlagEngine()
    engine.register_flag("feat-env", rule)

    ctx_dev = FlagContext.from_dict(user_id="u", environment="dev")
    ctx_staging = FlagContext.from_dict(user_id="u", environment="staging")
    ctx_prod = FlagContext.from_dict(user_id="u", environment="production")

    assert engine.is_enabled("feat-env", ctx_dev) is True
    assert engine.is_enabled("feat-env", ctx_staging) is True
    assert engine.is_enabled("feat-env", ctx_prod) is False


# ---------- 6. Contextual AND ----------


def test_flag_engine_contextual_rule_all_conditions_AND():
    """Contextual match_mode='all': alle Conditions muessen matchen."""
    rule = FlagRule.contextual(
        "feat-and",
        conditions=[
            ("hotel_id", "eq", "hotel-1"),
            ("environment", "eq", "production"),
        ],
        match_mode="all",
    )
    engine = FeatureFlagEngine()
    engine.register_flag("feat-and", rule)

    ctx_both = FlagContext.from_dict(
        user_id="u", hotel_id="hotel-1", environment="production"
    )
    ctx_one = FlagContext.from_dict(
        user_id="u", hotel_id="hotel-1", environment="staging"
    )
    ctx_other = FlagContext.from_dict(
        user_id="u", hotel_id="hotel-2", environment="production"
    )

    assert engine.is_enabled("feat-and", ctx_both) is True
    assert engine.is_enabled("feat-and", ctx_one) is False
    assert engine.is_enabled("feat-and", ctx_other) is False


# ---------- 7. ABTestVariantSelector deterministic ----------


def test_ab_test_variant_selector_deterministic():
    """Gleiche (flag_id, user_id) liefern gleichen Variant."""
    selector = ABTestVariantSelector()
    selector.register_variants("flag-AB", ["A", "B"], [1.0, 1.0])

    ctx = FlagContext.from_dict(user_id="user-7")
    v_first = selector.select_variant("flag-AB", ctx)
    v_second = selector.select_variant("flag-AB", ctx)
    v_third = selector.select_variant("flag-AB", ctx)

    assert v_first in {"A", "B"}
    assert v_first == v_second == v_third


# ---------- 8. AB-Test Distribution matches Weights ----------


def test_ab_test_variant_distribution_matches_weights():
    """10000 Users + 70/30-Weights -> Anteil-Toleranz +/-5%."""
    selector = ABTestVariantSelector()
    selector.register_variants(
        "flag-bias", ["majority", "minority"], [0.7, 0.3]
    )
    n = 10_000
    counts = {"majority": 0, "minority": 0}
    for i in range(n):
        ctx = FlagContext.from_dict(user_id=f"u-{i}")
        v = selector.select_variant("flag-bias", ctx)
        counts[v] = counts.get(v, 0) + 1

    majority_frac = counts["majority"] / n
    minority_frac = counts["minority"] / n
    assert 0.65 <= majority_frac <= 0.75, (
        f"majority {majority_frac:.4f} outside [0.65, 0.75]"
    )
    assert 0.25 <= minority_frac <= 0.35, (
        f"minority {minority_frac:.4f} outside [0.25, 0.35]"
    )


# ---------- 9. AuditLog records evaluations ----------


def test_audit_log_records_evaluations():
    """is_enabled erzeugt Audit-Records pro Aufruf."""
    audit = FlagAuditLog()
    engine = FeatureFlagEngine(audit_log=audit)
    engine.register_flag("feat-audit", FlagRule.boolean("feat-audit", True))

    ctx = FlagContext.from_dict(user_id="u-1", environment="production")
    for _ in range(5):
        engine.is_enabled("feat-audit", ctx)

    history = audit.get_history("feat-audit")
    assert len(history) == 5
    for rec in history:
        assert rec.flag_id == "feat-audit"
        assert rec.user_id == "u-1"
        assert rec.environment == "production"
        assert rec.result is True


# ---------- 10. AuditLog thread-safe ----------


def test_audit_log_thread_safe():
    """50 Threads mit je 100 Evaluationen -> 5000 Records, keine Lost-Updates."""
    audit = FlagAuditLog()
    engine = FeatureFlagEngine(audit_log=audit)
    engine.register_flag(
        "feat-thread",
        FlagRule.percentage("feat-thread", 50.0),
    )

    n_threads = 50
    n_per_thread = 100

    def worker(thread_idx: int) -> None:
        for j in range(n_per_thread):
            ctx = FlagContext.from_dict(user_id=f"t{thread_idx}-u{j}")
            engine.is_enabled("feat-thread", ctx)

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    history = audit.get_history("feat-thread")
    assert len(history) == n_threads * n_per_thread, (
        f"expected {n_threads * n_per_thread}, got {len(history)}"
    )


# ---------- 11. update_rule immediate effect ----------


def test_update_rule_immediately_takes_effect():
    """update_rule() wirkt beim naechsten is_enabled-Call."""
    engine = FeatureFlagEngine()
    engine.register_flag("feat-mut", FlagRule.boolean("feat-mut", True))
    ctx = FlagContext.from_dict(user_id="u-1")
    assert engine.is_enabled("feat-mut", ctx) is True

    engine.update_rule("feat-mut", FlagRule.boolean("feat-mut", False))
    assert engine.is_enabled("feat-mut", ctx) is False

    engine.update_rule("feat-mut", FlagRule.boolean("feat-mut", True))
    assert engine.is_enabled("feat-mut", ctx) is True


# ---------- 12. Unregistered flag returns default ----------


def test_unregistered_flag_returns_default():
    """is_enabled fuer unregistered flag liefert False; get_value liefert None."""
    engine = FeatureFlagEngine()
    ctx = FlagContext.from_dict(user_id="u-x")

    assert engine.is_enabled("does-not-exist", ctx) is False
    assert engine.get_value("does-not-exist", ctx) is None

    # Audit zeigt 2 Eintraege mit jeweils Default-Result
    history = engine.get_audit_log().get_history("does-not-exist")
    assert len(history) == 2
    assert history[0].result is False
    assert history[1].result is None


# CRUX-MK
