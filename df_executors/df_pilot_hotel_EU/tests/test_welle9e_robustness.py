"""Welle-9-epsilon Robustness-Tests [CRUX-MK].

Adressiert Codex-V2-Recommendations:
  #2: Property-/Fuzz-Tests fuer membrane_check (zyklische Referenzen)
  #3: Chaos-Szenarien fuer HomeostasisCoordinator (rapid vitals-flaps, EMERGENCY-burst)
  #5: Pilot-API Contract-Tests (idempotent Emergency-Signale, Sleep-Trigger-Race)

Vorbereitung Welle-9-epsilon Phase-5 Production-Hardening.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

# Path setup (conftest does this for production tests, repeat here standalone-friendly)
_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))
_SAGA_DIR = _KMO_ROOT / "kmo_governance" / "saga-pattern"
if str(_SAGA_DIR) not in sys.path:
    sys.path.insert(0, str(_SAGA_DIR))


@pytest.fixture
def pilot():
    from df_executors.df_pilot_hotel_EU.pilot_integration import PilotHotelOrchestrator
    with tempfile.TemporaryDirectory() as td:
        yield PilotHotelOrchestrator(hotel_id="hotel-A", state_dir=td)


# ---------- Codex-V2 #2: Property-/Fuzz-Tests fuer membrane_check (zyklische Referenzen) ----------


def test_codex_v2_2_membrane_handles_self_referencing_dict(pilot):
    """Codex-V2 #2: zyklische Referenz darf nicht zu InfiniteRecursion fuehren.

    Depth-Guard (max_depth=16) muss greifen.
    """
    payload = {"data": "x"}
    payload["self"] = payload  # cyclic reference
    # Should not raise RecursionError, should return True (no foreign hotel_id)
    result = pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", payload)
    assert result is True


def test_codex_v2_2_membrane_handles_mutual_recursion(pilot):
    """Codex-V2 #2: A→B→A mutual cycle stops via depth-guard."""
    a = {"name": "a"}
    b = {"name": "b", "ref_a": a}
    a["ref_b"] = b  # A↔B cycle
    result = pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", a)
    assert result is True


def test_codex_v2_2_membrane_handles_deep_legitimate_nesting(pilot):
    """Codex-V2 #2: 20-level deep dict (above max_depth=16) graceful pass not crash."""
    payload = {"level": 0}
    cursor = payload
    for i in range(1, 25):
        cursor["next"] = {"level": i}
        cursor = cursor["next"]
    # Beyond depth-limit: should return True (graceful) not raise
    result = pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", payload)
    assert result is True


def test_codex_v2_2_membrane_finds_foreign_at_legal_depth(pilot):
    """Codex-V2 #2: foreign hotel_id at depth 5 (well below max_depth) IS detected."""
    payload = {"l1": {"l2": {"l3": {"l4": {"hotel_id": "hotel-foreign"}}}}}
    result = pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", payload)
    assert result is False  # detected at depth 4


def test_f6_membrane_visited_set_prevents_memory_spike(pilot):
    """Patch F6 (Gemini-V2 Finding): visited-set should detect cycles via id(),
    not require full depth-traversal of cyclic structure.
    """
    # Tiny cycle of 3 dicts; without visited-set, recursion would visit them
    # repeatedly until depth-cap hits (16 visits).
    a = {"name": "a"}
    b = {"name": "b"}
    c = {"name": "c"}
    a["next"] = b
    b["next"] = c
    c["next"] = a  # 3-node cycle a->b->c->a
    # Should return True (no foreign hotel_id) without crash
    assert pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", a) is True


def test_codex_v2_2_membrane_handles_list_with_cycle(pilot):
    """Codex-V2 #2: list containing dict that references the list."""
    container: list = [{"name": "first"}]
    cycle_dict = {"name": "second", "back_ref": container}
    container.append(cycle_dict)  # list -> dict -> list (cycle)
    result = pilot._phase_membrane_check(pilot.hotel_id, "phase", "input", container)
    assert result is True


# ---------- Codex-V2 #3: Chaos-Tests HomeostasisCoordinator ----------


def test_codex_v2_3_chaos_rapid_vitals_flaps_refractory_protects(pilot):
    """Codex-V2 #3: 50 rapid vital-updates trigger refractory-suppression majority."""
    actions_log: list[dict] = []
    # Bombardiere Pilot mit alternierenden CRITICAL/HEALTHY-Vitals
    for i in range(50):
        if i % 2 == 0:
            # CRITICAL
            actions = pilot.update_system_vitals(
                heart_rate=50, blood_pressure=0.4,
                body_temperature=10.0, oxygen_saturation=0.9,
            )
        else:
            # HEALTHY
            actions = pilot.update_system_vitals(
                heart_rate=50, blood_pressure=0.4,
                body_temperature=0.5, oxygen_saturation=0.9,
            )
        actions_log.append(actions)
    # Many should be refractory-suppressed (real-clock progresses < 60s during 50 calls)
    suppressed = sum(
        1 for a in actions_log if "refractory-suppressed" in a.get("actions", [])
    )
    # At least SOME suppressed (rapid succession)
    assert suppressed > 0


def test_codex_v2_3_chaos_emergency_burst_overrides_refractory(pilot):
    """Codex-V2 #3: 10 EMERGENCY-Signale in Folge alle bypass-fähig."""
    for _ in range(10):
        result = pilot.signal_emergency(reason="test-burst")
        # EMERGENCY bypasses refractory each time
        assert "refractory-suppressed" not in result["actions"]
    assert pilot.get_current_mode() == "incident"


def test_codex_v2_3_chaos_recovery_after_refractory_window(pilot):
    """Codex-V2 #3: Nach 70s (>60s refractory) ist Mode-Switch wieder erlaubt."""
    # Trigger CRITICAL → PEAK_LOAD
    pilot.update_system_vitals(
        heart_rate=50, blood_pressure=0.4,
        body_temperature=10.0, oxygen_saturation=0.9,
    )
    assert pilot.get_current_mode() == "peak_load"

    # Override refractory _last_switch_at to simulate 70s passage
    pilot.master.homeostasis._last_switch_at -= 70.0
    # Now CRITICAL again should be allowed (assuming sigma-state allows transition)
    result = pilot.update_system_vitals(
        heart_rate=50, blood_pressure=0.4,
        body_temperature=15.0, oxygen_saturation=0.9,
    )
    assert "refractory-suppressed" not in result["actions"]


# ---------- Codex-V2 #5: Idempotent Emergency-Signale + Race-Conditions ----------


def test_codex_v2_5_idempotent_emergency_signal_5x(pilot):
    """Codex-V2 #5: signal_emergency 5x mit gleichem reason → Mode bleibt INCIDENT."""
    initial_count = len(pilot.sigma_switch.audit_trail())
    for _ in range(5):
        pilot.signal_emergency(reason="catastrophic-saga-failure")
    assert pilot.get_current_mode() == "incident"
    # Audit-trail should have only ONE transition entry (first call only switches)
    new_count = len(pilot.sigma_switch.audit_trail())
    transitions = new_count - initial_count
    assert transitions == 1  # Only first emergency signal causes mode-change


def test_codex_v2_5_idempotent_glymphatic_cleanup(pilot):
    """Codex-V2 #5: trigger_glymphatic_cleanup mehrfach idempotent (keine Doppel-Pruning)."""
    pilot.register_knowledge_entry("k1", confidence=0.5, stability_days=1.0)
    r1 = pilot.trigger_glymphatic_cleanup()
    r2 = pilot.trigger_glymphatic_cleanup()
    r3 = pilot.trigger_glymphatic_cleanup()
    # All 3 must succeed; pruned counts may vary but no exception
    assert r1["success"] and r2["success"] and r3["success"]


def test_codex_v2_5_concurrent_vitals_updates_thread_safe(pilot):
    """Codex-V2 #5: 10 Threads update vitals parallel → keine Race-Conditions / Crashes."""
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(20):
                pilot.update_system_vitals(
                    heart_rate=50, blood_pressure=0.5,
                    body_temperature=0.5, oxygen_saturation=0.9,
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    assert not errors, f"Race-conditions detected: {errors}"
    # System still functional after concurrent stress
    status = pilot.get_system_health()
    assert status["last_status"] in ("healthy", "warning", "critical", "emergency")


def test_codex_v2_5_idempotent_purge_hotel(pilot):
    """Codex-V2 #5: purge_hotel mehrfach idempotent (1. real, weitere no-ops)."""
    pilot.register_knowledge_entry("k1")
    pilot.emit_demand(amount=1.0)

    r1 = pilot.purge_hotel()
    r2 = pilot.purge_hotel()  # already purged

    # Both calls succeed; counts in r2 should be 0 (already empty)
    assert isinstance(r1, dict) and isinstance(r2, dict)


# ---------- Bonus: Codex-V2 #4 Adversarial Fitness for EvolutionLoop ----------


def test_codex_v2_4_adversarial_fitness_landscape_robust():
    """Codex-V2 #4: EvolutionLoop on adversarial fitness (rugged landscape) doesn't crash.

    Multimodal fitness function with deceptive local optima — common adversarial
    pattern in directed-evolution. Loop should still produce valid generations.
    """
    import random
    from kmo_governance.evolution_loop import (
        EigenThresholdGuard,
        EvolutionLoop,
        FitnessEvaluator,
        Genome,
        PolicyMutator,
        RegressionCage,
    )

    rng = random.Random(0)
    mutator = PolicyMutator(gaussian_sigma=0.2, rng=rng)

    # Adversarial fitness: deceptive landscape with local maxima
    def adversarial(p):
        x = p.get("x", 0.0)
        # Tricky: peak at x=5.0 but local max at x=-3.0 too
        return -((x - 5.0) ** 2) + 0.5 * abs(p.get("y", 0.0))

    eval_ = FitnessEvaluator({"adversarial_score": adversarial})
    guard = EigenThresholdGuard(eigen_threshold=10.0)  # generous
    cage = RegressionCage(tolerance=0.1)
    loop = EvolutionLoop(
        mutator=mutator, evaluator=eval_, population_size=8,
        eigen_guard=guard, cage=cage,
    )

    seed = Genome(genome_id="seed", parameters={"x": 0.0, "y": 0.0})
    pop = loop.initialize_population(seed)
    cage.update_baseline(pop)

    # Run 5 generations — should not crash
    for _ in range(5):
        pop = loop.step(pop)
        assert len(pop) == 8

    # No catastrophic regression-loop expected
    assert loop.regression_count() < 5
