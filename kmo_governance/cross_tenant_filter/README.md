# KMO Cross-Tenant-Data-Sharing-Filter [CRUX-MK]

**Welle-11-E1 Multi-Tenant-Erweiterung**

PolicyDecisionPoint + AnonymizationLayer (k>=5) fuer Cross-Tenant-Data-Sharing.

## Default-Policy

**DENY**. Sharing nur bei explicit policy match.

## Decision-Matrix

| Bedingung | Decision |
|-----------|----------|
| Same-Tenant (source==target) | ALLOW |
| Keine matching policy | DENY |
| Policy match + PUBLIC + no anon-required | ALLOW |
| Policy match + non-PUBLIC + record_count < 5 | DENY (k-Anonymity-Verletzung) |
| Policy match + non-PUBLIC + record_count >= 5 | ALLOW_WITH_ANONYMIZATION |

## k-Anonymity (k=5)

Jeder Record ist ununterscheidbar von mindestens k-1 anderen Records
bezueglich der Quasi-Identifier-Attribute.

## Anonymization-Toolkit

- `anonymize_records(drop_fields, hash_fields)` — Drop/Pseudonymize-Felder
- `generalize_field(records, field, fn)` — Generalisierung (z.B. PLZ 12345 -> 12***)
- `k_anonymity_test(records, quasi_identifiers, k=5)` — Pflicht-Pruefung

## Komponenten

- `src/data_sharing_policy.py` — PolicyDecisionPoint + SharingPolicy + 5-Sensitivity-Levels
- `src/anonymization_layer.py` — k-Anonymity-Test + Anonymize/Generalize-Funktionen

## Tests

20 Tests (Policy: 10, Anonymization: 10) — alle passing.

## CRUX-Bindung

- K_0: DIREKT GESCHUETZT (Cross-Tenant-Daten-Lecks verhindert)
- Q_0: DIREKT GESCHUETZT (k>=5 Anonymity erhaelt Privatsphaere)
- W_0: automatisierte Sharing-Decisions ohne Martin-Review pro Request
