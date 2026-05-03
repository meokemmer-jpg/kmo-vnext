"""KMO HeyLou-Pilot Cell-Layer Integration [CRUX-MK].

Welle-9α Phase-1.2.5: Pilot-DF fuer 1 Hotel mit komplettem Cell-Layer-Stack:
  - cell_boundary  (Membrane, Quotas, I/O-Audit, Multi-Tenancy)
  - apoptosis_engine (Multi-Signal-Trigger + Bcl-2 + Cytochrome-c)
  - wound_healing  (4-Phase-Lifecycle ersetzt direkte Saga-Compensation)
  - saga-pattern   (existing + Hotel-ID-Scoping)

Pilot-Hotel: EU-Apaleo (Architekt-Empfehlung wegen GDPR-Stringenz).

Diese Klasse orchestriert die 4 Module zu einem Single-Hotel-Saga-Run.
PRE-3 E2E-Tests verifizieren full booking pipeline through new Cell-Layer.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

# Ensure kmo/ is on sys.path for absolute imports.
_KMO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

# Saga-pattern: existing module not a package; use direct file import.
sys.path.insert(0, str(_KMO_ROOT / "kmo_governance" / "saga-pattern"))
from kmo_saga_engine import SagaEngine, SagaResult, SagaStatus  # noqa: E402

# Cell-Layer modules (proper packages).
from kmo_governance.apoptosis_engine import (  # noqa: E402
    ApoptoseState,
    ApoptosisEngine,
    Bcl2Modulator,
    TriggerType,
)
from kmo_governance.cell_boundary import (  # noqa: E402
    BoundaryAuditLog,
    CellBoundary,
    CellBoundaryManager,
    CellQuota,
    QuotaEnforcer,
    QuotaExhaustedError,
)
from kmo_governance.wound_healing import (  # noqa: E402
    HealingPhase,
    WoundHealingLifecycle,
)

# Tissue-Layer (Welle-9β Phase-2)
from kmo_governance.lateral_inhibition import (  # noqa: E402
    CorrelatedFailureDetector,
    LateralInhibitor,
)
from kmo_governance.quorum_sensing import QuorumEngine  # noqa: E402
from kmo_governance.stigmergic_blackboard import (  # noqa: E402
    BlackboardStore,
    SandpileLoadDistributor,
)

# Organ-Layer (Welle-9γ Phase-3)
from kmo_governance.abs_tier_engine import (  # noqa: E402
    ABSTier,
    ABSTierRouter,
    HormonePool,
    HormoneType,
    PricingHomeostasis,
)
from kmo_governance.hotel_membrane import (  # noqa: E402
    CrossHotelQueryBlocker,
    DataCategory,
    GDPRComplianceLayer,
    HotelMembrane,
)
from kmo_governance.multi_signal_policy import (  # noqa: E402
    MultiSignalAggregator,
    PolicyState,
    PolicyStateMachine,
    SignalSpec,
)

# Welle-9-delta Phase-4 Organism-Layer integration
from kmo_governance.sigma_switch import SigmaMode, SigmaSwitch  # noqa: E402
from kmo_governance.sleep_cycles import (  # noqa: E402
    CycleType,
    SleepCyclesEngine,
    SleepWindow,
)
from kmo_governance.knowledge_decay import KnowledgeDecayEngine  # noqa: E402
from kmo_governance.kmo_master_orchestrator import (  # noqa: E402
    HealthStatus,
    KMOMasterOrchestrator,
    VitalSigns,
)


class PilotHotelOrchestrator:
    """Single-Hotel Cell-Layer Pilot Orchestrator [CRUX-MK].

    Wires Cell-Boundary, Apoptose-Engine, Wound-Healing and Saga-Engine into
    one tenant-scoped pipeline. Phase-1 Skeleton: shows integration topology
    + PRE-3 E2E-tests work through it.

    Pre-Conditions:
        - hotel_id non-empty
        - state_dir, audit_db_path, snapshot_dir writable
        - quota optional (None = unlimited; not recommended for production)

    Post-Conditions:
        - Each saga-run creates a Cell-Boundary scoped to hotel_id
        - Quota-exhaustion triggers ApoptosisEngine.signal(QUOTA_EXHAUSTED)
        - Saga-FAILED triggers WoundHealingLifecycle (instead of direct compensation)
        - Audit-trail written to BoundaryAuditLog
    """

    def __init__(
        self,
        hotel_id: str,
        state_dir: Path,
        audit_db_path: Optional[Path] = None,
        snapshot_dir: Optional[Path] = None,
        quota: Optional[CellQuota] = None,
        tissue_id: Optional[str] = None,
        blackboard_db_path: Optional[Path] = None,
        df_topology: Optional[dict] = None,
    ) -> None:
        if not hotel_id:
            raise ValueError("hotel_id required")
        self.hotel_id = hotel_id
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.audit_log = BoundaryAuditLog(db_path=audit_db_path)
        self.bcl2 = Bcl2Modulator()
        self.apoptosis = ApoptosisEngine(
            snapshot_dir=snapshot_dir or (self.state_dir / "apoptose"),
            bcl2_modulator=self.bcl2,
        )
        # Wire live cell-state into Cytochrome-c-Snapshots (Copilot-Patch B).
        self.apoptosis.register_state_provider(self._provide_cell_state)
        self.saga = SagaEngine(self.state_dir)

        # Tissue-Layer (Welle-9β Phase-2): integration with Cell-Layer.
        # tissue_id default: "tissue-{hotel_id}" (one tissue per pilot for skeleton).
        self.tissue_id = tissue_id or f"tissue-{hotel_id}"
        self.quorum = QuorumEngine(
            K_d=2.0, hill_n=2.7, decay_lambda=0.05,
            activation_threshold=0.5, min_unique_dfs=3,
        )
        self.blackboard = BlackboardStore(
            db_path=blackboard_db_path or (self.state_dir / "blackboard.db"),
            machine_id=f"pilot-{hotel_id}",
            decay_lambda=0.01,
        )
        # Topology default: pilot itself as single-node (linear with itself).
        # In production: each DF-Run becomes a node with neighbor-DFs from same tissue.
        self._df_topology = df_topology or {}
        self.lateral = LateralInhibitor(
            topology=self._df_topology or {hotel_id: []},
        )
        self.failure_detector = CorrelatedFailureDetector(
            window_sec=60.0, z_threshold=3.0,
        )
        # Patch C4 (Codex-Finding #2): SandpileLoadDistributor instanziiert + verdrahtet,
        # nicht nur importiert. Topology default = pilot-self. Persistence via Blackboard.
        sandpile_topology = self._df_topology or {hotel_id: []}
        self.sandpile = SandpileLoadDistributor(
            topology=sandpile_topology,
            z_crit=4.0,
            blackboard=self.blackboard,
            tissue_id=self.tissue_id,
            df_id_self=hotel_id,
        )

        # Organ-Layer (Welle-9γ Phase-3) — verdrahtet im Pilot
        self.membrane = HotelMembrane(
            hotel_id=hotel_id,
            base_state_dir=self.state_dir,
            region="EU",
        )
        self.gdpr = GDPRComplianceLayer(
            audit_path=self.state_dir / "gdpr_audit.jsonl"
        )
        # Patch E2 (Welle-9γ Open-Item #1, Copilot+Codex): CrossHotelQueryBlocker
        # main-path-wired. Pilot-DFs are NOT in whitelist by default; they must use
        # hotel_id filter in any SQL query. Organism-Layer-DFs (Welle-9δ) can be
        # whitelisted explicitly for Cross-Hotel-Aggregations.
        self.query_blocker = CrossHotelQueryBlocker()
        self.hormone_pool = HormonePool(halflife_sec=4 * 3600)
        self.abs_router = ABSTierRouter(
            self.hormone_pool, K_d=10.0, hill_n=3.0,
            smart_max_y=0.3, hybrid_max_y=0.7,
        )
        self.homeostasis = PricingHomeostasis(
            self.hormone_pool, spiral_threshold=10.0,
        )
        # Multi-Signal-Policy with default 5-signal-spec set (revenue, latency, errors, cost, risk)
        default_specs = {
            "revenue": SignalSpec("revenue", K_d=100.0, hill_n=2.0, weight=2.0),
            "latency_ms": SignalSpec("latency_ms", K_d=200.0, hill_n=3.0, weight=1.5),
            "error_rate": SignalSpec("error_rate", K_d=0.05, hill_n=4.0, weight=2.5),
            "cost_eur": SignalSpec("cost_eur", K_d=1000.0, hill_n=2.0, weight=1.0),
            "risk_score": SignalSpec("risk_score", K_d=0.3, hill_n=3.0, weight=1.5),
        }
        self.multi_signal = MultiSignalAggregator(default_specs)
        self.policy_machine = PolicyStateMachine(
            self.multi_signal, initial_state=PolicyState.MODERATE,
        )

        # Welle-9-delta Phase-4 Organism-Layer instances (lazy-wired in master)
        self.sigma_switch = SigmaSwitch()
        self.sleep_cycles = SleepCyclesEngine(timezone_name="Europe/Berlin")
        self.sleep_cycles.add_window(
            CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6)
        )
        self.sleep_cycles.add_window(
            CycleType.WEEKLY, SleepWindow(start_hour=2, end_hour=6, weekday=6)
        )
        self.knowledge_decay = KnowledgeDecayEngine()
        self.master = KMOMasterOrchestrator(
            sigma_switch=self.sigma_switch,
            knowledge_decay=self.knowledge_decay,
            sleep_cycles=self.sleep_cycles,
        )
        self.master.enable_off_peak_actions()

        self.quota = quota or CellQuota(
            llm_token_budget=50_000,
            cpu_seconds=300,
            memory_mb=512,
            io_calls_per_minute=120,
        )

        # Per-saga-run cell-managers (lazy-created)
        self._cell_managers: dict[str, CellBoundaryManager] = {}
        self._enforcers: dict[str, QuotaEnforcer] = {}
        self._healings: dict[str, WoundHealingLifecycle] = {}
        self._lock = threading.RLock()

        # Wire Cell-Layer composition into Saga-Engine
        self.saga.set_cell_quotas(self.quota)
        self.saga.register_apoptosis_handler(self._on_quota_exhausted)
        self.saga.enable_wound_healing(self._healing_factory)
        # Welle-9γ Codex-Finding #1: Phase-2 main-control-path via phase_admit_check.
        # Default policy: allow all phases UNLESS correlated-failure-alarm fires.
        self.saga.register_phase_admit_check(self._phase_admit_check)
        # Welle-9δ Pre-Patch #5 (Codex Open-Item #5):
        # Membrane-check on saga-phase inputs/outputs (multi-tenancy enforcement).
        self.saga.register_phase_membrane_check(self._phase_membrane_check)

    # ---------------- Public API ----------------

    def begin_saga_run(self, run_id: str) -> tuple[CellBoundaryManager, QuotaEnforcer]:
        """Initialize cell-boundary for a saga-run. Returns manager + enforcer."""
        with self._lock:
            if run_id in self._cell_managers:
                return self._cell_managers[run_id], self._enforcers[run_id]
            boundary = CellBoundary(
                cell_id=run_id,
                hotel_id=self.hotel_id,
                quota=self.quota,
            )
            mgr = CellBoundaryManager(
                boundary,
                on_quota_exhausted=lambda reason, details: self._on_cell_quota_exhausted(
                    run_id, reason, details
                ),
            )
            enforcer = QuotaEnforcer(mgr, self.audit_log)
            self._cell_managers[run_id] = mgr
            self._enforcers[run_id] = enforcer
            return mgr, enforcer

    def execute_saga(
        self,
        run_id: str,
        initial_input: Any,
    ) -> SagaResult:
        """Run a saga end-to-end with Cell-Layer composition active."""
        # Ensure cell-boundary is initialized.
        self.begin_saga_run(run_id)
        return self.saga.execute(run_id, initial_input, hotel_id=self.hotel_id)

    def get_cell_state(self, run_id: str) -> dict:
        """Return current cell-state snapshot (for forensics)."""
        with self._lock:
            mgr = self._cell_managers.get(run_id)
            if mgr is None:
                return {}
            return {
                "cell_id": mgr.boundary.cell_id,
                "hotel_id": mgr.boundary.hotel_id,
                "consumed_tokens": mgr.consumed_tokens,
                "consumed_cpu": mgr.consumed_cpu,
                "consumed_memory": mgr.consumed_memory,
                "remaining_tokens": mgr.remaining_tokens(),
                "is_apoptosed": mgr.is_apoptosed,
                "apoptose_reason": mgr.apoptose_reason,
            }

    def get_apoptose_state(self, run_id: str) -> Optional[ApoptoseState]:
        return self.apoptosis.get_state(run_id, self.hotel_id)

    def get_healing(self, run_id: str) -> Optional[WoundHealingLifecycle]:
        with self._lock:
            return self._healings.get(run_id)

    def purge_hotel(self) -> dict:
        """GDPR cascade-delete all data for this pilot's hotel.

        Welle-9γ erweitert: GDPR-Consent + HormonePool werden auch gepurged.
        """
        events_deleted = self.audit_log.purge_hotel(self.hotel_id)
        snapshots_deleted = self.apoptosis.snapshotter.purge_hotel(self.hotel_id)
        gdpr_purged = self.gdpr.purge_hotel_data(self.hotel_id)
        hormones_deleted = self.hormone_pool.purge_hotel(self.hotel_id)
        return {
            "events_deleted": events_deleted,
            "snapshots_deleted": snapshots_deleted,
            "gdpr_consents_purged": gdpr_purged["consent_records_purged"],
            "hormones_deleted": hormones_deleted,
        }

    # ---------------- Internal hooks ----------------

    def _on_cell_quota_exhausted(self, run_id: str, reason: str, details: dict) -> None:
        """Cell-Boundary signaled quota-exhaustion. Forward to ApoptosisEngine."""
        self.apoptosis.signal(
            cell_id=run_id,
            hotel_id=self.hotel_id,
            trigger=TriggerType.QUOTA_EXHAUSTED,
            intensity=1.0,
        )

    def _on_quota_exhausted(self, cell_id: str, hotel_id: str, reason: str) -> None:
        """Saga-Engine signaled quota-exhaustion (Phase-1 stub)."""
        self.apoptosis.signal(
            cell_id=cell_id,
            hotel_id=hotel_id,
            trigger=TriggerType.QUOTA_EXHAUSTED,
            intensity=1.0,
        )

    def _healing_factory(
        self, saga_run_id: str, hotel_id: str, failure_reason: str
    ) -> WoundHealingLifecycle:
        """Create a WoundHealingLifecycle for a failed saga + start hemostasis."""
        healing = WoundHealingLifecycle(
            saga_run_id=saga_run_id,
            hotel_id=hotel_id,
            cleanup_callback=lambda ctx: self._healing_cleanup(saga_run_id, ctx),
            restart_callback=lambda ctx: self._healing_restart(saga_run_id, ctx),
            optimize_callback=lambda ctx: self._healing_optimize(saga_run_id, ctx),
        )
        healing.start_hemostasis(failure_reason)
        with self._lock:
            self._healings[saga_run_id] = healing
        return healing

    def _healing_cleanup(self, saga_run_id: str, ctx: Any) -> None:
        """Inflammation-phase: free cell resources."""
        with self._lock:
            mgr = self._cell_managers.pop(saga_run_id, None)
            self._enforcers.pop(saga_run_id, None)
        ctx.cleanup_artifacts.append(f"cell-released:{saga_run_id}")

    def _healing_restart(self, saga_run_id: str, ctx: Any) -> None:
        """Proliferation-phase: re-init cell + saga (Phase-1 logs only)."""
        ctx.extra.setdefault("restart_log", []).append(
            f"would-resume-{saga_run_id}"
        )

    def _healing_optimize(self, saga_run_id: str, ctx: Any) -> None:
        """Remodeling-phase: schema-migration / tuning (Phase-1 stub)."""
        ctx.optimization_notes.append(f"pilot-optimize:{saga_run_id}")

    def _provide_cell_state(self, cell_id: str, hotel_id: str) -> dict:
        """Live cell-state provider for Cytochrome-c-Snapshots (Patch B)."""
        # `cell_id` here is the saga_run_id (apoptosis_engine + cell_boundary share id).
        return self.get_cell_state(cell_id)

    # ---------- Tissue-Layer composition API (Welle-9β Phase-2) ----------

    def emit_tissue_signal(
        self, signal_type: str, df_id: str, strength: float = 1.0
    ) -> None:
        """Emit a quorum-sensing signal for this pilot's tissue + record on blackboard."""
        self.quorum.emit_signal(
            tissue_id=self.tissue_id,
            signal_type=signal_type,
            df_id=df_id,
            strength=strength,
        )
        self.blackboard.append(
            tissue_id=self.tissue_id,
            topic=f"signal:{signal_type}",
            written_by_df=df_id,
            payload={"strength": strength},
            ttl_sec=300,
        )

    def is_quorum_active(self, signal_type: str) -> bool:
        """Check whether tissue-level quorum is active for a given signal-type."""
        return self.quorum.is_quorum_active(self.tissue_id, signal_type)

    def admit_action(self, df_id: str, action_kind: str) -> bool:
        """Lateral-inhibition admission check for a df+action combo.

        Patch C5 (Codex-Finding #3): on admit, automatically signal_intent so
        future neighbor admissions accumulate inhibition state correctly.
        """
        if df_id not in self.lateral.topology:
            return False  # unknown df: refuse
        admitted = self.lateral.admit(df_id, action_kind)
        if admitted:
            self.lateral.signal_intent(df_id, action_kind)
        return admitted

    def increment_load(self, df_id: str, amount: float = 1.0) -> list:
        """Sandpile-SOC load increment + cascade-avalanche (Patch C4 Codex-#2 main-path)."""
        if df_id not in self.sandpile.topology:
            return []  # not in topology -> ignore (skeleton)
        return self.sandpile.increment_load(df_id, amount=amount)

    # ---------- Organ-Layer composition API (Welle-9γ Phase-3) ----------

    def emit_demand(self, amount: float = 1.0) -> None:
        """Emit demand-signal hormone for this pilot's hotel."""
        self.hormone_pool.emit(self.hotel_id, HormoneType.DEMAND_SIGNAL, amount)

    def emit_capacity_pressure(self, amount: float = 1.0) -> None:
        self.hormone_pool.emit(self.hotel_id, HormoneType.CAPACITY_PRESSURE, amount)

    def get_pricing_tier(self) -> ABSTier:
        """ABS-Tier-Routing decision (SMART/HYBRID/VOLL) per current hormones."""
        return self.abs_router.route(self.hotel_id)

    def check_pricing_homeostasis(self) -> bool:
        """Check + apply pricing-spiral negative-feedback. Returns True if dampened."""
        return self.homeostasis.check_and_dampen(self.hotel_id)

    def policy_tick(self, signals: dict) -> PolicyState:
        """Update policy-state-machine via current multi-signal aggregate."""
        return self.policy_machine.tick(signals)

    def grant_gdpr_consent(self, category: DataCategory, notes: str = "") -> None:
        """Record GDPR-consent for a data-category."""
        self.gdpr.grant_consent(self.hotel_id, category, notes=notes)

    def has_gdpr_consent(self, category: DataCategory) -> bool:
        return self.gdpr.has_consent(self.hotel_id, category)

    def check_sql_query(self, sql: str, caller_id: str) -> bool:
        """Patch E2: SQL-Query-Pre-Hook against Cross-Hotel-Leaks.

        Raises PermissionError if SQL query lacks hotel_id-filter and caller_id
        is not whitelisted for Cross-Hotel-Aggregations.
        """
        return self.query_blocker.check_query(sql, caller_id)

    def whitelist_aggregator(self, caller_id: str) -> None:
        """Add a caller-id to the Cross-Hotel-Aggregator-Whitelist (Organism-Layer)."""
        self.query_blocker.add_to_whitelist(caller_id)

    # ---------- Welle-9-delta Phase-4 Organism-Layer Public API ----------

    def get_system_health(self) -> dict:
        """Welle-9-delta: Top-Level system status from KMOMasterOrchestrator."""
        return self.master.get_status()

    def update_system_vitals(
        self,
        heart_rate: float,
        blood_pressure: float,
        body_temperature: float,
        oxygen_saturation: float,
    ) -> dict:
        """Welle-9-delta: feed vital-signs into homeostasis-coordinator.

        Returns action-summary (sigma_switch reactions, sleep transitions, etc.).
        """
        vitals = VitalSigns(
            timestamp=time.time(),
            heart_rate=heart_rate,
            blood_pressure=blood_pressure,
            body_temperature=body_temperature,
            oxygen_saturation=oxygen_saturation,
        )
        return self.master.update_vitals(vitals)

    def signal_emergency(self, reason: str) -> dict:
        """Welle-9-delta: trigger system-wide INCIDENT-mode."""
        return self.master.emergency_signal(reason)

    def get_current_mode(self) -> str:
        """Welle-9-delta: current SigmaSwitch-Mode (NORMAL/PEAK_LOAD/INCIDENT/...)."""
        return self.sigma_switch.current_mode().value

    def is_df_active(self, df_id: str) -> bool:
        """Welle-9-delta: True if df_id is allowed in current Mode."""
        return self.sigma_switch.is_df_active(df_id)

    def is_sleeping_now(self) -> bool:
        """Welle-9-delta: True if currently in sleep-window (off-peak/weekly)."""
        return self.sleep_cycles.should_sleep_now()

    def trigger_glymphatic_cleanup(self) -> dict:
        """Welle-9-delta: invoke off-peak knowledge_decay+prune (manual trigger)."""
        result = self.sleep_cycles.trigger_glymphatic_cleanup()
        return {
            "success": result.success,
            "items_pruned": result.items_pruned,
            "error": result.error,
        }

    def register_knowledge_entry(
        self,
        key: str,
        confidence: float = 0.5,
        stability_days: float = 1.0,
    ):
        """Welle-9-delta: register a knowledge entry (FSRS-tracked)."""
        return self.knowledge_decay.register(
            key=key,
            initial_confidence=confidence,
            initial_stability=stability_days,
        )

    def use_knowledge(self, key: str, performance: float = 1.0):
        """Welle-9-delta: LTP-boost on knowledge use."""
        return self.knowledge_decay.use(key, performance=performance)

    def _phase_admit_check(self, run_id: str, hotel_id: str, phase_id: str) -> bool:
        """Welle-9γ Codex-Finding #1 + Patch E3 (Welle-9γ Open-Item #4):
        Phase-2/3 main-control-path gate.

        Blocks:
        1. correlated-failure-alarm (tissue-wide Z-Score-Alert)
        2. EMERGENCY policy-state (multi_signal_policy says crisis)

        Phase-2/3 fully integrated into saga main-path.
        """
        if hotel_id != self.hotel_id:
            return True  # foreign saga: allow (we don't gate other tenants)
        # Block #1: correlated-failure-alarm fires for our tissue
        if self.is_correlated_failure():
            return False
        # Block #2 (Patch E3): EMERGENCY policy-state — system-wide crisis
        if self.policy_machine.state == PolicyState.EMERGENCY:
            return False
        return True

    def _phase_membrane_check(
        self, hotel_id: str, phase_id: str, kind: str, payload
    ) -> bool:
        """Welle-9δ Pre-Patch #5 + Patch F3 + Patch F6:
        Recursive Membrane-Check on saga-phase inputs/outputs.

        Patch F6 (Gemini-V2 Finding "Circular-Reference Risk"):
        Explicit visited-set fuer cycle-detection (Memory-Effizienz statt nur depth-cap).
        """
        if hotel_id != self.hotel_id:
            return True  # foreign saga: not our membrane
        # Patch F6: visited-set tracks Object-IDs zur Cycle-Detection
        return self._membrane_check_recursive(
            hotel_id, payload, depth=0, visited=set()
        )

    def _membrane_check_recursive(
        self,
        hotel_id: str,
        payload,
        depth: int = 0,
        max_depth: int = 16,
        visited=None,
    ) -> bool:
        """Recursive membrane-validation. Patch F3 + Patch F6 visited-set.

        Patch F6: visited-set verhindert Memory-Spike bei zyklischen Payloads.
        Cycle-Detection via id(obj) statt nur depth-cap.
        """
        if visited is None:
            visited = set()
        # Patch F6: cycle detection via object-id
        # Only track containers (dict/list/tuple/object) - scalars are immutable
        if isinstance(payload, (dict, list, tuple)) or hasattr(payload, "__dict__"):
            obj_id = id(payload)
            if obj_id in visited:
                return True  # cycle: already validated, treat as pass
            visited.add(obj_id)
        # Depth-guard against pathological non-cyclic nesting
        if depth > max_depth:
            return True  # graceful: don't block on deep recursion
        # None / scalars: pass
        if payload is None:
            return True
        if isinstance(payload, (str, int, float, bool)):
            return True
        # Dict: check local hotel_id then recurse into values
        if isinstance(payload, dict):
            tagged = payload.get("hotel_id")
            if tagged is not None and tagged != hotel_id:
                return False
            for value in payload.values():
                if not self._membrane_check_recursive(
                    hotel_id, value, depth + 1, max_depth, visited
                ):
                    return False
            return True
        # List / Tuple: recurse into each element
        if isinstance(payload, (list, tuple)):
            for item in payload:
                if not self._membrane_check_recursive(
                    hotel_id, item, depth + 1, max_depth, visited
                ):
                    return False
            return True
        # Dataclass-like: introspect __dict__
        if hasattr(payload, "__dict__"):
            return self._membrane_check_recursive(
                hotel_id, vars(payload), depth + 1, max_depth, visited
            )
        # Unknown type: pass (don't block on unexpected payload types)
        return True

    def record_failure(self, df_id: str) -> None:
        """Record a failure for correlated-failure-detection."""
        self.failure_detector.record_failure(self.tissue_id, df_id)

    def is_correlated_failure(self) -> bool:
        """Check tissue-wide correlated-failure-alarm via Z-score."""
        mean, sigma = self.failure_detector.baseline_stats(self.tissue_id)
        if sigma <= 0:
            return False
        return self.failure_detector.is_correlated_failure(
            self.tissue_id, mean=mean, sigma=sigma
        )


# CRUX-MK
