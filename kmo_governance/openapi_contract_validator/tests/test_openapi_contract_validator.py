# [CRUX-MK]
"""OpenAPI-Contract-Validator Tests (Welle-10 Phase-6.6)."""
from __future__ import annotations

import pytest

from kmo_governance.openapi_contract_validator import (
    ContractSchema,
    ContractValidator,
    SchemaRegistry,
)


# ---------------------------------------------------------------------------
# String + Integer + Boolean Tests
# ---------------------------------------------------------------------------
def test_string_valid():
    schema = ContractSchema(schema_id="s1", type_def={"type": "string"})
    result = ContractValidator.validate("hello", schema)
    assert result.valid


def test_string_type_mismatch():
    schema = ContractSchema(schema_id="s1", type_def={"type": "string"})
    result = ContractValidator.validate(42, schema)
    assert not result.valid
    assert result.get_errors()[0].path == "$"
    assert "string" in result.get_errors()[0].expected


def test_string_minLength_violation():
    schema = ContractSchema(
        schema_id="s1",
        type_def={"type": "string", "minLength": 3},
    )
    result = ContractValidator.validate("ab", schema)
    assert not result.valid
    assert "minLength" in result.get_errors()[0].expected


def test_string_enum_valid():
    schema = ContractSchema(
        schema_id="state",
        type_def={"type": "string", "enum": ["PENDING", "CONFIRMED"]},
    )
    result = ContractValidator.validate("PENDING", schema)
    assert result.valid


def test_string_enum_violation():
    schema = ContractSchema(
        schema_id="state",
        type_def={"type": "string", "enum": ["PENDING", "CONFIRMED"]},
    )
    result = ContractValidator.validate("CHECKED_IN", schema)
    assert not result.valid


def test_integer_minimum_violation():
    schema = ContractSchema(
        schema_id="age",
        type_def={"type": "integer", "minimum": 0},
    )
    result = ContractValidator.validate(-1, schema)
    assert not result.valid


def test_integer_maximum_violation():
    schema = ContractSchema(
        schema_id="quota",
        type_def={"type": "integer", "maximum": 100},
    )
    result = ContractValidator.validate(150, schema)
    assert not result.valid


def test_boolean_type_mismatch():
    schema = ContractSchema(schema_id="b", type_def={"type": "boolean"})
    result = ContractValidator.validate("true", schema)
    assert not result.valid


# ---------------------------------------------------------------------------
# Object Tests
# ---------------------------------------------------------------------------
def test_object_valid_with_required():
    schema = ContractSchema(
        schema_id="booking",
        type_def={
            "type": "object",
            "properties": {
                "booking_id": {"type": "string"},
                "hotel_id": {"type": "string"},
                "state": {"type": "string", "enum": ["PENDING", "CONFIRMED"]},
            },
            "required": ["booking_id", "hotel_id", "state"],
        },
    )
    result = ContractValidator.validate(
        {
            "booking_id": "b-123",
            "hotel_id": "h-1",
            "state": "PENDING",
        },
        schema,
    )
    assert result.valid


def test_object_missing_required_field():
    schema = ContractSchema(
        schema_id="booking",
        type_def={
            "type": "object",
            "properties": {"booking_id": {"type": "string"}},
            "required": ["booking_id"],
        },
    )
    result = ContractValidator.validate({}, schema)
    assert not result.valid
    assert any("booking_id" in v.path for v in result.get_errors())


def test_object_nested_violation():
    schema = ContractSchema(
        schema_id="nested",
        type_def={
            "type": "object",
            "properties": {
                "inner": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            },
            "required": ["inner"],
        },
    )
    result = ContractValidator.validate({"inner": {"value": "not_int"}}, schema)
    assert not result.valid
    assert any("inner.value" in v.path for v in result.get_errors())


def test_object_additionalProperties_warning():
    schema = ContractSchema(
        schema_id="strict",
        type_def={
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    result = ContractValidator.validate({"a": "ok", "extra": "bad"}, schema)
    assert any("extra" in v.path for v in result.get_warnings())


# ---------------------------------------------------------------------------
# Array Tests
# ---------------------------------------------------------------------------
def test_array_valid():
    schema = ContractSchema(
        schema_id="items",
        type_def={"type": "array", "items": {"type": "string"}},
    )
    result = ContractValidator.validate(["a", "b", "c"], schema)
    assert result.valid


def test_array_item_type_mismatch():
    schema = ContractSchema(
        schema_id="items",
        type_def={"type": "array", "items": {"type": "integer"}},
    )
    result = ContractValidator.validate([1, 2, "three"], schema)
    assert not result.valid
    errors = result.get_errors()
    assert any("[2]" in v.path for v in errors)


def test_array_minItems_violation():
    schema = ContractSchema(
        schema_id="non_empty",
        type_def={"type": "array", "items": {"type": "string"}, "minItems": 1},
    )
    result = ContractValidator.validate([], schema)
    assert not result.valid


# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------
def test_registry_register_and_lookup():
    reg = SchemaRegistry()
    schema = ContractSchema(schema_id="user", type_def={"type": "string"})
    reg.register(schema)
    assert reg.get("user") is schema
    assert "user" in reg.list_ids()


def test_registry_unknown_schema_raises():
    reg = SchemaRegistry()
    with pytest.raises(KeyError):
        reg.validate("unknown_schema", {})


def test_registry_validate_via_id():
    reg = SchemaRegistry()
    reg.register(
        ContractSchema(
            schema_id="apaleo_booking",
            type_def={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "hotel_id": {"type": "string"},
                },
                "required": ["booking_id", "hotel_id"],
            },
        )
    )
    result = reg.validate(
        "apaleo_booking",
        {"booking_id": "b1", "hotel_id": "h1"},
    )
    assert result.valid


# ---------------------------------------------------------------------------
# Frozen-Dataclass Tests
# ---------------------------------------------------------------------------
def test_contract_violation_frozen():
    from kmo_governance.openapi_contract_validator import ContractViolation

    v = ContractViolation(path="$.x", expected="string", actual="int", severity="error")
    with pytest.raises(Exception):
        v.path = "modified"  # frozen


def test_validation_result_frozen():
    from kmo_governance.openapi_contract_validator import ValidationResult

    r = ValidationResult(valid=True, violations=(), schema_id="s")
    with pytest.raises(Exception):
        r.valid = False  # frozen


def test_schema_id_required():
    with pytest.raises(ValueError):
        ContractSchema(schema_id="", type_def={"type": "string"})
