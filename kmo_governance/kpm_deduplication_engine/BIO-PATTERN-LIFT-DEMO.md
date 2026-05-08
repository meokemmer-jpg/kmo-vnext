# Bio-Pattern-Lift Demo: kpm_deduplication_engine [CRUX-MK]

**Welle-26 Phase-19 Round-2 KMO-vNext, Lift 5/5.**
**Quelle:** `kmo_governance/deduplication_engine` (Welle-20 + W20-P2 LRU).
**Bio-Aequivalent:** B-Cell-Memory (Antigen-Hash-Memory + Halbwertszeit + Recall-Frequency-Selection).

## Pattern-Mapping

| Hotel (deduplication_engine) | Trading (kpm_deduplication_engine) | Biologie (B-Cell-Memory) |
|---|---|---|
| `event_payload` (z.B. `{event_type: "checkin", reservation_id: ...}`) | `client_order_id` + `order_payload` (z.B. `{symbol: "AAPL", side: "BUY", qty: 100}`) | Antigen-Signature (B-Cell-Receptor-Binding) |
| `event_hash` (SHA256 ueber payload) | `order_hash` (SHA256 ueber order_payload, secondary check) | Antigen-Hash (Epitop-Pattern) |
| `EventRecord.first_seen_at` | `OrderRecord.first_seen_at` (TTL-Anker, immutable) | B-Cell-Activation-Time (Memory-Cell-Geburt) |
| `EventRecord.last_access_at` (W20-P2) | `OrderRecord.last_access_at` (W20-P2) | Last-Antigen-Recall (Memory-Refresh) |
| TTL 3600s (1h) | TTL 300s (5min) | Memory-Cell-Halflife (variabel je Pathogen) |
| LRU eviction (last_access) | LRU eviction (last_access) | Recall-Frequency-Selection (oft re-aktivierte Cells survive) |
| `_default_hash` (sorted-json + sha256) | `_default_hash` (sorted-json + sha256) | Epitop-Stable-Encoding |
| `force_expire` | `force_expire` (Use-case: Order-Cancel via Broker) | Apoptose (B-Cell-Tod auf Signal) |
| `cleanup_expired` | `cleanup_expired` | Background-Memory-Pruning |
| `list_active` | `list_active` + `query_by_strategy` | Active-B-Cell-Pool-Scan |
| - | `strategy_id` (Multi-Strategy-Audit) | Antibody-Class (IgM/IgG/IgA — Kontext-Marker) |

## Domain-Adjustments (Trading vs Hotel)

### Default-TTL: 300s (5min) statt 3600s (1h)

**Begruendung:** Trading-Latenz-Profil ist enger als Hotel-Event-Stream:
- Network-Retry-Window: typisch 1-30s (HTTP-Connect/Read-Timeout-Defaults)
- Strategy-Resend-Cycle: typisch 60-180s (Re-Evaluation nach Market-Tick)
- Broker-Ack-Timeout: typisch 10-60s (FIX/OUCH-Protocol-Limits)

→ 5min deckt 99% der legitimen Re-Submission-Cases ab. Laengere TTL erhoeht
Risiko, dass eine Strategie irrtuemlich denkt "Order ist noch im Markt"
obwohl sie laengst vom Broker zurueckgewiesen + Strategy-Side-State-Reset
hat. 1h waere Stale-Order-Re-Submission-Risiko.

### Primary-Key: client_order_id (statt event_hash)

**Begruendung:** `client_order_id` ist Broker-stable Identifier — von der
Strategie generiert (z.B. UUID4 oder timestamp+strategy+seqnum) und vom
Broker als Idempotency-Token akzeptiert. Hash-basierte Dedup wuerde
fehlschlagen wenn dieselbe logische Order mit minimal abweichendem
payload (z.B. `price: 150.0` vs `price: 150.00` oder Float-Precision-Drift)
re-submitted wird. `client_order_id` ist der robuste Anker.

`order_hash` bleibt als secondary check fuer **Audit-Trail** (MiFID-RTS-25
retention): Wenn dieselbe `client_order_id` mit divergentem `order_hash`
erscheint, ist das ein **Strategy-Bug-Signal** — die Strategie versucht,
unter derselben Idempotency-Token unterschiedliche Order zu submitten.
Dedup-Engine bewahrt den **originalen** `order_hash` im `OrderRecord` auf
(immutable), sodass der Audit den Bug erkennen kann.

### Pflicht-Feld: strategy_id

**Begruendung:** Multi-Strategy-Routing in KPM (mehrere parallele
Strategien teilen sich denselben Broker-Account). `query_by_strategy()`
ermoeglicht:
- Per-Strategy Dedup-Audit (z.B. fuer Compliance-Report)
- Strategy-Specific Force-Expire-Sweep (Strategy-Restart → alle pending
  Orders dieser Strategy invalidieren)
- Strategy-Level Hit-Rate-Analyse (welche Strategy submitted am haeufigsten
  Duplikate? Hinweis auf Bug)

Hotel-Vorlage hatte kein Aequivalent — Events kommen aus heterogenen
Quellen ohne Owner-Tag.

### True-LRU statt FIFO (W20-P2 Baseline beibehalten)

**Begruendung:** Aus Hotel-Vorlage uebernommen, weiter relevant in Trading:
- Hot-Order = recent Retries (Network-Glitch → 5-10 Retries in 30s)
- Idle-Order = first_seen aber dann verworfen (Strategy hat State-Reset)

True-LRU schuetzt Hot-Orders davor, durch Idle-Orders evicted zu werden.
FIFO-by-first_seen wuerde Hot-Order droppen wenn ihr first_seen_at
zufaellig der eldest-Wert ist — selbst wenn sie gerade aktiv re-tried wird.

## Cross-LLM-Audit-Status

CONDITIONAL bis Cross-LLM-Validierung mit Codex GPT-5.5 + Gemini 2.5 Pro
post-Welle-26-Phase-19. Pflicht per `rules/cross-llm-pflicht-e3-plus.md`
(E3 — Methoden-Audit ueber KPM-Domain-Adjustments).

**Pre-Audit-Checkliste:**
- [ ] Default-TTL 300s vs alternative Werte (60s? 600s?) wargame'n
- [ ] Primary-Key-Wahl client_order_id vs Hash vs (client_order_id, hash)-Tuple
- [ ] strategy_id-Validation: case-sensitive? whitespace-strip?
- [ ] Locking: RLock vs Lock vs Lock-Free-Atomic-Dict (Performance-Profil)
- [ ] hit_count-Overflow bei Lambda > 10^9/Tag (theoretisch)

## Falsifikations-Bedingung

Pattern-Lift falsifiziert wenn:
- Default-TTL 300s empirisch zu eng (>5% legitime Re-Submissions blocked
  faelschlich) → TTL-Bands (60-1800s) statt fixer Wert
- client_order_id-Primary-Key fuehrt zu Bug-Maskierung (gleiche
  client_order_id mit divergentem payload wird stillschweigend als
  Duplikat behandelt) → Strict-Mode mit ValueError statt Idempotency
- LRU-Eviction frisst Hot-Orders wenn alle Records hoch-frequent re-tried
  (Pathological-Workload) → Adaptive-Sizing statt fixed max_entries

## CRUX-Bindung

- **K_0:** geschuetzt — Doppel-Submission = doppeltes Risiko-Capital. Dedup
  verhindert Risk-Cap-Verletzung durch Network-Retry.
- **Q_0:** geschuetzt — Strategy-Bug-Signal (gleiche client_order_id +
  abweichender Hash) wird im Audit-Trail aufbewahrt, nicht ueberschrieben.
- **I_min:** strukturierte Idempotency-Pflicht fuer alle Strategien.
- **W_0:** Working-Capital-Lock-Risk reduziert (keine duplicate Orders im
  Markt, die Margin-Reserve binden).

CRUX-MK
