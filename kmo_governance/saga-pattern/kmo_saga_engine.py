"""KMO Saga-Engine: do/undo per phase with compensation chain + crash recovery.

Implements P-KMO-A2 (Saga-Pattern) per SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30 §P-KMO-A2.

Each phase has do/undo functions and an exit_criteria check. On phase failure,
undo runs in reverse order (compensation chain). State is persisted atomically
to JSON for crash recovery via resume().

CRUX-MK: K_0 protection via reverse-chain compensation (no partial commits).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import traceback
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


# ----- State enums -----

class PhaseStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    UNDOING = "UNDOING"
    UNDONE = "UNDONE"
    UNDO_FAILED = "UNDO_FAILED"
    SKIPPED = "SKIPPED"


class SagaStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    PARTIAL_COMPENSATION = "PARTIAL_COMPENSATION"


# ----- Dataclasses -----

@dataclass
class SagaPhase:
    phase_id: str
    name: str
    status: PhaseStatus = PhaseStatus.PENDING
    input: Any = None
    output: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SagaPhase":
        return cls(
            phase_id=d["phase_id"],
            name=d["name"],
            status=PhaseStatus(d.get("status", "PENDING")),
            input=d.get("input"),
            output=d.get("output"),
            error=d.get("error"),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
        )


@dataclass
class SagaRun:
    run_id: str
    phases: list[SagaPhase] = field(default_factory=list)
    current_phase_idx: int = 0
    overall_status: SagaStatus = SagaStatus.PENDING
    initial_input: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # Welle-9-alpha Phase-1.2.4: Multi-Tenancy Boundary (Cell-Layer integration).
    # Default "default-tenant" preserves backwards-compatibility with pre-Welle-9 state files.
    hotel_id: str = "default-tenant"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "phases": [p.to_dict() for p in self.phases],
            "current_phase_idx": self.current_phase_idx,
            "overall_status": self.overall_status.value,
            "initial_input": self.initial_input,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "hotel_id": self.hotel_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SagaRun":
        return cls(
            run_id=d["run_id"],
            phases=[SagaPhase.from_dict(p) for p in d.get("phases", [])],
            current_phase_idx=d.get("current_phase_idx", 0),
            overall_status=SagaStatus(d.get("overall_status", "PENDING")),
            initial_input=d.get("initial_input"),
            error=d.get("error"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            # Backwards-compat: pre-Welle-9 state-files had no hotel_id.
            hotel_id=d.get("hotel_id", "default-tenant"),
        )


@dataclass
class SagaResult:
    run_id: str
    status: SagaStatus
    final_output: Any = None
    error: Optional[str] = None
    phases_done: int = 0
    phases_undone: int = 0


# ----- Saga Engine -----

class SagaEngine:
    """Saga-Pattern Engine: do/undo per phase, compensation chain, crash recovery.

    Pre/Post-Conditions:
    - register_phase: phase_id is unique. do_func/undo_func accept (input, context).
    - execute: returns SagaResult with status DONE or COMPENSATED/PARTIAL_COMPENSATION.
    - resume: re-loads state from disk and continues at last RUNNING/PENDING phase.
    """

    def __init__(self, state_dir: Path | str):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._phases: list[tuple[str, str, Callable, Callable, Optional[Callable]]] = []
        # tuple: (phase_id, name, do_func, undo_func, exit_criteria_func)

        # Welle-9-alpha Phase-1.2.4: Cell-Layer composition hooks (all optional).
        # When unset, behavior is identical to pre-Welle-9 saga-engine.
        self._cell_quota: Optional[Any] = None  # CellQuota-like object (optional)
        self._apoptosis_handler: Optional[Callable[[str, str, str], None]] = None
        # signature: (cell_id=run_id, hotel_id, reason) -> None
        self._wound_healing_factory: Optional[
            Callable[[str, str, str], Any]
        ] = None
        # signature: (saga_run_id, hotel_id, failure_reason) -> WoundHealingLifecycle

        # Active healing-lifecycles per run_id (populated by enable_wound_healing factory at saga-failure).
        self._active_healings: dict[str, Any] = {}

        # Welle-9-gamma Codex-Finding #1: Phase-2 main-control-path hook.
        # Optional callback fired BEFORE each phase do_func. If returns False:
        # phase is blocked (raises BlockedByPhaseAdmitCheck) -> compensation-chain runs.
        # signature: (run_id, hotel_id, phase_id) -> bool
        self._phase_admit_check: Optional[Callable[[str, str, str], bool]] = None

        # Welle-9-delta Pre-Patch #5 (Codex-Finding "Saga membrane-checks on inputs/outputs").
        # Optional callback fired BEFORE do_func (kind="input") AND AFTER do_func
        # (kind="output"). Returns False -> phase fails, compensation runs.
        # Default behavior (no hook registered): no membrane-checks (backwards-compat).
        # signature: (hotel_id, phase_id, kind, payload) -> bool
        #   kind in {"input", "output"}
        self._phase_membrane_check: Optional[
            Callable[[str, str, str, Any], bool]
        ] = None

    def register_phase(
        self,
        phase_id: str,
        name: str,
        do_func: Callable[[Any, dict], Any],
        undo_func: Callable[[Any, Any, dict], None],
        exit_criteria_func: Optional[Callable[[Any], bool]] = None,
    ) -> None:
        """Register a phase. Order of registration = execution order.

        do_func(input, context) -> output
        undo_func(input, output, context) -> None  (compensation, must be idempotent)
        exit_criteria_func(output) -> bool  (True = pass, False = block, None = no check)
        """
        if any(p[0] == phase_id for p in self._phases):
            raise ValueError(f"Phase {phase_id!r} already registered")
        self._phases.append((phase_id, name, do_func, undo_func, exit_criteria_func))

    def _state_path(self, run_id: str) -> Path:
        return self.state_dir / f"{run_id}-state.json"

    def _atomic_write_state(self, run: SagaRun) -> None:
        """Atomic state write via tempfile + os.replace."""
        run.updated_at = time.time()
        target = self._state_path(run.run_id)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{run.run_id}-", suffix=".json.tmp", dir=str(self.state_dir)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(run.to_dict(), f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _load_state(self, run_id: str) -> Optional[SagaRun]:
        path = self._state_path(run_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return SagaRun.from_dict(data)

    def get_status(self, run_id: str) -> Optional[dict]:
        run = self._load_state(run_id)
        if run is None:
            return None
        return run.to_dict()

    def _build_initial_run(
        self, run_id: str, initial_input: Any, hotel_id: str = "default-tenant"
    ) -> SagaRun:
        phases = [
            SagaPhase(phase_id=p[0], name=p[1], status=PhaseStatus.PENDING)
            for p in self._phases
        ]
        return SagaRun(
            run_id=run_id,
            phases=phases,
            current_phase_idx=0,
            overall_status=SagaStatus.PENDING,
            initial_input=initial_input,
            hotel_id=hotel_id,
        )

    def execute(
        self,
        saga_run_id: str,
        initial_input: Any,
        hotel_id: str = "default-tenant",
    ) -> SagaResult:
        """Execute saga from scratch. Persists state after every transition.

        Welle-9-alpha Phase-1.2.4: optional `hotel_id` for Multi-Tenancy.
        Default "default-tenant" preserves pre-Welle-9 backwards-compat.
        """
        if not self._phases:
            raise RuntimeError("No phases registered")
        run = self._load_state(saga_run_id)
        if run is None:
            run = self._build_initial_run(saga_run_id, initial_input, hotel_id=hotel_id)
            self._atomic_write_state(run)
        return self._run_loop(run)

    # ---------- Welle-9-alpha Phase-1.2.4: Cell-Layer composition API ----------

    def set_cell_quotas(self, quota: Any) -> None:
        """Register a CellQuota-like object for all subsequent saga-runs.

        The quota is opaque to the engine (duck-typed); it is passed to the
        apoptosis_handler when quota-exhaustion occurs. Phase-1 stub.
        """
        self._cell_quota = quota

    def register_apoptosis_handler(
        self, handler: Callable[[str, str, str], None]
    ) -> None:
        """Register apoptose-callback for cell-quota-exhaustion.

        signature: (cell_id, hotel_id, reason) -> None
        Called when a saga-phase raises QuotaExhaustedError or related signal.
        """
        self._apoptosis_handler = handler

    def enable_wound_healing(
        self, factory: Callable[[str, str, str], Any]
    ) -> None:
        """Replace direct compensation with Wound-Healing-Lifecycle.

        signature: (saga_run_id, hotel_id, failure_reason) -> WoundHealingLifecycle

        When set: on saga-FAILED, the engine creates a WoundHealingLifecycle
        instance via the factory and stores it in self._active_healings[run_id].
        Compensation still runs as cleanup-semantics; the caller drives the
        lifecycle's transition phases.
        """
        self._wound_healing_factory = factory

    def get_active_healing(self, saga_run_id: str) -> Optional[Any]:
        """Return the WoundHealingLifecycle for a failed run (if any was created)."""
        return self._active_healings.get(saga_run_id)

    def register_phase_admit_check(
        self, check: Callable[[str, str, str], bool]
    ) -> None:
        """Welle-9γ Codex-Finding #1: hook to gate each phase via Phase-2 logic.

        signature: (run_id, hotel_id, phase_id) -> bool
        - True: phase proceeds normally
        - False: phase blocked, raises RuntimeError, triggers compensation
        """
        self._phase_admit_check = check

    def register_phase_membrane_check(
        self, check: Callable[[str, str, str, Any], bool]
    ) -> None:
        """Welle-9-delta Pre-Patch #5: membrane-check on phase inputs/outputs.

        Validates payloads against the saga's hotel_id (multi-tenancy enforcement).
        Fired BEFORE do_func (kind="input") and AFTER do_func (kind="output").

        signature: (hotel_id, phase_id, kind, payload) -> bool
          kind in {"input", "output"}
        - True: payload is membrane-conform, phase proceeds
        - False: payload violates membrane (e.g. wrong hotel_id tag), phase fails
        - Hook errors are treated as ADMIT (fail-open) for safety, like phase_admit_check.
        """
        self._phase_membrane_check = check

    def resume(self, saga_run_id: str) -> SagaResult:
        """Resume saga from persisted state. Crash-recovery entrypoint.

        If a phase is RUNNING (crash mid-phase), it's marked FAILED and compensation starts.
        """
        run = self._load_state(saga_run_id)
        if run is None:
            raise FileNotFoundError(f"No state for run {saga_run_id!r}")
        # Crash mid-phase detection: any RUNNING -> mark FAILED, trigger compensation
        for ph in run.phases:
            if ph.status == PhaseStatus.RUNNING:
                ph.status = PhaseStatus.FAILED
                ph.error = (ph.error or "") + " [resumed from crash, was RUNNING]"
                ph.finished_at = time.time()
                run.overall_status = SagaStatus.FAILED
                run.error = f"Crash recovery: phase {ph.phase_id} was RUNNING"
                self._atomic_write_state(run)
                break
        return self._run_loop(run)

    def _run_loop(self, run: SagaRun) -> SagaResult:
        """Main execution loop: forward through phases or run compensation chain."""
        if run.overall_status in (SagaStatus.DONE, SagaStatus.COMPENSATED, SagaStatus.PARTIAL_COMPENSATION):
            return self._build_result(run)

        # If FAILED already, only run compensation
        if run.overall_status == SagaStatus.FAILED:
            return self._compensate(run)

        # Forward execution
        run.overall_status = SagaStatus.RUNNING
        self._atomic_write_state(run)

        prev_output: Any = run.initial_input
        # Pick up last DONE phase output for chain
        for ph in run.phases:
            if ph.status == PhaseStatus.DONE:
                prev_output = ph.output
            else:
                break

        for idx in range(run.current_phase_idx, len(run.phases)):
            phase_def = self._phases[idx]
            phase_id, name, do_func, undo_func, exit_criteria_func = phase_def
            ph = run.phases[idx]

            if ph.status == PhaseStatus.DONE:
                prev_output = ph.output
                continue

            run.current_phase_idx = idx
            ph.status = PhaseStatus.RUNNING
            ph.input = prev_output
            ph.started_at = time.time()
            self._atomic_write_state(run)

            context: dict = {"run_id": run.run_id, "phase_idx": idx}
            try:
                # Welle-9γ Codex-Finding #1: phase_admit_check hook (Phase-2 main-path).
                if self._phase_admit_check is not None:
                    try:
                        admitted = self._phase_admit_check(
                            run.run_id, run.hotel_id, phase_id
                        )
                    except Exception:
                        # Hook errors must not crash saga; treat as ADMIT for safety.
                        admitted = True
                    if not admitted:
                        raise RuntimeError(
                            f"Phase {phase_id!r} blocked by phase_admit_check"
                        )
                # Welle-9-delta Pre-Patch #5: membrane-check on input.
                if self._phase_membrane_check is not None:
                    try:
                        input_ok = self._phase_membrane_check(
                            run.hotel_id, phase_id, "input", prev_output
                        )
                    except Exception:
                        input_ok = True  # fail-open
                    if not input_ok:
                        raise RuntimeError(
                            f"Phase {phase_id!r} input violates membrane "
                            f"(hotel_id={run.hotel_id!r})"
                        )
                output = do_func(prev_output, context)
                # Welle-9-delta Pre-Patch #5: membrane-check on output.
                if self._phase_membrane_check is not None:
                    try:
                        output_ok = self._phase_membrane_check(
                            run.hotel_id, phase_id, "output", output
                        )
                    except Exception:
                        output_ok = True  # fail-open
                    if not output_ok:
                        raise RuntimeError(
                            f"Phase {phase_id!r} output violates membrane "
                            f"(hotel_id={run.hotel_id!r})"
                        )
                # Exit criteria check
                if exit_criteria_func is not None:
                    if not exit_criteria_func(output):
                        raise RuntimeError(
                            f"Exit-criteria blocked phase {phase_id}"
                        )
                ph.output = output
                ph.status = PhaseStatus.DONE
                ph.finished_at = time.time()
                self._atomic_write_state(run)
                prev_output = output
            except Exception as e:
                ph.status = PhaseStatus.FAILED
                ph.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                ph.finished_at = time.time()
                run.overall_status = SagaStatus.FAILED
                run.error = f"Phase {phase_id} failed: {e}"
                self._atomic_write_state(run)
                # Welle-9-alpha Phase-1.2.4: route Cell-Layer hooks BEFORE compensation.
                # Apoptosis handler signals quota/state-corruption to ApoptosisEngine.
                if self._apoptosis_handler is not None:
                    try:
                        self._apoptosis_handler(
                            run.run_id, run.hotel_id, f"phase-{phase_id}-failed"
                        )
                    except Exception:
                        # Apoptose-callback failures must not mask phase-failure.
                        pass
                # Wound-healing factory: replace direct compensation with lifecycle.
                # The lifecycle is stored for caller retrieval; compensation
                # still runs as the cleanup-phase semantics (caller owns lifecycle walk).
                if self._wound_healing_factory is not None:
                    try:
                        self._active_healings[run.run_id] = (
                            self._wound_healing_factory(
                                run.run_id, run.hotel_id, str(e)
                            )
                        )
                    except Exception:
                        pass
                return self._compensate(run)

        run.overall_status = SagaStatus.DONE
        self._atomic_write_state(run)
        return self._build_result(run)

    def _compensate(self, run: SagaRun) -> SagaResult:
        """Reverse-chain undo of all DONE phases."""
        run.overall_status = SagaStatus.COMPENSATING
        self._atomic_write_state(run)

        any_undo_failed = False
        # Iterate in reverse: undo last DONE first
        for idx in range(len(run.phases) - 1, -1, -1):
            ph = run.phases[idx]
            if ph.status != PhaseStatus.DONE:
                continue
            phase_def = self._phases[idx]
            _, _, _, undo_func, _ = phase_def
            ph.status = PhaseStatus.UNDOING
            self._atomic_write_state(run)
            try:
                undo_func(ph.input, ph.output, {"run_id": run.run_id, "phase_idx": idx})
                ph.status = PhaseStatus.UNDONE
            except Exception as e:
                ph.status = PhaseStatus.UNDO_FAILED
                ph.error = (ph.error or "") + f" | undo: {type(e).__name__}: {e}"
                any_undo_failed = True
            self._atomic_write_state(run)

        run.overall_status = (
            SagaStatus.PARTIAL_COMPENSATION if any_undo_failed else SagaStatus.COMPENSATED
        )
        self._atomic_write_state(run)
        return self._build_result(run)

    def _build_result(self, run: SagaRun) -> SagaResult:
        phases_done = sum(1 for p in run.phases if p.status == PhaseStatus.DONE)
        phases_undone = sum(
            1 for p in run.phases if p.status in (PhaseStatus.UNDONE, PhaseStatus.UNDO_FAILED)
        )
        final_output: Any = None
        if run.overall_status == SagaStatus.DONE and run.phases:
            final_output = run.phases[-1].output
        return SagaResult(
            run_id=run.run_id,
            status=run.overall_status,
            final_output=final_output,
            error=run.error,
            phases_done=phases_done,
            phases_undone=phases_undone,
        )
