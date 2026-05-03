"""KMO HeyLou-Pilot E2E Tests [CRUX-MK].

Welle-9α Phase-1.2.5 Pre-Production-Bedingungen:
  - PRE-3 E2E:  full booking pipeline through Cell-Layer
  - PRE-4 Shared-Path: GDPR purge cascade + Multi-Tenancy isolation
  - PRE-5 Stress: 100-thread concurrent cell-quota consume

Phase-1 Skeleton: minimal but real integration through cell+apoptose+wound+saga.
"""

from __future__ import annotations

import threading

import pytest

from kmo_governance.apoptosis_engine import CascadeStage, TriggerType
from kmo_governance.cell_boundary import (
    CellQuota,
    QuotaExhaustedError,
)
from kmo_governance.wound_healing import HealingPhase
from kmo_saga_engine import SagaStatus

from df_executors.df_pilot_hotel_EU import PilotHotelOrchestrator


HOTEL_ID = "apaleo-eu-pilot-001"


# ---------------- Fixtures ----------------


@pytest.fixture
def pilot(tmp_path):
    return PilotHotelOrchestrator(
        hotel_id=HOTEL_ID,
        state_dir=tmp_path / "state",
        audit_db_path=tmp_path / "audit.db",
        snapshot_dir=tmp_path / "apoptose",
        quota=CellQuota(llm_token_budget=10_000, io_calls_per_minute=60),
    )


# ---------------- PRE-3 E2E: full booking pipeline through Cell-Layer ----------------


def test_pre3_e2e_full_booking_pipeline_succeeds(pilot):
    """Saga succeeds; cell-boundary tracks consumption; apoptose NOT triggered."""
    saga = pilot.saga

    def phase1_validate(inp, ctx):
        _, enforcer = pilot.begin_saga_run(ctx["run_id"])
        enforcer.validate_input(inp)
        enforcer.charge_tokens(500, payload={"step": "validate"})
        return {"validated": inp, "next": "reserve"}

    def phase1_undo(inp, out, ctx):
        return None

    def phase2_reserve(inp, ctx):
        _, enforcer = pilot.begin_saga_run(ctx["run_id"])
        enforcer.charge_tokens(800, payload={"step": "reserve"})
        return {"reserved": True, "booking_id": "bk-001"}

    def phase2_undo(inp, out, ctx):
        return None

    def phase3_confirm(inp, ctx):
        _, enforcer = pilot.begin_saga_run(ctx["run_id"])
        enforcer.charge_tokens(300, payload={"step": "confirm"})
        return {"confirmed": True, "booking_id": inp["booking_id"]}

    def phase3_undo(inp, out, ctx):
        return None

    saga.register_phase("validate", "Validate", phase1_validate, phase1_undo)
    saga.register_phase("reserve", "Reserve", phase2_reserve, phase2_undo)
    saga.register_phase("confirm", "Confirm", phase3_confirm, phase3_undo)

    result = pilot.execute_saga("booking-run-001", {"booking_id": "bk-001"})

    assert result.status == SagaStatus.DONE
    assert result.phases_done == 3

    # Cell-Boundary tracked consumption
    cell = pilot.get_cell_state("booking-run-001")
    assert cell["consumed_tokens"] == 1_600  # 500+800+300
    assert cell["is_apoptosed"] is False
    # Apoptose NOT triggered (under quota)
    apop = pilot.get_apoptose_state("booking-run-001")
    assert apop is None

    # Audit-Trail has hotel-scoped events: 1x validate (phase-1) + 3x consume_tokens
    events = pilot.audit_log.read_for_hotel(HOTEL_ID)
    assert len(events) >= 4
    types = [e.event_type for e in events]
    assert types.count("consume") == 3
    assert types.count("validate") >= 1


def test_pre3_e2e_quota_exhaustion_triggers_apoptose(pilot):
    """Quota-exhaustion raises QuotaExhaustedError + ApoptosisEngine signaled."""
    saga = pilot.saga

    def big_phase(inp, ctx):
        _, enforcer = pilot.begin_saga_run(ctx["run_id"])
        # Quota is 10_000; this consumes way too much.
        enforcer.charge_tokens(15_000, payload={"step": "big"})
        return {"ok": True}

    def big_undo(inp, out, ctx):
        return None

    saga.register_phase("big", "BigPhase", big_phase, big_undo)

    # Quota-exhaustion crashes phase -> Saga goes COMPENSATED.
    # Wound-Healing factory was wired -> healing-lifecycle created automatically
    # at saga-failure (NOTE: Phase-1 stub, factory is only invoked through
    # set_apoptosis_handler path in current saga-engine; we verify QuotaExhaustedError
    # propagates and ApoptosisEngine got signaled via cell-boundary callback).
    result = pilot.execute_saga("oom-run-001", {})

    assert result.status in (SagaStatus.COMPENSATED, SagaStatus.PARTIAL_COMPENSATION)
    cell = pilot.get_cell_state("oom-run-001")
    assert cell["is_apoptosed"] is True
    apop = pilot.get_apoptose_state("oom-run-001")
    assert apop is not None
    assert apop.cascade_stage == CascadeStage.APOPTOSED
    assert apop.apoptose_reason == TriggerType.QUOTA_EXHAUSTED.value


# ---------------- PRE-4 Shared-Path: GDPR purge + Multi-Tenancy ----------------


def test_pre4_shared_path_gdpr_purge_cascades(pilot, tmp_path):
    """purge_hotel() cascade-deletes audit + apoptose-snapshots for this pilot."""
    saga = pilot.saga

    def p1(inp, ctx):
        _, enforcer = pilot.begin_saga_run(ctx["run_id"])
        enforcer.charge_tokens(100)
        return {"ok": True}

    def u1(inp, out, ctx):
        return None

    saga.register_phase("p1", "P1", p1, u1)
    pilot.execute_saga("gdpr-run-001", {})

    assert len(pilot.audit_log.read_for_hotel(HOTEL_ID)) >= 1

    purged = pilot.purge_hotel()
    assert purged["events_deleted"] >= 1
    # After purge: hotel events gone
    assert pilot.audit_log.read_for_hotel(HOTEL_ID) == []


def test_pre4_multi_tenancy_isolation_two_pilots(tmp_path):
    """Two pilots with different hotel_id share audit_db but events are isolated."""
    shared_db = tmp_path / "shared_audit.db"

    pilot_eu = PilotHotelOrchestrator(
        hotel_id="apaleo-eu-001",
        state_dir=tmp_path / "eu_state",
        audit_db_path=shared_db,
        snapshot_dir=tmp_path / "eu_apoptose",
        quota=CellQuota(llm_token_budget=10_000),
    )
    pilot_us = PilotHotelOrchestrator(
        hotel_id="mews-us-002",
        state_dir=tmp_path / "us_state",
        audit_db_path=shared_db,
        snapshot_dir=tmp_path / "us_apoptose",
        quota=CellQuota(llm_token_budget=10_000),
    )

    # EU writes events
    _, eu_enforcer = pilot_eu.begin_saga_run("eu-run-1")
    eu_enforcer.charge_tokens(50)
    eu_enforcer.charge_tokens(50)

    # US writes events
    _, us_enforcer = pilot_us.begin_saga_run("us-run-1")
    us_enforcer.charge_tokens(99)

    # Each pilot only sees its own events
    eu_events = pilot_eu.audit_log.read_for_hotel("apaleo-eu-001")
    us_events = pilot_us.audit_log.read_for_hotel("mews-us-002")
    assert len(eu_events) == 2
    assert len(us_events) == 1
    assert all(e.hotel_id == "apaleo-eu-001" for e in eu_events)
    assert all(e.hotel_id == "mews-us-002" for e in us_events)

    # GDPR purge of EU does not affect US
    pilot_eu.purge_hotel()
    assert pilot_us.audit_log.read_for_hotel("mews-us-002")  # still there


# ---------------- PRE-5 Stress: 100-thread concurrent cell-quota consume ----------------


def test_pre5_stress_100_threads_cell_quota(pilot):
    """100 threads each consume 50 tokens against a 10_000-budget cell.

    No partial-counts, no double-count, total = 100 * 50 = 5_000.
    """
    _, enforcer = pilot.begin_saga_run("stress-run-001")
    errors: list[Exception] = []

    def worker():
        try:
            enforcer.charge_tokens(50)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    cell = pilot.get_cell_state("stress-run-001")
    assert cell["consumed_tokens"] == 5_000  # exactly 100 * 50
    assert cell["is_apoptosed"] is False


def test_pre5_stress_quota_overrun_apoptoses_cleanly(pilot):
    """200 threads each charge 100 tokens (=20k) against 10k-budget.

    Some succeed, some raise QuotaExhaustedError, but cell ends APOPTOSED.
    """
    _, enforcer = pilot.begin_saga_run("stress-overflow-run")
    success = 0
    fail = 0
    lock = threading.Lock()

    def worker():
        nonlocal success, fail
        try:
            enforcer.charge_tokens(100)
            with lock:
                success += 1
        except QuotaExhaustedError:
            with lock:
                fail += 1

    threads = [threading.Thread(target=worker) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    cell = pilot.get_cell_state("stress-overflow-run")
    # At least quota_limit/cost = 100 successful charges (10_000/100)
    assert success >= 100
    # Apoptosed once over-budget
    assert cell["is_apoptosed"] is True
    apop = pilot.get_apoptose_state("stress-overflow-run")
    assert apop is not None
    assert apop.cascade_stage == CascadeStage.APOPTOSED


# ---------------- Edge: orchestrator init validation ----------------


def test_orchestrator_requires_hotel_id(tmp_path):
    with pytest.raises(ValueError):
        PilotHotelOrchestrator(hotel_id="", state_dir=tmp_path)


# ---------------- Phase-2 Tissue-Layer Integration (Welle-9β) ----------------


def test_phase2_quorum_activates_via_pilot(pilot):
    """Pilot.emit_tissue_signal accumulates -> is_quorum_active fires when 3 unique DFs."""
    assert not pilot.is_quorum_active("demand_high")
    pilot.emit_tissue_signal("demand_high", df_id="df-A", strength=1.0)
    pilot.emit_tissue_signal("demand_high", df_id="df-B", strength=1.0)
    pilot.emit_tissue_signal("demand_high", df_id="df-C", strength=1.0)
    assert pilot.is_quorum_active("demand_high")


def test_phase2_blackboard_records_signal_events(pilot):
    """emit_tissue_signal also writes to blackboard for cross-DF subscribers."""
    pilot.emit_tissue_signal("demand_high", df_id="df-A", strength=1.5)
    pilot.emit_tissue_signal("demand_high", df_id="df-B", strength=1.0)
    events = pilot.blackboard.read_since(pilot.tissue_id)
    assert len(events) >= 2
    types = [e.topic for e in events]
    assert all(t == "signal:demand_high" for t in types)


def test_phase2_correlated_failure_detection_via_pilot(pilot):
    """record_failure + baseline-stats -> is_correlated_failure returns True at Z-spike."""
    # Build baseline: many low-failure-count windows
    for _ in range(50):
        pilot.failure_detector.add_baseline_sample(pilot.tissue_id, count=1)
    # Add some variance
    for c in [1, 0, 2, 1, 0, 2, 1, 1]:
        pilot.failure_detector.add_baseline_sample(pilot.tissue_id, count=c)
    # Inject burst of 20 failures
    for i in range(20):
        pilot.record_failure(df_id=f"df-{i}")
    assert pilot.is_correlated_failure()


# ---------------- Phase-3 Organ-Layer Integration (Welle-9γ) ----------------


def test_phase3_pricing_tier_routing_via_pilot(pilot):
    """Pilot.emit_demand + emit_capacity_pressure -> get_pricing_tier returns tier."""
    from kmo_governance.abs_tier_engine import ABSTier
    # No hormones: SMART
    assert pilot.get_pricing_tier() == ABSTier.SMART
    # High demand + capacity: VOLL
    pilot.emit_demand(50.0)
    pilot.emit_capacity_pressure(30.0)
    assert pilot.get_pricing_tier() == ABSTier.VOLL


def test_phase3_homeostasis_dampens_pricing_spiral(pilot):
    """check_pricing_homeostasis emits ANTI_PRICING when threshold exceeded."""
    from kmo_governance.abs_tier_engine import HormoneType
    # Push pricing-tier hormone above threshold
    for _ in range(20):
        pilot.hormone_pool.emit(pilot.hotel_id, HormoneType.PRICING_TIER, 1.0)
    triggered = pilot.check_pricing_homeostasis()
    assert triggered is True
    # ANTI_PRICING now > 0
    anti = pilot.hormone_pool.concentration(pilot.hotel_id, HormoneType.ANTI_PRICING)
    assert anti > 0


def test_phase3_gdpr_purge_cascade_via_pilot(pilot):
    """purge_hotel() now cascades to GDPR-Consent + HormonePool (Welle-9γ extended)."""
    from kmo_governance.hotel_membrane import DataCategory
    from kmo_governance.abs_tier_engine import HormoneType
    # Build state in all layers
    pilot.grant_gdpr_consent(DataCategory.BOOKING)
    pilot.grant_gdpr_consent(DataCategory.PAYMENT)
    pilot.emit_demand(10.0)
    _, enforcer = pilot.begin_saga_run("gdpr-cascade-test")
    enforcer.charge_tokens(100)
    # Purge
    result = pilot.purge_hotel()
    assert result["events_deleted"] >= 1
    assert result["gdpr_consents_purged"] == 2
    assert result["hormones_deleted"] >= 1


def test_phase3_anti_pricing_dampens_routing_d1_patch(pilot):
    """Patch D1 (Gemini-Finding 'Blind Receptors'): ANTI_PRICING reduces ABS-Tier-Routing.

    Without this patch: ANTI_PRICING is dead-end; routing ignores it.
    """
    from kmo_governance.abs_tier_engine import ABSTier, HormoneType
    # Route at high demand: VOLL
    pilot.emit_demand(50.0)
    pilot.emit_capacity_pressure(30.0)
    tier_before_anti = pilot.get_pricing_tier()
    assert tier_before_anti == ABSTier.VOLL

    # Inject heavy ANTI_PRICING -> should dampen the receptor
    pilot.hormone_pool.emit(pilot.hotel_id, HormoneType.ANTI_PRICING, 200.0)
    tier_after_anti = pilot.get_pricing_tier()
    # Either dropped to HYBRID or SMART (depending on Hill-Y curve)
    assert tier_after_anti in (ABSTier.HYBRID, ABSTier.SMART)


# ---------------- Welle-9γ.5 Patches E1+E2+E3 (Closed-Cross-LLM-Findings) ----------------


def test_e2_cross_hotel_query_blocker_via_pilot(pilot):
    """Patch E2 (Welle-9γ Open-Item #1 Copilot+Codex): CrossHotelQueryBlocker
    main-path-wired in Pilot. SQL-queries without hotel_id filter raise."""
    # Valid query with hotel_id filter
    assert pilot.check_sql_query(
        "SELECT * FROM bookings WHERE hotel_id = ?", caller_id="df-pricing"
    ) is True
    # Invalid query: no hotel_id filter -> blocked
    with pytest.raises(PermissionError):
        pilot.check_sql_query(
            "SELECT COUNT(*) FROM bookings", caller_id="df-pricing"
        )
    # Whitelisted aggregator: allowed
    pilot.whitelist_aggregator("organism-aggregator")
    assert pilot.check_sql_query(
        "SELECT COUNT(*) FROM bookings", caller_id="organism-aggregator"
    ) is True


def test_e3_phase_admit_check_blocks_in_emergency_state(pilot):
    """Patch E3 (Welle-9γ Open-Item #4 Copilot): policy-machine EMERGENCY state
    blocks phase-execution via saga.phase_admit_check."""
    from kmo_governance.multi_signal_policy import PolicyState
    saga = pilot.saga

    def do_p1(inp, ctx):
        return {"ok": True}

    def undo_p1(inp, out, ctx):
        return None

    saga.register_phase("p1", "P1", do_p1, undo_p1)

    # Force EMERGENCY state via tick(force=...)
    pilot.policy_machine.tick({}, force=PolicyState.EMERGENCY)
    assert pilot.policy_machine.state == PolicyState.EMERGENCY

    # Saga-execute now blocked by phase_admit_check via E3 path
    from kmo_saga_engine import SagaStatus
    result = pilot.execute_saga("emergency-blocked", initial_input={})
    # Phase blocked -> compensation runs -> COMPENSATED status
    assert result.status in (SagaStatus.COMPENSATED, SagaStatus.PARTIAL_COMPENSATION)


def test_e1_hormone_pool_ttl_pruning(pilot):
    """Patch E1 (Welle-9γ.5 Gemini O(N) Memory-Leak): TTL-Pruning of expired hormones."""
    from kmo_governance.abs_tier_engine import HormoneType
    # Inject many emissions over fake-time
    state = {"t": 1_000_000.0}
    pilot.hormone_pool._clock = lambda: state["t"]
    for _ in range(150):  # > gc_every (=100)
        pilot.hormone_pool.emit(pilot.hotel_id, HormoneType.DEMAND_SIGNAL, 1.0)
    initial = len(pilot.hormone_pool._emissions[(pilot.hotel_id, HormoneType.DEMAND_SIGNAL)])
    # Fast-forward beyond TTL (10 * 4h = 40h)
    state["t"] += 40 * 3600 + 100
    pruned = pilot.hormone_pool.gc_expired()
    assert pruned >= initial - 5  # almost all expired
    assert pilot.hormone_pool.concentration(pilot.hotel_id, HormoneType.DEMAND_SIGNAL) < 0.001


# ---------------- Welle-9-delta Pre-Patch #5 (Saga membrane-checks) ----------------


def test_pre5_membrane_check_blocks_foreign_hotel_id_in_input(pilot, tmp_path):
    """Pre-Patch #5: Saga rejects an input dict tagged with a foreign hotel_id."""
    saga = pilot.saga
    state_dir = tmp_path / "saga_state_pre5"
    state_dir.mkdir(exist_ok=True)
    saga.state_dir = state_dir

    # Register one phase that just echoes input (we want failure pre-do_func)
    saga._phases.clear()
    saga.register_phase(
        phase_id="echo_phase",
        name="Echo",
        do_func=lambda inp, ctx: inp,
        undo_func=lambda inp, out, ctx: None,
    )
    # Input tagged with FOREIGN hotel_id -> membrane-check returns False -> phase fails
    foreign_input = {"hotel_id": "hotel-foreign", "data": "xyz"}
    result = saga.execute(
        saga_run_id="test_pre5_foreign_input",
        initial_input=foreign_input,
        hotel_id=pilot.hotel_id,
    )
    # Saga failed because membrane blocked input
    from kmo_saga_engine import SagaStatus
    assert result.status in (SagaStatus.FAILED, SagaStatus.COMPENSATED)
    assert "membrane" in (result.error or "").lower()


def test_pre5_membrane_check_admits_matching_hotel_id(pilot, tmp_path):
    """Pre-Patch #5: Saga admits input tagged with matching hotel_id (control)."""
    saga = pilot.saga
    state_dir = tmp_path / "saga_state_pre5_ok"
    state_dir.mkdir(exist_ok=True)
    saga.state_dir = state_dir

    saga._phases.clear()
    saga.register_phase(
        phase_id="echo_phase",
        name="Echo",
        do_func=lambda inp, ctx: {"hotel_id": pilot.hotel_id, "result": "ok"},
        undo_func=lambda inp, out, ctx: None,
    )
    matching_input = {"hotel_id": pilot.hotel_id, "data": "xyz"}
    result = saga.execute(
        saga_run_id="test_pre5_matching_input",
        initial_input=matching_input,
        hotel_id=pilot.hotel_id,
    )
    from kmo_saga_engine import SagaStatus
    assert result.status == SagaStatus.DONE
    assert result.final_output == {"hotel_id": pilot.hotel_id, "result": "ok"}


def test_pre5_membrane_check_blocks_foreign_hotel_id_in_output(pilot, tmp_path):
    """Pre-Patch #5: Saga rejects an output dict tagged with a foreign hotel_id."""
    saga = pilot.saga
    state_dir = tmp_path / "saga_state_pre5_output"
    state_dir.mkdir(exist_ok=True)
    saga.state_dir = state_dir

    saga._phases.clear()
    saga.register_phase(
        phase_id="leak_phase",
        name="Leak",
        # Do_func returns output tagged with FOREIGN hotel_id -> membrane blocks
        do_func=lambda inp, ctx: {"hotel_id": "hotel-foreign", "leaked": True},
        undo_func=lambda inp, out, ctx: None,
    )
    result = saga.execute(
        saga_run_id="test_pre5_leak_output",
        initial_input=None,
        hotel_id=pilot.hotel_id,
    )
    from kmo_saga_engine import SagaStatus
    assert result.status in (SagaStatus.FAILED, SagaStatus.COMPENSATED)
    assert "membrane" in (result.error or "").lower()


# ---------- Patch F3 (Welle-9-delta Cross-LLM Finding #5: rekursive Validierung) ----------


def test_f3_membrane_blocks_nested_dict_with_foreign_hotel_id(pilot):
    """F3: deeply nested dict with foreign hotel_id detected."""
    nested = {
        "level1": {
            "level2": {
                "hotel_id": "hotel-foreign",  # FOREIGN deep inside
                "data": "leaked",
            }
        }
    }
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", nested) is False


def test_f3_membrane_passes_nested_with_matching_hotel_id(pilot):
    """F3: nested with matching hotel_id at all levels passes."""
    nested = {
        "outer": pilot.hotel_id,
        "level1": {
            "hotel_id": pilot.hotel_id,
            "level2": {"data": "ok"},
        },
    }
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", nested) is True


def test_f3_membrane_blocks_list_of_lists_with_foreign():
    """F3: list-of-list-of-dict with foreign hotel_id detected."""
    from df_executors.df_pilot_hotel_EU.pilot_integration import PilotHotelOrchestrator
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pilot = PilotHotelOrchestrator(hotel_id="hotel-A", state_dir=td)
        payload = [
            [{"hotel_id": pilot.hotel_id, "ok": True}],
            [{"hotel_id": "hotel-foreign", "leaked": True}],  # nested in inner list
        ]
        assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", payload) is False


def test_f3_membrane_passes_dataclass_like_object(pilot):
    """F3: object with __dict__ is recursively introspected."""
    class Booking:
        def __init__(self, hotel_id, amount):
            self.hotel_id = hotel_id
            self.amount = amount
    booking = Booking(pilot.hotel_id, 100)
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", booking) is True


def test_f3_membrane_blocks_dataclass_like_with_foreign_hotel(pilot):
    """F3: dataclass-like object with foreign hotel_id is blocked."""
    class Booking:
        def __init__(self, hotel_id, amount):
            self.hotel_id = hotel_id
            self.amount = amount
    booking = Booking("hotel-foreign", 100)
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", booking) is False


def test_f3_membrane_passes_scalars_and_none(pilot):
    """F3: scalars + None are unconditionally passed."""
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", None) is True
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", 42) is True
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", "string") is True
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", True) is True


def test_f3_membrane_passes_payload_without_hotel_id_field(pilot):
    """F3: payload with NO hotel_id field at all = backwards-compat pass."""
    payload = {"data": {"nested": {"more": [1, 2, 3]}}}
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", payload) is True


def test_f3_membrane_handles_tuple():
    """F3: tuple is treated like list."""
    from df_executors.df_pilot_hotel_EU.pilot_integration import PilotHotelOrchestrator
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pilot = PilotHotelOrchestrator(hotel_id="hotel-A", state_dir=td)
        good = ({"hotel_id": pilot.hotel_id, "ok": True},)
        bad = ({"hotel_id": "hotel-foreign", "leaked": True},)
        assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", good) is True
        assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", bad) is False


# ---------- Welle-9-delta Phase-4 Public-API integration tests ----------


def test_welle9d_get_system_health(pilot):
    """Welle-9-delta: get_system_health returns master status dict."""
    status = pilot.get_system_health()
    assert "last_status" in status
    assert "current_mode" in status
    assert status["current_mode"] == "normal"


def test_welle9d_update_vitals_healthy_no_mode_change(pilot):
    """Welle-9-delta: healthy vitals do not change mode."""
    actions = pilot.update_system_vitals(
        heart_rate=50.0,
        blood_pressure=0.4,
        body_temperature=0.5,
        oxygen_saturation=0.9,
    )
    assert actions["status"] == "healthy"
    assert pilot.get_current_mode() == "normal"


def test_welle9d_update_vitals_critical_triggers_peak_load(pilot):
    """Welle-9-delta: critical vitals route to PEAK_LOAD via homeostasis."""
    actions = pilot.update_system_vitals(
        heart_rate=50.0,
        blood_pressure=0.4,
        body_temperature=10.0,  # high error rate -> CRITICAL
        oxygen_saturation=0.9,
    )
    assert actions["status"] == "critical"
    assert pilot.get_current_mode() == "peak_load"


def test_welle9d_signal_emergency_routes_to_incident(pilot):
    """Welle-9-delta: emergency-signal sets sigma to INCIDENT."""
    pilot.signal_emergency(reason="catastrophic-saga-failure")
    assert pilot.get_current_mode() == "incident"


def test_welle9d_is_df_active_in_normal(pilot):
    """Welle-9-delta: NORMAL mode allows all DFs (empty whitelist)."""
    assert pilot.is_df_active("df-anything") is True


def test_welle9d_register_and_use_knowledge(pilot):
    """Welle-9-delta: knowledge_decay reachable via Pilot."""
    e = pilot.register_knowledge_entry("method-pareto-cut", confidence=0.5)
    assert e.use_count == 0
    pilot.use_knowledge("method-pareto-cut", performance=1.0)
    e2 = pilot.knowledge_decay.get("method-pareto-cut")
    assert e2.use_count == 1
    assert e2.confidence > 0.5


def test_welle9d_glymphatic_cleanup_via_pilot(pilot):
    """Welle-9-delta: trigger_glymphatic_cleanup invokes wired knowledge_decay."""
    pilot.register_knowledge_entry("k1", confidence=0.05, stability_days=0.5)
    result = pilot.trigger_glymphatic_cleanup()
    assert result["success"] is True
    # items_pruned >= 0; the test entry might not be pruned (age too short)
    assert "items_pruned" in result
