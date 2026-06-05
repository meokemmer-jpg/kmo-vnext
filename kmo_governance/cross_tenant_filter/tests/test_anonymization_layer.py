"""Anonymization-Layer Tests [CRUX-MK]."""
import pytest

from src.anonymization_layer import (
    k_anonymity_test, anonymize_records, generalize_field, DEFAULT_K,
)


def test_k_anonymity_pass_with_diverse_classes():
    records = [
        {"plz": "12345", "age_group": "30-40"} for _ in range(10)
    ]
    result = k_anonymity_test(records, ["plz", "age_group"], k=5)
    assert result["pass"] is True
    assert result["smallest_class_size"] == 10


def test_k_anonymity_fail_with_unique_records():
    records = [
        {"plz": "1234%d" % i, "age_group": "30"} for i in range(3)
    ]
    result = k_anonymity_test(records, ["plz", "age_group"], k=5)
    assert result["pass"] is False
    assert result["violating_classes"] == 3


def test_empty_records_passes():
    result = k_anonymity_test([], ["plz"], k=5)
    assert result["pass"] is True
    assert result["n_records"] == 0


def test_empty_quasi_identifiers_rejected():
    with pytest.raises(ValueError):
        k_anonymity_test([{"x": 1}], [], k=5)


def test_anonymize_drop_fields():
    records = [{"name": "Alice", "age": 30, "city": "Berlin"}]
    out = anonymize_records(records, drop_fields=["name"])
    assert "name" not in out[0]
    assert "age" in out[0]


def test_anonymize_hash_fields():
    records = [{"email": "alice@example.com", "age": 30}]
    out = anonymize_records(records, hash_fields=["email"])
    assert out[0]["email"] != "alice@example.com"
    assert len(out[0]["email"]) == 16  # truncated SHA256


def test_anonymize_does_not_mutate_original():
    records = [{"name": "Alice", "age": 30}]
    out = anonymize_records(records, drop_fields=["name"])
    assert "name" in records[0]  # original unveraendert
    assert "name" not in out[0]


def test_generalize_field():
    records = [{"plz": "12345"}, {"plz": "12399"}]
    out = generalize_field(records, "plz", lambda v: v[:2] + "***")
    assert out[0]["plz"] == "12***"
    assert out[1]["plz"] == "12***"


def test_default_k_is_5():
    assert DEFAULT_K == 5


def test_k_anonymity_violating_classes_count():
    records = [
        {"plz": "AAAAA"}, {"plz": "AAAAA"}, {"plz": "AAAAA"}, {"plz": "AAAAA"},
        {"plz": "AAAAA"},  # equivalence class size 5
        {"plz": "BBBBB"}, {"plz": "BBBBB"},  # size 2 (violating with k=5)
    ]
    result = k_anonymity_test(records, ["plz"], k=5)
    assert result["pass"] is False
    assert result["violating_classes"] == 1
    assert result["smallest_class_size"] == 2
