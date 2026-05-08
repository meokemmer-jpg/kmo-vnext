# Bio-Pattern-Lift Demo: chaos_engineering -> kpm_chaos_engineering [CRUX-MK]

**Welle-26 Phase-19 KMO-vNext Bio-Lift Round-1 (2/3)**
**Datum:** 2026-05-08
**Status:** CONDITIONAL (Pattern-Demo, Cross-LLM-Audit pending)

## Pattern-Quelle

`kmo_governance/chaos_engineering/` (Welle-9, Hotel-Domain)

- Bio-Aequivalent: Innate-Immunity-Stress-Test (kontrollierte Antigen-Exposition + Lymphozyten-Recovery)
- Use-Case: Hotel-Service-Failure-Injection (Latenz, Failure, Recovery-Verifikation)
- Pattern-Inspiration: Netflix Chaos-Monkey + Apoptosis-Engine + Wound-Healing-Lifecycle
- ~840 LoC, FailureInjector + ChaosScenario + ChaosMonkey + RecoveryVerifier + ResilienceScore

## Pattern-Ziel

`kmo_governance/kpm_chaos_engineering/` (Welle-26 Phase-19, Trading-Domain)

- Use-Case: KPM-Trading-Strategy-Adversarial-Fault-Injection
- Trading-Faults: Latency-Spike, Order-Reject, Quote-Hole, Slippage-Burst, Exchange-Disconnect
- 16 Tests + 2 Bonus-Tests (Handler-Exception, Handler-Wrong-Return-Type)
- ~330 LoC Code, KPM-Domain-spezifisch (FaultType + FaultSeverity + handler_fn)

## Bio-Mapping (Innate-Immunity-Stress-Test auf Trading)

| Hotel-Service                    | Trading-Strategy                            | Bio                                  |
|----------------------------------|---------------------------------------------|--------------------------------------|
| `ChaosScenario(Hotel-Service)`   | `ChaosScenario(Trade-Strategy)`             | Pathogen-Challenge                   |
| `target_service` / target_fn     | `target_strategy_id`                        | Tissue-Target                        |
| `FailureInjector`                | `fault_handler_fn`                          | Antigen-Receptor (handler-bound)     |
| `inject_latency` + `inject_failure` | `inject(scenario)` (handler simuliert Fault) | Antigen-Exposition                |
| `recovery_time_s`                | `actual_recovery_s`                         | Healing-Phase-Dauer                  |
| `success_rate` / `ResilienceScore` | `get_resilience_score(strategy_id)`        | Immune-Effectiveness                 |
| `RecoveryVerifier(retries)`      | (delegiert an handler_fn)                   | Lymphozyten-Antwort                  |
| `ChaosMonkey`                    | `KPMChaosEngineering`                       | Vakzinierungs-Schedule               |

## Pattern-Isomorphie

Strikte Architekturkern-Identitaet, nur Domaenen-Vokabular wechselt:

| Konzept                     | Hotel-Domain (chaos_engineering)        | Trading-Domain (kpm_chaos_engineering)    |
|-----------------------------|------------------------------------------|-------------------------------------------|
| **Aktive Einheit**          | Hotel-Service via `register_target`      | Trading-Strategy via `register_strategy`  |
| **Fault-Profil**            | `ChaosScenario(name, steps)`             | `ChaosScenario(scenario_id, fault_type, severity, params)` |
| **Fault-Modell**            | `FailureInjector` (latency + exception)  | `FaultType` Enum (5 Trading-Faults)       |
| **Schweregrad**             | implicit ueber probability/latency       | `FaultSeverity` Enum (MINOR/MODERATE/SEVERE/CRITICAL) |
| **Handler-Mechanik**        | step.inject_latency + step.inject_failure | `fault_handler_fn(scenario) -> ChaosOutcome` |
| **Outcome-Status**          | SUCCESS / FAILURE / RECOVERED            | `success: bool` + `actual_recovery_s`     |
| **Outcome-Frozen**          | `@dataclass(frozen=True)` ChaosOutcome   | `@dataclass(frozen=True)` ChaosOutcome    |
| **Recovery**                | `RecoveryVerifier` (extern)              | im handler_fn enthalten (single-shot)     |
| **Aggregat-Score**          | `ResilienceScore.score(outcomes)`        | `get_resilience_score(strategy_id)`       |
| **Audit-Trail**             | `monkey.outcomes` (list)                 | `get_outcomes()` (immutable tuple)        |
| **Synchronisation**         | `threading.RLock`                        | `threading.RLock`                         |
| **Concurrency-Cap**         | (kein expliziter Cap)                    | `max_concurrent_chaos` (Default 1)        |
| **Kill-Switch**             | (nicht eingebaut)                        | `pause_chaos()` / `resume_chaos()`        |
| **Handler-Exception**       | catch via try/except in scenario.run     | catch in inject(): synthetic failure outcome |

## KPM-Domain-spezifische Erweiterungen

Drei Erweiterungen ueber die reine Pattern-Lift hinaus, die Trading-Domain-
Realitaeten reflektieren:

1. **`FaultType` Enum (5 Klassen):**
   - `LATENCY_SPIKE` - Order-Submission-Latenz explodiert
   - `ORDER_REJECT` - Broker lehnt Orders ab
   - `QUOTE_HOLE` - Marktdaten-Stream haengt
   - `SLIPPAGE_BURST` - Realisiertes Fill weit von Quote
   - `EXCHANGE_DISCONNECT` - Voll-Outage des Exchange
   - Hotel-Pendant: implicit als FailureInjector-Configuration; KPM macht es explizit
     fuer Audit-Trail-Nachvollziehbarkeit (welche Fault-Klasse hat Strategy gekippt)

2. **`FaultSeverity` Enum + Severity-Multipliers:**
   - `MINOR` (1.0x) / `MODERATE` (2.5x) / `SEVERE` (6.0x) / `CRITICAL` (15.0x)
   - Skaliert latency-base und expected_recovery_s
   - K_0-Schutz: `CRITICAL` darf failen ohne Strategy-Vertrauensverlust

3. **Kill-Switch (`pause_chaos` / `resume_chaos`) + `max_concurrent_chaos`:**
   - K_0-Sicherheits-Pflicht: kein Multi-Fault-Storm
   - Default `max_concurrent_chaos=1` (sequential), overrideable
   - `pause_chaos` blockiert weitere `inject()`-Calls, RuntimeError sofort
   - Hotel-Pendant fehlt diese Mechanik (Hotel-Chaos ist sicherer als Trading-Chaos)

## Verifikation: 14 Pflicht-Tests + 2 Bonus

| Test-Konzept                           | Hotel-Domain Test                            | Trading-Domain Test                              |
|----------------------------------------|----------------------------------------------|--------------------------------------------------|
| Init-Validation                        | (implicit in FailureInjector __init__)       | `test_init_validation`                           |
| Register-Target/Strategy               | (implicit in monkey.register_target)         | `test_register_strategy`                         |
| Inject-Calls-Handler                   | `test_run_scenario_calls_target`             | `test_inject_calls_handler`                      |
| Unknown-Target/Strategy raises         | `test_schedule_chaos_unknown_target_raises`  | `test_inject_unknown_strategy_raises`            |
| Random/Generated-Scenario              | (manual scenario construction)               | `test_inject_random_picks_fault`                 |
| Outcome-Filterung                      | `ResilienceScore.get_breakdown`              | `test_get_outcomes_filtered`                     |
| Resilience-Score (all-success)         | `ResilienceScore.score == 1.0`               | `test_resilience_score_all_success`              |
| Resilience-Score (no-data default)     | `ResilienceScore.score([]) == 1.0`           | `test_resilience_score_no_outcomes_default`      |
| Pause-Mechanik                         | (nicht im Hotel-Pattern)                     | `test_pause_blocks_inject`                       |
| Resume-Mechanik                        | (nicht im Hotel-Pattern)                     | `test_resume_allows_inject`                      |
| Concurrency-Cap                        | (nicht im Hotel-Pattern)                     | `test_max_concurrent_chaos_enforced`             |
| Concurrent-Stress (50 Threads)         | (nicht im Hotel-Pattern)                     | `test_concurrent_inject_50_threads`              |
| Scenario-Frozen-Immutability           | `ChaosScenario` ist mutable (Hotel)          | `test_scenario_frozen` (KPM ist frozen)          |
| Outcome-Frozen-Immutability            | `test_chaos_outcome_frozen`                  | `test_outcome_frozen`                            |

KPM-Modul hat zusaetzlich:
- `test_handler_exception_becomes_failure_outcome` (Robustheit gegen Handler-Crash)
- `test_handler_returning_non_outcome_becomes_failure` (Protocol-Violation -> synthetic failure)

## Generalisierungs-These

Bio-Pattern-Architekturen sind domain-unabhaengig. Kern besteht aus:

1. **Strukturkern:** Enum-States + frozen Decision/Outcome-Records + Lock-protected Orchestrator
2. **Bio-Aequivalent:** Innate-Immunity-Stress-Test (Antigen-Exposition + Recovery-Messung)
3. **Domain-Schicht:** Vokabular-Mapping (Hotel-Service -> Trading-Strategy) ohne Aenderung der Strukturlogik

## Replikations-Roadmap (Beispiele)

| Pattern-Quelle (Hotel-Domain)          | Pattern-Ziel (KPM-Trading-Domain)                            | Lift-Aufwand |
|----------------------------------------|--------------------------------------------------------------|--------------|
| `chaos_engineering` (Welle-9)          | `kpm_chaos_engineering` (DIESES Modul)                       | 3-4h (DONE)  |
| `apoptosis_engine`                     | `kpm_stale_position_cleanup` (Tage-alte Limit-Orders)        | 2h           |
| `quorum_sensing`                       | `kpm_multi_broker_quorum` (3-of-5 Brokers agree on price)    | 2-3h         |
| `lateral_inhibition`                   | `kpm_strategy_selection` (winner-takes-all bei Conflict)     | 2h           |
| `wound_healing`                        | `kpm_portfolio_recovery` (graduelle Re-Allocation post-DD)   | 3h           |
| `stigmergic_blackboard`                | `kpm_multi_agent_coordination` via Blackboard                | 3h           |

## Verifikations-Status

- 16 KPM-Tests (14 Pflicht + 2 Bonus) passing
- Pattern-Isomorphie strikt eingehalten (siehe Tabelle)
- Pre/Post-Conditions dokumentiert (Class- und Method-Docstrings)
- Thread-Safety verifiziert (50-Thread-Stress-Test)
- Frozen Decision/Outcome (Audit-Trail-Integritaet)
- Stdlib only (random, time, threading, dataclasses, enum, uuid, typing)
- Cross-LLM-Audit pending (CONDITIONAL Status)
- Real-money-Trading explizit ausgeschlossen (Pattern-Demo, K_0-Schutz)

## Pattern-Lift als CRUX-Hebel

- **Q_0:** epistemische Integritaet via wiederverwendbares verified-by-test Pattern
- **W_0:** Multiplier ~30-50x (Bio-Pattern entwickelt einmal, lift-bar in N Domains)
- **rho-Schaetzung:** geschaetzt +50-150k EUR/J durch Architektur-Wiederverwendung
- **K_0:** geschuetzt durch:
  - Klare Trennung Pattern-Demo vs Real-Money
  - Kill-Switch (`pause_chaos`) + `max_concurrent_chaos` Default 1
  - Handler-Exception-Robustheit (synthetic failure outcome statt Crash)

[CRUX-MK]
