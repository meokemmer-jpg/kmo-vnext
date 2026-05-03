"""Pytest suite for KMO SagaEngine.

Covers:
- Happy-Path: all 7 phases DONE
- Phase-Fail-Undo-Chain: phase 4 fails, phases 1-3 undone in reverse
- Crash-Recovery: state with RUNNING phase resumed -> compensation
- Exit-criteria-block: wargame returns invalid verdict, saga blocks + compensates
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow tests to import sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kmo_saga_engine import (  # noqa: E402
    SagaEngine,
    SagaStatus,
    PhaseStatus,
)
from phase_registry import register_kmo_phases  # noqa: E402


# ----- Helpers -----

class CallTracker:
    def __init__(self):
        self.do_calls: list[str] = []
        self.undo_calls: list[str] = []

    def make_do(self, phase_id: str, fail: bool = False):
        def _do(inp, ctx):
            self.do_calls.append(phase_id)
            if fail:
                raise RuntimeError(f"intentional fail in {phase_id}")
            return {"phase": phase_id, "input": inp}
        return _do

    def make_undo(self, phase_id: str, fail: bool = False):
        def _undo(inp, out, ctx):
            self.undo_calls.append(phase_id)
            if fail:
                raise RuntimeError(f"undo fail in {phase_id}")
        return _undo


# ----- Tests -----

def test_happy_path_all_phases_done(tmp_path: Path):
    engine = SagaEngine(tmp_path)
    register_kmo_phases(engine)
    result = engine.execute("run-happy", initial_input={"hello": "world"})
    assert result.status == SagaStatus.DONE
    assert result.phases_done == 7
    assert result.phases_undone == 0
    assert result.final_output is not None
    assert result.final_output.get("approved") is True

    # State persisted
    state = engine.get_status("run-happy")
    assert state["overall_status"] == "DONE"
    assert all(p["status"] == "DONE" for p in state["phases"])


def test_phase_fail_triggers_reverse_undo_chain(tmp_path: Path):
    engine = SagaEngine(tmp_path)
    tracker = CallTracker()
    # 4 phases. Phase-3 fails. Expect undo of phase-2 then phase-1 (reverse).
    engine.register_phase("p1", "P1", tracker.make_do("p1"), tracker.make_undo("p1"))
    engine.register_phase("p2", "P2", tracker.make_do("p2"), tracker.make_undo("p2"))
    engine.register_phase("p3", "P3", tracker.make_do("p3", fail=True), tracker.make_undo("p3"))
    engine.register_phase("p4", "P4", tracker.make_do("p4"), tracker.make_undo("p4"))

    result = engine.execute("run-fail", initial_input=None)
    assert result.status == SagaStatus.COMPENSATED
    assert tracker.do_calls == ["p1", "p2", "p3"]
    # Reverse-undo: p2 then p1 (p3 never DONE so no undo)
    assert tracker.undo_calls == ["p2", "p1"]
    # After compensation: DONE phases transitioned to UNDONE, so phases_done counts post-state
    assert result.phases_done == 0
    assert result.phases_undone == 2

    state = engine.get_status("run-fail")
    assert state["phases"][0]["status"] == "UNDONE"
    assert state["phases"][1]["status"] == "UNDONE"
    assert state["phases"][2]["status"] == "FAILED"
    assert state["phases"][3]["status"] == "PENDING"


def test_undo_failure_yields_partial_compensation(tmp_path: Path):
    engine = SagaEngine(tmp_path)
    tracker = CallTracker()
    engine.register_phase("p1", "P1", tracker.make_do("p1"), tracker.make_undo("p1", fail=True))
    engine.register_phase("p2", "P2", tracker.make_do("p2"), tracker.make_undo("p2"))
    engine.register_phase("p3", "P3", tracker.make_do("p3", fail=True), tracker.make_undo("p3"))

    result = engine.execute("run-partial", initial_input=None)
    assert result.status == SagaStatus.PARTIAL_COMPENSATION
    assert tracker.undo_calls == ["p2", "p1"]
    state = engine.get_status("run-partial")
    assert state["phases"][0]["status"] == "UNDO_FAILED"
    assert state["phases"][1]["status"] == "UNDONE"


def test_crash_recovery_via_resume(tmp_path: Path):
    """Simulate crash: write a state with phase-2 RUNNING, then resume."""
    engine = SagaEngine(tmp_path)
    tracker = CallTracker()
    engine.register_phase("p1", "P1", tracker.make_do("p1"), tracker.make_undo("p1"))
    engine.register_phase("p2", "P2", tracker.make_do("p2"), tracker.make_undo("p2"))
    engine.register_phase("p3", "P3", tracker.make_do("p3"), tracker.make_undo("p3"))

    # Manually write a "crashed" state: p1 DONE, p2 RUNNING (mid-crash)
    state_path = tmp_path / "run-crash-state.json"
    crashed_state = {
        "run_id": "run-crash",
        "phases": [
            {
                "phase_id": "p1",
                "name": "P1",
                "status": "DONE",
                "input": None,
                "output": {"phase": "p1", "input": None},
                "error": None,
                "started_at": 1.0,
                "finished_at": 2.0,
            },
            {
                "phase_id": "p2",
                "name": "P2",
                "status": "RUNNING",
                "input": {"phase": "p1", "input": None},
                "output": None,
                "error": None,
                "started_at": 3.0,
                "finished_at": None,
            },
            {
                "phase_id": "p3",
                "name": "P3",
                "status": "PENDING",
                "input": None,
                "output": None,
                "error": None,
                "started_at": None,
                "finished_at": None,
            },
        ],
        "current_phase_idx": 1,
        "overall_status": "RUNNING",
        "initial_input": None,
        "error": None,
        "created_at": 0.0,
        "updated_at": 3.0,
    }
    state_path.write_text(json.dumps(crashed_state), encoding="utf-8")

    result = engine.resume("run-crash")
    # RUNNING -> FAILED -> compensation runs. p1 was DONE, gets undone.
    assert result.status == SagaStatus.COMPENSATED
    assert tracker.undo_calls == ["p1"]
    assert tracker.do_calls == []  # resume must not re-run phases on crash

    state = engine.get_status("run-crash")
    assert state["phases"][0]["status"] == "UNDONE"
    assert state["phases"][1]["status"] == "FAILED"
    assert "crash" in (state["phases"][1]["error"] or "").lower()


def test_exit_criteria_blocks_progression(tmp_path: Path):
    """Wargame returns invalid verdict -> exit_criteria fails -> compensation."""
    engine = SagaEngine(tmp_path)
    tracker = CallTracker()

    def bad_wargame(inp, ctx):
        tracker.do_calls.append("wargame")
        return {"verdict": "REJECTED"}  # not in allowed set

    def wargame_undo(inp, out, ctx):
        tracker.undo_calls.append("wargame")

    engine.register_phase("plan", "Plan", tracker.make_do("plan"), tracker.make_undo("plan"))
    engine.register_phase("spec", "Spec", tracker.make_do("spec"), tracker.make_undo("spec"))
    engine.register_phase(
        "wargame",
        "Wargame",
        bad_wargame,
        wargame_undo,
        exit_criteria_func=lambda out: out.get("verdict") in {"CONDITIONAL", "HARDENED"},
    )
    engine.register_phase("build", "Build", tracker.make_do("build"), tracker.make_undo("build"))

    result = engine.execute("run-block", initial_input=None)
    assert result.status == SagaStatus.COMPENSATED
    assert "wargame" in tracker.do_calls
    assert "build" not in tracker.do_calls  # never ran
    # Reverse-undo: spec then plan
    assert tracker.undo_calls == ["spec", "plan"]


def test_register_phase_duplicate_raises(tmp_path: Path):
    engine = SagaEngine(tmp_path)
    engine.register_phase("p1", "P1", lambda i, c: None, lambda i, o, c: None)
    with pytest.raises(ValueError):
        engine.register_phase("p1", "duplicate", lambda i, c: None, lambda i, o, c: None)


def test_resume_unknown_run_raises(tmp_path: Path):
    engine = SagaEngine(tmp_path)
    with pytest.raises(FileNotFoundError):
        engine.resume("nonexistent")


def test_idempotent_resume_after_done(tmp_path: Path):
    """Resuming a DONE saga is safe and returns same result."""
    engine = SagaEngine(tmp_path)
    register_kmo_phases(engine)
    r1 = engine.execute("run-done", initial_input=None)
    assert r1.status == SagaStatus.DONE
    r2 = engine.resume("run-done")
    assert r2.status == SagaStatus.DONE
    assert r2.phases_done == 7


def test_state_atomic_write_no_partial_files(tmp_path: Path):
    engine = SagaEngine(tmp_path)
    register_kmo_phases(engine)
    engine.execute("run-atomic", initial_input=None)
    # Only one state file plus no leftover .tmp files
    files = list(tmp_path.iterdir())
    tmp_files = [f for f in files if f.suffix == ".tmp" or ".tmp" in f.name]
    assert tmp_files == [], f"Leftover tmp files: {tmp_files}"
