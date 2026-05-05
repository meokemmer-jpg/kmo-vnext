# [CRUX-MK]
"""OpenAPI-Contract-Validator (Welle-10 Phase-6.6).

Inhouse-Schema-Validator gegen OpenAPI-3.0-aehnliche Schema-Specs.
Adressiert Cross-LLM-V3-LOW-Finding F3 (Codex): Contract-Drift-Risiko.

Bio-Aequivalent: MHC-I-Antigen-Presentation. Jedes API-Response wird
vor Konsumieren auf Schema-Konformitaet geprueft (Selbst-/Fremd-Erkennung).

Klassen:
  - ContractSchema: Frozen-Spec einer API-Endpoint-Response
  - SchemaRegistry: zentrale Aggregation aller Schemas
  - ContractValidator: laeuft Schema gegen Actual-Response
  - ValidationResult: Frozen-Output mit pass/fail + Violations
  - ContractViolation: Frozen-Detail je Verletzung
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Result-Types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ContractViolation:
    """Einzelne Schema-Verletzung."""

    path: str  # JSON-path wie "$.guest_data.email"
    expected: str  # erwarteter Typ/Wert
    actual: str  # tatsaechlicher Typ/Wert
    severity: str  # "error" | "warning"


@dataclass(frozen=True)
class ValidationResult:
    """Frozen-Output eines Validation-Runs."""

    valid: bool
    violations: tuple  # tuple of ContractViolation
    schema_id: str

    def get_errors(self) -> list:
        return [v for v in self.violations if v.severity == "error"]

    def get_warnings(self) -> list:
        return [v for v in self.violations if v.severity == "warning"]


# ---------------------------------------------------------------------------
# Schema-Spec
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ContractSchema:
    """OpenAPI-3.0-aehnliche Schema-Spec.

    type_def Beispiele:
        {"type": "string"}
        {"type": "integer", "minimum": 0}
        {"type": "object", "properties": {...}, "required": [...]}
        {"type": "array", "items": {...}}
    """

    schema_id: str
    type_def: dict
    description: str = ""

    def __post_init__(self) -> None:
        if not self.schema_id:
            raise ValueError("schema_id required")
        if not isinstance(self.type_def, dict):
            raise TypeError("type_def must be dict")


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------
class ContractValidator:
    """Schema-Validator (inhouse, kein jsonschema-lib).

    Pre: schema is ContractSchema.
    Post: returns ValidationResult mit allen Violations.
    """

    @staticmethod
    def validate(value: Any, schema: ContractSchema) -> ValidationResult:
        violations = []
        ContractValidator._check(value, schema.type_def, "$", violations)
        return ValidationResult(
            valid=len(violations) == 0,
            violations=tuple(violations),
            schema_id=schema.schema_id,
        )

    @staticmethod
    def _check(value: Any, spec: dict, path: str, violations: list) -> None:
        type_name = spec.get("type")

        if type_name == "string":
            if not isinstance(value, str):
                violations.append(
                    ContractViolation(
                        path=path,
                        expected="string",
                        actual=type(value).__name__,
                        severity="error",
                    )
                )
                return
            if "minLength" in spec and len(value) < spec["minLength"]:
                violations.append(
                    ContractViolation(
                        path=path,
                        expected=f"minLength {spec['minLength']}",
                        actual=f"length {len(value)}",
                        severity="error",
                    )
                )
            if "enum" in spec and value not in spec["enum"]:
                violations.append(
                    ContractViolation(
                        path=path,
                        expected=f"one of {spec['enum']}",
                        actual=repr(value),
                        severity="error",
                    )
                )

        elif type_name == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                violations.append(
                    ContractViolation(
                        path=path,
                        expected="integer",
                        actual=type(value).__name__,
                        severity="error",
                    )
                )
                return
            if "minimum" in spec and value < spec["minimum"]:
                violations.append(
                    ContractViolation(
                        path=path,
                        expected=f"minimum {spec['minimum']}",
                        actual=str(value),
                        severity="error",
                    )
                )
            if "maximum" in spec and value > spec["maximum"]:
                violations.append(
                    ContractViolation(
                        path=path,
                        expected=f"maximum {spec['maximum']}",
                        actual=str(value),
                        severity="error",
                    )
                )

        elif type_name == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                violations.append(
                    ContractViolation(
                        path=path,
                        expected="number",
                        actual=type(value).__name__,
                        severity="error",
                    )
                )

        elif type_name == "boolean":
            if not isinstance(value, bool):
                violations.append(
                    ContractViolation(
                        path=path,
                        expected="boolean",
                        actual=type(value).__name__,
                        severity="error",
                    )
                )

        elif type_name == "object":
            if not isinstance(value, dict):
                violations.append(
                    ContractViolation(
                        path=path,
                        expected="object",
                        actual=type(value).__name__,
                        severity="error",
                    )
                )
                return
            properties = spec.get("properties", {})
            required = spec.get("required", [])
            for req_key in required:
                if req_key not in value:
                    violations.append(
                        ContractViolation(
                            path=f"{path}.{req_key}",
                            expected="present (required)",
                            actual="missing",
                            severity="error",
                        )
                    )
            for key, val in value.items():
                if key in properties:
                    ContractValidator._check(
                        val, properties[key], f"{path}.{key}", violations
                    )
                elif spec.get("additionalProperties") is False:
                    violations.append(
                        ContractViolation(
                            path=f"{path}.{key}",
                            expected="(no additional properties)",
                            actual="extra key",
                            severity="warning",
                        )
                    )

        elif type_name == "array":
            if not isinstance(value, list):
                violations.append(
                    ContractViolation(
                        path=path,
                        expected="array",
                        actual=type(value).__name__,
                        severity="error",
                    )
                )
                return
            items_spec = spec.get("items", {})
            for i, item in enumerate(value):
                ContractValidator._check(
                    item, items_spec, f"{path}[{i}]", violations
                )
            if "minItems" in spec and len(value) < spec["minItems"]:
                violations.append(
                    ContractViolation(
                        path=path,
                        expected=f"minItems {spec['minItems']}",
                        actual=f"length {len(value)}",
                        severity="error",
                    )
                )

        elif type_name == "null":
            if value is not None:
                violations.append(
                    ContractViolation(
                        path=path,
                        expected="null",
                        actual=type(value).__name__,
                        severity="error",
                    )
                )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class SchemaRegistry:
    """Zentrale Aggregation aller bekannten Schemas.

    Ermoeglicht Look-up by schema_id, plus Versions-Tracking.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, ContractSchema] = {}
        self._lock = threading.RLock()

    def register(self, schema: ContractSchema) -> None:
        with self._lock:
            self._schemas[schema.schema_id] = schema

    def get(self, schema_id: str) -> Optional[ContractSchema]:
        with self._lock:
            return self._schemas.get(schema_id)

    def list_ids(self) -> list:
        with self._lock:
            return list(self._schemas.keys())

    def validate(
        self, schema_id: str, value: Any
    ) -> ValidationResult:
        schema = self.get(schema_id)
        if schema is None:
            raise KeyError(f"schema {schema_id!r} not registered")
        return ContractValidator.validate(value, schema)


# CRUX-MK
