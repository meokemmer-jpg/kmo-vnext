# [CRUX-MK]
"""KPM-Chaos-Engineering (Welle-26 Phase-19 Bio-Pattern-Lift).

Bio-Aequivalent: Innate-Immunity-Stress-Test (kontrollierte Antigen-Exposition
auf Trading-Strategy statt auf Hotel-Service).
Pattern-Quelle: kmo_governance.chaos_engineering (Welle-9, Hotel-Domain,
Netflix-Chaos-Monkey + Apoptosis + Wound-Healing inspiriert).

KPM-Domain-Note:
- KPM (Kemmer-Portfolio-Management) = Familien-Trading-System
- Adversarial fault-injection auf Trading-Strategien (kein echtes Geld)
- Trading-Faults: Latency-Spikes, Order-Rejects, Quote-Holes, Slippage-Bursts,
  Exchange-Disconnects
- Recovery-Time + P&L-Impact + Resilience-Score messen
- Severity-Stufen: MINOR / MODERATE / SEVERE / CRITICAL
- Kill-Switch: pause_chaos() / resume_chaos() (K_0-Sicherheit, no real money exposure)

Demonstriert Bio-Pattern-Lift: gleicher Architekturkern (Stress-Test +
Recovery-Verification + Resilience-Aggregation), andere Domaene
(Trading-Fault-Injection statt Hotel-Service-Failure).

Siehe BIO-PATTERN-LIFT-DEMO.md fuer Isomorphie-Tabelle.

Pattern-Inspiration:
- chaos_engineering (Hotel-Domain): FailureInjector + ChaosScenario + ChaosMonkey
- Netflix Chaos-Monkey: Production-Failure-Injection
- Innate Immunity: kontrollierte Antigen-Exposition + Lymphocyte-Recovery

NO external Dependencies (stdlib-only): random, time, threading, dataclasses,
enum, uuid, typing.

Public API:
    from kmo_governance.kpm_chaos_engineering import (
        FaultType,
        FaultSeverity,
        ChaosScenario,
        ChaosOutcome,
        KPMChaosEngineering,
    )

Usage:
    chaos = KPMChaosEngineering()
    chaos.register_strategy("kelly_0.4", lambda scenario: my_handler(scenario))
    scenario = ChaosScenario(
        scenario_id="latency-spike-1",
        fault_type=FaultType.LATENCY_SPIKE,
        severity=FaultSeverity.MODERATE,
        target_strategy_id="kelly_0.4",
        duration_s=5.0,
        params=(("min_ms", 100.0), ("max_ms", 500.0)),
        expected_recovery_s=2.0,
    )
    outcome = chaos.inject(scenario)
    score = chaos.get_resilience_score("kelly_0.4")
"""
from .kpm_chaos_engineering import (
    ChaosOutcome,
    ChaosScenario,
    FaultSeverity,
    FaultType,
    KPMChaosEngineering,
)

__all__ = [
    "ChaosOutcome",
    "ChaosScenario",
    "FaultSeverity",
    "FaultType",
    "KPMChaosEngineering",
]

# CRUX-MK
