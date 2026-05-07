"""Pytest-Suite for KMO Durable-Execution-State-Machine (P-KMO-A7).

Tests:
- happy-path start + transitions
- crash-recovery via recover() (process-kill simulated by new instance)
- event-sourcing replay (since-snapshot)
- snapshot + restore
- concurrent-transition-safety (filesystem-mutex)
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

# Allow tests to import sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kmo_durable_state_machine import (  # noqa: E402
    DurableStateMachine,
    WorkflowRun,
    WorkflowStatus,
    WorkflowNotFoundError,
    ConcurrentTransitionError,
)
from event_types import (  # noqa: E402
    EventType,
    make_routing_decision,
    make_df_status_change,
    make_stop_flag_transition,
    make_approval_state,
)


# ----- Happy Path -----

def test_start_workflow_creates_files(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    run = sm.start_workflow("wf-happy", initial_state={"phase_count": 7})
    assert run.workflow_id == "wf-happy"
    assert run.status == WorkflowStatus.RUNNING
    assert run.current_phase == "init"
    assert run.state_data["phase_count"] == 7
    assert (tmp_path / "wf-happy" / "events.jsonl").exists()


def test_start_workflow_rejects_duplicate(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    sm.start_workflow("wf-dup", initial_state={})
    with pytest.raises(ValueError):
        sm.start_workflow("wf-dup", initial_state={})


def test_transition_appends_event_and_updates_state(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    sm.start_workflow("wf-t", initial_state={"a": 1})
    run = sm.transition_phase(
        "wf-t",
        from_phase="init",
        to_phase="plan",
        state_patch={"plan_done": True},
    )
    assert run.current_phase == "plan"
    assert run.state_data["plan_done"] is True
    assert run.state_data["a"] == 1  # initial preserved
    assert run.sequence == 2


def test_seven_phase_workflow_happy_path(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    sm.start_workflow("kmo-run-001", initial_state={"target": "df-86"})
    phases = ["plan", "spec", "wargame", "build", "test", "demo", "approval"]
    prev = "init"
    for ph in phases:
        run = sm.transition_phase("kmo-run-001", prev, ph, state_patch={f"{ph}_done": True})
        prev = ph
    final = sm.recover("kmo-run-001")
    assert final.current_phase == "approval"
    for ph in phases:
        assert final.state_data[f"{ph}_done"] is True
    # 1 start + 7 transitions = 8 events
    history = sm.get_history("kmo-run-001")
    assert len(history) == 8


# ----- Recover / Crash Recovery -----

def test_recover_loads_state_after_simulated_crash(tmp_path: Path):
    """Simulate a crash by creating a NEW DurableStateMachine instance pointed
    at the same state_root. The fresh instance must reconstruct the workflow
    purely from disk artifacts (events.jsonl)."""
    sm1 = DurableStateMachine(state_root=tmp_path)
    sm1.start_workflow("wf-crash", initial_state={"x": 0})
    sm1.transition_phase("wf-crash", "init", "plan", {"x": 1})
    sm1.transition_phase("wf-crash", "plan", "build", {"x": 2})
    # "Crash": original instance is forgotten. New instance loads from disk.
    del sm1
    sm2 = DurableStateMachine(state_root=tmp_path)
    recovered = sm2.recover("wf-crash")
    assert recovered.current_phase == "build"
    assert recovered.state_data["x"] == 2
    assert recovered.sequence == 3


def test_recover_unknown_workflow_raises(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    with pytest.raises(WorkflowNotFoundError):
        sm.recover("does-not-exist")


def test_transition_unknown_workflow_raises(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    with pytest.raises(WorkflowNotFoundError):
        sm.transition_phase("nope", "a", "b")


def test_recover_continues_phase_after_restart(tmp_path: Path):
    """Crash mid-pipeline -> restart -> continue from current_phase."""
    sm = DurableStateMachine(state_root=tmp_path)
    sm.start_workflow("wf-resume", initial_state={"step": 0})
    sm.transition_phase("wf-resume", "init", "plan", {"step": 1})
    sm.transition_phase("wf-resume", "plan", "spec", {"step": 2})
    # New instance picks up
    sm2 = DurableStateMachine(state_root=tmp_path)
    run = sm2.recover("wf-resume")
    assert run.current_phase == "spec"
    # Continue from there
    sm2.transition_phase("wf-resume", "spec", "wargame", {"step": 3})
    final = sm2.recover("wf-resume")
    assert final.current_phase == "wargame"
    assert final.state_data["step"] == 3


# ----- Event-Sourcing Replay -----

def test_event_sourcing_replay_full_history(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    sm.start_workflow("wf-replay", initial_state={"counter": 0})
    for i in range(1, 6):
        sm.transition_phase(
            "wf-replay",
            from_phase=f"phase-{i-1}",
            to_phase=f"phase-{i}",
            state_patch={"counter": i},
        )
    history = sm.get_history("wf-replay")
    # 1 start + 5 transitions = 6 events
    assert len(history) == 6
    assert history[0].event_type == EventType.WORKFLOW_STARTED
    assert all(history[i].sequence == i + 1 for i in range(len(history)))
    # Replay-derived final state matches current
    run = sm.recover("wf-replay")
    assert run.state_data["counter"] == 5
    assert run.current_phase == "phase-5"


def test_replay_with_routing_and_approval_events(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    sm.start_workflow("wf-rich", initial_state={})
    # Mix of event-types
    sm.transition(
        "wf-rich",
        EventType.ROUTING_DECISION,
        payload={
            "phase": "build",
            "chosen_target": "df-86",
            "candidates": ["df-86", "df-87"],
            "rationale": "lowest-load",
        },
    )
    sm.transition(
        "wf-rich",
        EventType.DF_STATUS_CHANGE,
        payload={"df_id": "df-86", "from_status": "IDLE", "to_status": "RUNNING"},
    )
    sm.transition(
        "wf-rich",
        EventType.APPROVAL_STATE,
        payload={"gate_id": "gerdi-gate", "decision": "APPROVED", "approver": "gerdi"},
    )
    history = sm.get_history("wf-rich")
    assert len(history) == 4
    assert history[1].event_type == EventType.ROUTING_DECISION
    assert history[2].event_type == EventType.DF_STATUS_CHANGE
    assert history[3].event_type == EventType.APPROVAL_STATE
    # All recorded in audit history of state
    run = sm.recover("wf-rich")
    seen = run.state_data.get("__events_seen", [])
    assert len(seen) == 3


# ----- Snapshots -----

def test_snapshot_creates_file(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path, snapshot_every_n_events=999)
    sm.start_workflow("wf-snap", initial_state={"v": 1})
    sm.transition_phase("wf-snap", "init", "plan", {"v": 2})
    snap = sm.snapshot("wf-snap")
    assert snap.sequence == 2
    snap_files = list((tmp_path / "wf-snap" / "snapshots").glob("*.json"))
    assert len(snap_files) == 1


def test_recover_uses_snapshot_then_replays_newer_events(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path, snapshot_every_n_events=999)
    sm.start_workflow("wf-snap-replay", initial_state={"k": 0})
    sm.transition_phase("wf-snap-replay", "init", "plan", {"k": 1})
    sm.snapshot("wf-snap-replay")  # snapshot at seq=2
    sm.transition_phase("wf-snap-replay", "plan", "build", {"k": 2})
    sm.transition_phase("wf-snap-replay", "build", "test", {"k": 3})
    # New instance must combine snapshot + 2 newer events
    sm2 = DurableStateMachine(state_root=tmp_path)
    run = sm2.recover("wf-snap-replay")
    assert run.current_phase == "test"
    assert run.state_data["k"] == 3
    assert run.sequence == 4


def test_auto_snapshot_every_n_events(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path, snapshot_every_n_events=3)
    sm.start_workflow("wf-auto", initial_state={})
    # seq=1 (start), then 5 transitions -> auto-snapshots at seq=3 and seq=6
    for i in range(5):
        sm.transition_phase("wf-auto", f"p{i}", f"p{i+1}", {"i": i})
    snaps = sorted((tmp_path / "wf-auto" / "snapshots").glob("*.json"))
    assert len(snaps) >= 2


# ----- Concurrent-Transition-Safety -----

def test_concurrent_transitions_serialize(tmp_path: Path):
    """Two threads racing to transition: both succeed, sequence-numbers are
    contiguous (no gaps, no duplicates), one "wins" each commit slot."""
    sm = DurableStateMachine(state_root=tmp_path, lock_stale_after_s=10.0)
    sm.start_workflow("wf-race", initial_state={"hits": 0})
    n = 20
    barrier = threading.Barrier(n)
    errors: list[Exception] = []

    def worker(idx: int) -> None:
        barrier.wait()
        for _ in range(3):  # retry on contention
            try:
                sm.transition_phase("wf-race", "x", f"step-{idx}", {f"k{idx}": idx})
                return
            except ConcurrentTransitionError:
                time.sleep(0.005)
            except Exception as e:  # pragma: no cover
                errors.append(e)
                return

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert errors == []
    history = sm.get_history("wf-race")
    seqs = [e.sequence for e in history]
    # No duplicates, no gaps
    assert len(seqs) == len(set(seqs))
    assert seqs == sorted(seqs)
    assert seqs[0] == 1
    assert seqs[-1] == seqs[0] + len(seqs) - 1


def test_stale_lock_can_be_claimed(tmp_path: Path):
    """If a previous process crashed leaving state.lock behind, a new caller
    can claim it once lock_stale_after_s has elapsed."""
    sm = DurableStateMachine(state_root=tmp_path, lock_stale_after_s=0.1)
    sm.start_workflow("wf-stale", initial_state={})
    # Manually create a fake stale lock
    lock_dir = tmp_path / "wf-stale" / "state.lock"
    lock_dir.mkdir()
    (lock_dir / "pid").write_text("99999")
    # Force mtime into the past
    import os as _os
    old = time.time() - 60
    _os.utime(lock_dir, (old, old))
    # Now this transition should succeed despite stale lock
    run = sm.transition_phase("wf-stale", "init", "plan", {"recovered": True})
    assert run.current_phase == "plan"
    assert run.state_data["recovered"] is True


# ----- Helper-Constructor Smoke Tests -----

def test_event_helper_constructors(tmp_path: Path):
    rd = make_routing_decision(
        workflow_id="wf", sequence=5, phase="build",
        chosen_target="df-86", candidates=["df-86", "df-87"], rationale="x",
    )
    assert rd.event_type == EventType.ROUTING_DECISION
    assert rd.payload["chosen_target"] == "df-86"

    sc = make_df_status_change(
        workflow_id="wf", sequence=6, df_id="df-86",
        from_status="IDLE", to_status="RUNNING",
    )
    assert sc.event_type == EventType.DF_STATUS_CHANGE

    sf = make_stop_flag_transition(
        workflow_id="wf", sequence=7, flag_id="STOP-DF-86", raised=True,
    )
    assert sf.payload["raised"] is True

    ap = make_approval_state(
        workflow_id="wf", sequence=8, gate_id="gerdi-gate",
        decision="APPROVED", approver="gerdi",
    )
    assert ap.payload["decision"] == "APPROVED"


def test_list_workflows(tmp_path: Path):
    sm = DurableStateMachine(state_root=tmp_path)
    assert sm.list_workflows() == []
    sm.start_workflow("a", initial_state={})
    sm.start_workflow("b", initial_state={})
    assert sm.list_workflows() == ["a", "b"]


def test_events_jsonl_format_is_valid(tmp_path: Path):
    """Each line in events.jsonl must be valid JSON with required keys."""
    sm = DurableStateMachine(state_root=tmp_path)
    sm.start_workflow("wf-fmt", initial_state={})
    sm.transition_phase("wf-fmt", "init", "plan", {"x": 1})
    path = tmp_path / "wf-fmt" / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        d = json.loads(line)
        assert "event_id" in d
        assert "workflow_id" in d
        assert "event_type" in d
        assert "sequence" in d
