# [CRUX-MK]
"""KPM-Demo-Application End-to-End-Tests (Welle-31 Phase-24).

Beweist: 9 KPM-Module orchestriert in 1 Pipeline. Trinity-Tests:
  - Conservative: Happy-Path (alle 9 Stages PASS).
  - Aggressive:   Reject-Paths (jede Stage kann ausschalten).
  - Contrarian:   Edge-Cases (Concurrent, Chaos, Failover, Result-Frozen).

CRUX-MK
"""
from __future__ import annotations

import threading
import time

import pytest

from kmo_governance.kpm_chaos_engineering import (
    ChaosOutcome,
    ChaosScenario,
    FaultSeverity,
)
from kmo_governance.kpm_demo_application import (
    KPMTradeAdmissionPipeline,
    TradeAdmissionResult,
)
from kmo_governance.kpm_distributed_lock_manager import PositionSide
from kmo_governance.kpm_feature_flag_engine import FlagState
from kmo_governance.kpm_saga_orchestrator import SagaPhase, SagaStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


PRIMARY = "kelly-0.4"
STANDBY_FIRST = "kelly-0.3"
STANDBY_SECOND = "kelly-0.2"


def _build_pipeline(
    backpressure_max_orders_per_second: float = 100.0,
) -> KPMTradeAdmissionPipeline:
    return KPMTradeAdmissionPipeline(
        primary_strategy_id=PRIMARY,
        standby_strategy_ids=[STANDBY_FIRST, STANDBY_SECOND],
        backpressure_max_orders_per_second=backpressure_max_orders_per_second,
    )


def _enable_strategy(
    pipe: KPMTradeAdmissionPipeline, strategy_id: str
) -> None:
    pipe.feature_flags.set_state(
        flag_id=f"strategy_{strategy_id}",
        new_state=FlagState.ENABLED,
        changed_by="test",
        reason="test-enable",
    )


def _submit(
    pipe: KPMTradeAdmissionPipeline,
    *,
    strategy_id: str = PRIMARY,
    instrument_id: str = "BTCUSDT",
    side: PositionSide = PositionSide.LONG,
    quantity: float = 0.5,
    price: float = 42000.0,
    client_order_id: str = "ord-001",
    request_id: str = "req-001",
    chaos_mode: bool = False,
    allocation_pct: float | None = None,
) -> TradeAdmissionResult:
    return pipe.submit_trade(
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        side=side,
        quantity=quantity,
        price=price,
        client_order_id=client_order_id,
        request_id=request_id,
        chaos_mode=chaos_mode,
        allocation_pct=allocation_pct,
    )


# ---------------------------------------------------------------------------
# 1. Happy-Path
# ---------------------------------------------------------------------------


def test_full_pipeline_happy_path():
    """Alle 9 Stages PASS, success=True, decision_path enthaelt alle stage_names."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    result = _submit(pipe)

    assert result.success is True
    assert result.audit_event_id is not None
    assert result.saga_id is not None
    assert result.active_strategy_id == PRIMARY
    assert result.elapsed_ms >= 0.0
    assert result.timestamp > 0
    # Decision-Path enthaelt 9 Stages (kein Chaos):
    expected_stages = (
        "feature_flag",
        "deduplication",
        "backpressure",
        "lock_acquire",
        "failover_route",
        "saga_execute",
        "homeostasis_record",
        "audit_publish",
        "lock_release",
    )
    assert result.decision_path == expected_stages


# ---------------------------------------------------------------------------
# 2. Reject-Paths (Stages koennen jeweils Pipeline stoppen)
# ---------------------------------------------------------------------------


def test_feature_flag_disabled_rejects():
    """Stage 1: Strategy-Flag DISABLED -> REJECT, kein lock acquired."""
    pipe = _build_pipeline()
    # KEIN _enable_strategy -> bleibt DISABLED

    result = _submit(pipe)

    assert result.success is False
    assert "strategy_disabled" in result.reason
    assert result.decision_path == ("feature_flag",)
    assert result.audit_event_id is None
    assert result.saga_id is None


def test_duplicate_order_rejects():
    """Stage 2: gleiches client_order_id zweimal -> 2. ist REJECT."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    first = _submit(pipe, client_order_id="ord-dup", request_id="req-1")
    second = _submit(pipe, client_order_id="ord-dup", request_id="req-2")

    assert first.success is True
    assert second.success is False
    assert "duplicate_order" in second.reason
    assert second.decision_path[-1] == "deduplication"


def test_backpressure_blocked_rejects():
    """Stage 3: Backpressure custom-handler liefert REJECT-action."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # Force REJECT via custom action handler fuer alle FlowStates,
    # damit egal welche Rate -> REJECT.
    from kmo_governance.kpm_backpressure_engine import (
        FlowState,
        ThrottleAction,
    )

    def force_reject(_rate: float) -> ThrottleAction:
        return ThrottleAction(
            action_type="REJECT",
            delay_ms=0.0,
            reason="forced_reject_for_test",
            timestamp=time.time(),
        )

    for state in FlowState:
        pipe.backpressure.register_action(state, force_reject)

    result = _submit(pipe)

    assert result.success is False
    assert "backpressure_blocked" in result.reason
    assert result.decision_path[-1] == "backpressure"


def test_lock_conflict_rejects():
    """Stage 4: Lock auf (instrument, side) bereits gehalten -> REJECT."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # Hold lock aus separater Quelle (anderer holder_strategy_id).
    held = pipe.lock_manager.acquire(
        instrument_id="ETHUSDT",
        position_side=PositionSide.LONG,
        holder_strategy_id="external-holder",
    )
    assert held.success

    result = _submit(pipe, instrument_id="ETHUSDT")

    assert result.success is False
    assert "lock_held" in result.reason
    assert result.decision_path[-1] == "lock_acquire"


def test_saga_failure_triggers_cleanup():
    """Stage 6: Saga-Handler raises -> REJECT + Lock released."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # Override EXECUTE-Phase mit Failure-Handler
    def execute_fails(_step: SagaStep) -> dict:
        raise RuntimeError("simulated broker reject")

    pipe.saga.register_handler(SagaPhase.EXECUTE, execute_fails)

    result = _submit(pipe, instrument_id="DOGEUSDT")

    assert result.success is False
    assert "saga_failed" in result.reason
    assert result.saga_id is not None  # Saga wurde versucht

    # Lock muss freigegeben sein -> nochmal acquire moeglich
    re_acq = pipe.lock_manager.acquire(
        instrument_id="DOGEUSDT",
        position_side=PositionSide.LONG,
        holder_strategy_id="post-cleanup-check",
    )
    assert re_acq.success is True


# ---------------------------------------------------------------------------
# 3. Side-Effects-Verification (Audit, Homeostasis)
# ---------------------------------------------------------------------------


def test_audit_event_emitted_on_success():
    """Stage 8: Audit-Bus enthaelt Event mit korrektem strategy_id +
    compliance-tags."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    result = _submit(pipe, client_order_id="ord-audit-1", request_id="req-a-1")
    assert result.success
    assert result.audit_event_id is not None

    # Query Audit-Bus
    events = pipe.audit_bus.query(strategy_id=PRIMARY)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_id == result.audit_event_id
    assert ev.instrument_id == "BTCUSDT"
    # compliance_tags wurden gesetzt
    from kmo_governance.kpm_audit_event_bus import ComplianceTag
    assert ComplianceTag.MIFID_BEST_EXEC in ev.compliance_tags
    assert ComplianceTag.POSITION_LIMIT in ev.compliance_tags


def test_homeostasis_records_post_execute():
    """Stage 7: Homeostasis-Controller hat allocation-record nach success."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    initial_history_len = len(pipe.homeostasis.get_history())

    _submit(pipe, allocation_pct=55.0)
    _submit(
        pipe,
        client_order_id="ord-hh-2",
        request_id="req-hh-2",
        allocation_pct=70.0,
    )

    history_after = pipe.homeostasis.get_history()
    assert len(history_after) == initial_history_len + 2
    # Letzter Record passt
    assert history_after[-1].allocation_pct == 70.0


# ---------------------------------------------------------------------------
# 4. Concurrent Trades
# ---------------------------------------------------------------------------


def test_concurrent_trades_isolated():
    """5 strategies parallel auf disjunkte (instrument, side) -> alle ok,
    no cross-contamination."""
    pipe = _build_pipeline(backpressure_max_orders_per_second=1000.0)
    _enable_strategy(pipe, PRIMARY)
    _enable_strategy(pipe, STANDBY_FIRST)
    _enable_strategy(pipe, STANDBY_SECOND)

    # Strategy-Flags fuer 5 verschiedene strategy_ids -> wir nutzen 3
    # bereits-registrierte + verzichten auf die anderen 2 (nutzen
    # gleichen primary mit unterschiedlichen instruments).

    instruments = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    results: list[TradeAdmissionResult] = [None] * len(instruments)
    errors: list[Exception] = []

    def worker(idx: int, instr: str) -> None:
        try:
            results[idx] = _submit(
                pipe,
                strategy_id=PRIMARY,
                instrument_id=instr,
                client_order_id=f"ord-conc-{idx}",
                request_id=f"req-conc-{idx}",
            )
        except Exception as exc:  # pragma: no cover - defensiv
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(i, instr))
        for i, instr in enumerate(instruments)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"unexpected exceptions: {errors}"
    assert all(r is not None for r in results)
    assert all(r.success for r in results), [
        (r.reason, r.decision_path) for r in results if not r.success
    ]
    # Alle decision_paths sind komplett (9 Stages)
    for r in results:
        assert len(r.decision_path) == 9


# ---------------------------------------------------------------------------
# 5. Chaos-Mode
# ---------------------------------------------------------------------------


def test_chaos_mode_injects_fault():
    """chaos_mode=True triggert chaos_engineering.inject_random vor saga."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # Chaos-Outcomes vor Pipeline = 0
    assert len(pipe.chaos.get_outcomes(PRIMARY)) == 0

    result = _submit(pipe, chaos_mode=True)

    assert result.success is True
    assert "chaos_inject" in result.decision_path
    # Outcome wurde aufgezeichnet
    outcomes = pipe.chaos.get_outcomes(PRIMARY)
    assert len(outcomes) == 1
    assert outcomes[0].success is True  # default-handler liefert success


# ---------------------------------------------------------------------------
# 6. Failover-Routing
# ---------------------------------------------------------------------------


def test_failover_uses_standby_when_primary_down():
    """Primary >= health_threshold unprofitable Trades -> active_strategy
    wechselt zu standby."""
    pipe = _build_pipeline()
    # Primary muss aktiviert sein, aber failover.route() entscheidet trotzdem.
    _enable_strategy(pipe, PRIMARY)
    _enable_strategy(pipe, STANDBY_FIRST)

    # Fuettere primary mit health_threshold (3) Verlusten
    for _ in range(pipe.failover.health_threshold):
        pipe.failover.record_trade_outcome(PRIMARY, profitable=False)

    result = _submit(pipe, strategy_id=PRIMARY)

    assert result.success is True
    # Active strategy muss standby sein
    assert result.active_strategy_id == STANDBY_FIRST
    # decision_path enthaelt failover_route
    assert "failover_route" in result.decision_path


# ---------------------------------------------------------------------------
# 7. Decision-Path-Completeness
# ---------------------------------------------------------------------------


def test_decision_path_complete():
    """Alle 9 stage-namen kommen in happy-path-decision_path vor."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    result = _submit(pipe)
    assert result.success
    expected = {
        "feature_flag",
        "deduplication",
        "backpressure",
        "lock_acquire",
        "failover_route",
        "saga_execute",
        "homeostasis_record",
        "audit_publish",
        "lock_release",
    }
    assert set(result.decision_path) == expected


# ---------------------------------------------------------------------------
# 8. Latenz-Messung
# ---------------------------------------------------------------------------


def test_elapsed_ms_measured():
    """elapsed_ms ist > 0 und < unrealistische obergrenze."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    result = _submit(pipe)

    assert result.success
    assert result.elapsed_ms >= 0.0
    # Pipeline ist all-stdlib + lock + dataclass-Construction.
    # 5 Sekunden ist grosszuegig (CI cold-start).
    assert result.elapsed_ms < 5000.0


# ---------------------------------------------------------------------------
# 9. Result-Frozen-Immutability
# ---------------------------------------------------------------------------


def test_result_frozen_immutability():
    """TradeAdmissionResult ist frozen dataclass; Attr-Assignment raises."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    result = _submit(pipe)

    with pytest.raises(Exception):  # FrozenInstanceError
        result.success = False  # type: ignore[misc]
    with pytest.raises(Exception):
        result.reason = "tampered"  # type: ignore[misc]
    # decision_path ist tuple -> immutable
    with pytest.raises(TypeError):
        result.decision_path[0] = "hacked"  # type: ignore[index]


# ---------------------------------------------------------------------------
# 10. Pre-Condition-Validierung
# ---------------------------------------------------------------------------


def test_invalid_inputs_rejected():
    """Pre-Conditions in submit_trade werden geprueft."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    with pytest.raises(ValueError):
        pipe.submit_trade(
            strategy_id="",
            instrument_id="X",
            side=PositionSide.LONG,
            quantity=1.0,
            price=1.0,
            client_order_id="ok",
            request_id="ok",
        )
    with pytest.raises(ValueError):
        pipe.submit_trade(
            strategy_id=PRIMARY,
            instrument_id="X",
            side=PositionSide.LONG,
            quantity=0,  # zero
            price=1.0,
            client_order_id="ok",
            request_id="ok",
        )
    with pytest.raises(ValueError):
        pipe.submit_trade(
            strategy_id=PRIMARY,
            instrument_id="X",
            side=PositionSide.LONG,
            quantity=1.0,
            price=-1.0,  # negative
            client_order_id="ok",
            request_id="ok",
        )
    with pytest.raises(ValueError):
        pipe.submit_trade(
            strategy_id=PRIMARY,
            instrument_id="X",
            side="not-an-enum",  # type: ignore[arg-type]
            quantity=1.0,
            price=1.0,
            client_order_id="ok",
            request_id="ok",
        )


# ---------------------------------------------------------------------------
# 11. Ctor-Validierung
# ---------------------------------------------------------------------------


def test_ctor_validation():
    """Pipeline-Konstruktor prueft primary + standby."""
    with pytest.raises(ValueError):
        KPMTradeAdmissionPipeline(
            primary_strategy_id="",
            standby_strategy_ids=["s"],
        )
    with pytest.raises(ValueError):
        KPMTradeAdmissionPipeline(
            primary_strategy_id="p",
            standby_strategy_ids=[],
        )


# ---------------------------------------------------------------------------
# 12. Saga-Compensation-Pattern
# ---------------------------------------------------------------------------


def test_saga_compensation_log_on_failure():
    """Saga-Failure -> compensation_log enthaelt Eintraege fuer
    completed-then-rolled-back-steps."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # CONFIRM-Phase failt; VALIDATE/RESERVE/EXECUTE haben schon completed.
    def confirm_fails(_step: SagaStep) -> dict:
        raise RuntimeError("simulated confirm-failure")

    compensated_phases: list[str] = []

    def comp_recorder_factory(phase_name: str):
        def comp(_step: SagaStep) -> None:
            compensated_phases.append(phase_name)
        return comp

    pipe.saga.register_handler(SagaPhase.CONFIRM, confirm_fails)
    for phase in (SagaPhase.VALIDATE, SagaPhase.RESERVE, SagaPhase.EXECUTE):
        pipe.saga.register_compensator(
            phase, comp_recorder_factory(phase.value)
        )

    result = _submit(pipe, instrument_id="LTCUSDT")
    assert result.success is False
    assert "saga_failed" in result.reason
    # Drei vorherige Phases wurden compensated (reverse-order: execute,
    # reserve, validate).
    assert compensated_phases == ["execute", "reserve", "validate"]


# ---------------------------------------------------------------------------
# 13. Lock-Cleanup-On-Saga-Fail
# ---------------------------------------------------------------------------


def test_lock_released_after_saga_fail():
    """Saga-Fail -> Lock muss released sein, neue acquire moeglich."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    def execute_fails(_step: SagaStep) -> dict:
        raise RuntimeError("boom")

    pipe.saga.register_handler(SagaPhase.EXECUTE, execute_fails)

    result = _submit(
        pipe,
        instrument_id="XRPUSDT",
        client_order_id="ord-cleanup",
        request_id="req-cleanup",
    )
    assert result.success is False

    # Re-Acquire muss gehen (Lock released)
    re = pipe.lock_manager.acquire(
        instrument_id="XRPUSDT",
        position_side=PositionSide.LONG,
        holder_strategy_id="post-fail-check",
    )
    assert re.success is True


# ---------------------------------------------------------------------------
# 14. Repeated-Trades skalieren ohne Lock-Contention
# ---------------------------------------------------------------------------


def test_repeated_trades_release_locks_correctly():
    """N sequentielle Trades auf gleichem (instrument, side) gehen alle durch
    weil Pipeline Lock pro Trade akquiriert + released."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    n = 10
    results = []
    for i in range(n):
        r = _submit(
            pipe,
            instrument_id="SOLUSDT",
            client_order_id=f"ord-rep-{i}",
            request_id=f"req-rep-{i}",
        )
        results.append(r)

    assert all(r.success for r in results)
    assert len(set(r.audit_event_id for r in results)) == n  # unique events


# ---------------------------------------------------------------------------
# 15. Audit-Trail enthaelt request_id-Metadata
# ---------------------------------------------------------------------------


def test_audit_metadata_contains_request_id():
    """Audit-Event hat request_id + client_order_id + saga_id im
    metadata-Tuple."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    result = _submit(
        pipe, client_order_id="ord-meta", request_id="req-meta"
    )
    assert result.success

    events = pipe.audit_bus.query(strategy_id=PRIMARY)
    ev = events[0]
    md = ev.get_metadata_dict()
    assert md["client_order_id"] == "ord-meta"
    assert md["request_id"] == "req-meta"
    assert md["saga_id"] == result.saga_id


# ---------------------------------------------------------------------------
# 16. Backpressure-Delay erlaubt Trade aber markiert delayed
# ---------------------------------------------------------------------------


def test_backpressure_delay_does_not_reject():
    """Backpressure DELAY-action -> Trade laeuft durch (kein REJECT)."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # Force DELAY via custom handler fuer alle states
    from kmo_governance.kpm_backpressure_engine import (
        FlowState,
        ThrottleAction,
    )

    def force_delay(_rate: float) -> ThrottleAction:
        return ThrottleAction(
            action_type="DELAY",
            delay_ms=10.0,
            reason="forced_delay_for_test",
            timestamp=time.time(),
        )

    for state in FlowState:
        pipe.backpressure.register_action(state, force_delay)

    result = _submit(pipe)
    assert result.success is True
    # decision_path enthaelt alle 9 Stages
    assert "backpressure" in result.decision_path
    assert "saga_execute" in result.decision_path


# ---------------------------------------------------------------------------
# 17. P-V15-1: Cleanup-Atomicity Tests (Cross-LLM-V15 Konsens-Patch)
# ---------------------------------------------------------------------------


def test_release_lock_returns_status_dict():
    """P-V15-1: _release_lock liefert dict {'released': bool, 'reason': str}."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)
    # Trade ausfuehren -> Stage 9 ruft _release_lock
    result = _submit(pipe, instrument_id="ATOMUSDT")
    assert result.success is True

    # Manueller Aufruf nach erfolgreichem Run: keine aktive Lease.
    rel = pipe._release_lock("ATOMUSDT", PositionSide.LONG)
    assert isinstance(rel, dict)
    assert "released" in rel
    assert "reason" in rel
    assert rel["released"] is True
    assert rel["reason"] == "no_lease"


def test_release_lock_failure_marks_cleanup_failed():
    """P-V15-1: lock_manager.release-Failure -> success=False + cleanup_failed in reason."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # Patch lock_manager.release zu einem Failure-Result
    from kmo_governance.kpm_distributed_lock_manager import TradeLockResult

    real_release = pipe.lock_manager.release

    def failing_release(instrument_id, position_side, lease_token):
        return TradeLockResult(
            success=False,
            instrument_id=instrument_id,
            position_side=position_side,
            timestamp=time.time(),
            reason="simulated_release_failure",
        )

    pipe.lock_manager.release = failing_release

    result = _submit(pipe, instrument_id="OPUSDT")
    # Despite Saga-Success, Cleanup-Failure -> success=False
    assert result.success is False
    assert "cleanup_failed" in result.reason
    assert "simulated_release_failure" in result.reason

    # Restore
    pipe.lock_manager.release = real_release


def test_pipeline_returns_failure_on_cleanup_fail():
    """P-V15-1: Saga-Failure + Release-Failure -> success=False mit beiden Reasons."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # Saga-Failure simulieren
    def execute_fails(_step: SagaStep) -> dict:
        raise RuntimeError("simulated saga failure")

    pipe.saga.register_handler(SagaPhase.EXECUTE, execute_fails)

    # Release-Failure simulieren
    from kmo_governance.kpm_distributed_lock_manager import TradeLockResult

    def failing_release(instrument_id, position_side, lease_token):
        return TradeLockResult(
            success=False,
            instrument_id=instrument_id,
            position_side=position_side,
            timestamp=time.time(),
            reason="release_failed_too",
        )

    pipe.lock_manager.release = failing_release

    result = _submit(pipe, instrument_id="MATICUSDT")
    assert result.success is False
    assert "saga_failed" in result.reason
    assert "cleanup_failed" in result.reason
    assert "release_failed_too" in result.reason


def test_double_release_idempotent():
    """P-V15-1: 2x _release_lock im selben Run -> 2. Aufruf no-op (kein Double-Release)."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)

    # 1. submit_trade fuer state-setup
    result = _submit(pipe, instrument_id="LINKUSDT")
    assert result.success is True
    # Nach erfolgreichem Run sollte _lease_token None sein
    assert pipe._lease_token is None

    # 2. Manuelle 2x _release_lock-Calls -> beide no-op (kein Crash)
    rel1 = pipe._release_lock("LINKUSDT", PositionSide.LONG)
    assert rel1["released"] is True
    assert rel1["reason"] == "no_lease"

    rel2 = pipe._release_lock("LINKUSDT", PositionSide.LONG)
    assert rel2["released"] is True
    assert rel2["reason"] == "no_lease"

    # 3. Counter-Track: Anzahl real_release-Calls in lock_manager
    call_count = {"n": 0}
    real_release = pipe.lock_manager.release

    def counting_release(instrument_id, position_side, lease_token):
        call_count["n"] += 1
        return real_release(
            instrument_id=instrument_id,
            position_side=position_side,
            lease_token=lease_token,
        )

    pipe.lock_manager.release = counting_release

    # Frischer Run mit aktivem Token, dann Doppel-Release-Versuch
    result2 = _submit(pipe, instrument_id="LINKUSDT", client_order_id="ord-2")
    # Stage-9 hat genau 1x release ausgefuehrt
    assert call_count["n"] == 1
    # _lease_token ist nach erfolgreichem Stage-9 None
    assert pipe._lease_token is None
    # Manueller Doppel-Release nach success-Run -> no-op (no real release)
    pipe._release_lock("LINKUSDT", PositionSide.LONG)
    assert call_count["n"] == 1  # Counter unveraendert -> idempotent


# ---------------------------------------------------------------------------
# Welle-36 V2: Stage-10 Observability-Tests (Vagusnerv-Pattern)
# ---------------------------------------------------------------------------


def test_stage10_observability_records_trade_latency_histogram() -> None:
    """Stage-10 Pflicht: trade_latency_ms Histogram bekommt Observation."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)
    _submit(pipe)
    buckets = pipe.observability.get_histogram_buckets(
        "trade_latency_ms", outcome="success",
    )
    # +Inf Bucket immer total observation count (Prometheus-Konvention)
    assert buckets[float("inf")] >= 1


def test_stage10_observability_inc_counter_per_trade() -> None:
    """Stage-10 Pflicht: trades_total Counter wird pro Trade incremented."""
    pipe = _build_pipeline()
    _enable_strategy(pipe, PRIMARY)
    for i in range(3):
        _submit(pipe, instrument_id=f"INST{i}", client_order_id=f"ord-w36-{i}")
    snap = pipe.observability.get_metric("trades_total", outcome="success")
    assert snap.value == 3.0


def test_stage10_observability_active_strategies_gauge() -> None:
    """Stage-10: active_strategies Gauge = primary + standbys."""
    pipe = _build_pipeline()
    snap = pipe.observability.get_metric("active_strategies")
    # PRIMARY + 2 standbys = 3
    assert snap.value == 3.0


def test_stage10_observability_independent_of_outcome() -> None:
    """Stage-10: auch reject-Pfade erhoehen Counter mit outcome=reject."""
    pipe = _build_pipeline()
    # Flag NICHT enablen -> reject in Stage-1
    result = _submit(pipe, client_order_id="ord-w36-reject", request_id="req-w36-reject")
    assert result.success is False
    snap_reject = pipe.observability.get_metric("trades_total", outcome="reject")
    assert snap_reject.value == 1.0


# CRUX-MK
