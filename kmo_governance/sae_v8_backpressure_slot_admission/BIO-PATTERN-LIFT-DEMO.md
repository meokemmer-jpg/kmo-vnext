# Bio-Pattern-Lift Demo: SAE-v8 Backpressure-Slot-Admission [CRUX-MK]

**Welle:** 34 Phase 27 (Lift 16/N, 4. SAE-v8-Domain-Modul)
**Pattern-Quelle:** `kmo_governance/backpressure_engine/backpressure_engine.py` (Welle-9, Hotel-Domain, ~801 LoC)
**Bio-Aequivalent:** Karotis-Sinus-Baroreflex (Drucksensoren -> reflexive vagale Hemmung)

## Idee

Baroreflex-Pattern (Druck-Sensoren -> reflexive Kapazitaets-Reduktion via vagale Hemmung)
wird vom Hotel-Capacity-Throttling-Domain bzw. KPM-Trading-Order-Flow-Throttling auf
SAE-v8-Slot-Admission-Throttling gehoben. Statt System-Last (Hotel-Latenz/Queue) oder
Order-Flow-Velocity (Trading) misst SAE-v8 die **Slot-Admission-Velocity** (admissions/min)
pro **3 Achsen**: Global, per-AgentClass, per-Trinity-Variant.

Beispiel: Pool ist mit 65% Conservative-Variants gefuellt -> Throttle weitere
Conservative-Admissions, um Trinity-Variant-Diversitaet (Conservative/Aggressive/Contrarian)
zu erhalten. Reflex-Aequivalent zur "vagalen Hemmung" auf der Trinity-Variant-Achse.

## Bio-Mapping (Auftrag-Tabelle 3-Domain-Vergleich)

| Hotel (`backpressure_engine`) | KPM (`kpm_backpressure_engine`) | SAE-v8 (`sae_v8_backpressure_slot_admission`) | Baroreflex |
|---|---|---|---|
| `event_rate` (latency/queue/etc.) | `order_rate` (orders/s) | `admission_rate` (slots/min) | Heart-Rate |
| `THROTTLED`-State (capacity reduce) | `THROTTLED`-State (DELAY orders) | `THROTTLED`-State (DELAY slot-admission) | Vagale Hemmung |
| `BLOCKED`/REJECT-Signal | `BLOCKED`-State (REJECT orders) | `BLOCKED`-State (REJECT slot-admission, max 200 slots) | Sympatho-Inhibition |
| n/a (1-Achse global) | per-strategy (2-Achsen) | per-(agent_class+trinity_variant) (3-Achsen-Throttling) | Multi-Receptor |

## Isomorphie-Tabelle (vollstaendig, 3 Domains)

| Hotel (`backpressure_engine`) | KPM (`kpm_backpressure_engine`) | SAE-v8 (`sae_v8_backpressure_slot_admission`) | Baroreflex-Aequivalent |
|---|---|---|---|
| `PressureSignal` (frozen) | `OrderFlowSample` (frozen) | `SlotAdmissionSample` (frozen) | Druck-Messwert |
| `SignalType {QUEUE_DEPTH,LATENCY,...}` | n/a (Order-Flow) | n/a (Slot-Admission) | Sensor-Kanal |
| `Decision {APPLY,RELEASE,HOLD}` | `FlowState {NORMAL/ELEVATED/THROTTLED/BLOCKED}` | `SlotFlowState {NORMAL/ELEVATED/THROTTLED/BLOCKED}` | Reflex-Tier |
| `ControllerDecision` (frozen) | `BackpressureDecision` (frozen) | `SAESlotBackpressureDecision` (frozen) | Reflex-Audit-Eintrag |
| `PressureSensor.sample_all()` | `record_order()` | `record_admission()` | Druck-Sampling |
| `get_aggregate_pressure()` | rolling-window rate (orders/s) | rolling-window rate (admissions/min) | Aggregat-Druck |
| `AdaptiveCapacity.adjust(p)` | `evaluate(strategy_id)` | `evaluate(agent_class, trinity_variant)` | Reflex-Reaktion |
| `BackpressureController.tick()` | `evaluate()` mit Audit-Trail | `evaluate()` mit Audit-Trail | Reflex-Tick |
| `QueueOverflowGuard.try_enqueue()` | `ThrottleAction {ALLOW/DELAY/REJECT}` | `AdmissionThrottleAction {ALLOW/DELAY/REJECT}` | Submission-Gate |
| Schmitt-Trigger (high/low Hysterese) | Schmitt-Trigger (elevated/blocked-pct) | Schmitt-Trigger (elevated/blocked-pct) | Reflex-Schwelle |
| `register_source(source_id, fn)` | `register_action(state, fn)` | `register_action(state, fn)` | Custom-Reflex-Handler |
| `history()` | `get_decisions()` (immutable tuple) | `get_decisions()` (immutable tuple) | Reflex-Historie |

## Domain-Spezifika (SAE-v8, Welle-34)

| Aspekt | Hotel | KPM (Trading) | SAE-v8 |
|---|---|---|---|
| **Sampling-Achse** | 5 Signal-Typen | 1 Signal: Order-Flow (orders/s) | 1 Signal: Slot-Admission (admissions/min) |
| **State-Achsen** | 1 (global capacity) | 2 (per-Strategy + Global) | **3** (per-AgentClass + per-Trinity-Variant + Global) |
| **Reflex-Tier** | 3 (APPLY/RELEASE/HOLD) | 4 (NORMAL/ELEVATED/THROTTLED/BLOCKED) | 4 (NORMAL/ELEVATED/THROTTLED/BLOCKED) |
| **Submission-Gate** | QueueOverflowGuard (bool/depth) | ThrottleAction (ALLOW/DELAY/REJECT + delay_ms) | AdmissionThrottleAction (ALLOW/DELAY/REJECT + delay_ms) |
| **Default-Hard-Caps** | base_capacity (ein Wert) | max_orders/s + max_notional/min (zwei Werte) | max_admissions/min + max_total_slots (200, SAE-v8-Default) |
| **Schwellen** | high=0.8 / low=0.4 (Hysterese-Band) | elevated=70% / blocked=95% | elevated=70% / blocked=95% |
| **Beispiel-Holder** | `"queue-depth-source"` | `"kelly-0.4-strat"` | `"REVENUE_MANAGEMENT"+"Conservative"` |
| **Window** | sample-list (replace-on-call) | rolling deque(maxlen=60) | rolling deque(maxlen=60) |
| **Window-Unit** | per-tick | seconds (orders/s) | minutes (admissions/min) |
| **Trinity-Awareness** | n/a | n/a | **explizit: 3-Variant-Pflicht-Check** |

## SAE-v8 Trinity-Awareness (3. Achse, einzigartig)

SAE-v8 unterscheidet sich von Hotel + KPM durch die **Trinity-Variant-Achse**:

- SAE-v8 hat 200 Slots × 3 Trinity-Variants = 600 Agenten.
- Wenn z.B. 65% des Pools mit `Conservative` belegt sind, droht Variant-Imbalance.
- `evaluate(trinity_variant="Conservative")` prueft Conservative-spezifische Admission-Rate.
- BLOCKED auf Conservative-Achse -> REJECT neuer Conservative-Admissions, andere Variants
  laufen weiter.
- Q_0-Schutz: Variant-Diversitaet bleibt erhalten (Trinity-Pattern in `coding.md` §2 sakrosankt).

## CRUX-Bindung (SAE-v8-spezifisch verschaerft)

- **K_0 (Familien-Kapital):** Slot-Pool-Saturation-Schutz verhindert Agent-Spawn-Kaskaden
  bei Volatilitaets-Phasen. SAE-v8 Hard-Cap 200 Slots, BLOCKED-State automatisch REJECT.
- **Q_0 (Qualitaet):** Per-AgentClass + Per-Trinity-Variant + Global FlowState verhindert
  dass eine einzelne Variant-Klasse den Pool dominiert. Trinity-Pattern (C/A/Co) bleibt
  intakt. Eine geflutete REVENUE_MANAGEMENT-Klasse blockiert nur sich selbst, andere
  Klassen laufen weiter.
- **I_min (Integritaet):** `AdmissionThrottleAction` + `SAESlotBackpressureDecision`
  frozen + Audit-Trail via `get_decisions()` -> komplette Reflex-Historie unveraenderlich.
- **W_0 (Working Capital):** `deque(maxlen=N)` haelt amortisierten O(1)-Overhead auch
  bei hoher Admission-Frequenz (rolling window evicted automatisch). 3 separate Buffer
  (Global + per-Class + per-Variant) haben jeweils maxlen-Bound.

## Tests (17 stueck, alle passing)

1. `test_init_validation` — Pre-Conditions (max_admissions/min, max_total_slots, history_window, threshold-pct, max_decisions_history)
2. `test_record_admission_appends` — Sample-Insertion + Validation (empty class/variant/slot_id, invalid trinity_variant)
3. `test_initial_state_normal` — Default-State NORMAL + ALLOW vor jeglichem Sample
4. `test_elevated_state_at_threshold` — 48/min -> 80% pct -> ELEVATED + ALLOW (warn)
5. `test_blocked_state_at_critical` — 72/min -> 120% pct -> BLOCKED + REJECT
6. `test_evaluate_uses_rolling_window` — history_window=3 evicted aeltere Samples
7. `test_per_agent_class_isolation` — class-A BLOCKED vs class-B NORMAL gleichzeitig
8. `test_per_trinity_variant_isolation` — Conservative BLOCKED vs Aggressive NORMAL + invalid-variant Validation
9. `test_register_custom_action` — Custom-Handler ueberschreibt Default fuer SlotFlowState
10. `test_history_window_limits` — deque(maxlen) auto-evict (100 records, nur 5 behalten)
11. `test_reset_clears` — alle 3 Achsen + Decisions auf NORMAL/empty nach reset()
12. `test_concurrent_record_50_threads` — Barrier + 50 Threads x 10 Admissions = 500 evaluate-calls, kein Race
13. `test_decision_frozen` — FrozenInstanceError bei SAESlotBackpressureDecision-Mutation
14. `test_action_frozen` — FrozenInstanceError bei AdmissionThrottleAction + SlotAdmissionSample
15. `test_get_decisions_history` — immutable tuple-Return, Insertion-Order
16. `test_slot_admission_sample_validation` — Pre-Conditions SlotAdmissionSample (alle 4 Felder + invalid trinity_variant)
17. `test_admission_throttle_action_validation` — Pre-Conditions AdmissionThrottleAction (alle 4 Felder + DELAY-Spezial)

## Welle-34 Bio-Pattern-Lift-Bilanz

Welle-34 = SAE-v8-Wiring. Lift 16/N, 4. SAE-v8-Domain-Modul. Pattern unveraendert in
Architektur-Kern (Sensor + Threshold-Mapping + Reflex-Action + Audit-Trail), nur
Domain-Spezifika angepasst:
- Single-Signal-Type (Slot-Admission) statt 5 Signaltypen (Hotel) bzw. 1 (KPM-Order-Flow)
- 3-Achsen-State (Per-AgentClass + Per-Trinity-Variant + Global) statt 2-Achsen (KPM) oder 1-Achse (Hotel)
- Window-Unit Minuten statt Sekunden (Slot-Admission ist langsamer als Order-Flow)
- Trinity-Variant-Validation als Domain-spezifische Pflicht (Conservative/Aggressive/Contrarian)
- Hard-Cap max_total_slots=200 als zusaetzliche SAE-v8-Constraint

## Pattern-Lift Verifikation

- [x] frozen Dataclasses (SlotAdmissionSample, AdmissionThrottleAction, SAESlotBackpressureDecision)
- [x] threading.RLock (re-entrant lock, alle public-Methoden)
- [x] stdlib only (threading, time, dataclasses, enum, collections.deque, typing)
- [x] CRUX-MK Header + Footer in beiden Files (.py + __init__.py)
- [x] Pre/Post-Conditions in `__post_init__` der Frozen-Types
- [x] Pre-Conditions in `__init__` der Engine
- [x] Relative Imports (`from .sae_v8_backpressure_slot_admission import ...`) im __init__.py
- [x] Per-AgentClass + Per-Trinity-Variant + Global State (3-Achsen-Throttling)
- [x] Custom-Action-Handler via `register_action()`
- [x] Audit-Trail via `get_decisions()` (immutable tuple)
- [x] Trinity-Variant-Validation (Conservative/Aggressive/Contrarian, sakrosankt per `coding.md` §2)

## CRUX-MK
