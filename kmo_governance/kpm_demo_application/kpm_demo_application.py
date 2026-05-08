# [CRUX-MK]
"""KPM-Demo-Application End-to-End-Pipeline (Welle-31 Phase-24 KMO-vNext).

End-to-End-Orchestrator der 9 KPM-Bio-Pattern-Lift-Module als produktionsnahe
Trade-Admission-Pipeline. Demonstriert dass die Module orchestriert wie ein
Trading-Stack zusammenspielen — nicht nur isoliert testbar sind.

Pipeline-Flow pro submit_trade():
  1. feature_flag_engine.evaluate(flag_id="strategy_<id>", request_id)
       -> wenn enabled=False: REJECT mit reason="strategy_disabled"
  2. deduplication_engine.check(client_order_id, payload, strategy_id)
       -> wenn is_duplicate=True: REJECT mit reason="duplicate_order"
  3. backpressure_engine.evaluate(strategy_id)
       -> action_type=REJECT: REJECT mit reason="backpressure_blocked"
       -> action_type=DELAY:  weiter, mark "delayed=True"
  4. distributed_lock_manager.acquire(instrument_id, position_side, holder)
       -> wenn success=False: REJECT mit reason="lock_held"
  5. trading_failover.route()
       -> active_strategy_id (PRIMARY oder FAILED_OVER-standby)
  6. saga_orchestrator.execute_saga([VALIDATE, RESERVE, EXECUTE,
                                      CONFIRM, SETTLE])
       -> wenn state != COMPLETED: cleanup_lock + REJECT
                                    mit reason="saga_failed"
  7. homeostasis_controller.record_allocation(asset_class, allocation_pct)
  8. audit_event_bus.publish(event_type, instrument_id, ...) -> final_audit
  9. distributed_lock_manager.release(...) -> cleanup

Optional chaos_mode=True: chaos_engineering.inject_random(strategy_id)
                          BEVOR Step 6 (Saga). Test-Hook fuer Resilience.

Threading: alle KPM-Module sind RLock-protected. Pipeline selbst ist
           thread-safe per Modul, aber concurrent submit_trade auf gleichem
           (instrument_id, position_side) wird durch Lock-Manager
           serialisiert.

Bio-Aequivalent: Komplette Immun-/Kreislauf-/Stoffwechsel-Kaskade einer
                 lebenden Zelle bei Antigen-Exposition (Trade als Antigen,
                 Pipeline als 9-stufige Selbstkontrolle).

CRUX-Bindung:
- K_0: Multi-Stage-Reject schuetzt vor Half-Open-Orders + Lock-Hijacking +
       Cap-Burst.
- Q_0: Audit-Trail (decision_path tuple) + frozen-Result fuer
       MiFID-RTS-25 Forensik.
- I_min: 9-Stages-Pflicht via State-Machine. Jeder REJECT ist deterministisch
         und reproducible.
- W_0: Lock-Auto-Release bei Saga-Fehler -> kein Working-Capital-Lock.

CRUX-MK
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# Relative imports innerhalb des kmo_governance-Pakets.
from ..kpm_audit_event_bus import (
    ComplianceTag,
    KPMAuditEventBus,
    TradeEventType,
)
from ..kpm_backpressure_engine import (
    KPMBackpressureEngine,
)
from ..kpm_chaos_engineering import (
    ChaosOutcome,
    ChaosScenario,
    FaultSeverity,
    FaultType,
    KPMChaosEngineering,
)
from ..kpm_deduplication_engine import (
    KPMDeduplicationEngine,
)
from ..kpm_distributed_lock_manager import (
    KPMDistributedTradeLockManager,
    PositionSide,
)
from ..kpm_feature_flag_engine import (
    FlagState,
    KPMFeatureFlagEngine,
)
from ..kpm_homeostasis_controller import (
    KPMHomeostasisController,
)
from ..kpm_saga_orchestrator import (
    KPMSagaOrchestrator,
    SagaPhase,
    SagaState,
    SagaStep,
)
from ..kpm_trading_failover import (
    FailoverState,
    KPMTradingFailover,
)


# Stage-Namen (Constants, exposed in decision_path):
STAGE_FEATURE_FLAG = "feature_flag"
STAGE_DEDUPLICATION = "deduplication"
STAGE_BACKPRESSURE = "backpressure"
STAGE_LOCK_ACQUIRE = "lock_acquire"
STAGE_FAILOVER_ROUTE = "failover_route"
STAGE_CHAOS_INJECT = "chaos_inject"  # optional
STAGE_SAGA_EXECUTE = "saga_execute"
STAGE_HOMEOSTASIS_RECORD = "homeostasis_record"
STAGE_AUDIT_PUBLISH = "audit_publish"
STAGE_LOCK_RELEASE = "lock_release"


@dataclass(frozen=True)
class TradeAdmissionResult:
    """Frozen Result einer kompletten Trade-Admission-Pipeline.

    Pre-Conditions:
        success ist bool.
        decision_path ist tuple of stage-name strings (Audit-Trail).
        reason non-empty (warum success oder warum REJECT).
        audit_event_id ist Optional[str] (uuid wenn Audit publiziert wurde).
        saga_id ist Optional[str] (uuid wenn Saga ausgefuehrt wurde).
        elapsed_ms >= 0.
        timestamp > 0.

    Post-Conditions:
        Frozen / hashable / immutable. Audit-Trail kann nicht ex-post
        manipuliert werden.

    Felder:
        success            : True wenn Trade durch alle 9 Stages durchlief.
        decision_path      : tuple aller durchlaufenen stage_names.
        reason             : human-readable Begruendung.
        audit_event_id     : event_id aus audit_event_bus.publish() (oder None).
        saga_id            : saga_id aus saga_orchestrator (oder None).
        active_strategy_id : Strategy-ID die letztendlich aktiv war
                             (primary oder failover-standby).
        elapsed_ms         : Wall-Clock-Latenz der Pipeline in Millisekunden.
        timestamp          : Unix-Timestamp am Ende der Pipeline.
    """

    success: bool
    decision_path: tuple
    reason: str
    audit_event_id: Optional[str]
    saga_id: Optional[str]
    active_strategy_id: str
    elapsed_ms: float
    timestamp: float

    def __post_init__(self) -> None:
        if not isinstance(self.decision_path, tuple):
            raise ValueError("decision_path must be tuple")
        if not self.reason:
            raise ValueError("reason required")
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must be >= 0")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be > 0")
        if not self.active_strategy_id:
            raise ValueError("active_strategy_id required")


def _default_saga_handler(step: SagaStep) -> dict:
    """Default Saga-Handler: liefert leeren Erfolg-Dict (no real broker).

    Pattern-Demo-Implementation. Reale Pipeline wuerde hier broker-spezifische
    Handler registrieren (z.B. Margin-Reservation-Call, Order-Submit-Call).
    """
    return {
        "step_id": step.step_id,
        "phase": step.phase.value,
        "ack": True,
    }


def _default_saga_compensator(step: SagaStep) -> None:
    """Default Saga-Compensator: no-op (Pattern-Demo).

    Reale Pipeline wuerde hier Margin-Release / Reverse-Order-Submit ausfuehren.
    """
    return None


def _default_chaos_handler(scenario: ChaosScenario) -> ChaosOutcome:
    """Default Chaos-Handler: synthetic-success outcome (Pattern-Demo)."""
    return ChaosOutcome(
        scenario_id=scenario.scenario_id,
        success=True,
        actual_recovery_s=scenario.expected_recovery_s,
        pnl_impact=0.0,
        observations=(f"default-handler {scenario.fault_type.value}",),
        timestamp=time.time(),
    )


class KPMTradeAdmissionPipeline:
    """End-to-End-Pipeline-Orchestrator der 9 KPM-Module.

    Pre-Conditions:
        primary_strategy_id non-empty.
        standby_strategy_ids non-empty list.

    Post-Conditions:
        Alle 9 Module instanziiert mit Trading-Defaults (siehe __init__).
        Saga + Chaos haben Default-Handler/-Compensator pre-registered fuer
        alle Phasen / strategy_ids in failover-pool.
        Pipeline ist thread-safe (RLock + per-Modul-Locks).

    Usage:
        pipe = KPMTradeAdmissionPipeline(
            primary_strategy_id="kelly-0.4",
            standby_strategy_ids=["kelly-0.3", "kelly-0.2"],
        )
        # Pre-Flight: Strategy-Flag aktivieren.
        pipe.feature_flags.set_state(
            "strategy_kelly-0.4", FlagState.ENABLED, "owner", "go-live"
        )
        result = pipe.submit_trade(
            strategy_id="kelly-0.4",
            instrument_id="BTCUSDT",
            side=PositionSide.LONG,
            quantity=0.5,
            price=42000.0,
            client_order_id="ord-001",
            request_id="req-001",
        )
        assert result.success
    """

    def __init__(
        self,
        primary_strategy_id: str,
        standby_strategy_ids: list,
        backpressure_max_orders_per_second: float = 100.0,
        backpressure_max_notional_per_minute: float = 1_000_000.0,
        homeostasis_setpoint_pct: float = 60.0,
        homeostasis_asset_class: str = "equities",
        lock_default_ttl_s: float = 5.0,
        dedup_default_ttl_s: float = 300.0,
        feature_flag_audit_retention_h: float = 168.0,
        audit_retention_h: float = 168.0,
        chaos_default_severity: FaultSeverity = FaultSeverity.MINOR,
    ) -> None:
        if not primary_strategy_id:
            raise ValueError("primary_strategy_id required")
        if not standby_strategy_ids:
            raise ValueError("standby_strategy_ids required (>=1)")

        self._primary_strategy_id = primary_strategy_id
        self._standby_strategy_ids = list(standby_strategy_ids)
        self._homeostasis_asset_class = homeostasis_asset_class
        self._lock = threading.RLock()

        # 1. Feature-Flag-Engine
        self.feature_flags = KPMFeatureFlagEngine(
            default_audit_retention_h=feature_flag_audit_retention_h,
        )

        # 2. Deduplication-Engine
        self.deduplication = KPMDeduplicationEngine(
            default_ttl_s=dedup_default_ttl_s,
        )

        # 3. Backpressure-Engine
        self.backpressure = KPMBackpressureEngine(
            max_orders_per_second=backpressure_max_orders_per_second,
            max_notional_per_minute=backpressure_max_notional_per_minute,
        )

        # 4. Distributed-Lock-Manager
        self.lock_manager = KPMDistributedTradeLockManager(
            default_ttl_s=lock_default_ttl_s,
        )

        # 5. Trading-Failover (Active-Standby)
        self.failover = KPMTradingFailover(
            primary_strategy_id=primary_strategy_id,
            standby_strategy_ids=standby_strategy_ids,
        )

        # 6. Saga-Orchestrator (Multi-Leg-Atomicity)
        self.saga = KPMSagaOrchestrator()
        for phase in SagaPhase:
            self.saga.register_handler(phase, _default_saga_handler)
            self.saga.register_compensator(phase, _default_saga_compensator)

        # 7. Homeostasis-Controller (Allocation-Drift)
        self.homeostasis = KPMHomeostasisController(
            setpoint_pct=homeostasis_setpoint_pct,
            asset_class=homeostasis_asset_class,
        )

        # 8. Audit-Event-Bus (Compliance)
        self.audit_bus = KPMAuditEventBus(retention_window_h=audit_retention_h)

        # 9. Chaos-Engineering (optional Pre-Saga-Inject)
        self.chaos = KPMChaosEngineering(
            default_severity=chaos_default_severity,
        )
        # Register default-handler fuer alle bekannten Strategien
        for sid in [primary_strategy_id, *standby_strategy_ids]:
            self.chaos.register_strategy(sid, _default_chaos_handler)

        # Pre-register Feature-Flag pro Strategy (default DISABLED).
        # Caller muss set_state(ENABLED) machen um trades durchzulassen.
        for sid in [primary_strategy_id, *standby_strategy_ids]:
            self.feature_flags.register_flag(
                flag_id=f"strategy_{sid}",
                strategy_id=sid,
                default_state=FlagState.DISABLED,
                description=f"Master-Switch fuer {sid}",
                owner_session_id="kpm-demo",
            )

    def _build_result(
        self,
        success: bool,
        decision_path: list,
        reason: str,
        active_strategy_id: str,
        start_monotonic: float,
        audit_event_id: Optional[str] = None,
        saga_id: Optional[str] = None,
    ) -> TradeAdmissionResult:
        """Internal: konstruiert TradeAdmissionResult mit gemessener elapsed_ms."""
        elapsed_ms = max(0.0, (time.monotonic() - start_monotonic) * 1000.0)
        return TradeAdmissionResult(
            success=success,
            decision_path=tuple(decision_path),
            reason=reason,
            audit_event_id=audit_event_id,
            saga_id=saga_id,
            active_strategy_id=active_strategy_id,
            elapsed_ms=elapsed_ms,
            timestamp=time.time(),
        )

    def submit_trade(
        self,
        strategy_id: str,
        instrument_id: str,
        side: PositionSide,
        quantity: float,
        price: float,
        client_order_id: str,
        request_id: str,
        chaos_mode: bool = False,
        allocation_pct: Optional[float] = None,
    ) -> TradeAdmissionResult:
        """Run kompletten 9-Stage-Pipeline fuer einen Trade.

        Pre-Conditions:
            strategy_id non-empty (muss in failover-pool sein).
            instrument_id non-empty.
            side ist PositionSide-Enum.
            quantity > 0.
            price > 0.
            client_order_id non-empty.
            request_id non-empty.

        Post-Conditions:
            TradeAdmissionResult (frozen) zurueckgegeben.
            Bei success=True: alle 9 Stages durchlaufen, Audit-Event publiziert,
                              Lock released, Allocation recorded.
            Bei success=False: Pipeline early-exited, Lock released falls
                               schon acquired, decision_path enthaelt den
                               REJECT-Stage.

        Notes:
            chaos_mode=True schaltet Pre-Saga-Chaos-Inject ein (Test-Hook).
            allocation_pct=None nutzt eine domain-Default-Schaetzung
            (price * quantity / nominal-portfolio-base) waere zu komplex —
            wir nutzen 60.0 als Default fuer den Demo-Pfad.
        """
        # Input-Validierung (Pre-Conditions)
        if not strategy_id:
            raise ValueError("strategy_id required")
        if not instrument_id:
            raise ValueError("instrument_id required")
        if not isinstance(side, PositionSide):
            raise ValueError("side must be PositionSide enum")
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if price <= 0:
            raise ValueError("price must be > 0")
        if not client_order_id:
            raise ValueError("client_order_id required")
        if not request_id:
            raise ValueError("request_id required")

        start_monotonic = time.monotonic()
        decision_path: list = []
        active_strategy_id = strategy_id
        flag_id = f"strategy_{strategy_id}"
        lease_token: Optional[str] = None

        # ----- Stage 1: Feature-Flag -----
        decision_path.append(STAGE_FEATURE_FLAG)
        flag_decision = self.feature_flags.evaluate(
            flag_id=flag_id,
            request_id=request_id,
        )
        if not flag_decision.enabled:
            return self._build_result(
                success=False,
                decision_path=decision_path,
                reason=f"strategy_disabled (flag={flag_decision.state.value})",
                active_strategy_id=active_strategy_id,
                start_monotonic=start_monotonic,
            )

        # ----- Stage 2: Deduplication -----
        decision_path.append(STAGE_DEDUPLICATION)
        dedup_payload = {
            "instrument_id": instrument_id,
            "side": side.value,
            "quantity": quantity,
            "price": price,
        }
        dedup_result = self.deduplication.check(
            client_order_id=client_order_id,
            order_payload=dedup_payload,
            strategy_id=strategy_id,
        )
        if dedup_result.is_duplicate:
            return self._build_result(
                success=False,
                decision_path=decision_path,
                reason=f"duplicate_order (client_order_id={client_order_id})",
                active_strategy_id=active_strategy_id,
                start_monotonic=start_monotonic,
            )

        # ----- Stage 3: Backpressure -----
        decision_path.append(STAGE_BACKPRESSURE)
        notional = quantity * price
        self.backpressure.record_order(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            notional=notional,
        )
        bp_decision = self.backpressure.evaluate(strategy_id=strategy_id)
        if bp_decision.action.action_type == "REJECT":
            return self._build_result(
                success=False,
                decision_path=decision_path,
                reason=f"backpressure_blocked (state={bp_decision.state.value})",
                active_strategy_id=active_strategy_id,
                start_monotonic=start_monotonic,
            )
        delayed = bp_decision.action.action_type == "DELAY"

        # ----- Stage 4: Lock-Acquire -----
        decision_path.append(STAGE_LOCK_ACQUIRE)
        lock_result = self.lock_manager.acquire(
            instrument_id=instrument_id,
            position_side=side,
            holder_strategy_id=strategy_id,
        )
        if not lock_result.success:
            return self._build_result(
                success=False,
                decision_path=decision_path,
                reason=(
                    f"lock_held (conflict={lock_result.conflict_holder})"
                ),
                active_strategy_id=active_strategy_id,
                start_monotonic=start_monotonic,
            )
        assert lock_result.lease is not None
        lease_token = lock_result.lease.lease_token

        # Hilfs-Helper: cleanup-on-error
        def _release_lock() -> None:
            assert lease_token is not None
            self.lock_manager.release(
                instrument_id=instrument_id,
                position_side=side,
                lease_token=lease_token,
            )

        try:
            # ----- Stage 5: Failover-Routing -----
            decision_path.append(STAGE_FAILOVER_ROUTE)
            routing_decision = self.failover.route()
            active_strategy_id = routing_decision.active_strategy_id
            if routing_decision.state == FailoverState.FAILED_OVER:
                # Standby-strategy active; wir respektieren das.
                pass

            # ----- Optional Stage: Chaos-Inject (Pre-Saga) -----
            if chaos_mode:
                decision_path.append(STAGE_CHAOS_INJECT)
                self.chaos.inject_random(strategy_id=active_strategy_id)

            # ----- Stage 6: Saga-Execute -----
            decision_path.append(STAGE_SAGA_EXECUTE)
            steps = [
                SagaStep(
                    step_id=f"{client_order_id}-{phase.value}",
                    phase=phase,
                    instrument_id=instrument_id,
                    action_data=(
                        ("strategy_id", active_strategy_id),
                        ("side", side.value),
                        ("quantity", quantity),
                        ("price", price),
                    ),
                    compensation_data=(
                        ("client_order_id", client_order_id),
                    ),
                )
                for phase in (
                    SagaPhase.VALIDATE,
                    SagaPhase.RESERVE,
                    SagaPhase.EXECUTE,
                    SagaPhase.CONFIRM,
                    SagaPhase.SETTLE,
                )
            ]
            saga_outcome = self.saga.execute_saga(steps)
            saga_id = saga_outcome.saga_id
            if saga_outcome.state != SagaState.COMPLETED:
                _release_lock()
                return self._build_result(
                    success=False,
                    decision_path=decision_path,
                    reason=(
                        f"saga_failed (state={saga_outcome.state.value}, "
                        f"failed_step={saga_outcome.failed_step})"
                    ),
                    active_strategy_id=active_strategy_id,
                    start_monotonic=start_monotonic,
                    saga_id=saga_id,
                )

            # ----- Stage 7: Homeostasis-Record -----
            decision_path.append(STAGE_HOMEOSTASIS_RECORD)
            effective_alloc_pct = (
                allocation_pct
                if allocation_pct is not None
                else self.homeostasis.setpoint_pct
            )
            self.homeostasis.record_allocation(
                asset_class=self._homeostasis_asset_class,
                allocation_pct=effective_alloc_pct,
            )

            # ----- Stage 8: Audit-Publish -----
            decision_path.append(STAGE_AUDIT_PUBLISH)
            event_type = (
                TradeEventType.BUY
                if side == PositionSide.LONG
                else TradeEventType.SELL
            )
            audit_event = self.audit_bus.publish(
                strategy_id=active_strategy_id,
                event_type=event_type,
                instrument_id=instrument_id,
                quantity=quantity,
                price=price,
                compliance_tags=frozenset({
                    ComplianceTag.MIFID_BEST_EXEC,
                    ComplianceTag.POSITION_LIMIT,
                }),
                metadata=(
                    ("client_order_id", client_order_id),
                    ("request_id", request_id),
                    ("saga_id", saga_id),
                    ("delayed", delayed),
                ),
            )

            # ----- Stage 9: Lock-Release -----
            decision_path.append(STAGE_LOCK_RELEASE)
            _release_lock()
            lease_token = None  # markiert dass Release schon erfolgte

            return self._build_result(
                success=True,
                decision_path=decision_path,
                reason=(
                    f"admitted (saga={saga_id[:8]}..., "
                    f"audit={audit_event.event_id[:8]}...)"
                ),
                active_strategy_id=active_strategy_id,
                start_monotonic=start_monotonic,
                audit_event_id=audit_event.event_id,
                saga_id=saga_id,
            )
        except Exception as exc:
            # Defensive: bei UNEXPECTED-Exception Lock immer releasen.
            if lease_token is not None:
                try:
                    _release_lock()
                except Exception:
                    pass  # secondary error; original exc weiter
            return self._build_result(
                success=False,
                decision_path=decision_path,
                reason=f"pipeline_exception ({type(exc).__name__}: {exc})",
                active_strategy_id=active_strategy_id,
                start_monotonic=start_monotonic,
            )


# CRUX-MK
