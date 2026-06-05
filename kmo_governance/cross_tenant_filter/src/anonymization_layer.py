# Anonymization-Layer (k-Anonymity k>=5) [CRUX-MK]
"""
k-Anonymity-Test (k>=5 Pflicht).

k-Anonymity: Jeder Record ist ununterscheidbar von mindestens k-1 anderen
Records bezueglich der Quasi-Identifier-Attribute.

Anti-Pattern: einzelne Records mit eindeutigen Tenant-Markern preisgeben.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


DEFAULT_K = 5


def k_anonymity_test(records: list[dict[str, Any]],
                     quasi_identifiers: list[str],
                     k: int = DEFAULT_K) -> dict[str, Any]:
    """Pruef k-Anonymity ueber records.

    Args:
        records: Liste von Records (dict).
        quasi_identifiers: Felder die fuer Eindeutigkeits-Test zaehlen.
        k: Minimum Equivalence-Class-Size (Default 5).

    Returns:
        {pass: bool, smallest_class_size: int, violating_classes: int, k: int}
    """
    if not records:
        return {"pass": True, "smallest_class_size": 0,
                "violating_classes": 0, "k": k, "n_records": 0}
    if not quasi_identifiers:
        raise ValueError("quasi_identifiers darf nicht leer sein")

    # Gruppiere records nach quasi-identifier-Tupel
    counter: Counter = Counter()
    for r in records:
        key = tuple(r.get(qi) for qi in quasi_identifiers)
        counter[key] += 1

    smallest = min(counter.values()) if counter else 0
    violating = sum(1 for c in counter.values() if c < k)

    return {
        "pass": smallest >= k,
        "smallest_class_size": smallest,
        "violating_classes": violating,
        "k": k,
        "n_records": len(records),
        "n_classes": len(counter),
    }


def anonymize_records(records: list[dict[str, Any]],
                       drop_fields: list[str] | None = None,
                       hash_fields: list[str] | None = None) -> list[dict[str, Any]]:
    """Anonymisiert Records.

    Args:
        records: Input-Records.
        drop_fields: Felder die vollstaendig entfernt werden.
        hash_fields: Felder die SHA256-gehasht werden (Pseudonymisierung).

    Returns:
        Anonymisierte Records (neue Liste, Original unveraendert).
    """
    import hashlib
    drop_fields = drop_fields or []
    hash_fields = hash_fields or []

    output = []
    for r in records:
        new_r = {}
        for k, v in r.items():
            if k in drop_fields:
                continue
            if k in hash_fields:
                new_r[k] = hashlib.sha256(str(v).encode("utf-8")).hexdigest()[:16]
            else:
                new_r[k] = v
        output.append(new_r)
    return output


def generalize_field(records: list[dict[str, Any]], field_name: str,
                      generalization_fn) -> list[dict[str, Any]]:
    """Generalisierung eines Feldes (z.B. PLZ 12345 -> 12***)."""
    output = []
    for r in records:
        new_r = dict(r)
        if field_name in new_r:
            new_r[field_name] = generalization_fn(new_r[field_name])
        output.append(new_r)
    return output
