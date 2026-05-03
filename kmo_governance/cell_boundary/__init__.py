"""KMO Cell-Boundary Module [CRUX-MK].

KMO-vNext Phase-1 Modul 2.1 (Welle-9α). Cell-Membrane mit Resource-Quotas,
I/O-Channel-Validierung, Multi-Tenancy-Boundary, Audit-Trail, Apoptose-Hook.

Public API:
    from kmo_governance.cell_boundary import (
        CellBoundary,
        CellQuota,
        CellBoundaryManager,
        QuotaEnforcer,
        BoundaryAuditLog,
        QuotaExhaustedError,
        SchemaViolationError,
    )

Bio-Aequivalent: Lipid-Bilayer mit selektiven Channels (Aquaporine, GPCR,
Ionen-Kanaele). Active-Transport (Na/K-ATPase) als Quota-Pump-Analog.

K11-K16 + LC1-LC5 konform. Siehe README.md fuer Details.
"""

from .boundary_audit import BoundaryAuditLog, BoundaryEvent
from .cell_boundary import (
    APOPTOSE_REASON_QUOTA_EXHAUSTED,
    APOPTOSE_REASON_SCHEMA_VIOLATION,
    CellBoundary,
    CellBoundaryManager,
    CellQuota,
    QuotaExhaustedError,
    SchemaViolationError,
)
from .quota_enforcer import QuotaEnforcer

__all__ = [
    "APOPTOSE_REASON_QUOTA_EXHAUSTED",
    "APOPTOSE_REASON_SCHEMA_VIOLATION",
    "BoundaryAuditLog",
    "BoundaryEvent",
    "CellBoundary",
    "CellBoundaryManager",
    "CellQuota",
    "QuotaEnforcer",
    "QuotaExhaustedError",
    "SchemaViolationError",
]

# CRUX-MK
