# Bio-Pattern-Lift Demo: 3-Domain-Isomorphie [CRUX-MK]

**Welle-30 Phase-23 KMO-vNext Wild-Code-Blindtest 1/3**
**Datum:** 2026-05-08
**Status:** CONDITIONAL (Pattern-Demo, Cross-LLM-Audit pending)

## Kontext

Dieses Modul ist die **3. Domain** in einer 3-fachen Bio-Pattern-Lift-Kette
(Hotel -> Trading -> Familien-Decision-Audit). Ziel des Wild-Code-Blindtests:
belegen, dass das Lymphatic-System-Pattern domain-unabhaengig sauber liftbar ist.

## Pattern-Quelle (Welle-9, 1. Domain)

`kmo_governance/audit_event_bus/` (Hotel-Domain)

- Bio-Aequivalent: Lymphatic-System (peripher gesammelte Wahrnehmungs-Events
  zentral aggregiert)
- Use-Case: Hotel-Audit-Events (CHECK_IN, OVERBOOKING, COMPLAINT, REFUND)
- ~210 LoC, 16 Tests passing
- Retention-Default: 1h (Operational-Audit)

## 2. Lift (Welle-26 Phase-19, 2. Domain)

`kmo_governance/kpm_audit_event_bus/` (KPM-Trading-Domain)

- Use-Case: KPM-Trading-Audit-Trail (BUY/SELL/CANCEL/PARTIAL_FILL/REJECT/ADJUSTMENT)
- ~290 LoC, 17+ Tests passing
- Retention-Default: 168h (MiFID-RTS-25 Mindest-Window)
- Compliance-Tags: KYC/AML/MIFID_BEST_EXEC/POSITION_LIMIT/RISK_BUDGET/LATE_TRADING

## 3. Lift (Welle-30 Phase-23, 3. Domain -- HIER)

`kmo_governance/cape_familien_audit_bus/` (Cape-Coral-Vault Familien-Decision-Domain)

- Use-Case: Familien-Decision-Audit-Trail (Wegzug, E-2-Visa, Wegzugsteuer, Schul-Wahl,
  Brueder-Vereinbarungen, Medical-Decisions)
- ~310 LoC, 17 Tests passing
- Retention-Default: 8760h (1 Jahr GDPR-Familien-Default)
- Compliance-Tags: PERSONAL_DATA/FAMILIAL/LEGAL/FINANCIAL_K0/MEDICAL_PRIVACY/GDPR/US_RELOCATION

## 3-Domain-Isomorphie-Tabelle

Die folgende Tabelle zeigt die strikte Pattern-Isomorphie ueber 3 Domains.
Architekturkern (Lymphatic-System) bleibt identisch, nur die Domaenen-Vokabular-Schicht aendert sich.

| Konzept                | Hotel (audit_event_bus)         | KPM-Trading (kpm_audit_event_bus)             | Cape-Coral-Familien (cape_familien_audit_bus)        | Lymphatic-Bio-Aequivalent       |
|------------------------|---------------------------------|-----------------------------------------------|------------------------------------------------------|---------------------------------|
| **Bus-Klasse**         | `AuditEventBus`                 | `KPMAuditEventBus`                            | `CapeFamilienAuditBus`                               | Lymphknoten                     |
| **Event-Klasse**       | `AuditEvent`                    | `TradeAuditEvent`                             | `FamilienAuditEvent`                                 | Reife T-Zelle (immutable)       |
| **Event-Typ-Enum**     | `AuditEventLevel`               | `TradeEventType`                              | `FamilienDecisionType`                               | Antigen-Klassifikator           |
| **Event-Typ-Werte**    | INFO/WARN/ERROR/CRITICAL        | BUY/SELL/CANCEL/PARTIAL_FILL/REJECT/ADJUSTMENT | DECISION_FAMILIAL/DECISION_VISA/DECISION_TAX/DECISION_MEDICAL/DECISION_FINANCIAL/DECISION_PROCEDURAL | Antigen-Sorten |
| **Tag-Marker**         | `level` (Schweregrad)           | `compliance_tags` (Multi-Tag frozenset)       | `compliance_tags` (Multi-Tag frozenset)              | MHC-Class-I/II-Marker           |
| **Domaenen-Tags**      | (keine, level dient als Filter) | KYC/AML/MIFID_BEST_EXEC/POSITION_LIMIT/RISK_BUDGET/LATE_TRADING | PERSONAL_DATA/FAMILIAL/LEGAL/FINANCIAL_K0/MEDICAL_PRIVACY/GDPR/US_RELOCATION | MHC-Marker-Subtyp |
| **Origin-ID**          | `source` (z.B. "hotel-pilot-EU")| `strategy_id` (z.B. "strat-aggressive-001")   | `family_member_role` (z.B. "test_member_a")          | Antigen-Origin (Gewebe/Zelle)   |
| **Domaenen-Daten**     | `payload` (dict generic)        | `instrument_id` + `quantity` + `price`        | `context` (str, semantischer Decision-Kontext)       | Antigen-Spezifika               |
| **Frozen-Immutability**| `@dataclass(frozen=True)`       | `@dataclass(frozen=True)`                     | `@dataclass(frozen=True)`                            | T-Zell-Membran-Stabilitaet      |
| **Event-ID-Generation**| counter+timestamp deterministisch | `uuid.uuid4()` idempotent + cluster-verteilbar | `uuid.uuid4()` idempotent + cluster-verteilbar    | T-Zell-Klon-ID                  |
| **Publish**            | `publish(source, level, payload)` | `publish(strategy_id, event_type, instrument_id, quantity, price, tags, metadata)` | `publish(decision_type, family_member_role, context, compliance_tags, metadata)` | Antigen-Aufnahme |
| **Query**              | `query(AuditQuery)`             | `query(strategy_id?, event_type?, since?, until?, compliance_tag?)` | `query(decision_type?, family_member_role?, since?, until?, compliance_tag?)` | Lymphknoten-Recall |
| **Validation**         | `__post_init__` Pre-Cond        | `validate_event(event) -> (bool, missing)`    | `validate_event(event) -> (bool, missing)`           | MHC-Match-Check                 |
| **Stats**              | `count()`                       | `get_stats() -> dict`                         | `get_stats() -> dict` (+ by_family_member_role)      | Lymphknoten-Zell-Population     |
| **Retention-Cleanup**  | `prune_expired()` (TTL_s)       | `cleanup_old(now=None)` (retention_window_h)  | `cleanup_old(now=None)` (retention_window_h)         | Apoptose alter T-Zellen         |
| **Default-Retention**  | 1h                              | 168h (MiFID-RTS-25 = 7 Tage)                  | 8760h (1 Jahr GDPR-Familien)                         | Gedaechtnis-T-Zellen-Halbwertszeit |
| **Max-Size-Cap**       | 10.000                          | 100.000 (Trading-Volumen hoeher)              | 1.000 (Familien-Volumen geringer)                    | Lymphknoten-Kapazitaet          |
| **Synchronisation**    | `threading.RLock`               | `threading.RLock`                             | `threading.RLock`                                    | Zellgrenzen-Kontrolle           |
| **Subscriber-Pattern** | `subscribe/unsubscribe`         | (NICHT geliftet, Audit-Trail-Fokus)           | (NICHT geliftet, Audit-Trail-Fokus)                  | Lymphozyten-Rekrutierung        |

## Domain-spezifische Besonderheiten der Cape-Coral-Familien-Domain

Die folgenden Erweiterungen ueber reine Pattern-Isomorphie hinaus reflektieren
Familien-Decision-Vault-Realitaeten:

### 1. GDPR-First-Retention: 8760h (1 Jahr) als Default

- **Hotel:** 1h (kurzfristige Operational-Audit)
- **KPM:** 168h (regulatorisches MiFID-Mindest-Fenster)
- **Cape-Coral:** **8760h (1 Jahr)** -- Familien-Decisions brauchen lange
  Nachvollziehbarkeit (z.B. Wegzugsteuer-Frist erfordert 7-Jahre-Dokumentation),
  GDPR-Pflicht zur Begruendung von Datenverarbeitung ueber Familien-Vault-Lebensdauer

### 2. `by_family_member_role` Stats-Erweiterung

- Hotel/KPM tracken nur `by_event_type` + `by_compliance_tag`
- Cape-Coral fuegt `by_family_member_role` als dynamisch wachsendes Sub-Dict hinzu
- Begruendung: Familien-Vault muss pro Member-Rolle (Brueder, Eltern, Kinder, Partner)
  Decision-Volumen tracken fuer Bandbreiten-Analyse

### 3. `context: str` statt `payload: dict`

- Hotel: `payload: dict` (generisches Event-Daten-Container)
- KPM: strukturierte Felder (`instrument_id`, `quantity`, `price`)
- Cape-Coral: `context: str` (semantischer Freitext-Decision-Kontext)
- Begruendung: Familien-Decisions sind oft narrativ ("Brueder-Vereinbarung Erbe XYZ"),
  nicht strukturiert wie Trading-Orders

### 4. Q_0-PFLICHT: KEINE Real-Familien-Daten

- Subagent-Datenschutz-Invariante: alle Tests verwenden ausschliesslich dummy-Daten
  (`test_member_a`, `test_member_b`, ...) und dummy-Kontexte (`test_ctx_1`, ...)
- Real-Familien-Daten (Brueder-Namen, Adressen, Beziehungs-Details) sind
  NIE Test-Input -- diese Datenschutz-Invariante ist Q_0-Pflicht (Familien-Privacy)

### 5. `metadata: tuple-of-tuples` mit Strukturpflicht

- Cape-Coral validiert in `__post_init__` dass `metadata` ein tuple-of-tuples ist,
  jeder Eintrag eine 2-tuple `(key, value)` -- strikter als KPM (das nur tuple verlangt)
- Begruendung: Familien-Vault-Metadata MUSS strukturiert sein (key/value Provenance)
  fuer GDPR-Auskunftsrechte

## Verifikation: alle 3 Module bestehen aequivalente Tests

| Test-Konzept                          | Hotel                                | KPM-Trading                                     | Cape-Coral-Familien                                |
|---------------------------------------|--------------------------------------|--------------------------------------------------|----------------------------------------------------|
| Konstruktor-Validation                | `test_retention_policy_validation`   | `test_init_validation`                           | `test_init_validation`                             |
| Publish liefert Event zurueck         | `test_event_bus_publish_returns_event` | `test_publish_creates_event`                   | `test_publish_creates_event`                       |
| Stats-Tracking                        | `test_event_bus_count_tracks_events` | `test_publish_increments_stats`                  | `test_publish_increments_stats`                    |
| Query nach Origin                     | `test_event_bus_query_by_source`     | `test_query_by_strategy_id`                      | `test_query_by_family_member`                      |
| Query nach Event-Typ                  | `test_event_bus_query_by_level`      | `test_query_by_event_type`                       | `test_query_by_decision_type`                      |
| Query nach Zeit-Range                 | (implizit start_ts/end_ts)           | `test_query_by_time_range`                       | `test_query_by_time_range`                         |
| Query nach Tag-Marker                 | `test_event_bus_query_by_payload_match`| `test_query_by_compliance_tag`                | `test_query_by_compliance_tag`                     |
| Compliance-Validation                 | (`__post_init__` Pre-Cond)           | `test_validate_event_with_compliance_required`   | `test_validate_event_compliance_required`          |
| Retention-Cleanup                     | `test_event_bus_prune_expired`       | `test_cleanup_old_purges_expired`                | `test_cleanup_old_purges`                          |
| Stats-Snapshot                        | (implizit `count()`)                 | `test_get_stats_correct_counts`                  | `test_get_stats_correct`                           |
| Concurrent-Stress 50 Threads          | `test_event_bus_concurrent_publish_50_threads` | `test_concurrent_publish_50_threads`   | `test_concurrent_publish_50_threads`               |
| Frozen-Immutability                   | `test_audit_event_frozen`            | `test_event_frozen_immutability`                 | `test_event_frozen_immutability`                   |
| Eindeutige Event-IDs                  | (implizit Counter)                   | `test_event_unique_uuid`                         | `test_event_unique_uuid`                           |
| Pre-Cond-Validation                   | `test_audit_event_invalid_*`         | `test_publish_invalid_quantity_raises` u.a.     | `test_publish_invalid_decision_type_raises` u.a.   |

## Falsifikations-Bedingung Bio-Pattern-Lift

Lift gilt als gescheitert wenn:

- Das Pattern in der 3. Domain (Cape-Coral-Familien) erfordert architektonische Aenderungen,
  die nicht durch reine Vokabular-Schicht abdeckbar sind (z.B. neuer Aggregations-Mechanismus)
- Compliance-Tag-Filterung skaliert nicht auf 7 Tags (Cape-Coral hat 7 vs KPM 6 vs Hotel 0)
- Concurrent-Publish-Stress mit 50 Threads zeigt Race-Condition in Cape-Coral
- GDPR-Default-Retention 8760h ist regulatorisch unzureichend (BfDI/EDPB-Pruefung)
- Familien-Vokabular kollidiert mit anderen Modulen (z.B. `family_member_role` ist zu generisch)

## CRUX-Bindung

- **K_0** (Kapital): geschuetzt durch Audit-Trail-Vollstaendigkeit (Wegzugsteuer-Decisions
  retro-rekonstruierbar, IRS/BMF-Pruefungs-fest)
- **Q_0** (Qualitaet): erhoeht (jede Familien-Decision mit Compliance-Tag-Provenance,
  keine "stille" Decision ohne Audit-Marker; Q_0-Datenschutz durch dummy-Test-Daten-Pflicht)
- **I_min** (Ordnung): strukturierte Compliance-Tag-Taxonomie (PERSONAL_DATA/FAMILIAL/
  LEGAL/FINANCIAL_K0/MEDICAL_PRIVACY/GDPR/US_RELOCATION) mappt 1:1 auf
  Cape-Coral-Vault-PARA-Struktur
- **W_0** (Working-Capital): minimal (Audit-Bus ist In-Memory + cleanup_old, keine
  externe DB-Latenz; Q_0-Familien-Daten verlassen Process-Boundary nicht)

## Promotion-Pfad

- **v0.1.0 (jetzt, 2026-05-08):** CONDITIONAL via Welle-30 Phase-23 Wild-Code-Blindtest 1/3
- **v0.2.0:** Cross-LLM-2OF3-HARDENED (Codex+Gemini+Grok adversarial-Pruefung der
  3-Domain-Isomorphie)
- **v1.0.0:** HARDENED-PRODUCTION nach Cape-Coral-Vault-Realwelt-Erprobung +
  GDPR-Audit durch Datenschutzbeauftragten
- **NIE CLAUDE.md-Promotion** (bleibt Domain-Spezial-Modul, keine Verfassungs-Rang)

## Cross-Reference

- **Pattern-Quelle:** `kmo_governance/audit_event_bus/audit_event_bus.py` (Welle-9)
- **2. Lift:** `kmo_governance/kpm_audit_event_bus/kpm_audit_event_bus.py` (Welle-26 Phase-19)
- **3. Lift (HIER):** `kmo_governance/cape_familien_audit_bus/cape_familien_audit_bus.py`
- **Schwester-Module Welle-30 Wild-Code-Blindtest 2/3 + 3/3:** TBD (KMO-vNext Plan-V6)
- **Regulatorischer Anchor:** GDPR Art.5 Abs.1 lit.e (Speicherbegrenzung), Art.13/14
  (Informationspflicht), Art.30 (Verarbeitungsverzeichnis)
- **CLAUDE.md-Anchor:** §0 PRE-ACTION-VERIFICATION-PFLICHT (PocketOS-Lehre 2026-04-27)
  -- bei Familien-Vault-Operationen MUSS env_tag (dev/staging/prod) verifiziert werden

[CRUX-MK]
