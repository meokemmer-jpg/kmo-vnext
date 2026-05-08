# [CRUX-MK]
"""KPM-Feature-Flag-Engine Tests (Welle-29 Phase-22 Bio-Pattern-Lift)."""
from __future__ import annotations

import threading

import pytest

from kmo_governance.kpm_feature_flag_engine import (
    FlagAuditEvent,
    FlagDecision,
    FlagDefinition,
    FlagState,
    KPMFeatureFlagEngine,
)


# ----------------------------------------------------------------- init_validation
def test_init_validation():
    """Pre-Conditions am Konstruktor werden geprueft."""
    with pytest.raises(ValueError):
        KPMFeatureFlagEngine(default_audit_retention_h=0)
    with pytest.raises(ValueError):
        KPMFeatureFlagEngine(default_audit_retention_h=-1.0)

    # Default OK
    engine = KPMFeatureFlagEngine()
    assert engine.default_audit_retention_h == 168.0  # MiFID-RTS-25 Default

    # Custom OK
    e2 = KPMFeatureFlagEngine(default_audit_retention_h=240.0)
    assert e2.default_audit_retention_h == 240.0


# ------------------------------------------------------------------- register_flag
def test_register_flag():
    """register_flag erzeugt FlagDefinition mit default_state."""
    engine = KPMFeatureFlagEngine()
    definition = engine.register_flag(
        flag_id="strat-aggressive-001",
        strategy_id="aggressive-momentum",
        default_state=FlagState.DISABLED,
        description="Aggressive momentum strategy",
        owner_session_id="kpm-session-001",
    )
    assert isinstance(definition, FlagDefinition)
    assert definition.flag_id == "strat-aggressive-001"
    assert definition.strategy_id == "aggressive-momentum"
    assert definition.default_state == FlagState.DISABLED
    assert definition.description == "Aggressive momentum strategy"
    assert definition.owner_session_id == "kpm-session-001"
    assert definition.created_at > 0

    # Listed in registry
    assert "strat-aggressive-001" in engine.list_flags()

    # Pre-Condition-Fehler
    with pytest.raises(ValueError):
        engine.register_flag(flag_id="", strategy_id="x", default_state=FlagState.DISABLED)
    with pytest.raises(ValueError):
        engine.register_flag(flag_id="x", strategy_id="", default_state=FlagState.DISABLED)
    with pytest.raises(TypeError):
        engine.register_flag(flag_id="x", strategy_id="y", default_state="not-an-enum")


# ----------------------------------------------------------- register_duplicate_raises
def test_register_duplicate_raises():
    """Doppel-Registrierung schlaegt fehl."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.DISABLED
    )
    with pytest.raises(ValueError, match="already registered"):
        engine.register_flag(
            flag_id="strat-001", strategy_id="s2", default_state=FlagState.ENABLED
        )


# ------------------------------------------------------------------- get_flag_unknown
def test_get_flag_unknown_raises():
    """get_flag fuer unregistriertes flag_id wirft KeyError."""
    engine = KPMFeatureFlagEngine()
    with pytest.raises(KeyError):
        engine.get_flag("missing-flag")
    with pytest.raises(ValueError):
        engine.get_flag("")


# ----------------------------------------------------------- set_state_creates_audit
def test_set_state_creates_audit_event():
    """set_state erzeugt FlagAuditEvent und aktualisiert state."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.DISABLED
    )
    event = engine.set_state(
        flag_id="strat-001",
        new_state=FlagState.RAMP_UP,
        changed_by="kpm-admin",
        reason="Begin gradual rollout",
    )
    assert isinstance(event, FlagAuditEvent)
    assert event.flag_id == "strat-001"
    assert event.old_state == FlagState.DISABLED
    assert event.new_state == FlagState.RAMP_UP
    assert event.changed_by == "kpm-admin"
    assert "gradual rollout" in event.reason

    # State persistiert
    decision = engine.evaluate("strat-001", "req-1")
    assert decision.state == FlagState.RAMP_UP

    # Audit log fragment
    audit = engine.get_audit_log("strat-001")
    assert len(audit) == 1
    assert audit[0] == event

    # Pre-Cond
    with pytest.raises(ValueError):
        engine.set_state("", FlagState.ENABLED, "x")
    with pytest.raises(TypeError):
        engine.set_state("strat-001", "not-enum", "x")
    with pytest.raises(ValueError):
        engine.set_state("strat-001", FlagState.ENABLED, "")
    with pytest.raises(KeyError):
        engine.set_state("ghost", FlagState.ENABLED, "x")


# ----------------------------------------------------- set_percentage_only_ramp_up
def test_set_percentage_rollout_only_ramp_up():
    """set_percentage_rollout ist nur in RAMP_UP zulaessig."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.DISABLED
    )

    # In DISABLED -> RuntimeError
    with pytest.raises(RuntimeError, match="RAMP_UP"):
        engine.set_percentage_rollout("strat-001", 25.0, "kpm-admin")

    # Wechsel zu RAMP_UP
    engine.set_state("strat-001", FlagState.RAMP_UP, "kpm-admin")
    event = engine.set_percentage_rollout(
        "strat-001", 50.0, "kpm-admin", reason="Mid-ramp"
    )
    assert isinstance(event, FlagAuditEvent)
    assert "percentage_rollout=50.00" in event.reason
    assert event.old_state == FlagState.RAMP_UP  # state unchanged
    assert event.new_state == FlagState.RAMP_UP

    # Wechsel zu ENABLED -> set_percentage erneut blockiert
    engine.set_state("strat-001", FlagState.ENABLED, "kpm-admin")
    with pytest.raises(RuntimeError, match="RAMP_UP"):
        engine.set_percentage_rollout("strat-001", 75.0, "kpm-admin")

    # Range-Check
    engine.set_state("strat-001", FlagState.RAMP_UP, "kpm-admin")
    with pytest.raises(ValueError):
        engine.set_percentage_rollout("strat-001", -1.0, "kpm-admin")
    with pytest.raises(ValueError):
        engine.set_percentage_rollout("strat-001", 100.5, "kpm-admin")


# ----------------------------------------------------- evaluate_disabled_returns_false
def test_evaluate_disabled_returns_false():
    """DISABLED-State -> enabled=False fuer alle request_ids."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.DISABLED
    )
    for i in range(20):
        decision = engine.evaluate("strat-001", f"req-{i}")
        assert isinstance(decision, FlagDecision)
        assert decision.state == FlagState.DISABLED
        assert decision.enabled is False
        assert "DISABLED" in decision.reason


# ----------------------------------------------------- evaluate_enabled_returns_true
def test_evaluate_enabled_returns_true():
    """ENABLED-State -> enabled=True fuer alle request_ids."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.ENABLED
    )
    for i in range(20):
        decision = engine.evaluate("strat-001", f"req-{i}")
        assert decision.state == FlagState.ENABLED
        assert decision.enabled is True
        assert "ENABLED" in decision.reason


# -------------------------------------------------- evaluate_ramp_up_deterministic
def test_evaluate_ramp_up_uses_hash_deterministic():
    """RAMP_UP: gleiche request_id liefert immer gleiches Ergebnis."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.RAMP_UP
    )
    engine.set_percentage_rollout("strat-001", 50.0, "kpm-admin")

    # Gleiche request_id -> stabiles Ergebnis ueber 5 Calls
    first = engine.evaluate("strat-001", "deterministic-key").enabled
    for _ in range(5):
        assert engine.evaluate("strat-001", "deterministic-key").enabled == first

    # Andere request_ids -> evtl. unterschiedliche Buckets,
    # aber jede einzelne wieder stabil
    keys = [f"key-{k}" for k in range(10)]
    snapshots = {k: engine.evaluate("strat-001", k).enabled for k in keys}
    for k in keys:
        assert engine.evaluate("strat-001", k).enabled == snapshots[k]


# ---------------------------------------------------- evaluate_ramp_up_distribution
def test_evaluate_ramp_up_distribution():
    """RAMP_UP mit 1000 unique request_ids: Verteilung ~ percentage_rollout (+/- 5pp)."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.RAMP_UP
    )
    engine.set_percentage_rollout("strat-001", 30.0, "kpm-admin")

    enabled_count = 0
    n = 1000
    for i in range(n):
        decision = engine.evaluate("strat-001", f"unique-req-{i:05d}")
        if decision.enabled:
            enabled_count += 1
    # Bei 30% Rollout sollten ~300/1000 enabled sein, Toleranz +/-5pp (250-350).
    pct = (enabled_count / n) * 100.0
    assert 25.0 <= pct <= 35.0, f"Expected ~30%, got {pct:.2f}%"


# -------------------------------------------------- emergency_off_blocks_state_change
def test_emergency_off_blocks_state_change():
    """EMERGENCY_OFF blockiert weitere set_state-Aufrufe (ausser idempotent)."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.ENABLED
    )
    engine.emergency_off("strat-001", "kpm-admin", reason="Production incident")

    # State == EMERGENCY_OFF
    decision = engine.evaluate("strat-001", "req-1")
    assert decision.state == FlagState.EMERGENCY_OFF
    assert decision.enabled is False

    # set_state(ENABLED) -> RuntimeError
    with pytest.raises(RuntimeError, match="EMERGENCY_OFF"):
        engine.set_state("strat-001", FlagState.ENABLED, "kpm-admin")

    # set_state(EMERGENCY_OFF) -> idempotent OK
    event = engine.set_state(
        "strat-001", FlagState.EMERGENCY_OFF, "kpm-admin", reason="Re-confirm"
    )
    assert event.new_state == FlagState.EMERGENCY_OFF

    # emergency_off braucht reason
    with pytest.raises(ValueError, match="reason required"):
        engine.emergency_off("strat-001", "kpm-admin", reason="")


# ----------------------------------------------------------- clear_emergency_unblocks
def test_clear_emergency_unblocks():
    """clear_emergency setzt zurueck auf DISABLED und ist idempotent."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-001", strategy_id="s1", default_state=FlagState.ENABLED
    )
    engine.emergency_off("strat-001", "kpm-admin", reason="Production incident")

    # clear -> True (Wechsel)
    cleared = engine.clear_emergency("strat-001", "kpm-admin")
    assert cleared is True
    decision = engine.evaluate("strat-001", "req-1")
    assert decision.state == FlagState.DISABLED

    # Nochmal clear -> False (kein Wechsel, idempotent)
    cleared2 = engine.clear_emergency("strat-001", "kpm-admin")
    assert cleared2 is False

    # Nach clear: set_state wieder erlaubt
    engine.set_state("strat-001", FlagState.ENABLED, "kpm-admin")
    decision = engine.evaluate("strat-001", "req-1")
    assert decision.state == FlagState.ENABLED


# --------------------------------------------------------- audit_log_filtered_by_flag
def test_audit_log_filtered_by_flag():
    """get_audit_log filtert nach flag_id; ohne flag_id -> alle Events."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag("flag-a", "strategy-a", FlagState.DISABLED)
    engine.register_flag("flag-b", "strategy-b", FlagState.DISABLED)

    engine.set_state("flag-a", FlagState.ENABLED, "user1")
    engine.set_state("flag-b", FlagState.RAMP_UP, "user2")
    engine.set_state("flag-a", FlagState.DISABLED, "user1", reason="rollback")

    all_events = engine.get_audit_log()
    assert len(all_events) == 3

    a_events = engine.get_audit_log("flag-a")
    assert len(a_events) == 2
    for e in a_events:
        assert e.flag_id == "flag-a"

    b_events = engine.get_audit_log("flag-b")
    assert len(b_events) == 1
    assert b_events[0].flag_id == "flag-b"


# ---------------------------------------------------- concurrent_set_state_50_threads
def test_concurrent_set_state_50_threads():
    """50 parallele set_state-Calls -> kein Race; Audit-Log enthaelt alle 50 Events."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag(
        flag_id="strat-concurrent",
        strategy_id="concurrent-test",
        default_state=FlagState.DISABLED,
    )

    states = [
        FlagState.DISABLED,
        FlagState.RAMP_UP,
        FlagState.ENABLED,
    ]

    def worker(idx: int) -> None:
        target = states[idx % len(states)]
        engine.set_state(
            "strat-concurrent",
            target,
            changed_by=f"worker-{idx}",
            reason=f"thread-{idx}",
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    audit = engine.get_audit_log("strat-concurrent")
    assert len(audit) == 50
    # Alle Events haben unterschiedliche changed_by-Werte
    changers = {e.changed_by for e in audit}
    assert len(changers) == 50


# ------------------------------------------------------------------- decision_frozen
def test_decision_frozen():
    """FlagDecision ist immutable + hashable."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag("strat-001", "s1", FlagState.ENABLED)
    decision = engine.evaluate("strat-001", "req-1")

    with pytest.raises(Exception):
        decision.flag_id = "mutated"  # type: ignore
    with pytest.raises(Exception):
        decision.enabled = False  # type: ignore

    # Hashable check
    assert hash(decision) is not None


# --------------------------------------------------------------------- event_frozen
def test_event_frozen():
    """FlagAuditEvent ist immutable + hashable."""
    engine = KPMFeatureFlagEngine()
    engine.register_flag("strat-001", "s1", FlagState.DISABLED)
    event = engine.set_state("strat-001", FlagState.ENABLED, "kpm-admin")

    with pytest.raises(Exception):
        event.flag_id = "mutated"  # type: ignore
    with pytest.raises(Exception):
        event.new_state = FlagState.DISABLED  # type: ignore

    # Hashable check
    assert hash(event) is not None


# CRUX-MK
