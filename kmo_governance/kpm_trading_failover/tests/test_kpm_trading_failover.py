# [CRUX-MK]
"""KPM-Trading-Failover Tests (Welle-23 Phase-16 Bio-Pattern-Lift).

Iso-morphe Test-Suite zum Hotel-Domain-Pattern (failover_router/tests),
KPM-Domain-spezifisch fuer Trading-Strategie-Failover.
"""
from __future__ import annotations

import threading

import pytest

from kmo_governance.kpm_trading_failover import (
    FailoverState,
    KPMTradingFailover,
    StrategyStatus,
    TradingDecision,
)


def test_init_validation_kelly_fraction_range():
    """kelly_fraction-Override muss in [0, 0.5] liegen."""
    with pytest.raises(ValueError):
        KPMTradingFailover(
            primary_strategy_id="aggressive_kelly_04",
            standby_strategy_ids=["conservative_kelly_02"],
            kelly_per_strategy={"aggressive_kelly_04": 0.7},  # > KELLY_MAX
        )
    with pytest.raises(ValueError):
        KPMTradingFailover(
            primary_strategy_id="p",
            standby_strategy_ids=["s"],
            kelly_per_strategy={"s": -0.1},  # < KELLY_MIN
        )
    # auch base validation
    with pytest.raises(ValueError):
        KPMTradingFailover(primary_strategy_id="", standby_strategy_ids=["s1"])
    with pytest.raises(ValueError):
        KPMTradingFailover(primary_strategy_id="p", standby_strategy_ids=[])
    with pytest.raises(ValueError):
        KPMTradingFailover(
            primary_strategy_id="p",
            standby_strategy_ids=["s"],
            health_threshold=0,
        )


def test_initial_state_primary_aggressive_kelly():
    """Initial-State: PRIMARY mit aggressive Kelly-Fraction (0.4)."""
    r = KPMTradingFailover(
        primary_strategy_id="aggressive_kelly_04",
        standby_strategy_ids=["conservative_kelly_03", "ultra_conservative_kelly_02"],
    )
    assert r.state == FailoverState.PRIMARY
    assert r.active_strategy == "aggressive_kelly_04"
    # Default Kelly-Fraction fuer primary = 0.4
    assert r.kelly_per_strategy["aggressive_kelly_04"] == 0.4
    # Default Kelly-Fraction fuer erste standby = 0.3
    assert r.kelly_per_strategy["conservative_kelly_03"] == 0.3
    # Default Kelly-Fraction fuer zweite standby = 0.2
    assert r.kelly_per_strategy["ultra_conservative_kelly_02"] == 0.2


def test_route_to_primary_when_healthy():
    """Routing -> Primary wenn keine Loss-Streak."""
    r = KPMTradingFailover("aggressive", ["conservative"])
    decision = r.route()
    assert decision.active_strategy_id == "aggressive"
    assert decision.state == FailoverState.PRIMARY
    assert decision.expected_kelly_fraction == 0.4


def test_failover_when_primary_strategy_loses_streak():
    """Failover bei 3 unprofitablen Trades in Folge."""
    r = KPMTradingFailover(
        primary_strategy_id="aggressive",
        standby_strategy_ids=["conservative"],
        health_threshold=3,
    )
    for _ in range(3):
        r.record_trade_outcome("aggressive", profitable=False)
    decision = r.route()
    assert decision.active_strategy_id == "conservative"
    assert decision.state == FailoverState.FAILED_OVER
    # Conservative-Kelly = 0.3 (graduelle Reduktion)
    assert decision.expected_kelly_fraction == 0.3
    assert "DOWN" in decision.reason
    assert "failover" in decision.reason


def test_failover_skips_unhealthy_standby():
    """Failover skips standby falls auch DOWN, nimmt naechste healthy."""
    r = KPMTradingFailover(
        primary_strategy_id="p",
        standby_strategy_ids=["s1_down", "s2_healthy"],
        health_threshold=2,
    )
    # Beide primary AND s1 down
    for _ in range(2):
        r.record_trade_outcome("p", profitable=False)
        r.record_trade_outcome("s1_down", profitable=False)
    decision = r.route()
    assert decision.active_strategy_id == "s2_healthy"
    assert decision.state == FailoverState.FAILED_OVER


def test_recovery_state_after_primary_returns_profitable():
    """Nach Failover: 1 profitabler Trade primary -> RECOVERING-State."""
    r = KPMTradingFailover("p", ["s1"], health_threshold=2)
    for _ in range(2):
        r.record_trade_outcome("p", profitable=False)
    r.route()  # Failover
    # Primary erholt sich
    r.record_trade_outcome("p", profitable=True)
    decision = r.route()
    assert decision.state == FailoverState.RECOVERING
    assert "RECOVERING" in decision.reason
    assert "manual promote" in decision.reason


def test_promote_to_primary_resumes_aggressive_kelly():
    """Manual Promote nach Recovery -> aggressive Kelly resumes."""
    r = KPMTradingFailover("aggressive", ["conservative"], health_threshold=2)
    for _ in range(2):
        r.record_trade_outcome("aggressive", profitable=False)
    r.route()  # FAILED_OVER
    r.record_trade_outcome("aggressive", profitable=True)
    decision = r.promote_to_primary()
    assert decision.state == FailoverState.PRIMARY
    assert decision.active_strategy_id == "aggressive"
    assert r.active_strategy == "aggressive"
    # Aggressive Kelly = 0.4 wieder aktiv
    assert decision.expected_kelly_fraction == 0.4
    assert "Phronesis" in decision.reason


def test_promote_unhealthy_raises():
    """Promote auf unhealthy primary -> RuntimeError (K_0-Schutz)."""
    r = KPMTradingFailover("p", ["s1"], health_threshold=2)
    for _ in range(2):
        r.record_trade_outcome("p", profitable=False)
    with pytest.raises(RuntimeError) as exc:
        r.promote_to_primary()
    assert "not HEALTHY" in str(exc.value)


def test_health_recovery_resets_loss_count():
    """profitable=True nach Loss-Streak resettet loss-counter."""
    r = KPMTradingFailover("p", ["s1"], health_threshold=3)
    r.record_trade_outcome("p", profitable=False)
    r.record_trade_outcome("p", profitable=False)
    r.record_trade_outcome("p", profitable=True)  # Reset
    r.record_trade_outcome("p", profitable=False)  # Erst 1 nach Reset
    statuses = r.get_strategy_statuses()
    # Nur 1 Loss seit Reset, NICHT 3 -> sollte nicht DOWN sein
    assert statuses["p"] != StrategyStatus.DOWN


def test_kelly_fraction_per_strategy():
    """Kelly-Fraction-Override pro Strategie via constructor."""
    r = KPMTradingFailover(
        primary_strategy_id="custom_primary",
        standby_strategy_ids=["custom_standby"],
        kelly_per_strategy={
            "custom_primary": 0.45,
            "custom_standby": 0.15,
        },
    )
    assert r.kelly_per_strategy["custom_primary"] == 0.45
    assert r.kelly_per_strategy["custom_standby"] == 0.15
    decision = r.route()
    assert decision.expected_kelly_fraction == 0.45


def test_concurrent_trade_outcomes_50_threads():
    """Thread-Safety: 50 parallele Threads schreiben Outcomes."""
    r = KPMTradingFailover("p", ["s1"], health_threshold=1000)

    def worker():
        for _ in range(20):
            r.record_trade_outcome("p", profitable=True)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Alle Outcomes profitable -> primary HEALTHY
    assert r.get_strategy_statuses()["p"] == StrategyStatus.HEALTHY


def test_decision_frozen_immutability():
    """TradingDecision muss frozen sein (Audit-Trail-Integritaet)."""
    r = KPMTradingFailover("p", ["s1"])
    decision = r.route()
    with pytest.raises(Exception):
        decision.active_strategy_id = "modified"  # type: ignore[misc]


def test_unknown_strategy_id_raises():
    """record_trade_outcome auf unbekannte Strategy -> ValueError."""
    r = KPMTradingFailover("p", ["s1"])
    with pytest.raises(ValueError):
        r.record_trade_outcome("nonexistent_strategy", profitable=True)


def test_all_down_returns_primary_fallback():
    """Wenn alle Strategien DOWN -> all-down fallback."""
    r = KPMTradingFailover("p", ["s1"], health_threshold=2)
    for _ in range(2):
        r.record_trade_outcome("p", profitable=False)
        r.record_trade_outcome("s1", profitable=False)
    decision = r.route()
    assert "all strategies DOWN" in decision.reason
    assert "high risk" in decision.reason


def test_audit_trail_records_all_decisions():
    """get_decisions() liefert alle bisherigen routing decisions."""
    r = KPMTradingFailover("p", ["s1"])
    r.route()
    r.route()
    r.route()
    decisions = r.get_decisions()
    assert len(decisions) == 3
    for d in decisions:
        assert isinstance(d, TradingDecision)


def test_strategy_statuses_snapshot():
    """get_strategy_statuses liefert vollstaendigen Snapshot."""
    r = KPMTradingFailover("p", ["s1", "s2"])
    statuses = r.get_strategy_statuses()
    assert statuses["p"] == StrategyStatus.HEALTHY
    assert "s1" in statuses
    assert "s2" in statuses


# CRUX-MK
