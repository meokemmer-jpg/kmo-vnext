# Bio-Pattern-Lift Demo: audit_event_bus -> kpm_audit_event_bus [CRUX-MK]

**Welle-26 Phase-19 KMO-vNext Plan-V6**
**Datum:** 2026-05-08
**Status:** CONDITIONAL (Pattern-Demo, Cross-LLM-Audit pending)

## Pattern-Quelle

`kmo_governance/audit_event_bus/` (Welle-9, Hotel-Domain)

- Bio-Aequivalent: Lymphatic-System (peripher gesammelte Wahrnehmungs-Events zentral aggregiert)
- Use-Case: Hotel-Audit-Events (z.B. CHECK_IN, OVERBOOKING, COMPLAINT, REFUND)
- 16 Tests passing, ~210 LoC

## Pattern-Ziel

`kmo_governance/kpm_audit_event_bus/` (Welle-26 Phase-19, Trading-Domain)

- Use-Case: KPM-Trading-Audit-Trail (BUY/SELL/CANCEL/PARTIAL_FILL/REJECT/ADJUSTMENT)
- 17 Tests passing, ~290 LoC
- KPM-Domain-spezifisch: Compliance-Tag-Filterung (KYC/AML/MIFID-Best-Exec/Position-Limit/Risk-Budget/Late-Trading) + MiFID-RTS-25 Retention >= 168h

## Isomorphie-Tabelle

Die folgende Tabelle zeigt die strikte Pattern-Isomorphie. Architekturkern bleibt identisch, nur die Domaenen-Vokabular-Schicht aendert sich:

| Konzept                     | Hotel-Domain (audit_event_bus)        | Trading-Domain (kpm_audit_event_bus)         | Lymphatic-Bio-Aequivalent          |
|-----------------------------|---------------------------------------|----------------------------------------------|-------------------------------------|
| **Event-Typ-Enum**          | `AuditEventLevel`                     | `TradeEventType`                             | Antigen-Klassifikator               |
| **Event-Typ-Werte**         | INFO/WARN/ERROR/CRITICAL              | BUY/SELL/CANCEL/PARTIAL_FILL/REJECT/ADJUSTMENT | Antigen-Sorten                    |
| **Tag/Level-Marker**        | level (Schweregrad)                   | `compliance_tags` (Multi-Tag frozenset)      | MHC-Class-I/II-Marker auf Antigen   |
| **Domaenen-spez. Tags**     | (keine, level dient als Filter)       | KYC/AML/MIFID_BEST_EXEC/POSITION_LIMIT/RISK_BUDGET/LATE_TRADING | MHC-Marker-Subtyp        |
| **Origin-ID**               | `source` (z.B. "hotel-pilot-EU")      | `strategy_id` (z.B. "strat-aggressive-001")  | Antigen-Origin (Gewebe/Zelle)       |
| **Frozen-Event-Klasse**     | `AuditEvent`                          | `TradeAuditEvent`                            | Reife T-Zelle (immutable Marker)    |
| **Pflichtfelder**           | event_id, source, level, payload, ts  | event_id, strategy_id, event_type, instrument_id, quantity, price, ts, compliance_tags, metadata | -- |
| **Event-ID-Generierung**    | counter+timestamp deterministisch     | uuid4 (idempotent + verteilbar)              | T-Zell-Klon-ID                      |
| **Hauptklasse**             | `AuditEventBus`                       | `KPMAuditEventBus`                           | Lymphknoten                         |
| **Publish-Operation**       | `publish(source, level, payload)`     | `publish(strategy_id, event_type, instrument_id, quantity, price, tags, metadata)` | Antigen-Aufnahme |
| **Query-Operation**         | `query(AuditQuery)`                   | `query(strategy_id?, event_type?, since?, until?, compliance_tag?)` | Lymphknoten-Antigen-Recall |
| **Validation**              | `__post_init__` Pre-Cond              | `validate_event(event)` -> (bool, missing_tags) | MHC-Match-Check                  |
| **Stats-Snapshot**          | `count()`                             | `get_stats()` -> {total_published, total_purged, by_event_type, by_compliance_tag, current_count} | Lymphknoten-Zell-Population |
| **Retention-Cleanup**       | `prune_expired()` (TTL_s)             | `cleanup_old(now=None)` (retention_window_h) | Apoptose alter T-Zellen             |
| **Default-Retention**       | 1h (3600s)                            | 168h (MiFID-RTS-25 = 7 Tage)                 | Gedaechtnis-T-Zellen-Halbwertszeit  |
| **Max-Size-Cap**            | 10.000                                | 100.000 (Trading-Volumen hoeher)             | Lymphknoten-Kapazitaet              |
| **Synchronisation**         | `threading.RLock`                     | `threading.RLock`                            | Zellgrenzen-Kontrolle               |
| **Subscriber-Pattern**      | `subscribe/unsubscribe`               | (NICHT geliftet, da Audit-Trail-Fokus)       | Lymphozyten-Rekrutierung            |

## KPM-Domain-spezifische Erweiterungen

Drei Erweiterungen ueber die reine Pattern-Lift hinaus, die Trading-Domain-Realitaeten reflektieren:

1. **Multi-Tag-Compliance** (`compliance_tags: frozenset[ComplianceTag]`):
   - Hotel: ein `level` pro Event
   - Trading: mehrere `compliance_tags` parallel (z.B. {KYC, AML, MIFID_BEST_EXEC} fuer einen Buy-Trade)
   - Validation via `validate_event()` prueft Subset-Konformitaet gegen `compliance_required`-Set

2. **MiFID-RTS-25 Retention-Default:**
   - Hotel-Default: 1h (kurze Retention fuer Operational-Audit)
   - Trading-Default: 168h = 7 Tage (regulatorischer Mindest-Window)
   - Hardcap erhoeht: 100.000 statt 10.000 (Trading-Volumen-Wachstum)

3. **uuid4 statt Counter-ID:**
   - Hotel: `f"{source}-{int(time.time()*1000)}-{counter}"` deterministisch
   - Trading: `str(uuid.uuid4())` idempotent + Cluster-verteilbar
   - Begruendung: Trading-Worker laufen parallel auf Multi-Node-Setup, Counter-ID waere Race-Hotspot

4. **Strukturierte Pre-Conditions:**
   - Hotel: `payload` ist generisches dict
   - Trading: explizite Pflichtfelder `instrument_id`, `quantity > 0`, `price > 0`
   - Begruendung: jede Trading-Order MUSS Instrument + Menge + Preis haben (FIX-Protokoll-Kompat)

## Verifikation: beide Module bestehen aequivalente Tests

| Test-Konzept                                | Hotel-Domain Test                       | Trading-Domain Test                                  |
|---------------------------------------------|-----------------------------------------|------------------------------------------------------|
| Konstruktor-Validation                      | `test_retention_policy_validation`      | `test_init_validation`                               |
| Publish liefert Event zurueck               | `test_event_bus_publish_returns_event`  | `test_publish_creates_event`                         |
| Stats-Tracking                              | `test_event_bus_count_tracks_events`    | `test_publish_increments_stats`                      |
| Query nach Origin                           | `test_event_bus_query_by_source`        | `test_query_by_strategy_id`                          |
| Query nach Event-Typ-Filter                 | `test_event_bus_query_by_level`         | `test_query_by_event_type`                           |
| Query nach Zeit-Range                       | (implizit ueber start_ts/end_ts)        | `test_query_by_time_range`                           |
| Query nach Tag/Marker                       | `test_event_bus_query_by_payload_match` | `test_query_by_compliance_tag`                       |
| Compliance-Validation                       | (`__post_init__` Pre-Cond Tests)        | `test_validate_event_with_compliance_required`       |
| Retention-Cleanup                           | `test_event_bus_prune_expired`          | `test_cleanup_old_purges_expired`                    |
| Stats-Snapshot                              | (implizit `count()`)                    | `test_get_stats_correct_counts`                      |
| Concurrent-Stress (50 Threads)              | `test_event_bus_concurrent_publish_50_threads` | `test_concurrent_publish_50_threads`          |
| Frozen-Immutability                         | `test_audit_event_frozen`               | `test_event_frozen_immutability`                     |
| Eindeutige Event-IDs                        | (implizit ueber Counter)                | `test_event_unique_uuid`                             |
| Pre-Cond-Validation                         | `test_audit_event_invalid_source_raises` + `test_audit_event_invalid_level_type_raises` | `test_publish_invalid_quantity_raises` + `test_publish_invalid_price_raises` + `test_publish_invalid_event_type_raises` + `test_query_invalid_filter_types` |

## Falsifikations-Bedingung

Bio-Pattern-Lift ist gescheitert wenn:

- Compliance-Tag-Filterung vergroebert MiFID-RTS-25-Audit-Anforderungen (z.B. fehlende late_trading-Detection)
- Concurrent-Publish-Stress unter 1000-Worker-Last Race-Conditions zeigt
- uuid4-Kollision auftritt (theoretisch ausgeschlossen, aber Test-Verifikation in `test_event_unique_uuid`)
- Retention-Default 168h fuer MiFID-RTS-25 unzureichend (BaFin-Pruefung)

## CRUX-Bindung

- **K_0** (Kapital): geschuetzt durch Audit-Trail-Vollstaendigkeit (Trading-Decisions
  retro-rekonstruierbar bei Verlust-Streak, BaFin-Pruefung-fest)
- **Q_0** (Qualitaet): erhoeht (jede Trade-Entscheidung mit Compliance-Tag-Provenance,
  keine "stille" Order-Ausfuehrung ohne Audit-Marker)
- **I_min** (Ordnung): strukturierte Compliance-Tag-Taxonomie (KYC/AML/MIFID/...)
- **W_0** (Working-Capital): minimal (Audit-Bus ist In-Memory + cleanup_old, keine
  externe DB-Latenz)

## Promotion-Pfad

- **v0.1.0 (jetzt, 2026-05-08):** CONDITIONAL via Welle-26 Phase-19 Lift-1/3
- **v0.2.0:** Cross-LLM-2OF3-HARDENED (Codex+Gemini+Grok adversarial-Pruefung)
- **v1.0.0:** HARDENED-PRODUCTION nach 3 Monate Shadow-Mode + realer KPM-Trade-Audit-Daten
- **NIE CLAUDE.md-Promotion** (bleibt Domain-Spezial-Modul)

## Cross-Reference

- Pattern-Quelle: `kmo_governance/audit_event_bus/audit_event_bus.py` (Welle-9, ~210 LoC, 16 Tests)
- Schwester-Modul: `kmo_governance/kpm_trading_failover/kpm_trading_failover.py` (Welle-23, Bio-Lift Kollateral-Kreislauf)
- Regulatorischer Anchor: MiFID-II RTS 25 (Mindest-Aufbewahrung 5 Jahre fuer Trading-Records, In-Memory-Window 168h)
- KPM-Sizing-Rule: `~/.claude/rules/kpm-sizing.md` Variante-D (Compliance-Tag POSITION_LIMIT mappt auf Kelly-Fraction-Bounds)

[CRUX-MK]
