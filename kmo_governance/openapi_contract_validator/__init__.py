# [CRUX-MK]
"""OpenAPI Contract Validator (Welle-10 Phase-6.6).

Adressiert Cross-LLM-V3 Finding F3 (LOW-Convergence, Codex):
Contract-Drift-Risiko zwischen Apaleo-Mock-Stack und Real-Apaleo-API.

Bio-Aequivalent: MHC-I-Selbst-Erkennung (Antigen-Presentation-Validation).
"""
from .openapi_contract_validator import (
    ContractSchema,
    ContractValidator,
    ContractViolation,
    SchemaRegistry,
    ValidationResult,
)

__all__ = [
    "ContractSchema",
    "ContractValidator",
    "ContractViolation",
    "SchemaRegistry",
    "ValidationResult",
]

# CRUX-MK
