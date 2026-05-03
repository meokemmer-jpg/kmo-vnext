"""KMO 7-Phase Pipeline Registry: do/undo stubs for SagaEngine.

Phases per SPEC-KMO-DARK-FACTORY-BETRIEBSGELAENDE-2026-04-30:
1. Plan -> 2. Spec -> 3. Wargame -> 4. Build -> 5. Test -> 6. DEV-Demo -> 7. Approval/Gerdi

Each phase is a stub: do_func produces a payload, undo_func compensates.
Real implementations replace these stubs.
"""

from __future__ import annotations

from typing import Any

from kmo_saga_engine import SagaEngine


# ----- Phase do/undo stubs (deterministic, idempotent) -----

def do_plan(inp: Any, ctx: dict) -> dict:
    return {"phase": "plan", "input": inp, "plan_id": f"PLAN-{ctx['run_id']}"}


def undo_plan(inp: Any, out: Any, ctx: dict) -> None:
    # Compensation: drop plan artifact (idempotent: no-op if already gone)
    return None


def do_spec(inp: Any, ctx: dict) -> dict:
    return {"phase": "spec", "from_plan": inp, "spec_id": f"SPEC-{ctx['run_id']}"}


def undo_spec(inp: Any, out: Any, ctx: dict) -> None:
    return None


def do_wargame(inp: Any, ctx: dict) -> dict:
    return {"phase": "wargame", "from_spec": inp, "verdict": "CONDITIONAL"}


def undo_wargame(inp: Any, out: Any, ctx: dict) -> None:
    return None


def do_build(inp: Any, ctx: dict) -> dict:
    return {"phase": "build", "from_wargame": inp, "build_artifact": f"BUILD-{ctx['run_id']}"}


def undo_build(inp: Any, out: Any, ctx: dict) -> None:
    # Compensation: would delete build artifact in real implementation
    return None


def do_test(inp: Any, ctx: dict) -> dict:
    return {"phase": "test", "from_build": inp, "tests_passed": True}


def undo_test(inp: Any, out: Any, ctx: dict) -> None:
    return None


def do_dev_demo(inp: Any, ctx: dict) -> dict:
    return {"phase": "dev_demo", "from_test": inp, "demo_url": f"http://localhost/demo/{ctx['run_id']}"}


def undo_dev_demo(inp: Any, out: Any, ctx: dict) -> None:
    return None


def do_approval(inp: Any, ctx: dict) -> dict:
    return {"phase": "approval", "from_demo": inp, "approver": "gerdi", "approved": True}


def undo_approval(inp: Any, out: Any, ctx: dict) -> None:
    return None


# ----- Exit criteria (block conditions) -----

def exit_criteria_wargame(out: dict) -> bool:
    """Wargame must produce a verdict (CONDITIONAL or stronger)."""
    return out.get("verdict") in {"CONDITIONAL", "SIM-HARDENED", "2OF3-HARDENED", "HARDENED"}


def exit_criteria_test(out: dict) -> bool:
    return bool(out.get("tests_passed"))


def exit_criteria_approval(out: dict) -> bool:
    return bool(out.get("approved"))


# ----- Registration helper -----

def register_kmo_phases(engine: SagaEngine) -> None:
    """Register the canonical KMO 7-phase pipeline on a SagaEngine."""
    engine.register_phase("plan", "Plan", do_plan, undo_plan)
    engine.register_phase("spec", "Spec", do_spec, undo_spec)
    engine.register_phase("wargame", "Wargame", do_wargame, undo_wargame, exit_criteria_wargame)
    engine.register_phase("build", "Build", do_build, undo_build)
    engine.register_phase("test", "Test", do_test, undo_test, exit_criteria_test)
    engine.register_phase("dev_demo", "DEV-Demo", do_dev_demo, undo_dev_demo)
    engine.register_phase("approval", "Approval/Gerdi", do_approval, undo_approval, exit_criteria_approval)
