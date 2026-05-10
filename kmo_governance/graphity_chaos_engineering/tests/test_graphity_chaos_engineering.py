# [CRUX-MK]
"""Tests fuer Graphity-Chaos-Engineering (Welle-38 Phase-31).

Trinity-Tests:
  - Conservative: Happy-Path (handler succeeds, outcome.success=True)
  - Aggressive:   Pause-Block + Max-Concurrent + Unregistered-Manuscript
  - Contrarian:   Frozen-Immutability + Stability-Decay + Aggregate-Score
"""
from __future__ import annotations

import threading

import pytest

from kmo_governance.graphity_chaos_engineering import (
    FaultSeverity,
    GraphityChaosEngineering,
    GraphityChaosOutcome,
    GraphityChaosScenario,
    VerlagFaultType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_handler(scenario: GraphityChaosScenario) -> dict:
    return {
        "success": True,
        "editorial_consensus_recovered": True,
        "manuscripts_blocked": 0,
    }


def _fail_handler(scenario: GraphityChaosScenario) -> dict:
    return {
        "success": False,
        "editorial_consensus_recovered": False,
        "manuscripts_blocked": 2,
    }


def _scenario(
    manuscript_id: str = "manu-001",
    fault_type: VerlagFaultType = VerlagFaultType.AUTHOR_BURNOUT,
    severity: FaultSeverity = FaultSeverity.MODERATE,
    editor_role: str = "author",
) -> GraphityChaosScenario:
    return GraphityChaosScenario(
        scenario_id="sc-001",
        fault_type=fault_type,
        severity=severity,
        manuscript_id=manuscript_id,
        editor_role=editor_role,
        duration_s=0.1,
        expected_recovery_s=1.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_init_validation() -> None:
    """Init-Pre-Conditions."""
    GraphityChaosEngineering()  # default OK
    with pytest.raises(ValueError):
        GraphityChaosEngineering(max_concurrent_chaos=0)
    with pytest.raises(ValueError):
        GraphityChaosEngineering(max_outcomes_history=-1)


def test_scenario_validation() -> None:
    """GraphityChaosScenario Pre-Conditions."""
    with pytest.raises(ValueError, match="scenario_id"):
        GraphityChaosScenario(
            scenario_id="",
            fault_type=VerlagFaultType.AUTHOR_BURNOUT,
            severity=FaultSeverity.MINOR,
            manuscript_id="m1",
            editor_role="author",
            duration_s=0.1,
        )
    with pytest.raises(ValueError, match="duration_s"):
        GraphityChaosScenario(
            scenario_id="sc",
            fault_type=VerlagFaultType.AUTHOR_BURNOUT,
            severity=FaultSeverity.MINOR,
            manuscript_id="m1",
            editor_role="author",
            duration_s=0,
        )
    with pytest.raises(TypeError):
        GraphityChaosScenario(
            scenario_id="sc",
            fault_type="not-an-enum",  # type: ignore[arg-type]
            severity=FaultSeverity.MINOR,
            manuscript_id="m1",
            editor_role="author",
            duration_s=0.1,
        )


def test_register_and_inject_success() -> None:
    """Conservative: Happy-Path (registered + ok_handler)."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    outcome = chaos.inject(_scenario())
    assert outcome.success is True
    assert outcome.editorial_consensus_recovered is True
    assert outcome.manuscripts_blocked == 0
    assert outcome.fault_type == VerlagFaultType.AUTHOR_BURNOUT


def test_inject_unregistered_manuscript() -> None:
    """Aggressive: kein Handler -> Failed-Outcome (graceful)."""
    chaos = GraphityChaosEngineering()
    outcome = chaos.inject(_scenario(manuscript_id="never-registered"))
    assert outcome.success is False
    assert outcome.error == "manuscript_not_registered"


def test_pause_chaos_blocks_inject() -> None:
    """Aggressive: pause_chaos blockt inject (K_0-Schutz)."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    chaos.pause_chaos()
    outcome = chaos.inject(_scenario())
    assert outcome.success is False
    assert outcome.error == "chaos_paused"


def test_resume_after_pause() -> None:
    """Resume re-enables inject."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    chaos.pause_chaos()
    chaos.resume_chaos()
    outcome = chaos.inject(_scenario())
    assert outcome.success is True


def test_max_concurrent_chaos_limit() -> None:
    """Aggressive: max_concurrent=1 enforces serial faults via in-handler block."""
    chaos = GraphityChaosEngineering(max_concurrent_chaos=1)
    in_handler = threading.Event()
    can_finish = threading.Event()

    def blocking_handler(s):
        in_handler.set()
        can_finish.wait(timeout=2.0)
        return {"success": True, "editorial_consensus_recovered": True, "manuscripts_blocked": 0}

    chaos.register_manuscript("manu-001", blocking_handler)
    results = []

    def worker():
        results.append(chaos.inject(_scenario()))

    t1 = threading.Thread(target=worker)
    t1.start()
    in_handler.wait(timeout=2.0)  # first worker is now in-handler, holds slot
    # second inject should immediately fail with max_concurrent_reached
    second = chaos.inject(_scenario())
    assert second.success is False
    assert second.error == "max_concurrent_reached"
    can_finish.set()
    t1.join(timeout=3.0)
    assert len(results) == 1
    assert results[0].success is True


def test_outcome_frozen_immutability() -> None:
    """Contrarian: GraphityChaosOutcome frozen."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    outcome = chaos.inject(_scenario())
    with pytest.raises(Exception):
        outcome.success = False  # type: ignore[misc]


def test_stability_decay_after_severe_fault() -> None:
    """Contrarian: SEVERE fault decays stability score."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _fail_handler)
    initial = chaos.get_stability_score("manu-001")
    chaos.inject(_scenario(severity=FaultSeverity.SEVERE))
    after = chaos.get_stability_score("manu-001")
    assert after < initial  # decay occurred
    assert after >= 0.0


def test_stability_recovery_bonus_on_success() -> None:
    """Contrarian: success+consensus boosts stability (within bounds)."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    # First inject decays, recovery-bonus restores partially
    chaos.inject(_scenario(severity=FaultSeverity.MINOR))
    after_first = chaos.get_stability_score("manu-001")
    # Should still be high (minor decay 0.05 - bonus 0.02 = ~0.97)
    assert 0.9 <= after_first <= 1.0


def test_get_outcomes_filter_by_editor_role() -> None:
    """Filter outcomes by editor_role."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    chaos.inject(_scenario(editor_role="author"))
    chaos.inject(_scenario(editor_role="editor"))
    author_outcomes = chaos.get_outcomes(editor_role="author")
    assert len(author_outcomes) == 1
    assert author_outcomes[0].editor_role == "author"


def test_get_outcomes_filter_by_fault_type() -> None:
    """Filter outcomes by fault_type."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    chaos.inject(_scenario(fault_type=VerlagFaultType.AUTHOR_BURNOUT))
    chaos.inject(_scenario(fault_type=VerlagFaultType.TYPESETTING_ERROR))
    burnout_outcomes = chaos.get_outcomes(fault_type=VerlagFaultType.AUTHOR_BURNOUT)
    assert len(burnout_outcomes) == 1


def test_get_aggregate_score_empty() -> None:
    """Empty-Aggregate: success_rate=0, total=0."""
    chaos = GraphityChaosEngineering()
    score = chaos.get_aggregate_score()
    assert score["total"] == 0.0
    assert score["success_rate"] == 0.0


def test_get_aggregate_score_with_outcomes() -> None:
    """Aggregate-Score reflects outcomes."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    for _ in range(5):
        chaos.inject(_scenario())
    score = chaos.get_aggregate_score()
    assert score["total"] == 5.0
    assert score["success_rate"] == 1.0
    assert score["consensus_rate"] == 1.0


def test_outcomes_history_bounded() -> None:
    """max_outcomes_history bounds deque (Anti-OOM)."""
    chaos = GraphityChaosEngineering(max_outcomes_history=3)
    chaos.register_manuscript("manu-001", _ok_handler)
    for _ in range(10):
        chaos.inject(_scenario())
    outcomes = chaos.get_outcomes()
    assert len(outcomes) == 3


def test_handler_exception_returns_failed_outcome() -> None:
    """Aggressive: handler raises -> success=False with error."""
    def boom(s):
        raise RuntimeError("simulated")

    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", boom)
    outcome = chaos.inject(_scenario())
    assert outcome.success is False
    assert "RuntimeError" in (outcome.error or "")


def test_register_empty_manuscript_id_raises() -> None:
    """Pre-Cond: manuscript_id non-empty."""
    chaos = GraphityChaosEngineering()
    with pytest.raises(ValueError):
        chaos.register_manuscript("", _ok_handler)


# ---------------------------------------------------------------------------
# W39-P1+P3 Patches (Codex V19 W19-I3 + W19-Race-Risk)
# ---------------------------------------------------------------------------


def test_w39p1_stability_decay_capped_at_005() -> None:
    """W39-P1: Stability-Decay capped bei 0.05 pro Fault, auch bei CRITICAL."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _fail_handler)
    initial = chaos.get_stability_score("manu-001")  # 1.0
    chaos.inject(_scenario(severity=FaultSeverity.CRITICAL))
    after = chaos.get_stability_score("manu-001")
    decay = initial - after
    assert decay <= 0.0501  # capped (float-Toleranz), NICHT 0.75 (15.0 * 0.05) wie vorher
    assert decay > 0.0


def test_w39p3_failed_outcome_paused_appended_to_history() -> None:
    """W39-P3: paused-Outcomes werden in history appended (Audit-Trail-Voll)."""
    chaos = GraphityChaosEngineering()
    chaos.register_manuscript("manu-001", _ok_handler)
    chaos.pause_chaos()
    chaos.inject(_scenario())  # paused -> failed_outcome
    outcomes = chaos.get_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].error == "chaos_paused"


def test_w39p3_failed_outcome_unregistered_appended_to_history() -> None:
    """W39-P3: unregistered-manuscript-Outcomes in history."""
    chaos = GraphityChaosEngineering()
    chaos.inject(_scenario(manuscript_id="never-registered"))
    outcomes = chaos.get_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].error == "manuscript_not_registered"


# CRUX-MK
