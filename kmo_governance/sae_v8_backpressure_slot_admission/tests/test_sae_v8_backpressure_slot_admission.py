# [CRUX-MK]
"""Tests fuer SAE-v8 Backpressure-Slot-Admission (Welle-34 Phase-27 Bio-Pattern-Lift Lift 16).

Pflicht-Coverage (per Subagent-K29 Auftrag):
- test_init_validation
- test_record_admission_appends
- test_initial_state_normal
- test_elevated_state_at_threshold
- test_blocked_state_at_critical
- test_evaluate_uses_rolling_window
- test_per_agent_class_isolation
- test_per_trinity_variant_isolation
- test_register_custom_action
- test_history_window_limits
- test_reset_clears
- test_concurrent_record_50_threads
- test_decision_frozen
- test_action_frozen
- test_get_decisions_history
"""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from kmo_governance.sae_v8_backpressure_slot_admission import (
    AdmissionThrottleAction,
    SAESlotBackpressureDecision,
    SAEv8BackpressureSlotAdmission,
    SlotAdmissionSample,
    SlotFlowState,
)


# ---------- Init / Validation ----------


def test_init_validation() -> None:
    # Happy path
    eng = SAEv8BackpressureSlotAdmission(
        max_admissions_per_minute=60.0,
        max_total_slots=200,
    )
    assert eng.get_state() == SlotFlowState.NORMAL

    # Pre-condition violations
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(0.0)  # max_admissions <= 0
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(60.0, max_total_slots=0)
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(60.0, history_window=0)
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(
            60.0, elevated_threshold_pct=-1.0,
        )
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(
            60.0, blocked_threshold_pct=101.0,
        )
    # elevated >= blocked verboten
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(
            60.0,
            elevated_threshold_pct=80.0,
            blocked_threshold_pct=80.0,
        )
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(
            60.0,
            elevated_threshold_pct=90.0,
            blocked_threshold_pct=80.0,
        )
    # max_decisions_history >= 1
    with pytest.raises(ValueError):
        SAEv8BackpressureSlotAdmission(60.0, max_decisions_history=0)


# ---------- record_admission ----------


def test_record_admission_appends() -> None:
    eng = SAEv8BackpressureSlotAdmission(60.0, history_window=5)
    eng.record_admission("REVENUE_MANAGEMENT", "Conservative", "slot-001")
    eng.record_admission("REVENUE_MANAGEMENT", "Aggressive", "slot-002")
    eng.record_admission("HOUSEKEEPING", "Contrarian", "slot-003")

    # Validation
    with pytest.raises(ValueError):
        eng.record_admission("", "Conservative", "slot-001")
    with pytest.raises(ValueError):
        eng.record_admission("AC", "", "slot-001")
    with pytest.raises(ValueError):
        eng.record_admission("AC", "Conservative", "")
    with pytest.raises(ValueError):
        eng.record_admission("AC", "InvalidVariant", "slot-001")

    # Decision basiert auf samples
    d_global = eng.evaluate()
    assert d_global.current_rate > 0.0


# ---------- Initial State ----------


def test_initial_state_normal() -> None:
    eng = SAEv8BackpressureSlotAdmission(60.0)
    # Vor jeglichem record_admission -> NORMAL + ALLOW
    assert eng.get_state() == SlotFlowState.NORMAL
    decision = eng.evaluate()
    assert decision.state == SlotFlowState.NORMAL
    assert decision.action.action_type == "ALLOW"
    assert decision.current_rate == 0.0


# ---------- ELEVATED State ----------


def test_elevated_state_at_threshold() -> None:
    """80% of max=60/min -> 48/min -> ELEVATED + ALLOW (warn).

    Mit history_window=60, default duration_min=1.0 minimum.
    Inject 48 admissions -> 48/min = 80% -> ELEVATED.
    """
    eng = SAEv8BackpressureSlotAdmission(
        60.0,
        history_window=60,
        elevated_threshold_pct=70.0,
        blocked_threshold_pct=95.0,
    )
    # 48 admissions in <1 min window -> rate=48/min = 80%
    for i in range(48):
        eng.record_admission("AC", "Conservative", f"slot-{i:03d}")

    decision = eng.evaluate()
    # 80% liegt zwischen elevated (70) und mid_band ((70+95)/2=82.5)
    # -> ELEVATED-Tier
    assert decision.state == SlotFlowState.ELEVATED
    assert decision.action.action_type == "ALLOW"
    assert "elevated" in decision.action.reason.lower()


# ---------- BLOCKED State ----------


def test_blocked_state_at_critical() -> None:
    """120% of max=60/min -> 72/min -> BLOCKED + REJECT."""
    eng = SAEv8BackpressureSlotAdmission(
        60.0,
        history_window=80,
        elevated_threshold_pct=70.0,
        blocked_threshold_pct=95.0,
    )
    # 72 admissions in <1 min -> 72/min = 120% -> BLOCKED
    for i in range(72):
        eng.record_admission("AC", "Conservative", f"slot-{i:03d}")

    decision = eng.evaluate()
    assert decision.state == SlotFlowState.BLOCKED
    assert decision.action.action_type == "REJECT"


# ---------- Rolling Window ----------


def test_evaluate_uses_rolling_window() -> None:
    """history_window=3 -> alte Samples werden evicted."""
    eng = SAEv8BackpressureSlotAdmission(60.0, history_window=3)
    # 5 records, aber nur 3 bleiben in deque(maxlen=3)
    for i in range(5):
        eng.record_admission("AC", "Conservative", f"slot-{i}")

    # Decision benutzt nur die letzten 3 Samples
    d = eng.evaluate()
    assert d.current_rate > 0.0
    # Audit trail enthaelt die decision
    assert len(eng.get_decisions()) == 1


# ---------- Per-AgentClass Isolation ----------


def test_per_agent_class_isolation() -> None:
    """class-A gefluted (BLOCKED) vs class-B leer (NORMAL) gleichzeitig."""
    eng = SAEv8BackpressureSlotAdmission(60.0, history_window=80)
    # class-A: 72 records -> BLOCKED
    for i in range(72):
        eng.record_admission("REVENUE_MANAGEMENT", "Conservative", f"slot-A-{i}")
    # class-B: 1 record -> NORMAL
    eng.record_admission("HOUSEKEEPING", "Conservative", "slot-B-1")

    d_a = eng.evaluate(agent_class="REVENUE_MANAGEMENT")
    d_b = eng.evaluate(agent_class="HOUSEKEEPING")

    assert d_a.state == SlotFlowState.BLOCKED
    assert d_b.state == SlotFlowState.NORMAL

    # State-Snapshots
    assert eng.get_state(agent_class="REVENUE_MANAGEMENT") == SlotFlowState.BLOCKED
    assert eng.get_state(agent_class="HOUSEKEEPING") == SlotFlowState.NORMAL


# ---------- Per-Trinity-Variant Isolation ----------


def test_per_trinity_variant_isolation() -> None:
    """Conservative gefluted (BLOCKED) vs Aggressive leer (NORMAL)."""
    eng = SAEv8BackpressureSlotAdmission(60.0, history_window=80)
    # Conservative: 72 records -> BLOCKED
    for i in range(72):
        eng.record_admission("AC", "Conservative", f"slot-cons-{i}")
    # Aggressive: 1 record -> NORMAL
    eng.record_admission("AC", "Aggressive", "slot-agg-1")

    d_c = eng.evaluate(trinity_variant="Conservative")
    d_a = eng.evaluate(trinity_variant="Aggressive")

    assert d_c.state == SlotFlowState.BLOCKED
    assert d_a.state == SlotFlowState.NORMAL

    # State-Snapshots
    assert eng.get_state(trinity_variant="Conservative") == SlotFlowState.BLOCKED
    assert eng.get_state(trinity_variant="Aggressive") == SlotFlowState.NORMAL

    # Validation: invalid trinity_variant
    with pytest.raises(ValueError):
        eng.evaluate(trinity_variant="InvalidVariant")
    with pytest.raises(ValueError):
        eng.get_state(trinity_variant="InvalidVariant")


# ---------- Custom Action Handler ----------


def test_register_custom_action() -> None:
    eng = SAEv8BackpressureSlotAdmission(60.0)

    custom_calls: list[float] = []

    def custom_throttled(current_rate: float) -> AdmissionThrottleAction:
        custom_calls.append(current_rate)
        return AdmissionThrottleAction(
            action_type="DELAY",
            delay_ms=999.0,
            reason="custom-throttled-handler",
            timestamp=time.time(),
        )

    eng.register_action(SlotFlowState.THROTTLED, custom_throttled)

    # Force THROTTLED-State: 55/min -> 91.6% (im Band 82.5-95)
    for i in range(55):
        eng.record_admission("AC", "Conservative", f"slot-{i:03d}")

    decision = eng.evaluate()
    assert decision.state == SlotFlowState.THROTTLED
    assert decision.action.action_type == "DELAY"
    assert decision.action.delay_ms == 999.0
    assert decision.action.reason == "custom-throttled-handler"
    assert len(custom_calls) == 1

    # Validation
    with pytest.raises(TypeError):
        eng.register_action("not-a-state", custom_throttled)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        eng.register_action(SlotFlowState.NORMAL, "not-callable")  # type: ignore[arg-type]


# ---------- History Window Limits ----------


def test_history_window_limits() -> None:
    """deque(maxlen=5) wirft alte Samples raus bei 100 Inserts."""
    eng = SAEv8BackpressureSlotAdmission(60.0, history_window=5)
    for i in range(100):
        eng.record_admission("AC", "Conservative", f"slot-{i:03d}")

    # Internal state: nur 5 samples in global buffer
    # Wir koennen nicht direkt darauf zugreifen, aber evaluate() rate
    # spiegelt die Begrenzung: 5 admissions / 60s window = 5/min
    d = eng.evaluate()
    # Da nur 5 samples bleiben und window_min ~= 1.0:
    assert d.current_rate <= 5.0


# ---------- Reset ----------


def test_reset_clears() -> None:
    eng = SAEv8BackpressureSlotAdmission(60.0, history_window=80)
    for i in range(72):
        eng.record_admission("AC", "Conservative", f"slot-{i:03d}")
    eng.evaluate()
    eng.evaluate(agent_class="AC")
    eng.evaluate(trinity_variant="Conservative")

    assert eng.get_state() == SlotFlowState.BLOCKED
    assert len(eng.get_decisions()) == 3

    eng.reset()
    assert eng.get_state() == SlotFlowState.NORMAL
    assert eng.get_state(agent_class="AC") == SlotFlowState.NORMAL
    assert eng.get_state(trinity_variant="Conservative") == SlotFlowState.NORMAL
    assert len(eng.get_decisions()) == 0

    # Re-evaluate nach Reset -> NORMAL/ALLOW (kein Sample)
    d = eng.evaluate()
    assert d.state == SlotFlowState.NORMAL
    assert d.action.action_type == "ALLOW"


# ---------- Concurrency ----------


def test_concurrent_record_50_threads() -> None:
    """50 Threads, jeweils 10 Admissions = 500 Total -> kein Race."""
    eng = SAEv8BackpressureSlotAdmission(
        60.0, history_window=1000, max_decisions_history=10000
    )

    barrier = threading.Barrier(50)

    def worker(thread_id: int) -> None:
        barrier.wait()
        for j in range(10):
            eng.record_admission(
                f"AC-{thread_id % 3}",
                ("Conservative", "Aggressive", "Contrarian")[j % 3],
                f"slot-{thread_id}-{j}",
            )
            eng.evaluate()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 500 evaluate-calls -> 500 decisions im audit trail
    decisions = eng.get_decisions()
    assert len(decisions) == 500


# ---------- Frozen Decision ----------


def test_decision_frozen() -> None:
    eng = SAEv8BackpressureSlotAdmission(60.0)
    eng.record_admission("AC", "Conservative", "slot-001")
    decision = eng.evaluate()

    # Mutation muss FrozenInstanceError werfen
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.state = SlotFlowState.BLOCKED  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.current_rate = 999.0  # type: ignore[misc]


# ---------- Frozen Action / Sample ----------


def test_action_frozen() -> None:
    action = AdmissionThrottleAction(
        action_type="ALLOW",
        delay_ms=0.0,
        reason="test",
        timestamp=time.time(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.action_type = "REJECT"  # type: ignore[misc]

    sample = SlotAdmissionSample(
        timestamp=time.time(),
        agent_class="AC",
        trinity_variant="Conservative",
        admission_count=1,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        sample.admission_count = 99  # type: ignore[misc]


# ---------- get_decisions History ----------


def test_get_decisions_history() -> None:
    eng = SAEv8BackpressureSlotAdmission(60.0)
    eng.record_admission("AC", "Conservative", "slot-001")

    decisions: list[SAESlotBackpressureDecision] = []
    for _ in range(5):
        decisions.append(eng.evaluate())

    snapshot = eng.get_decisions()
    assert isinstance(snapshot, tuple)
    assert len(snapshot) == 5
    # Insertion-Order erhalten
    for original, snap_item in zip(decisions, snapshot):
        assert original is snap_item

    # Mutation des Snapshots darf interne Liste nicht beeinflussen
    # (tuple ist immutable -> kein Test der Mutation moeglich, aber Snapshot stable)
    eng.evaluate()
    assert len(snapshot) == 5  # unveraendert
    assert len(eng.get_decisions()) == 6


# ---------- SlotAdmissionSample Validation ----------


def test_slot_admission_sample_validation() -> None:
    now = time.time()
    # Happy path
    s = SlotAdmissionSample(
        timestamp=now,
        agent_class="AC",
        trinity_variant="Conservative",
        admission_count=1,
    )
    assert s.timestamp == now

    # timestamp <= 0
    with pytest.raises(ValueError):
        SlotAdmissionSample(
            timestamp=0.0,
            agent_class="AC",
            trinity_variant="Conservative",
            admission_count=1,
        )
    # agent_class empty
    with pytest.raises(ValueError):
        SlotAdmissionSample(
            timestamp=now,
            agent_class="",
            trinity_variant="Conservative",
            admission_count=1,
        )
    # trinity_variant empty
    with pytest.raises(ValueError):
        SlotAdmissionSample(
            timestamp=now,
            agent_class="AC",
            trinity_variant="",
            admission_count=1,
        )
    # trinity_variant invalid
    with pytest.raises(ValueError):
        SlotAdmissionSample(
            timestamp=now,
            agent_class="AC",
            trinity_variant="InvalidVariant",
            admission_count=1,
        )
    # admission_count < 1
    with pytest.raises(ValueError):
        SlotAdmissionSample(
            timestamp=now,
            agent_class="AC",
            trinity_variant="Conservative",
            admission_count=0,
        )


# ---------- AdmissionThrottleAction Validation ----------


def test_admission_throttle_action_validation() -> None:
    now = time.time()
    # Happy paths
    AdmissionThrottleAction(
        action_type="ALLOW", delay_ms=0.0, reason="ok", timestamp=now
    )
    AdmissionThrottleAction(
        action_type="REJECT", delay_ms=0.0, reason="reject", timestamp=now
    )
    AdmissionThrottleAction(
        action_type="DELAY", delay_ms=100.0, reason="delay", timestamp=now
    )

    # Invalid action_type
    with pytest.raises(ValueError):
        AdmissionThrottleAction(
            action_type="INVALID",
            delay_ms=0.0,
            reason="x",
            timestamp=now,
        )
    # Negative delay_ms
    with pytest.raises(ValueError):
        AdmissionThrottleAction(
            action_type="ALLOW",
            delay_ms=-1.0,
            reason="x",
            timestamp=now,
        )
    # DELAY mit delay_ms == 0
    with pytest.raises(ValueError):
        AdmissionThrottleAction(
            action_type="DELAY",
            delay_ms=0.0,
            reason="x",
            timestamp=now,
        )
    # Empty reason
    with pytest.raises(ValueError):
        AdmissionThrottleAction(
            action_type="ALLOW",
            delay_ms=0.0,
            reason="",
            timestamp=now,
        )
    # timestamp <= 0
    with pytest.raises(ValueError):
        AdmissionThrottleAction(
            action_type="ALLOW",
            delay_ms=0.0,
            reason="ok",
            timestamp=0.0,
        )


# CRUX-MK
