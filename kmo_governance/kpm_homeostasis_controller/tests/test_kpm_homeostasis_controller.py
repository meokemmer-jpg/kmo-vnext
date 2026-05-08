# [CRUX-MK]
"""Tests fuer KPMHomeostasisController (Welle-26 Phase-19 Bio-Pattern-Lift).

Bio-Aequivalent: Thermoregulation auf Portfolio-Drift-Setpoint.
Setpoint-basierte Feedback-Regelung mit REDUCE/INCREASE/HALT-Aktionen
ueber/unter Schwellen, Rolling-Average ueber history_window Samples.
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.kpm_homeostasis_controller import (
    AllocationSample,
    HomeostasisState,
    KPMHomeostasisController,
    KPMHomeostasisDecision,
    RebalanceAction,
)


# ---------- 1. Init Validation ----------


def test_init_validation():
    # setpoint_pct in [0, 100]
    with pytest.raises(ValueError):
        KPMHomeostasisController(setpoint_pct=-1.0, asset_class="equities")
    with pytest.raises(ValueError):
        KPMHomeostasisController(setpoint_pct=101.0, asset_class="equities")

    # asset_class non-empty
    with pytest.raises(ValueError):
        KPMHomeostasisController(setpoint_pct=60.0, asset_class="")

    # mild_threshold_pct must be > 0
    with pytest.raises(ValueError):
        KPMHomeostasisController(
            setpoint_pct=60.0,
            asset_class="equities",
            mild_threshold_pct=0.0,
        )
    with pytest.raises(ValueError):
        KPMHomeostasisController(
            setpoint_pct=60.0,
            asset_class="equities",
            mild_threshold_pct=-1.0,
        )

    # critical_threshold_pct must be > mild_threshold_pct
    with pytest.raises(ValueError):
        KPMHomeostasisController(
            setpoint_pct=60.0,
            asset_class="equities",
            mild_threshold_pct=5.0,
            critical_threshold_pct=5.0,
        )
    with pytest.raises(ValueError):
        KPMHomeostasisController(
            setpoint_pct=60.0,
            asset_class="equities",
            mild_threshold_pct=10.0,
            critical_threshold_pct=5.0,
        )

    # history_window must be >= 1
    with pytest.raises(ValueError):
        KPMHomeostasisController(
            setpoint_pct=60.0,
            asset_class="equities",
            history_window=0,
        )
    with pytest.raises(ValueError):
        KPMHomeostasisController(
            setpoint_pct=60.0,
            asset_class="equities",
            history_window=-1,
        )

    # Valid construction
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
        history_window=20,
    )
    assert ctrl.setpoint_pct == 60.0
    assert ctrl.asset_class == "equities"
    assert ctrl.mild_threshold_pct == 5.0
    assert ctrl.critical_threshold_pct == 15.0
    assert ctrl.history_window == 20

    # Boundary: setpoint_pct=0 allowed (no equities exposure target)
    ctrl0 = KPMHomeostasisController(setpoint_pct=0.0, asset_class="cash")
    assert ctrl0.setpoint_pct == 0.0

    # Boundary: setpoint_pct=100 allowed (full allocation)
    ctrl100 = KPMHomeostasisController(setpoint_pct=100.0, asset_class="cash")
    assert ctrl100.setpoint_pct == 100.0


# ---------- 2. Initial State NORMAL ----------


def test_initial_state_normal():
    ctrl = KPMHomeostasisController(setpoint_pct=60.0, asset_class="equities")
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.NORMAL
    assert decision.current_allocation_pct == 60.0  # setpoint default
    assert decision.setpoint_pct == 60.0
    assert decision.deviation_pct == 0.0
    assert decision.action is None
    assert "no allocations" in decision.reason


# ---------- 3. record_allocation Appends ----------


def test_record_allocation_appends():
    ctrl = KPMHomeostasisController(setpoint_pct=60.0, asset_class="equities")
    assert len(ctrl.get_history()) == 0
    ctrl.record_allocation("equities", 60.0)
    assert len(ctrl.get_history()) == 1
    ctrl.record_allocation("equities", 62.0)
    ctrl.record_allocation("equities", 64.0)
    assert len(ctrl.get_history()) == 3
    samples = ctrl.get_history()
    assert samples[0].allocation_pct == 60.0
    assert samples[2].allocation_pct == 64.0
    assert all(isinstance(s, AllocationSample) for s in samples)
    assert all(s.asset_class == "equities" for s in samples)


# ---------- 4. Within Setpoint -> NORMAL ----------


def test_within_setpoint_normal():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
    )
    # Average = 61pp, deviation = 1pp < 5pp mild
    ctrl.record_allocation("equities", 60.0)
    ctrl.record_allocation("equities", 61.0)
    ctrl.record_allocation("equities", 62.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.NORMAL
    assert decision.action is None
    assert abs(decision.current_allocation_pct - 61.0) < 0.001
    assert abs(decision.deviation_pct - 1.0) < 0.001


# ---------- 5. Above Mild -> REDUCING_POSITION ----------


def test_above_mild_triggers_reducing():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
    )
    # Average = 67pp, deviation = +7pp > +5pp mild, < +15pp critical
    ctrl.record_allocation("equities", 67.0)
    ctrl.record_allocation("equities", 67.0)
    ctrl.record_allocation("equities", 67.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.REDUCING_POSITION
    assert decision.action is not None
    assert decision.action.action_type == "REDUCE"
    assert decision.action.target_asset_class == "equities"
    assert decision.action.magnitude_pct > 0
    assert abs(decision.action.magnitude_pct - 7.0) < 0.001


# ---------- 6. Below Mild -> INCREASING_POSITION ----------


def test_below_mild_triggers_increasing():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
    )
    # Average = 53pp, deviation = -7pp < -5pp mild, > -15pp critical
    ctrl.record_allocation("equities", 53.0)
    ctrl.record_allocation("equities", 53.0)
    ctrl.record_allocation("equities", 53.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.INCREASING_POSITION
    assert decision.action is not None
    assert decision.action.action_type == "INCREASE"
    assert decision.action.target_asset_class == "equities"
    assert abs(decision.action.magnitude_pct - 7.0) < 0.001


# ---------- 7. Above Critical -> CRITICAL + HALT ----------


def test_above_critical_returns_critical():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
    )
    # Average = 80pp, deviation = +20pp >= +15pp critical
    ctrl.record_allocation("equities", 80.0)
    ctrl.record_allocation("equities", 80.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.CRITICAL
    assert decision.action is not None
    assert decision.action.action_type == "HALT"  # Cliff-Effect-Schutz K_0
    assert decision.action.magnitude_pct == 0.0  # HALT hat keine Magnitude

    # Auch bei negativer Deviation (Allocation weit unter Setpoint)
    ctrl2 = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
    )
    ctrl2.record_allocation("equities", 40.0)
    ctrl2.record_allocation("equities", 40.0)
    decision2 = ctrl2.evaluate()
    assert decision2.state == HomeostasisState.CRITICAL
    assert decision2.action.action_type == "HALT"


# ---------- 8. Rolling Average Smoothing (single spike doesnt trigger) ----------


def test_uses_rolling_avg():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
        history_window=10,
    )
    # 9 normale Samples bei 60pp
    for _ in range(9):
        ctrl.record_allocation("equities", 60.0)
    # 1 Spike bei 90pp -> Average = (9*60 + 90) / 10 = 63pp -> deviation 3pp < 5pp mild
    ctrl.record_allocation("equities", 90.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.NORMAL
    assert decision.action is None
    # Beweist: Single-Spike triggert nicht (Whipsaw-Schutz)


# ---------- 9. register_action Custom ----------


def test_register_custom_action():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
    )

    custom_called = []

    def custom_reducer(deviation_pct: float) -> RebalanceAction:
        custom_called.append(deviation_pct)
        # Halbe Magnitude (custom Logik, z.B. abgeschwaechte Reaktion)
        return RebalanceAction(
            action_type="REDUCE",
            target_asset_class="equities",
            magnitude_pct=abs(deviation_pct) / 2,
            reason=f"custom-half: dev={deviation_pct:.2f}",
            timestamp=time.time(),
        )

    ctrl.register_action(HomeostasisState.REDUCING_POSITION, custom_reducer)

    # Trigger REDUCING_POSITION
    ctrl.record_allocation("equities", 68.0)
    ctrl.record_allocation("equities", 68.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.REDUCING_POSITION
    assert len(custom_called) == 1
    assert decision.action is not None
    assert "custom-half" in decision.action.reason
    # custom magnitude = 8pp / 2 = 4pp
    assert abs(decision.action.magnitude_pct - 4.0) < 0.001

    # Validation: state Pflicht-Typ
    with pytest.raises(TypeError):
        ctrl.register_action("not_a_state", custom_reducer)
    # Validation: action_fn callable
    with pytest.raises(TypeError):
        ctrl.register_action(HomeostasisState.CRITICAL, "not_callable")


# ---------- 10. history_window Limits ----------


def test_history_window_limits():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        history_window=10,
    )
    # 100 Samples appenden
    for i in range(100):
        ctrl.record_allocation("equities", 60.0 + (i % 5))
    # History capped bei 10 (deque maxlen)
    history = ctrl.get_history()
    assert len(history) == 10
    # Letzter Eintrag hat den hoechsten Index-basierenden Wert (95-99 mod 5)
    # Wir pruefen nur die Gesamtlaenge + Reset-Effekt
    assert all(isinstance(s, AllocationSample) for s in history)


# ---------- 11. Reset Clears ----------


def test_reset_clears():
    ctrl = KPMHomeostasisController(setpoint_pct=60.0, asset_class="equities")
    # Custom action register
    ctrl.register_action(
        HomeostasisState.CRITICAL,
        lambda d: RebalanceAction(
            action_type="HALT",
            target_asset_class="equities",
            magnitude_pct=0.0,
            reason="custom-halt",
            timestamp=time.time(),
        ),
    )
    # Samples + Decision
    ctrl.record_allocation("equities", 70.0)
    ctrl.record_allocation("equities", 70.0)
    _ = ctrl.evaluate()
    assert len(ctrl.get_history()) == 2
    assert len(ctrl.get_decisions()) == 1

    ctrl.reset()
    assert len(ctrl.get_history()) == 0
    assert len(ctrl.get_decisions()) == 0
    # Custom action bleibt registriert -> trigger erneut um zu beweisen
    ctrl.record_allocation("equities", 80.0)
    ctrl.record_allocation("equities", 80.0)
    decision = ctrl.evaluate()
    # CRITICAL state still uses custom action
    assert decision.state == HomeostasisState.CRITICAL
    assert decision.action.reason == "custom-halt"


# ---------- 12. Concurrent Record (50 threads) ----------


def test_concurrent_record_50_threads():
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        history_window=200,
    )

    def worker(value: float) -> None:
        for _ in range(4):
            ctrl.record_allocation("equities", value)

    threads = [
        threading.Thread(target=worker, args=(60.0 + (i % 10),))
        for i in range(50)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    history = ctrl.get_history()
    # 50 threads * 4 records = 200 -> exakt history_window-Cap
    assert len(history) == 200
    # Keine Race-Conditions (alle Samples valid)
    assert all(isinstance(s, AllocationSample) for s in history)
    assert all(s.asset_class == "equities" for s in history)


# ---------- 13. Decision Frozen (immutable) ----------


def test_decision_frozen():
    ctrl = KPMHomeostasisController(setpoint_pct=60.0, asset_class="equities")
    ctrl.record_allocation("equities", 60.0)
    decision = ctrl.evaluate()
    assert isinstance(decision, KPMHomeostasisDecision)
    with pytest.raises((AttributeError, TypeError)):
        decision.state = HomeostasisState.CRITICAL  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        decision.deviation_pct = 99.0  # type: ignore[misc]
    # Validation in Decision-Constructor
    with pytest.raises(ValueError):
        KPMHomeostasisDecision(
            state=HomeostasisState.NORMAL,
            current_allocation_pct=60.0,
            setpoint_pct=60.0,
            deviation_pct=0.0,
            action=None,
            reason="",
            timestamp=time.time(),
        )
    with pytest.raises(ValueError):
        KPMHomeostasisDecision(
            state=HomeostasisState.NORMAL,
            current_allocation_pct=60.0,
            setpoint_pct=60.0,
            deviation_pct=0.0,
            action=None,
            reason="ok",
            timestamp=0.0,
        )


# ---------- 14. Action Frozen (immutable) ----------


def test_action_frozen():
    action = RebalanceAction(
        action_type="REDUCE",
        target_asset_class="equities",
        magnitude_pct=5.0,
        reason="test",
        timestamp=time.time(),
    )
    with pytest.raises((AttributeError, TypeError)):
        action.action_type = "INCREASE"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        action.magnitude_pct = 99.0  # type: ignore[misc]

    # Validation: action_type whitelist
    with pytest.raises(ValueError):
        RebalanceAction(
            action_type="UNKNOWN",
            target_asset_class="equities",
            magnitude_pct=5.0,
            reason="x",
            timestamp=time.time(),
        )
    # Validation: magnitude_pct >= 0
    with pytest.raises(ValueError):
        RebalanceAction(
            action_type="REDUCE",
            target_asset_class="equities",
            magnitude_pct=-1.0,
            reason="x",
            timestamp=time.time(),
        )
    # Validation: target_asset_class non-empty
    with pytest.raises(ValueError):
        RebalanceAction(
            action_type="REDUCE",
            target_asset_class="",
            magnitude_pct=1.0,
            reason="x",
            timestamp=time.time(),
        )
    # Validation: reason non-empty
    with pytest.raises(ValueError):
        RebalanceAction(
            action_type="REDUCE",
            target_asset_class="equities",
            magnitude_pct=1.0,
            reason="",
            timestamp=time.time(),
        )
    # Validation: timestamp > 0
    with pytest.raises(ValueError):
        RebalanceAction(
            action_type="REDUCE",
            target_asset_class="equities",
            magnitude_pct=1.0,
            reason="x",
            timestamp=0.0,
        )
    # HALT mit magnitude_pct = 0 ist erlaubt
    halt = RebalanceAction(
        action_type="HALT",
        target_asset_class="equities",
        magnitude_pct=0.0,
        reason="critical",
        timestamp=time.time(),
    )
    assert halt.action_type == "HALT"


# ---------- 15. get_history Returns Snapshot ----------


def test_get_history_snapshot():
    ctrl = KPMHomeostasisController(setpoint_pct=60.0, asset_class="equities")
    ctrl.record_allocation("equities", 60.0)
    ctrl.record_allocation("equities", 61.0)
    snapshot = ctrl.get_history()
    # Snapshot ist Tuple (immutable) -> kann nicht mutiert werden
    assert isinstance(snapshot, tuple)
    with pytest.raises((AttributeError, TypeError)):
        snapshot.append(  # type: ignore[attr-defined]
            AllocationSample(
                timestamp=time.time(),
                asset_class="equities",
                allocation_pct=99.0,
            )
        )
    # Original-History bleibt unveraendert (Snapshot != live-deque)
    ctrl.record_allocation("equities", 62.0)
    new_snapshot = ctrl.get_history()
    assert len(new_snapshot) == 3
    assert len(snapshot) == 2  # alter Snapshot unveraendert

    # Decisions ebenfalls als immutable tuple
    _ = ctrl.evaluate()
    decisions = ctrl.get_decisions()
    assert isinstance(decisions, tuple)
    assert len(decisions) == 1


# ---------- 16. Setpoint Zero Handling (cash-only Allocation) ----------


def test_setpoint_zero_handling():
    """Setpoint 0% (no allocation) als Edge-Case (z.B. kein Equities-Exposure)."""
    ctrl = KPMHomeostasisController(
        setpoint_pct=0.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
    )
    # 0% allocation -> NORMAL
    ctrl.record_allocation("equities", 0.0)
    ctrl.record_allocation("equities", 0.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.NORMAL
    assert decision.deviation_pct == 0.0

    # 7% allocation aber Setpoint=0 -> REDUCING (Equities sollten 0 sein)
    ctrl.reset()
    ctrl.record_allocation("equities", 7.0)
    ctrl.record_allocation("equities", 7.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.REDUCING_POSITION
    assert decision.action is not None
    assert decision.action.action_type == "REDUCE"

    # 20% allocation aber Setpoint=0 -> CRITICAL
    ctrl.reset()
    ctrl.record_allocation("equities", 20.0)
    ctrl.record_allocation("equities", 20.0)
    decision = ctrl.evaluate()
    assert decision.state == HomeostasisState.CRITICAL
    assert decision.action.action_type == "HALT"


# ---------- 17. Bonus: AllocationSample Validation ----------


def test_allocation_sample_validation():
    # Valid
    s = AllocationSample(
        timestamp=time.time(),
        asset_class="equities",
        allocation_pct=60.0,
    )
    assert s.allocation_pct == 60.0

    # asset_class non-empty
    with pytest.raises(ValueError):
        AllocationSample(
            timestamp=time.time(),
            asset_class="",
            allocation_pct=60.0,
        )
    # timestamp > 0
    with pytest.raises(ValueError):
        AllocationSample(
            timestamp=0.0,
            asset_class="equities",
            allocation_pct=60.0,
        )
    # allocation_pct in [0, 100]
    with pytest.raises(ValueError):
        AllocationSample(
            timestamp=time.time(),
            asset_class="equities",
            allocation_pct=-1.0,
        )
    with pytest.raises(ValueError):
        AllocationSample(
            timestamp=time.time(),
            asset_class="equities",
            allocation_pct=101.0,
        )
    # Frozen
    with pytest.raises((AttributeError, TypeError)):
        s.allocation_pct = 99.0  # type: ignore[misc]


# ---------- 18. Bonus: Mixed asset_class Filter ----------


def test_mixed_asset_class_filtering():
    """Controller fuer 'equities' filtert Samples anderer asset_classes raus."""
    ctrl = KPMHomeostasisController(
        setpoint_pct=60.0,
        asset_class="equities",
        mild_threshold_pct=5.0,
        critical_threshold_pct=15.0,
    )
    # Mix von equities + bonds
    ctrl.record_allocation("equities", 60.0)
    ctrl.record_allocation("bonds", 90.0)  # ignoriert (andere asset_class)
    ctrl.record_allocation("equities", 61.0)
    ctrl.record_allocation("bonds", 95.0)  # ignoriert
    ctrl.record_allocation("equities", 62.0)
    decision = ctrl.evaluate()
    # Average aus equities-only = 61pp -> deviation = 1pp -> NORMAL
    assert decision.state == HomeostasisState.NORMAL
    assert abs(decision.current_allocation_pct - 61.0) < 0.001

    # History enthaelt aber alle Samples (Audit-Trail)
    assert len(ctrl.get_history()) == 5


# CRUX-MK
