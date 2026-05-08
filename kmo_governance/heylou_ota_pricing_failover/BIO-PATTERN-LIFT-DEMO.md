# Bio-Pattern-Lift Demo: failover_router -> heylou_ota_pricing_failover [CRUX-MK]

**Welle-35 Phase-28 KMO-vNext (7. Domain, 18. Lift)**
**Datum:** 2026-05-07
**Status:** CONDITIONAL (Pattern-Demo, Cross-LLM-Audit pending)

## Pattern-Quelle

`kmo_governance/failover_router/` (Welle-19 Phase-13.1, Hotel-Mock-Domain)

- Bio-Aequivalent: Kollateral-Kreislauf (Active-Standby Failover bei Hauptarterien-Block)
- Use-Case: Hotel-Node-Failover (z.B. Pilot-Hotel-EU primary, Backup-Hotel-EU2 standby)
- ~240 LoC, threading.RLock-protected

## Pattern-Ziel

`kmo_governance/heylou_ota_pricing_failover/` (Welle-35 Phase-28, HeyLou-OTA-Pricing-Domain)

- Use-Case: HeyLou-Hotels nutzen multiple OTA-Pricing-Sources (Booking.com primary,
  Expedia + Direct-Booking + GDS-Amadeus standbys) fuer Verfuegbarkeit + Rate-Parity
- 14 Tests passing
- HeyLou-Domain-spezifisch: Pricing-Freshness-Cache-Tiers (graduiert von 30s primary
  bis 300s+ standby), erhoehter health_threshold=5 (OTA-API-Volatilitaet)

## Isomorphie-Tabelle

Die folgende Tabelle zeigt die strikte Pattern-Isomorphie. Architekturkern bleibt
identisch (Active-Standby + State-Machine + frozen Decision-Record + Lock), nur die
Domaenen-Vokabular-Schicht aendert sich:

| Konzept                       | Hotel-Mock (failover_router)         | KPM-Trading (kpm_trading_failover)               | HeyLou-OTA (heylou_ota_pricing_failover)              | Bio-Aequivalent           |
|-------------------------------|--------------------------------------|--------------------------------------------------|-------------------------------------------------------|---------------------------|
| **Aktive Einheit**            | `node_id`                            | `strategy_id`                                    | `ota_source`                                          | Hauptarterie-Knoten       |
| **Standby-Einheiten**         | `standby_node_ids`                   | `standby_strategy_ids`                           | `standby_otas`                                        | Kollateral-Gefaesse       |
| **Health-Status Enum**        | `NodeStatus`                         | `StrategyStatus`                                 | `OTASourceStatus`                                     | Vitalitaets-Marker        |
| **Health-Werte**              | HEALTHY / DEGRADED / DOWN            | HEALTHY / DEGRADED / DOWN                        | HEALTHY / DEGRADED / DOWN                             | -                         |
| **Failover-State Enum**       | `FailoverState`                      | `FailoverState` (gleich!)                        | `FailoverState` (gleich!)                             | -                         |
| **State-Werte**               | PRIMARY / FAILED_OVER / RECOVERING   | PRIMARY / FAILED_OVER / RECOVERING               | PRIMARY / FAILED_OVER / RECOVERING                    | Apoptose-Phase            |
| **Decision-Record**           | `RouteDecision` (frozen)             | `TradingDecision` (frozen)                       | `OTAPricingDecision` (frozen)                         | -                         |
| **Decision-Felder**           | target_node_id, state, reason, ts    | active_strategy_id, state, reason, ts, kelly    | target_ota_source, state, reason, ts, freshness_s     | -                         |
| **Hauptklasse**               | `FailoverRouter`                     | `KPMTradingFailover`                             | `HeyLouOTAPricingFailover`                            | -                         |
| **Health-Recording**          | `record_health(node_id, healthy)`    | `record_trade_outcome(strategy_id, profitable)`  | `record_booking_outcome(ota_source, successful)`      | -                         |
| **health_threshold (default)**| 3                                    | 3                                                | **5** (OTAs volatiler als Hotel-Nodes)                | Apoptose-Schwelle         |
| **Routing**                   | `route()`                            | `route()`                                        | `route()`                                             | Blutfluss-Steuerung       |
| **Manuelle Promotion**        | `promote_to_primary()`               | `promote_to_primary()`                           | `promote_to_primary()`                                | Recovery-Signal           |
| **Status-Snapshot**           | `get_node_statuses()` -> dict        | `get_strategy_statuses()` -> dict                | `get_ota_statuses()` -> dict                          | -                         |
| **Audit-Trail**               | `get_decisions()` -> list            | `get_decisions()` -> list                        | `get_decisions()` -> **tuple** (immutable)            | Audit-Snapshot            |
| **Failover-Trigger**          | 3 Health-Checks rot                  | 3 unprofitable Trades in Folge                   | 5 fehlgeschlagene Bookings in Folge                   | Iskaemie-Schwellwert      |
| **Synchronisation**           | `threading.RLock`                    | `threading.RLock`                                | `threading.RLock`                                     | Phasen-Synchronisation    |
| **Fallback bei All-Down**     | route-to-primary                     | route-to-primary (high-risk-warning)             | route-to-primary (stale-pricing-warning)              | Nothilfe-Routing          |

## HeyLou-Domain-spezifische Erweiterungen

Drei Erweiterungen ueber die reine Pattern-Lift hinaus, die OTA-Pricing-Realitaeten
reflektieren:

1. **Pricing-Freshness pro OTA-Source** (`freshness_per_ota: dict[str, float]`):
   - Primary default 30.0s (frische Live-Preise von Booking.com Direct-Connect)
   - Standby[0] default 60.0s (Expedia Cache-Window)
   - Standby[1] default 300.0s (Direct-Booking-Engine Cache)
   - Weitere standbys: graduiert (300s + 300s pro Index)
   - Validation: alle Werte >= FRESHNESS_MIN_S = 0.0s

2. **`expected_pricing_freshness_s` im Decision-Record:**
   - Audit-Trail enthaelt jede Routing-Entscheidung mit erwarteter Pricing-Freshness
   - Wichtig fuer Rate-Parity-Compliance downstream (Booking.com Rate-Parity-Pflicht)

3. **Erhoehter health_threshold (default 5 statt 3):**
   - OTAs sind volatiler als Hotel-Nodes (transient API-Errors, Rate-Limits, Booking-Caches)
   - 5 fehlgeschlagene Bookings in Folge tolerantere Schwelle
   - Schuetzt vor False-Positive-Failovers durch transient Network-Issues

4. **`get_decisions()` -> tuple (statt list):**
   - Spec-Pflicht macht Audit-Trail immutable nach Snapshot
   - Anti-Tampering-Mechanik: kein .append moeglich auf Snapshot

## Verifikation: heylou_ota_pricing_failover Test-Coverage

| Test                                          | Konzept                                                  |
|-----------------------------------------------|----------------------------------------------------------|
| `test_init_validation`                        | Pflicht-Felder + Threshold + Freshness-Range             |
| `test_initial_state_primary`                  | Initial PRIMARY mit fresh-pricing-defaults                |
| `test_route_to_primary_when_healthy`          | route() liefert primary bei Erfolg                        |
| `test_failover_when_primary_5_fails`          | Failover-Trigger bei 5 fehlgeschlagenen Bookings          |
| `test_failover_skips_unhealthy_standby`       | Failover skippt down standbys                             |
| `test_recovery_state_after_primary_returns_successful` | RECOVERING-State (no auto-promote)              |
| `test_promote_to_primary`                     | Manuelle Promotion zurueck                                |
| `test_promote_unhealthy_raises`               | promote() raises bei nicht-healthy primary                |
| `test_health_recovery_resets_fail_count`      | Successful booking reset counter                          |
| `test_freshness_per_ota_default_graduated`    | Default-Freshness-Tiers korrekt                           |
| `test_concurrent_record_outcomes_50_threads`  | 50-Thread-Stress-Test (race-free)                         |
| `test_decision_frozen_immutability`           | OTAPricingDecision ist frozen (Audit-Integritaet)         |
| `test_unknown_ota_raises`                     | record() raises bei unknown ota                           |
| `test_get_decisions_returns_immutable_tuple`  | Spec-Pflicht: tuple statt list                            |
| `test_all_down_returns_primary_fallback`      | All-Down -> primary fallback mit warning-reason           |
| `test_freshness_per_ota_override`             | Override-Mechanik wirkt korrekt                           |

## Generalisierungs-These

**These:** Bio-Pattern-Architekturen sind domain-unabhaengig. Active-Standby-Failover
funktioniert isomorph in:

- **Hotel-Domain** (Node-Failover) - Welle-19
- **KPM-Trading-Domain** (Strategy-Failover) - Welle-23
- **HeyLou-OTA-Pricing-Domain** (Pricing-Source-Failover) - **Welle-35 (this)**

Strukturkern besteht aus:

1. **State-Machine** (Enum HEALTHY/DEGRADED/DOWN + Enum PRIMARY/FAILED_OVER/RECOVERING)
2. **Frozen Decision-Record** (Audit-Trail immutable)
3. **Lock-protected Mutator-Klasse** (threading.RLock)
4. **Bio-Aequivalent** (Kollateral-Kreislauf bei Hauptarterien-Block)
5. **Domain-Schicht** (Vokabular-Mapping ohne Aenderung der Strukturlogik)

## Pattern-Lift als CRUX-Hebel

- **Q_0:** epistemische Integritaet via wiederverwendbare verified-by-test Patterns
  (Cross-Domain-Aequivalenz reduziert Sycophancy-Risk)
- **W_0:** Multiplier ~30-50x (Bio-Pattern entwickelt einmal in Welle-19, lift-bar
  in N Domains; 7. Domain in Welle-35)
- **rho-Schaetzung:** ~+50-150k EUR/J durch Architektur-Wiederverwendung statt Neuentwicklung
- **K_0:** geschuetzt durch klare Trennung Pattern-Demo vs Real-OTA-API
  (alle Test-OTAs als "test_*" markiert, kein Production-API-Call)

## Sample-Bilanz Welle-35 Phase-28

- 7. Domain: heylou_ota_pricing_failover (Hotel-Operations + Trading + OTA-Pricing)
- 18. Bio-Pattern-Lift in KMO-System
- 4. Failover-Variant (Hotel + Trading + OTA + ?)

[CRUX-MK]
