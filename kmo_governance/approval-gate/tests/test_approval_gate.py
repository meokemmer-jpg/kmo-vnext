"""Tests for KMO Approval-Gate [CRUX-MK]."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kmo_approval_gate import ApprovalGate, ApprovalToken, DualApprovalToken  # noqa: E402
from kmo_audit_log import AuditLog  # noqa: E402

TEST_SECRET = "test-secret-do-not-use-in-prod-32bytes!!"


@pytest.fixture
def gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ApprovalGate:
    """Fresh gate per test with isolated DB+config + isolated audit-log."""
    db = tmp_path / "approvals.db"
    cfg = tmp_path / "identities.yaml"
    cfg.write_text(
        "identities:\n"
        "  martin: primary\n"
        "  gerdi: secondary\n"
        "  imke: tertiary\n"
        "  unauthorized_test: none\n",
        encoding="utf-8",
    )
    # Redirect AuditLog default path to tmp_path for test isolation
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr("kmo_audit_log.DEFAULT_LOG_PATH", audit_path)

    g = ApprovalGate(db_path=db, config_path=cfg, secret=TEST_SECRET)
    return g


def test_request_and_verify_token_happy_path(gate: ApprovalGate) -> None:
    token = gate.request_approval("df-86-prod", "deploy", "martin")
    assert gate.verify_token(token, "df-86-prod", "deploy") is True


def test_unauthorized_requester_rejected(gate: ApprovalGate) -> None:
    with pytest.raises(PermissionError):
        gate.request_approval("df-86-prod", "deploy", "stranger")


def test_double_use_prevention(gate: ApprovalGate) -> None:
    token = gate.request_approval("df-86-prod", "deploy", "martin")
    assert gate.verify_token(token, "df-86-prod", "deploy") is True
    # Second use must fail
    assert gate.verify_token(token, "df-86-prod", "deploy") is False


def test_resource_mismatch_rejected(gate: ApprovalGate) -> None:
    token = gate.request_approval("df-86-prod", "deploy", "martin")
    assert gate.verify_token(token, "df-99-prod", "deploy") is False


def test_action_mismatch_rejected(gate: ApprovalGate) -> None:
    token = gate.request_approval("df-86-prod", "deploy", "martin")
    assert gate.verify_token(token, "df-86-prod", "rollback") is False


def test_revoke_token(gate: ApprovalGate) -> None:
    token = gate.request_approval("df-86-prod", "deploy", "gerdi")
    gate.revoke_token(token)
    assert gate.verify_token(token, "df-86-prod", "deploy") is False


def test_revoke_unparseable_token_silent_noop(gate: ApprovalGate) -> None:
    # Must not raise
    gate.revoke_token("not-a-valid-token")


def test_tampered_signature_rejected(gate: ApprovalGate) -> None:
    token = gate.request_approval("df-86-prod", "deploy", "martin")
    parsed = ApprovalToken.deserialize(token)
    # Tamper signature
    tampered = ApprovalToken(
        requester=parsed.requester,
        resource=parsed.resource,
        action=parsed.action,
        issued_at=parsed.issued_at,
        expires_at=parsed.expires_at,
        nonce=parsed.nonce,
        signature="0" * 64,
    )
    assert gate.verify_token(tampered.serialize(), "df-86-prod", "deploy") is False


def test_expired_token_rejected(gate: ApprovalGate) -> None:
    """Token with expires_at in past must fail."""
    token = gate.request_approval("df-86-prod", "deploy", "martin")
    parsed = ApprovalToken.deserialize(token)
    # Manually create expired token (signed correctly but past)
    past = int(time.time()) - 3600
    expired_sig = gate._sign(  # noqa: SLF001
        parsed.requester, parsed.resource, parsed.action,
        parsed.issued_at, past, parsed.nonce,
    )
    expired = ApprovalToken(
        requester=parsed.requester,
        resource=parsed.resource,
        action=parsed.action,
        issued_at=parsed.issued_at,
        expires_at=past,
        nonce=parsed.nonce,
        signature=expired_sig,
    )
    assert gate.verify_token(expired.serialize(), "df-86-prod", "deploy") is False


def test_deploy_lock_acquire_and_release(gate: ApprovalGate) -> None:
    assert gate.acquire_deploy_lock("df-86-prod", "martin") is True
    assert gate.acquire_deploy_lock("df-86-prod", "gerdi") is False  # held
    assert gate.release_deploy_lock("df-86-prod", "martin") is True
    assert gate.acquire_deploy_lock("df-86-prod", "gerdi") is True  # now available


def test_deploy_lock_release_wrong_holder(gate: ApprovalGate) -> None:
    gate.acquire_deploy_lock("df-86-prod", "martin")
    assert gate.release_deploy_lock("df-86-prod", "wrong") is False


def test_secret_required(tmp_path: Path) -> None:
    """No ENV + no ctor secret = RuntimeError."""
    import os
    saved = os.environ.pop("KMO_APPROVAL_SECRET", None)
    try:
        with pytest.raises(RuntimeError):
            ApprovalGate(db_path=tmp_path / "x.db", config_path=tmp_path / "x.yaml")
    finally:
        if saved:
            os.environ["KMO_APPROVAL_SECRET"] = saved


# ----------------------------------------------------------------------
# A4.2 Dual-Control + Atomic Pre-Deploy (Welle-4)
# ----------------------------------------------------------------------


def test_dual_approval_happy_path(gate: ApprovalGate) -> None:
    """Three distinct identities (imke=requester, martin=primary, gerdi=secondary)."""
    dual = gate.request_dual_approval(
        resource="df-86-prod",
        action="deploy",
        requester="imke",
        primary_signer="martin",
        secondary_signer="gerdi",
    )
    assert isinstance(dual, DualApprovalToken)
    assert gate.verify_dual_token(dual, "df-86-prod", "deploy") is True


def test_dual_approval_same_identity_rejected(gate: ApprovalGate) -> None:
    """Primary == secondary signer must REJECT (not dual-control, just single)."""
    with pytest.raises(PermissionError):
        gate.request_dual_approval(
            resource="df-86-prod",
            action="deploy",
            requester="imke",
            primary_signer="martin",
            secondary_signer="martin",
        )


def test_dual_approval_requester_is_signer_rejected(gate: ApprovalGate) -> None:
    """Requester == primary_signer must REJECT (no separation-of-duties)."""
    with pytest.raises(PermissionError):
        gate.request_dual_approval(
            resource="df-86-prod",
            action="deploy",
            requester="martin",
            primary_signer="martin",
            secondary_signer="gerdi",
        )


def test_pre_deploy_atomic_happy_path(gate: ApprovalGate, tmp_path: Path) -> None:
    """All 4 steps PASS, transaction commits, lock acquired, audit appended."""
    dual = gate.request_dual_approval(
        resource="df-86-prod",
        action="deploy",
        requester="imke",
        primary_signer="martin",
        secondary_signer="gerdi",
    )
    ok = gate.pre_deploy_atomic(dual, "df-86-prod", "deploy", holder="imke")
    assert ok is True
    # Lock now held → second acquire fails
    assert gate.acquire_deploy_lock("df-86-prod", "stranger") is False
    # Tokens consumed → re-verify must fail
    assert gate.verify_dual_token(dual, "df-86-prod", "deploy") is False


def test_pre_deploy_atomic_rollback_on_lock_fail(
    gate: ApprovalGate, tmp_path: Path
) -> None:
    """Lock pre-held → atomic must ROLLBACK: tokens NOT used, audit NOT appended."""
    # Pre-hold lock under different holder
    assert gate.acquire_deploy_lock("df-86-prod", "stranger") is True

    dual = gate.request_dual_approval(
        resource="df-86-prod",
        action="deploy",
        requester="imke",
        primary_signer="martin",
        secondary_signer="gerdi",
    )
    audit_log = AuditLog()
    chain_size_before = sum(1 for _ in audit_log.log_path.read_text().splitlines() if _)

    ok = gate.pre_deploy_atomic(dual, "df-86-prod", "deploy", holder="imke")
    assert ok is False

    # Tokens MUST still be unused → verify_dual_token still True
    assert gate.verify_dual_token(dual, "df-86-prod", "deploy") is True

    # Audit-Chain MUST NOT have grown
    chain_size_after = sum(1 for _ in audit_log.log_path.read_text().splitlines() if _)
    assert chain_size_after == chain_size_before


def test_pre_deploy_atomic_rollback_on_token_invalid(
    gate: ApprovalGate, tmp_path: Path
) -> None:
    """Tampered token → atomic must ROLLBACK before lock acquired."""
    dual = gate.request_dual_approval(
        resource="df-86-prod",
        action="deploy",
        requester="imke",
        primary_signer="martin",
        secondary_signer="gerdi",
    )
    # Tamper primary signature
    bad_primary = ApprovalToken(
        requester=dual.primary.requester,
        resource=dual.primary.resource,
        action=dual.primary.action,
        issued_at=dual.primary.issued_at,
        expires_at=dual.primary.expires_at,
        nonce=dual.primary.nonce,
        signature="0" * 64,
    )
    bad_dual = DualApprovalToken(primary=bad_primary, secondary=dual.secondary, requester=dual.requester)

    ok = gate.pre_deploy_atomic(bad_dual, "df-86-prod", "deploy", holder="imke")
    assert ok is False

    # No lock → fresh acquire works
    assert gate.acquire_deploy_lock("df-86-prod", "later") is True


def test_pre_deploy_atomic_audit_chain_integrity(
    gate: ApprovalGate, tmp_path: Path
) -> None:
    """Pre-Deploy event correctly chained into hash-chain."""
    dual = gate.request_dual_approval(
        resource="df-86-prod",
        action="deploy",
        requester="imke",
        primary_signer="martin",
        secondary_signer="gerdi",
    )
    ok = gate.pre_deploy_atomic(dual, "df-86-prod", "deploy", holder="imke")
    assert ok is True

    audit_log = AuditLog()
    assert audit_log.verify_chain() is True
    # Last entry action should reflect pre-deploy:deploy
    lines = [ln for ln in audit_log.log_path.read_text().splitlines() if ln.strip()]
    assert any("pre_deploy:deploy" in ln for ln in lines)
