# Bio-Pattern-Lift Demo: KPM-Backpressure-Engine [CRUX-MK]

**Welle:** 27 Phase 20
**Pattern-Quelle:** `kmo_governance/backpressure_engine/backpressure_engine.py` (Welle-9, Hotel-Domain, ~801 LoC)
**Bio-Aequivalent:** Karotis-Sinus-Baroreflex (Drucksensoren -> reflexive vagale Hemmung)

## Idee

Baroreflex-Pattern (Druck-Sensoren -> reflexive Kapazitaets-Reduktion via vagale Hemmung)
wird vom Hotel-Capacity-Throttling-Domain auf KPM-Trading-Order-Flow-Throttling gehoben.
Statt Hotel-System-Last (Latenz/Queue/Errors/CPU/Memory) misst KPM die **Order-Flow-Velocity**
(orders/s, notional/min). Beim Ueberschreiten der Hard-Caps wird Order-Submission gedrosselt
(THROTTLED) oder blockiert (BLOCKED) — Trader-Aequivalent zur "vagalen Hemmung".

## Bio-Mapping (Auftrag-Tabelle)

| Hotel (`backpressure_engine`) | Trading (`kpm_backpressure_engine`) | Baroreflex |
|---|---|---|
| `event_rate` (latency/queue/etc.) | `order_rate` (orders/s) | Heart-Rate |
| `max_rate_threshold` | `max_orders_per_second` | Baroreflex-Setpoint |
| `THROTTLED`-State (capacity reduction) | `THROTTLED`-State (DELAY orders) | Vagale Hemmung |
| `BLOCKED`/REJECT-Signal | `BLOCKED`-State (REJECT orders) | Sympatho-Inhibition |

## Isomorphie-Tabelle (vollstaendig)

| Hotel (`backpressure_engine`) | Trading (`kpm_backpressure_engine`) | Baroreflex-Aequivalent |
|---|---|---|
| `PressureSignal` (frozen) | `OrderFlowSample` (frozen) | Druck-Messwert |
| `SignalType {QUEUE_DEPTH,LATENCY,...}` | n/a (vereinfacht: nur Order-Flow) | Sensor-Kanal |
| `Decision {APPLY_PRESSURE,RELEASE,HOLD}` | `FlowState {NORMAL,ELEVATED,THROTTLED,BLOCKED}` | Reflex-Tier |
| `ControllerDecision` (frozen) | `BackpressureDecision` (frozen) | Reflex-Audit-Eintrag |
| `PressureSensor.sample_all()` | `KPMBackpressureEngine.record_order()` | Druck-Sampling |
| `PressureSensor.get_aggregate_pressure()` | rolling-window rate computation | Aggregat-Druck |
| `AdaptiveCapacity.adjust(pressure)` | `KPMBackpressureEngine.evaluate(strategy_id)` | Reflex-Reaktion |
| `BackpressureController.tick()` | `evaluate()` mit Audit-Trail | Reflex-Tick |
| `QueueOverflowGuard.try_enqueue()` | `ThrottleAction {ALLOW,DELAY,REJECT}` | Submission-Gate |
| Schmitt-Trigger (high/low Hysterese) | Threshold-Mapping (elevated/blocked-pct) | Reflex-Schwelle |
| `register_source(source_id, fn)` | `register_action(state, fn)` | Custom-Reflex-Handler |
| `history()` | `get_decisions()` (immutable tuple) | Reflex-Historie |

## Domain-Spezifika (KPM, Welle-27)

| Aspekt | Hotel | Trading |
|---|---|---|
| **Sampling-Achse** | 5 Signal-Typen (Latency/Queue/Error/CPU/Memory) | 1 Signal: Order-Flow (orders/s) + Notional (currency/min) |
| **State-Achsen** | 1 (global capacity) | 2 (per-Strategy + Global) |
| **Reflex-Tier** | 3 (APPLY/RELEASE/HOLD) | 4 (NORMAL/ELEVATED/THROTTLED/BLOCKED) |
| **Submission-Gate** | QueueOverflowGuard (bool/depth) | ThrottleAction (ALLOW/DELAY/REJECT + delay_ms) |
| **Default-Hard-Caps** | base_capacity (ein Wert) | max_orders_per_second + max_notional_per_minute (zwei Werte) |
| **Schwellen** | high=0.8 / low=0.4 (Hysterese-Band) | elevated=70% / blocked=95% (Schmitt-Trigger ohne Hysterese) |
| **Beispiel-Holder** | `"queue-depth-source"`, `"cpu-source"` | `"kelly-0.4-strat"`, `"momentum-rsi-strat"` |
| **Window** | sample-list (replace-on-call) | rolling deque(maxlen=history_window=60) |
| **list_active Return** | `list[ControllerDecision]` | `tuple[BackpressureDecision, ...]` (immutable Snapshot) |

## CRUX-Bindung (Trading-spezifisch verschaerft)

- **K_0 (Familien-Kapital):** Burst-Schutz blockiert Marktorder-Kaskaden bei
  Vola-Spikes. Eine fehlerhafte Strategy kann nicht mehr Order-Flooding ausloesen,
  da BLOCKED-State automatisch REJECT zurueckliefert.
- **Q_0 (Qualitaet):** Per-Strategy + Global FlowState verhindert dass eine einzelne
  defekte Strategy alle anderen mitreisst. LONG-Strategy Burst -> nur diese Strategy
  blockiert; SHORT-Strategien laufen weiter.
- **I_min (Integritaet):** `ThrottleAction` + `BackpressureDecision` frozen + Audit-Trail
  via `get_decisions()` -> komplette Reflex-Historie unveraenderlich.
- **W_0 (Working Capital):** `deque(maxlen=N)` haelt amortisierten O(1)-Overhead auch
  bei hoher Order-Frequenz (rolling window evicted automatisch).

## Tests (17 stueck, alle passing)

1. `test_init_validation` — Pre-Conditions (max_*, history_window, threshold-pct, elevated<blocked)
2. `test_record_order_appends` — Sample-Insertion + Validation (empty strat/instrument, neg notional)
3. `test_initial_state_normal` — Default-State NORMAL + ALLOW vor jeglichem Sample
4. `test_elevated_state_at_threshold` — 8/s -> 80% pct -> ELEVATED + ALLOW (warn)
5. `test_blocked_state_at_critical` — 12/s -> 120% pct -> BLOCKED + REJECT
6. `test_throttled_state_band` — 9/s -> 90% pct (im Band 82.5-95) -> THROTTLED + DELAY
7. `test_evaluate_uses_rolling_window` — history_window=3 evicted aeltere Samples
8. `test_per_strategy_state_independence` — strat-a BLOCKED vs strat-b NORMAL gleichzeitig
9. `test_register_custom_action` — Custom-Handler ueberschreibt Default fuer FlowState
10. `test_history_window_limits` — deque(maxlen) auto-evict (100 records, nur 5 behalten)
11. `test_reset_clears` — alles auf NORMAL nach reset()
12. `test_concurrent_record_50_threads` — Barrier + 50 Threads, kein Race
13. `test_decision_frozen` — FrozenInstanceError bei BackpressureDecision-Mutation
14. `test_action_frozen` — FrozenInstanceError bei ThrottleAction + OrderFlowSample
15. `test_get_decisions_history` — immutable tuple-Return, Insertion-Order
16. `test_orderflow_sample_validation` — Pre-Conditions OrderFlowSample (alle 5 Felder)
17. `test_throttle_action_validation` — Pre-Conditions ThrottleAction (alle 4 Felder + DELAY-Spezial)

## Welle-27 Bio-Pattern-Lift-Bilanz

Welle-27 = Multi-Domain-Pattern-Lift Erweiterung. Lift 7/7 Welle-26+27. Pattern unveraendert in
Architektur-Kern (Sensor + Threshold-Mapping + Reflex-Action + Audit-Trail), nur Domain-Spezifika
angepasst:
- Single-Signal-Type (Order-Flow) statt 5 Signaltypen
- 4 Reflex-Tiers (NORMAL/ELEVATED/THROTTLED/BLOCKED) statt 3 (APPLY/RELEASE/HOLD)
- 2-Achsen-State (Per-Strategy + Global) statt 1-Achse (Global)
- Rolling-Window via deque(maxlen) statt static-list-replace
- ThrottleAction-Submission-Gate mit delay_ms statt boolean QueueOverflowGuard

## Pattern-Lift Verifikation

- [x] frozen Dataclasses (OrderFlowSample, ThrottleAction, BackpressureDecision)
- [x] threading.RLock (re-entrant lock, alle public-Methoden)
- [x] stdlib only (threading, time, dataclasses, enum, collections.deque, typing)
- [x] CRUX-MK Header + Footer in beiden Files (.py + __init__.py)
- [x] Pre/Post-Conditions in `__post_init__` der Frozen-Types
- [x] Pre-Conditions in `__init__` der Engine
- [x] Relative Imports (`from .kpm_backpressure_engine import ...`) im __init__.py
- [x] Per-Strategy + Global State (2-Achsen-Throttling)
- [x] Custom-Action-Handler via `register_action()`
- [x] Audit-Trail via `get_decisions()` (immutable tuple)

## CRUX-MK
