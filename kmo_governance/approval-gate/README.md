# KMO Approval-Gate [CRUX-MK]

Patch P-KMO-A4 — Technische Approval-Gates fuer KMO Dark-Factory Production-Resources.

## Use-Case

Vor jeder Production-Deployment-Action (DF-86 prod-Run, Drive-Sync prod, KMO-prod-Migration) ist ein signed approval token Pflicht (siehe `rules/df-akzeptanz-kriterien.md` K11-K15 + Pre-Action-Verification-Pflicht).

Komponenten:
- **`kmo_approval_gate.py`** — HMAC-signed tokens (24h TTL, single-use), 2-Stage-Identitaeten (Martin + Gerdi), deploy-locks pro Resource
- **`kmo_audit_log.py`** — Append-only hash-chain audit-log (SHA256-Kette, tamper-detection)

## Setup

```bash
# 1. Set shared secret (>= 32 random bytes)
export KMO_APPROVAL_SECRET="$(openssl rand -hex 32)"

# 2. (Optional) Configure authorized identities
mkdir -p ~/.kmo
cat > ~/.kmo/authorized_identities.yaml <<EOF
identities:
  martin: primary
  gerdi: secondary
EOF

# 3. Install deps
pip install pyyaml pytest

# 4. Run tests
cd /Users/make/Projects/dark-factories/kmo/approval-gate
python -m pytest tests/ -v
```

## Examples

### Request + Verify
```python
from kmo_approval_gate import ApprovalGate
from kmo_audit_log import AuditLog

gate = ApprovalGate()
log = AuditLog()

# Martin requests approval for DF-86 prod-deploy
token = gate.request_approval(resource="df-86-prod", action="deploy", requester="martin")

# Later: deploy-pipeline verifies before executing
if gate.verify_token(token, resource="df-86-prod", action="deploy"):
    log.append(action="deploy", resource="df-86-prod", requester="martin",
               approver_token_nonce=token[:32])
    # ... proceed with deploy
```

### Deploy-Lock
```python
if gate.acquire_deploy_lock("df-86-prod", holder="martin"):
    try:
        # exclusive deploy
        ...
    finally:
        gate.release_deploy_lock("df-86-prod", holder="martin")
```

### Audit-Chain Verify
```python
assert log.verify_chain(), "Chain tampered!"
```

## Storage

- **DB**: `~/.kmo/approval_gate.db` (SQLite, approvals + deploy_locks)
- **Audit-Log**: `branch-hub/audit/kmo-approval-chain.jsonl` (immutable hash-chain)
- **Config**: `~/.kmo/authorized_identities.yaml`

## CRUX-Bindung

- K_0: Pre-Action-Verification verhindert Mass-Destruktiv-Aktionen ohne 2-Stage-Approval
- Q_0: Audit-Chain ist tamper-evident (SHA256-link), Forensik moeglich
- I_min: SQLite + JSONL = strukturierte Persistenz
- W_0: Single-use-Tokens verhindern Replay-Attacks

## A4.2 Dual-Control (Welle-4)

Re-Re-Wargame Pre-Production-Bedingung 2 schliesst zwei Schwaechen:
1. Single-Token-Approval (ein autorisierter Nutzer reicht) -> **Dual-Control Pflicht**.
2. 3-separate-Calls (verify + lock + audit) -> **eine atomare SQLite-Transaction**.

### Beispiel-Flow

```python
from kmo_approval_gate import ApprovalGate

gate = ApprovalGate()

# Imke (requester) bittet Martin (primary) + Gerdi (secondary) um Mit-Zeichnung
dual = gate.request_dual_approval(
    resource="df-86-prod",
    action="deploy",
    requester="imke",
    primary_signer="martin",
    secondary_signer="gerdi",
)

# Atomic Pipeline: verify_dual + acquire_lock + audit_append in EINER Transaction
ok = gate.pre_deploy_atomic(dual, "df-86-prod", "deploy", holder="imke")
if ok:
    # Lock haelt 24h, beide Tokens consumed, Audit-Block geschrieben
    ...  # actual deploy
```

### Threat-Model

| Angriff | A4.1 | A4.2 |
|---------|------|------|
| Single-Identity-Compromise | Bypass moeglich | Blockiert (3-way disjoint) |
| Race-Window verify->lock | Approval-Theater moeglich | Atomic (BEGIN IMMEDIATE) |
| Audit-Append nach Lock-Fail | Inkonsistenz moeglich | Rollback alle 4 Steps |
| Token-Replay nach Lock-Acquire | Verschiebung moeglich | Tokens markiert IM TX |

**Identity-Disjointness:** `requester != primary_signer != secondary_signer != requester`. Damit ist kein 2-Personen-Bypass moeglich (Kollusion benoetigt 3 Identitaeten).

**Pre-Deploy-Audit-Event:** `action = "pre_deploy:<original_action>"` mit kombiniertem Nonce-Prefix `<primary[:16]>+<secondary[:16]>` als Forensik-Anker.

## Pending

- Cross-LLM Code-Review via W-Patch-A4-Pentagon (Welle 1 nach Implementation)
- Integration in DF-86 deploy-script + DF-Akzeptanz-Validator
- Pre-Production-Bedingung 2: **COMPLETE** (Welle-4 A4.2)
