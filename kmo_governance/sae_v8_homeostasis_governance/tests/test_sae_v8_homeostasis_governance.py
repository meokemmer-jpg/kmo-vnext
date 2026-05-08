# [CRUX-MK]
"""Tests fuer SAEv8HomeostasisGovernance (Welle-34 Phase-27 Bio-Pattern-Lift).

Bio-Aequivalent: Thermoregulation auf SAE-Governance-Tier-Setpoint.
Setpoint-basierte Feedback-Regelung mit RELEGATE/PROMOTE/HALT-Aktionen
ueber/unter Schwellen, Rolling-Average ueber history_window Samples.
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.sae_v8_homeostasis_governance import (
    GovernanceSample,
    GovernanceState,
    SAEGovernanceDecision,
    SAEv8HomeostasisGovernance,
    SlotAdjustmentAction,
)


# ---------- 1. Init Validation ----------


def test_init_validation():
    # setpoint_q_norm in [-2, +2]
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(setpoint_q_norm=-2.1)
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(setpoint_q_norm=2.1)

    # mild_threshold_pct must be > 0
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(mild_threshold_pct=0.0)
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(mild_threshold_pct=-1.0)

    # critical_threshold_pct must be > mild_threshold_pct
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(
            mild_threshold_pct=10.0,
            critical_threshold_pct=10.0,
        )
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(
            mild_threshold_pct=20.0,
            critical_threshold_pct=10.0,
        )

    # history_window must be >= 1
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(history_window=0)
    with pytest.raises(ValueError):
        SAEv8HomeostasisGovernance(history_window=-1)

    # Valid construction
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
        history_window=50,
    )
    assert gov.setpoint_q_norm == 0.0
    assert gov.mild_threshold_pct == 10.0
    assert gov.critical_threshold_pct == 30.0
    assert gov.history_window == 50

    # Boundary: setpoint_q_norm = -2 (Floor)
    gov_min = SAEv8HomeostasisGovernance(setpoint_q_norm=-2.0)
    assert gov_min.setpoint_q_norm == -2.0

    # Boundary: setpoint_q_norm = +2 (Ceiling)
    gov_max = SAEv8HomeostasisGovernance(setpoint_q_norm=2.0)
    assert gov_max.setpoint_q_norm == 2.0


# ---------- 2. Initial State NORMAL ----------


def test_initial_state_normal():
    gov = SAEv8HomeostasisGovernance(setpoint_q_norm=0.0)
    decision = gov.evaluate()
    assert decision.state == GovernanceState.NORMAL
    assert decision.current_q_norm == 0.0  # setpoint default
    assert decision.setpoint_q_norm == 0.0
    assert decision.deviation_pct == 0.0
    assert decision.action is None
    assert "no governance samples" in decision.reason


# ---------- 3. record_governance Appends ----------


def test_record_governance_appends():
    gov = SAEv8HomeostasisGovernance(setpoint_q_norm=0.0)
    assert len(gov.get_history()) == 0
    gov.record_governance("slot-001", 0.0)
    assert len(gov.get_history()) == 1
    gov.record_governance("slot-001", 0.2)
    gov.record_governance("slot-001", 0.4)
    assert len(gov.get_history()) == 3
    samples = gov.get_history()
    assert samples[0].q_norm == 0.0
    assert samples[2].q_norm == 0.4
    assert all(isinstance(s, GovernanceSample) for s in samples)
    assert all(s.slot_id == "slot-001" for s in samples)


# ---------- 4. record_governance: invalid q_norm raises ----------


def test_record_invalid_q_norm_raises():
    gov = SAEv8HomeostasisGovernance(setpoint_q_norm=0.0)
    # q_norm < -2 verboten
    with pytest.raises(ValueError):
        gov.record_governance("slot-001", -2.5)
    # q_norm > +2 verboten
    with pytest.raises(ValueError):
        gov.record_governance("slot-001", 2.5)
    # Boundary: q_norm = -2 erlaubt
    gov.record_governance("slot-001", -2.0)
    # Boundary: q_norm = +2 erlaubt
    gov.record_governance("slot-001", 2.0)
    assert len(gov.get_history()) == 2


# ---------- 5. Within Setpoint -> NORMAL ----------


def test_within_setpoint_normal():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
    )
    # Average q_norm = 0.1, deviation = 0.1/4*100 = 2.5% < 10% mild
    gov.record_governance("slot-001", 0.0)
    gov.record_governance("slot-001", 0.1)
    gov.record_governance("slot-001", 0.2)
    decision = gov.evaluate("slot-001")
    assert decision.state == GovernanceState.NORMAL
    assert decision.action is None
    assert abs(decision.current_q_norm - 0.1) < 0.001
    # deviation_pct = (0.1 - 0.0) / 4 * 100 = 2.5%
    assert abs(decision.deviation_pct - 2.5) < 0.01


# ---------- 6. Above Mild -> RELEGATING_SLOT ----------


def test_above_mild_triggers_relegating():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
    )
    # Average q_norm = 0.6, deviation = 0.6/4*100 = 15% > 10% mild, < 30% critical
    gov.record_governance("slot-001", 0.6)
    gov.record_governance("slot-001", 0.6)
    gov.record_governance("slot-001", 0.6)
    decision = gov.evaluate("slot-001")
    assert decision.state == GovernanceState.RELEGATING_SLOT
    assert decision.action is not None
    assert decision.action.action_type == "RELEGATE"
    assert decision.action.target_slot_id == "slot-001"
    assert decision.action.magnitude_pct > 0
    # magnitude_pct = abs_dev = 15%
    assert abs(decision.action.magnitude_pct - 15.0) < 0.01


# ---------- 7. Below Mild -> PROMOTING_SLOT ----------


def test_below_mild_triggers_promoting():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
    )
    # Average q_norm = -0.6, deviation = -0.6/4*100 = -15% < -10% mild, > -30% critical
    gov.record_governance("slot-001", -0.6)
    gov.record_governance("slot-001", -0.6)
    gov.record_governance("slot-001", -0.6)
    decision = gov.evaluate("slot-001")
    assert decision.state == GovernanceState.PROMOTING_SLOT
    assert decision.action is not None
    assert decision.action.action_type == "PROMOTE"
    assert decision.action.target_slot_id == "slot-001"
    assert abs(decision.action.magnitude_pct - 15.0) < 0.01


# ---------- 8. Above Critical -> CRITICAL + HALT ----------


def test_above_critical_returns_critical():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
    )
    # Average q_norm = 1.5, deviation = 1.5/4*100 = 37.5% >= 30% critical
    gov.record_governance("slot-001", 1.5)
    gov.record_governance("slot-001", 1.5)
    decision = gov.evaluate("slot-001")
    assert decision.state == GovernanceState.CRITICAL
    assert decision.action is not None
    assert decision.action.action_type == "HALT"  # Cliff-Effect-Schutz K_0
    assert decision.action.magnitude_pct == 0.0  # HALT hat keine Magnitude

    # Auch bei negativer Deviation (q_norm weit unter Setpoint)
    gov2 = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
    )
    gov2.record_governance("slot-002", -1.5)
    gov2.record_governance("slot-002", -1.5)
    decision2 = gov2.evaluate("slot-002")
    assert decision2.state == GovernanceState.CRITICAL
    assert decision2.action.action_type == "HALT"


# ---------- 9. Rolling Average Smoothing (single spike doesnt trigger) ----------


def test_uses_rolling_avg():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
        history_window=10,
    )
    # 9 normale Samples bei q_norm=0.0
    for _ in range(9):
        gov.record_governance("slot-001", 0.0)
    # 1 Spike bei q_norm=2.0 -> Average = (9*0 + 2.0) / 10 = 0.2
    # deviation = 0.2/4*100 = 5% < 10% mild -> kein Trigger
    gov.record_governance("slot-001", 2.0)
    decision = gov.evaluate("slot-001")
    assert decision.state == GovernanceState.NORMAL
    assert decision.action is None
    # Beweist: Single-Spike triggert nicht (Whipsaw-Schutz gegen
    # Reward-Stream-Spikes auf einzelne Slots)


# ---------- 10. register_action Custom ----------


def test_register_custom_action():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
    )

    custom_called = []

    def custom_relegator(deviation_pct: float) -> SlotAdjustmentAction:
        custom_called.append(deviation_pct)
        # Halbe Magnitude (custom Logik, z.B. abgeschwaechte Reaktion)
        return SlotAdjustmentAction(
            action_type="RELEGATE",
            target_slot_id="slot-001",
            magnitude_pct=abs(deviation_pct) / 2,
            reason=f"custom-half: dev={deviation_pct:.2f}",
            timestamp=time.time(),
        )

    gov.register_action(GovernanceState.RELEGATING_SLOT, custom_relegator)

    # Trigger RELEGATING_SLOT (q_norm=0.8 -> deviation=20% > 10% mild)
    gov.record_governance("slot-001", 0.8)
    gov.record_governance("slot-001", 0.8)
    decision = gov.evaluate("slot-001")
    assert decision.state == GovernanceState.RELEGATING_SLOT
    assert len(custom_called) == 1
    assert decision.action is not None
    assert "custom-half" in decision.action.reason
    # custom magnitude = 20% / 2 = 10%
    assert abs(decision.action.magnitude_pct - 10.0) < 0.01

    # Validation: state Pflicht-Typ
    with pytest.raises(TypeError):
        gov.register_action("not_a_state", custom_relegator)
    # Validation: action_fn callable
    with pytest.raises(TypeError):
        gov.register_action(GovernanceState.CRITICAL, "not_callable")


# ---------- 11. history_window Limits ----------


def test_history_window_limits():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        history_window=10,
    )
    # 100 Samples appenden
    for i in range(100):
        gov.record_governance("slot-001", (i % 5) * 0.1)
    # History capped bei 10 (deque maxlen)
    history = gov.get_history()
    assert len(history) == 10
    assert all(isinstance(s, GovernanceSample) for s in history)


# ---------- 12. Reset Clears ----------


def test_reset_clears():
    gov = SAEv8HomeostasisGovernance(setpoint_q_norm=0.0)
    # Custom action register
    gov.register_action(
        GovernanceState.CRITICAL,
        lambda d: SlotAdjustmentAction(
            action_type="HALT",
            target_slot_id="slot-001",
            magnitude_pct=0.0,
            reason="custom-halt",
            timestamp=time.time(),
        ),
    )
    # Samples + Decision
    gov.record_governance("slot-001", 0.5)
    gov.record_governance("slot-001", 0.5)
    _ = gov.evaluate("slot-001")
    assert len(gov.get_history()) == 2
    assert len(gov.get_decisions()) == 1

    gov.reset()
    assert len(gov.get_history()) == 0
    assert len(gov.get_decisions()) == 0
    # Custom action bleibt registriert -> trigger erneut um zu beweisen
    gov.record_governance("slot-001", 1.5)
    gov.record_governance("slot-001", 1.5)
    decision = gov.evaluate("slot-001")
    # CRITICAL state still uses custom action
    assert decision.state == GovernanceState.CRITICAL
    assert decision.action.reason == "custom-halt"


# ---------- 13. Concurrent Record (50 threads) ----------


def test_concurrent_record_50_threads():
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        history_window=200,
    )

    def worker(value: float) -> None:
        for _ in range(4):
            gov.record_governance("slot-001", value)

    threads = [
        threading.Thread(target=worker, args=((i % 10) * 0.05,))
        for i in range(50)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    history = gov.get_history()
    # 50 threads * 4 records = 200 -> exakt history_window-Cap
    assert len(history) == 200
    # Keine Race-Conditions (alle Samples valid)
    assert all(isinstance(s, GovernanceSample) for s in history)
    assert all(s.slot_id == "slot-001" for s in history)


# ---------- 14. Decision Frozen (immutable) ----------


def test_decision_frozen():
    gov = SAEv8HomeostasisGovernance(setpoint_q_norm=0.0)
    gov.record_governance("slot-001", 0.0)
    decision = gov.evaluate("slot-001")
    assert isinstance(decision, SAEGovernanceDecision)
    with pytest.raises((AttributeError, TypeError)):
        decision.state = GovernanceState.CRITICAL  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        decision.deviation_pct = 99.0  # type: ignore[misc]
    # Validation in Decision-Constructor
    with pytest.raises(ValueError):
        SAEGovernanceDecision(
            state=GovernanceState.NORMAL,
            current_q_norm=0.0,
            setpoint_q_norm=0.0,
            deviation_pct=0.0,
            action=None,
            reason="",
            timestamp=time.time(),
        )
    with pytest.raises(ValueError):
        SAEGovernanceDecision(
            state=GovernanceState.NORMAL,
            current_q_norm=0.0,
            setpoint_q_norm=0.0,
            deviation_pct=0.0,
            action=None,
            reason="ok",
            timestamp=0.0,
        )


# ---------- 15. Action Frozen (immutable) ----------


def test_action_frozen():
    action = SlotAdjustmentAction(
        action_type="RELEGATE",
        target_slot_id="slot-001",
        magnitude_pct=15.0,
        reason="test",
        timestamp=time.time(),
    )
    with pytest.raises((AttributeError, TypeError)):
        action.action_type = "PROMOTE"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        action.magnitude_pct = 99.0  # type: ignore[misc]

    # Validation: action_type whitelist
    with pytest.raises(ValueError):
        SlotAdjustmentAction(
            action_type="UNKNOWN",
            target_slot_id="slot-001",
            magnitude_pct=5.0,
            reason="x",
            timestamp=time.time(),
        )
    # Validation: magnitude_pct >= 0
    with pytest.raises(ValueError):
        SlotAdjustmentAction(
            action_type="RELEGATE",
            target_slot_id="slot-001",
            magnitude_pct=-1.0,
            reason="x",
            timestamp=time.time(),
        )
    # Validation: target_slot_id non-empty
    with pytest.raises(ValueError):
        SlotAdjustmentAction(
            action_type="RELEGATE",
            target_slot_id="",
            magnitude_pct=1.0,
            reason="x",
            timestamp=time.time(),
        )
    # Validation: reason non-empty
    with pytest.raises(ValueError):
        SlotAdjustmentAction(
            action_type="RELEGATE",
            target_slot_id="slot-001",
            magnitude_pct=1.0,
            reason="",
            timestamp=time.time(),
        )
    # Validation: timestamp > 0
    with pytest.raises(ValueError):
        SlotAdjustmentAction(
            action_type="RELEGATE",
            target_slot_id="slot-001",
            magnitude_pct=1.0,
            reason="x",
            timestamp=0.0,
        )
    # HALT mit magnitude_pct = 0 ist erlaubt
    halt = SlotAdjustmentAction(
        action_type="HALT",
        target_slot_id="slot-001",
        magnitude_pct=0.0,
        reason="critical",
        timestamp=time.time(),
    )
    assert halt.action_type == "HALT"


# ---------- 16. get_history Returns Snapshot ----------


def test_get_history_snapshot():
    gov = SAEv8HomeostasisGovernance(setpoint_q_norm=0.0)
    gov.record_governance("slot-001", 0.0)
    gov.record_governance("slot-001", 0.1)
    snapshot = gov.get_history()
    # Snapshot ist Tuple (immutable) -> kann nicht mutiert werden
    assert isinstance(snapshot, tuple)
    with pytest.raises((AttributeError, TypeError)):
        snapshot.append(  # type: ignore[attr-defined]
            GovernanceSample(
                timestamp=time.time(),
                slot_id="slot-001",
                q_norm=0.5,
            )
        )
    # Original-History bleibt unveraendert (Snapshot != live-deque)
    gov.record_governance("slot-001", 0.2)
    new_snapshot = gov.get_history()
    assert len(new_snapshot) == 3
    assert len(snapshot) == 2  # alter Snapshot unveraendert

    # Decisions ebenfalls als immutable tuple
    _ = gov.evaluate("slot-001")
    decisions = gov.get_decisions()
    assert isinstance(decisions, tuple)
    assert len(decisions) == 1


# ---------- 17. Bonus: GovernanceSample Validation ----------


def test_governance_sample_validation():
    # Valid
    s = GovernanceSample(
        timestamp=time.time(),
        slot_id="slot-001",
        q_norm=0.5,
    )
    assert s.q_norm == 0.5

    # slot_id non-empty
    with pytest.raises(ValueError):
        GovernanceSample(
            timestamp=time.time(),
            slot_id="",
            q_norm=0.0,
        )
    # timestamp > 0
    with pytest.raises(ValueError):
        GovernanceSample(
            timestamp=0.0,
            slot_id="slot-001",
            q_norm=0.0,
        )
    # q_norm in [-2, +2]
    with pytest.raises(ValueError):
        GovernanceSample(
            timestamp=time.time(),
            slot_id="slot-001",
            q_norm=-2.5,
        )
    with pytest.raises(ValueError):
        GovernanceSample(
            timestamp=time.time(),
            slot_id="slot-001",
            q_norm=2.5,
        )
    # Frozen
    with pytest.raises((AttributeError, TypeError)):
        s.q_norm = 1.0  # type: ignore[misc]


# ---------- 18. Bonus: Multi-Slot Filter (slot_id=None vs filter) ----------


def test_multi_slot_filtering():
    """Controller kann optional auf bestimmten slot_id filtern."""
    gov = SAEv8HomeostasisGovernance(
        setpoint_q_norm=0.0,
        mild_threshold_pct=10.0,
        critical_threshold_pct=30.0,
    )
    # Mix von slot-001 und slot-002
    gov.record_governance("slot-001", 0.0)
    gov.record_governance("slot-002", 1.5)  # Critical-Range
    gov.record_governance("slot-001", 0.1)
    gov.record_governance("slot-002", 1.5)
    gov.record_governance("slot-001", 0.2)

    # Filter auf slot-001: avg = 0.1, deviation = 2.5% -> NORMAL
    decision_001 = gov.evaluate("slot-001")
    assert decision_001.state == GovernanceState.NORMAL
    assert abs(decision_001.current_q_norm - 0.1) < 0.001

    # Filter auf slot-002: avg = 1.5, deviation = 37.5% -> CRITICAL
    decision_002 = gov.evaluate("slot-002")
    assert decision_002.state == GovernanceState.CRITICAL
    assert decision_002.action.action_type == "HALT"
    assert decision_002.action.target_slot_id == "slot-002"

    # Kein Filter (slot_id=None) -> aggregiert alle Samples
    # avg = (0.0 + 1.5 + 0.1 + 1.5 + 0.2) / 5 = 0.66, deviation = 16.5%
    # -> RELEGATING_SLOT (mild < 16.5% < critical)
    decision_all = gov.evaluate(slot_id=None)
    assert decision_all.state == GovernanceState.RELEGATING_SLOT
    assert decision_all.action.target_slot_id == "ALL_SLOTS"

    # History enthaelt alle Samples (Audit-Trail)
    assert len(gov.get_history()) == 5


# CRUX-MK
