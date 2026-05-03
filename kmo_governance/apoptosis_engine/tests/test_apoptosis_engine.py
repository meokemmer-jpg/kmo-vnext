"""KMO Apoptosis-Engine Tests [CRUX-MK].

Spec-Section: SPEC-KMO-VNEXT-BIO-ARCHITEKTUR §Phase-1.2.2 Tests-Block.

Pflicht-Tests (8-10):
- test_apoptose_trigger_state_korruption
- test_apoptose_trigger_stop_flag
- test_apoptose_trigger_max_retries
- test_apoptose_bcl2_protection_delays_death
- test_apoptose_cytochrome_c_snapshot_preserved
- test_apoptose_cascade_3_stages
- test_apoptose_cleanup_idempotent
"""

from __future__ import annotations

import json

import pytest

from kmo_governance.apoptosis_engine import (
    ApoptoseState,
    ApoptosisEngine,
    Bcl2Modulator,
    CascadeStage,
    CytochromeCSnapshotter,
    TriggerType,
)


# ---------------- Fixtures ----------------


@pytest.fixture
def snapshot_root(tmp_path):
    return tmp_path / "apoptose"


@pytest.fixture
def fixed_clock():
    state = {"t": 1_700_000_000.0}

    def clock() -> float:
        return state["t"]

    def tick(dt: float) -> None:
        state["t"] += dt

    clock.tick = tick  # type: ignore[attr-defined]
    return clock


@pytest.fixture
def engine(snapshot_root, fixed_clock):
    return ApoptosisEngine(
        snapshot_dir=snapshot_root,
        threshold=0.5,
        clock=fixed_clock,
    )


# ---------------- Pflicht-Tests ----------------


def test_apoptose_trigger_state_korruption(engine):
    """STATE_KORRUPTION with intensity=1.0 (weight=1.0) -> score=1.0 >= 0.5 -> trigger."""
    state = engine.signal("cell-1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=1.0)
    assert state.cascade_stage == CascadeStage.APOPTOSED
    assert state.apoptose_reason == TriggerType.STATE_KORRUPTION.value
    assert engine.is_apoptosed("cell-1", "hotel-A")


def test_apoptose_trigger_stop_flag(engine):
    """STOP_FLAG has weight=1000 -> immediate trigger even at low intensity."""
    state = engine.signal("cell-1", "hotel-A", TriggerType.STOP_FLAG, intensity=0.001)
    # 1000 * 0.001 = 1.0 >= 0.5
    assert state.cascade_stage == CascadeStage.APOPTOSED
    assert state.apoptose_reason == TriggerType.STOP_FLAG.value


def test_apoptose_trigger_max_retries(engine):
    """MAX_RETRIES weight=0.5 -> needs intensity > 1.0 to trigger alone, accumulates."""
    # First signal: 0.5 * 1.0 = 0.5 (just at threshold but score must be >= eff_threshold)
    state = engine.signal("cell-1", "hotel-A", TriggerType.MAX_RETRIES, intensity=1.0)
    # 0.5 >= 0.5 (default threshold), should trigger
    assert state.cascade_stage == CascadeStage.APOPTOSED

    # Fresh cell: ramp up over multiple signals
    s2 = engine.signal("cell-2", "hotel-A", TriggerType.MAX_RETRIES, intensity=0.5)  # 0.25
    assert s2.cascade_stage == CascadeStage.NOT_TRIGGERED
    s2 = engine.signal("cell-2", "hotel-A", TriggerType.MAX_RETRIES, intensity=0.5)  # 0.5
    assert s2.cascade_stage == CascadeStage.APOPTOSED


def test_apoptose_bcl2_protection_delays_death(snapshot_root, fixed_clock):
    """Bcl-2 protection raises eff_threshold so cell survives single STATE_KORRUPTION signal."""
    bcl2 = Bcl2Modulator(clock=fixed_clock)
    engine = ApoptosisEngine(
        snapshot_dir=snapshot_root,
        bcl2_modulator=bcl2,
        threshold=0.5,
        clock=fixed_clock,
    )
    # Add 2 protections -> offset = log1p(2) ≈ 1.0986 -> eff_threshold ≈ 1.5986
    bcl2.protect_pending_decision("cell-1", "hotel-A", "decision-X", ttl_sec=600)
    bcl2.protect_pending_decision("cell-1", "hotel-A", "decision-Y", ttl_sec=600)

    # State_korruption intensity=1.0 -> score=1.0 < 1.5986 -> NO trigger
    state = engine.signal("cell-1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=1.0)
    assert state.cascade_stage == CascadeStage.NOT_TRIGGERED
    assert state.accumulated_score == pytest.approx(1.0)

    # Release protections; next signal trips threshold
    for tok in [t.token_id for t in bcl2.list_active("cell-1", "hotel-A")]:
        bcl2.release_protection(tok)
    # Now eff_threshold = 0.5; existing score 1.0 already exceeds, but no new signal
    # has been delivered, so nothing fires. Send another tiny signal:
    state = engine.signal("cell-1", "hotel-A", TriggerType.MAX_RETRIES, intensity=0.1)
    # score now 1.0 + 0.05 = 1.05 >= 0.5
    assert state.cascade_stage == CascadeStage.APOPTOSED


def test_apoptose_cytochrome_c_snapshot_preserved(engine, snapshot_root):
    """Snapshot file written before EFFECTOR_CASCADE; contains forensic payload."""
    engine.register_state_provider(
        lambda cid, hid: {"consumed_tokens": 999, "last_op": "booking-write"}
    )
    state = engine.signal("cell-X", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=1.0)
    assert state.snapshot_path is not None
    snap = json.loads(open(state.snapshot_path).read())
    assert snap["cell_id"] == "cell-X"
    assert snap["hotel_id"] == "hotel-A"
    assert snap["apoptose_reason"] == TriggerType.STATE_KORRUPTION.value
    assert snap["cell_state"]["consumed_tokens"] == 999
    assert len(snap["signals"]) == 1
    assert snap["signals"][0]["trigger"] == TriggerType.STATE_KORRUPTION.value


def test_apoptose_cascade_3_stages(engine):
    """Final cascade_stage is APOPTOSED; intermediate stages traversed (CLEANUP last)."""
    state = engine.signal("cell-1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=2.0)
    # 3-stage cascade ran synchronously; final state is APOPTOSED
    assert state.cascade_stage == CascadeStage.APOPTOSED
    # Sanity: cascade module-stage constants are exported
    from kmo_governance.apoptosis_engine import (
        CASCADE_STAGE_CLEANUP,
        CASCADE_STAGE_EFFECTOR_CASCADE,
        CASCADE_STAGE_INITIAL_CHECK,
    )
    assert CASCADE_STAGE_INITIAL_CHECK == "initial_check"
    assert CASCADE_STAGE_EFFECTOR_CASCADE == "effector_cascade"
    assert CASCADE_STAGE_CLEANUP == "cleanup"


def test_apoptose_cleanup_idempotent(engine):
    """Re-signaling an apoptosed cell does not re-run cascade or change state."""
    s1 = engine.signal("cell-1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=2.0)
    snap_path_before = s1.snapshot_path
    # Subsequent signals: appended but no re-cascade
    s2 = engine.signal("cell-1", "hotel-A", TriggerType.MAX_RETRIES, intensity=1.0)
    assert s2.cascade_stage == CascadeStage.APOPTOSED
    assert s2.snapshot_path == snap_path_before  # not re-written
    assert len(s2.signals) == 2  # both events recorded


# ---------------- Edge: trigger_probability ----------------


def test_trigger_probability_sigmoid(engine):
    """trigger_probability = sigmoid(score - eff_threshold) ∈ (0, 1)."""
    p_empty = engine.trigger_probability("cell-new", "hotel-A")
    # score=0, eff_t=0.5 -> sigmoid(-0.5) ≈ 0.378
    assert 0.3 < p_empty < 0.5

    engine.signal("cell-new", "hotel-A", TriggerType.MAX_RETRIES, intensity=0.4)
    # score=0.2, eff_t=0.5 -> sigmoid(-0.3) ≈ 0.426
    p_after = engine.trigger_probability("cell-new", "hotel-A")
    assert p_empty < p_after < 0.5


# ---------------- Edge: Multi-Signal accumulation ----------------


def test_multi_signal_accumulation(engine):
    """Independent signals accumulate; combined score crosses threshold."""
    s = engine.signal("cell-1", "hotel-A", TriggerType.MAX_RETRIES, intensity=0.4)
    assert s.cascade_stage == CascadeStage.NOT_TRIGGERED  # 0.5*0.4 = 0.2
    s = engine.signal("cell-1", "hotel-A", TriggerType.MAX_RETRIES, intensity=0.4)
    assert s.cascade_stage == CascadeStage.NOT_TRIGGERED  # +0.2 = 0.4
    s = engine.signal("cell-1", "hotel-A", TriggerType.MAX_RETRIES, intensity=0.4)
    # +0.2 = 0.6 >= 0.5 -> trigger
    assert s.cascade_stage == CascadeStage.APOPTOSED


# ---------------- Edge: Multi-Tenancy Isolation ----------------


def test_apoptose_hotel_isolation(engine, snapshot_root):
    """Apoptosing hotel-A cell-1 does NOT affect hotel-B cell-1 (Multi-Tenancy)."""
    engine.signal("cell-1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=2.0)
    assert engine.is_apoptosed("cell-1", "hotel-A")
    assert not engine.is_apoptosed("cell-1", "hotel-B")
    # Snapshots are partitioned by hotel
    snapshotter = CytochromeCSnapshotter(snapshot_root)
    a_snaps = snapshotter.list_for_hotel("hotel-A")
    b_snaps = snapshotter.list_for_hotel("hotel-B")
    assert len(a_snaps) == 1
    assert len(b_snaps) == 0


# ---------------- Edge: Bcl-2 expiry releases protection ----------------


def test_bcl2_expiry_releases_protection(snapshot_root, fixed_clock):
    """Expired bcl-2 protection no longer raises eff_threshold."""
    bcl2 = Bcl2Modulator(clock=fixed_clock)
    bcl2.protect_pending_decision("cell-1", "hotel-A", "X", ttl_sec=10)
    assert bcl2.count_active_protections("cell-1", "hotel-A") == 1
    fixed_clock.tick(11)
    assert bcl2.count_active_protections("cell-1", "hotel-A") == 0
    purged = bcl2.purge_expired()
    assert purged == 1


# ---------------- Edge: Snapshot GDPR purge ----------------


def test_snapshot_purge_hotel_gdpr(engine, snapshot_root):
    """purge_hotel removes all snapshots for that hotel."""
    engine.signal("cell-A1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=2.0)
    engine.signal("cell-A2", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=2.0)
    engine.signal("cell-B1", "hotel-B", TriggerType.STATE_KORRUPTION, intensity=2.0)
    snapshotter = CytochromeCSnapshotter(snapshot_root)
    assert len(snapshotter.list_for_hotel("hotel-A")) == 2
    deleted = snapshotter.purge_hotel("hotel-A")
    assert deleted == 2
    assert snapshotter.list_for_hotel("hotel-A") == []
    # Hotel-B unaffected
    assert len(snapshotter.list_for_hotel("hotel-B")) == 1


# ---------------- Edge: invalid input ----------------


def test_invalid_signal_input(engine):
    with pytest.raises(ValueError):
        engine.signal("", "hotel-A", TriggerType.STATE_KORRUPTION)
    with pytest.raises(ValueError):
        engine.signal("cell-1", "", TriggerType.STATE_KORRUPTION)
    with pytest.raises(TypeError):
        engine.signal("cell-1", "hotel-A", "not-a-trigger")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        engine.signal("cell-1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=-1)


# ---------------- Edge: state_provider exception is logged not raised ----------------


def test_state_provider_exception_does_not_block_cascade(engine):
    """If state_provider throws, snapshot still written with error-marker."""
    def bad_provider(cell_id, hotel_id):
        raise RuntimeError("state-provider boom")

    engine.register_state_provider(bad_provider)
    state = engine.signal("cell-1", "hotel-A", TriggerType.STATE_KORRUPTION, intensity=2.0)
    assert state.cascade_stage == CascadeStage.APOPTOSED
    assert state.snapshot_path is not None
    snap = json.loads(open(state.snapshot_path).read())
    assert "_state_provider_error" in snap["cell_state"]
