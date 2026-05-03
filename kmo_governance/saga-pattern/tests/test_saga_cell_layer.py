"""KMO Saga-Engine Cell-Layer Integration Tests [CRUX-MK].

Welle-9-alpha Phase-1.2.4: Saga-Engine erweitert um:
  - hotel_id Pflicht-Field auf SagaRun (mit Backwards-Compat-Default)
  - set_cell_quotas() / register_apoptosis_handler() / enable_wound_healing()
  - hotel_id Parameter in execute()

Existing 9 Saga-Tests muessen UNVERAENDERT passing bleiben (Hardstop).
Diese Datei: 5 neue Tests fuer Cell-Layer-Composition.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kmo_saga_engine import SagaEngine, SagaRun, SagaStatus  # noqa: E402


# ---------------- Pflicht-Tests ----------------


def test_saga_run_hotel_id_field_default_backwards_compat():
    """SagaRun has hotel_id field with default 'default-tenant' for backwards-compat."""
    run = SagaRun(run_id="r-1")
    assert run.hotel_id == "default-tenant"


def test_saga_execute_with_hotel_id_param(tmp_path):
    """execute() accepts hotel_id; persisted in state file."""
    engine = SagaEngine(tmp_path)

    def do_p1(inp, ctx):
        return {"ok": True}

    def undo_p1(inp, out, ctx):
        return None

    engine.register_phase("p1", "P1", do_p1, undo_p1)
    result = engine.execute("run-tenant", initial_input={}, hotel_id="apaleo-eu-001")
    assert result.status == SagaStatus.DONE
    state = engine.get_status("run-tenant")
    assert state["hotel_id"] == "apaleo-eu-001"


def test_saga_state_file_backwards_compat_missing_hotel_id(tmp_path):
    """Pre-Welle-9 state files (without hotel_id) load with default 'default-tenant'."""
    pre_welle_9_state = {
        "run_id": "old-run",
        "phases": [],
        "current_phase_idx": 0,
        "overall_status": "DONE",
        "initial_input": None,
        "error": None,
        "created_at": 1.0,
        "updated_at": 2.0,
        # NOTE: no hotel_id field (pre-Welle-9 format)
    }
    state_path = tmp_path / "old-run-state.json"
    state_path.write_text(json.dumps(pre_welle_9_state), encoding="utf-8")

    run = SagaRun.from_dict(json.loads(state_path.read_text()))
    assert run.run_id == "old-run"
    assert run.hotel_id == "default-tenant"  # backwards-compat default


def test_saga_cell_layer_composition_hooks_api(tmp_path):
    """set_cell_quotas / register_apoptosis_handler / enable_wound_healing API exists."""
    engine = SagaEngine(tmp_path)

    # All three hooks are callable + accept opaque args (Phase-1 stub).
    engine.set_cell_quotas({"llm_token_budget": 50_000})

    apoptosis_calls: list[tuple] = []

    def apoptosis_handler(cell_id: str, hotel_id: str, reason: str) -> None:
        apoptosis_calls.append((cell_id, hotel_id, reason))

    engine.register_apoptosis_handler(apoptosis_handler)

    healing_calls: list[tuple] = []

    def healing_factory(saga_run_id: str, hotel_id: str, reason: str):
        healing_calls.append((saga_run_id, hotel_id, reason))
        return object()  # opaque healing lifecycle

    engine.enable_wound_healing(healing_factory)

    # Internal state mounted (private attrs accessible for tests):
    assert engine._cell_quota == {"llm_token_budget": 50_000}
    assert engine._apoptosis_handler is apoptosis_handler
    assert engine._wound_healing_factory is healing_factory


def test_saga_run_hotel_id_persisted_in_state_file(tmp_path):
    """to_dict/from_dict round-trip preserves hotel_id."""
    run = SagaRun(run_id="r-1", hotel_id="mews-us-007")
    d = run.to_dict()
    assert d["hotel_id"] == "mews-us-007"
    restored = SagaRun.from_dict(d)
    assert restored.hotel_id == "mews-us-007"


# ---------------- Welle-9γ Saga-Hook Tests (Codex-Finding adressing) ----------------


def test_saga_phase_admit_check_blocks_phase(tmp_path):
    """phase_admit_check returning False raises + triggers compensation."""
    engine = SagaEngine(tmp_path)

    def do_p1(inp, ctx):
        return {"ok": True}

    def undo_p1(inp, out, ctx):
        return None

    engine.register_phase("p1", "P1", do_p1, undo_p1)

    block_calls: list[tuple] = []

    def admit_check(run_id: str, hotel_id: str, phase_id: str) -> bool:
        block_calls.append((run_id, hotel_id, phase_id))
        return False  # always block

    engine.register_phase_admit_check(admit_check)
    result = engine.execute("blocked-run", initial_input={}, hotel_id="hA")

    # Phase-blocked -> compensation runs
    assert result.status == SagaStatus.COMPENSATED
    assert len(block_calls) == 1
    assert block_calls[0] == ("blocked-run", "hA", "p1")


def test_saga_phase_admit_check_admits(tmp_path):
    """phase_admit_check returning True allows phases to proceed."""
    engine = SagaEngine(tmp_path)

    def do_p1(inp, ctx):
        return {"ok": True}

    def undo_p1(inp, out, ctx):
        return None

    engine.register_phase("p1", "P1", do_p1, undo_p1)
    engine.register_phase_admit_check(lambda r, h, p: True)
    result = engine.execute("admitted-run", initial_input={}, hotel_id="hA")
    assert result.status == SagaStatus.DONE


def test_saga_phase_admit_check_exception_fails_open(tmp_path):
    """If phase_admit_check raises, treated as ADMIT (fails-open for safety)."""
    engine = SagaEngine(tmp_path)
    engine.register_phase("p1", "P1", lambda i, c: {"ok": True}, lambda i, o, c: None)

    def buggy_check(r, h, p):
        raise RuntimeError("buggy hook")

    engine.register_phase_admit_check(buggy_check)
    result = engine.execute("buggy-hook-run", initial_input={}, hotel_id="hA")
    # Hook crashed -> fails open -> phase admitted -> DONE
    assert result.status == SagaStatus.DONE
