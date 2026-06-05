# KMO Multi-Tenant-Approval-Gate [CRUX-MK]

**Welle-11-E1 Multi-Tenant-Erweiterung**

Approval-Gate mit Pre-Action-Check (PocketOS-Lehre + Multi-Tenant-Policy).

## Decision-Logic

| Bedingung | Decision |
|-----------|----------|
| `requires_martin_phronesis=True` | ESCALATE (Hard-No-Delegate) |
| `CROSS_TENANT_DATA_SHARING` ohne Policy | BLOCK |
| `prod + DATA_DELETION + non-reversible` | BLOCK |
| `prod + blast_radius >= 5000` | BLOCK |
| `prod + blast_radius >= 100` | ESCALATE |
| `prod + non-reversible` | ESCALATE |
| Sonst | APPROVED |

## Komponenten

- `src/approval_request.py` — ApprovalRequest dataclass + 6 OperationCategories
- `src/approval_gate.py` — pre_action_check (approve/block/escalate)

## Tests

17 Tests (Request: 7, Gate: 10) — alle passing.

## CRUX-Bindung

- K_0: DIREKT GESCHUETZT (Approval-Gate verhindert ungewollte Operationen)
- Q_0: Phronesis-Hard-No-Delegate
- W_0: Approval-Automatisierung reduziert Martin-Review auf Phronesis-Faelle
