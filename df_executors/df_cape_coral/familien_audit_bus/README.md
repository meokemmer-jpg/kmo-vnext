# Familien-Audit-Bus (Cape-Coral-Vault Lymphatic-Pattern) [CRUX-MK]

**Welle-30 W-30-1:** External-Generalisation des Bio-Patterns aus
`kmo_governance/outbox-pattern/` auf eine 3. Domain (Cape-Coral-Vault
Familien-Verwaltung). Adressiert Welle-12 Cross-LLM-V12 Adversarial-Note:
"Generalisierung NUR intern-validiert, kein externer Wild-Code-Blindtest."

## Bio-Pattern-Korrespondenz

```
Lymphatic-System (Original)             Familien-Audit-Bus (hier)
========================================================================
Lymphatic-Knoten                  -->   Familien-Mitglied (Filter-Node)
Antigen / Pathogen                -->   Familien-Decision
Filter-Kriterium (Antikoerper)    -->   Mitglied-spezifisch (Veto/Info/Read)
Verteilte Filterung               -->   Bus-Distribution zu allen Filtern
Sammlung in Lymphknoten           -->   JSONL-Log + Markdown-Cards
Persistierung im Gewebe           -->   Cape-Coral-Vault (PARA-Struktur)
Adaptive Antikoerperbildung       -->   custom_filter_func (K_0/Q_0-Schwellen)
```

## Pattern-Reuse aus outbox-pattern

Direkt uebernommen:
- `atomic_write_json()` (tempfile + os.replace)
- SQLite-State-Backend mit `~/Library/Application Support/`
- Sequenz-Counter pro `(machine, topic)` -> hier: `(domain)`
- Idempotenz via UUID4 (event_id -> decision_id)
- Stats-Dataclass-Pattern fuer Run-Reports

Domain-spezifisch erweitert:
- Domain-Whitelist (5 Domains: relocation/health/education/finance/relations)
- Multi-Filter-Distribution (Lymphatic statt 1:1-Producer-Consumer)
- Markdown-Rendering im Cape-Coral-Vault PARA-Stil
- Veto-Aggregation (Consent-Berechtigte koennen blocken)

## Architektur

```
                        FamilienAuditBus
                              |
              +---------------+---------------+
              |                               |
       submit_decision()              process_pending()
              |                               |
              v                               v
      bus/<domain>-<seq>-<id>.json     Lymphatic-Verteilung
              |                       (an alle relevanten Filter)
              |                               |
              |                               v
              |              FamilienDecisionFilter (pro Member)
              |                  - Martin (Veto: relocation+finance)
              |                  - Gerdi  (Veto: relocation+finance)
              |                  - Sebastian (Info: relations)
              |                  - Eltern  (Info: relations)
              |                               |
              |                               v
              |                        FilterDecision
              |                  (approve/veto/info/abstain)
              |                               |
              |                               v
              |                  FamilienAuditPersister
              |                               |
              |              +----------------+----------------+
              |              v                                 v
              |       JSONL-Append                     Markdown-Decision-Card
              |  branch-hub/audit/                    projects/cape-coral-
              |  familien-audit-log.jsonl             relocation/decision-cards/
              v                                       DC-FAM-<DOMAIN>-...md
   (Idempotency: SQLite processed_decisions
    verhindert Doppel-Verarbeitung)
```

## Files

- `familien_audit_bus.py` (~301 LOC): `FamilienAuditBus`, `FamilienDecisionEnvelope`, `atomic_write_json()`
- `familien_decision_filter.py` (~136 LOC): `FamilienDecisionFilter`, `FilterDecision`, Action-Konstanten
- `familien_audit_persister.py` (~191 LOC): `FamilienAuditPersister`, JSONL-Append + Markdown-Render
- `tests/test_familien_audit_bus.py` (~314 LOC): 15 pytest Tests (alle 12 Pflicht-Klassen + 3 Edge-Cases)

## Tests

```bash
cd /Users/make/Projects/dark-factories/kmo
python3 -m pytest df_executors/df_cape_coral/familien_audit_bus/ -q --tb=no
# Erwartung: 15 passed in <0.1s
```

## Beispiel-Verwendung

```python
from familien_audit_bus import (
    FamilienAuditBus, FamilienDecisionFilter, FamilienAuditPersister,
    FilterDecision, ACTION_VETO, ACTION_APPROVE,
    DOMAIN_RELOCATION, DOMAIN_FINANCE,
)

# 1. Bus + Persister einrichten
bus = FamilienAuditBus(
    bus_dir=Path("branch-hub/familien-bus"),
    audit_dir=Path("branch-hub/familien-audit"),
)
bus.attach_persister(FamilienAuditPersister(
    vault_root=Path("~/CapeCoral-Vault").expanduser(),
))

# 2. Filter-Nodes pro Mitglied registrieren
def gerdi_relocation_filter(envelope):
    """Gerdi vetoes wenn Cape-Coral-Move vor 2027."""
    timeline = envelope.payload.get("timeline", "")
    if "2026" in timeline:
        return FilterDecision(
            member_id="gerdi", decision_id=envelope.decision_id,
            action=ACTION_VETO,
            rationale="Familien-Stabilitaet erfordert 2027+",
        )
    return FilterDecision(
        member_id="gerdi", decision_id=envelope.decision_id,
        action=ACTION_APPROVE, rationale="Timeline akzeptabel",
    )

bus.register_filter(FamilienDecisionFilter(member_id="martin"))
bus.register_filter(FamilienDecisionFilter(
    member_id="gerdi",
    consent_domains=[DOMAIN_RELOCATION, DOMAIN_FINANCE],
    custom_filter_func=gerdi_relocation_filter,
))

# 3. Decision einreichen
envelope = bus.submit_decision(
    proposer_member_id="martin",
    domain=DOMAIN_RELOCATION,
    title="Cape-Coral-Move-2027-Q2",
    payload={"timeline": "2027-Q2", "rho_eur_per_year": 250_000},
    requires_consent=["gerdi"],
)

# 4. Pending-Decisions verarbeiten
stats = bus.process_pending()
# {'polled': 1, 'processed': 1, 'approved_count': 1, 'vetoed_count': 0, ...}
```

## Architektur-Note: Warum Lymphatic-Pattern auf Familien-Audit passt

Das Lymphatic-System hat 3 Eigenschaften die auf Familien-Decision-Audit
abbilden:

1. **Verteilte Erkennung ohne zentrale Autoritaet:** Lymphknoten erkennen
   Antigene unabhaengig voneinander. Hier: Jedes Familien-Mitglied bewertet
   eine Decision unabhaengig — kein zentraler "Familien-Manager" der alle
   Praeferenzen kennt. Das ist isomorph zu CRUX-Verfassung §0.4 E5
   FIXPUNKT-2 (Ebenen-Kollaps-Verbot: Meta-Score darf Objekt-Score nicht
   verzerren — hier: Filter-Decisions sind unabhaengig, Aggregation
   passiert erst im Bus).

2. **Adaptive Antikoerperbildung:** Lymphknoten lernen neue Pathogene durch
   wiederholte Exposition. Hier: `custom_filter_func` erlaubt
   mitglied-spezifische Schwellen die ueber Zeit angepasst werden (z.B.
   Martin's K_0-Schwelle sinkt wenn Familien-Vermoegen waechst).

3. **Persistente Memory in Lymphknoten:** Lymphatic-System speichert
   Antikoerper-Templates fuer Re-Exposition. Hier: SQLite +
   `processed_decisions` verhindert Doppelverarbeitung bei Drive-Sync-Race
   (analog Outbox-Idempotenz).

**rho-Begruendung (Cape-Coral-Domain vs Hotel-Outbox-Original):**

Hotel-Outbox-Original adressiert Cross-Machine-Sync (Mac/Windows/Mobile)
fuer Hotel-Operations — Lambda hoch (~10-100 Events/Tag), CM moderat.

Familien-Audit-Bus adressiert Cape-Coral-Relocation-Decisions —
Lambda niedriger (~1-5 Decisions/Monat), CM dafuer extrem hoch:
- 1 vermiedener Familien-Konflikt durch fehlendes Veto-Recht: rho-Schaden
  10-50k EUR (Therapie, Anwalt, Brueder-Beziehung)
- 1 falscher K_0-Vermoegens-Transfer ohne Konsens: 100-500k EUR Schaden
- 1 falscher Cape-Coral-Move-Zeitpunkt: 50-200k EUR (Wegzugssteuer + Re-Move)

Geschaetzter rho-Beitrag: **+50-150k EUR/Jahr** durch strukturierte
Veto-Rechte + persistierten Audit-Trail (analog Hotel-Outbox: K_0-Schutz
durch Atomic-Write, hier: K_0+Q_0-Schutz durch Veto-Aggregation).

## CRUX-Bindung

- **K_0:** geschuetzt — Veto-Recht der Consent-Berechtigten verhindert
  unilateral K_0-Decisions (Wegzugssteuer, Vermoegens-Transfer)
- **Q_0:** direkt zentral — Familien-Audit-Trail-Integritaet via atomic
  JSONL-Append + Markdown-Cards (rules/audit-trail.md §1 Format)
- **I_min:** strukturierte Lymphatic-Verteilung statt ad-hoc Familien-Chat
- **W_0:** Martin-Bandbreite optimiert — Filter-Logik mitglied-spezifisch,
  keine zentrale Koordinations-Last

## Cross-Reference

- **Bio-Pattern-Vorbild:** `kmo_governance/outbox-pattern/`
- **Spec:** Welle-30 W-30-1 Plan-V8 External-Generalisation
- **Cape-Coral-Vault:** CLAUDE.md `projects/cape-coral-relocation/`
- **rules/audit-trail.md §1:** JSONL-Format-Konformitaet

[CRUX-MK]
