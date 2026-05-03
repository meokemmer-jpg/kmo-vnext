"""Tests for KMO Audit-Log [CRUX-MK]."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kmo_audit_log import AuditLog, GENESIS_HASH  # noqa: E402


@pytest.fixture
def log(tmp_path: Path) -> AuditLog:
    return AuditLog(log_path=tmp_path / "chain.jsonl")


def test_append_and_verify_empty_chain(log: AuditLog) -> None:
    """Empty chain verifies as valid."""
    assert log.verify_chain() is True


def test_single_append(log: AuditLog) -> None:
    entry = log.append("deploy", "df-86-prod", "martin", "nonce-abc")
    assert entry.block_index == 0
    assert entry.prev_hash == GENESIS_HASH
    assert log.verify_chain() is True


def test_multiple_appends_chain_correctly(log: AuditLog) -> None:
    e1 = log.append("deploy", "df-86-prod", "martin", "nonce-1")
    e2 = log.append("rollback", "df-86-prod", "gerdi", "nonce-2")
    e3 = log.append("deploy", "df-87-prod", "martin", "nonce-3")
    assert e2.prev_hash == e1.block_hash
    assert e3.prev_hash == e2.block_hash
    assert e2.block_index == 1
    assert e3.block_index == 2
    assert log.verify_chain() is True


def test_tampering_detection_content(log: AuditLog) -> None:
    """Modifying an existing entry's action breaks the chain."""
    log.append("deploy", "df-86-prod", "martin", "nonce-1")
    log.append("rollback", "df-86-prod", "gerdi", "nonce-2")
    assert log.verify_chain() is True

    # Tamper: change action of first entry
    lines = log.log_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["action"] = "TAMPERED"
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    log.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert log.verify_chain() is False


def test_tampering_detection_inserted_block(log: AuditLog) -> None:
    """Inserting a forged block (with correct hash field but wrong prev_hash) breaks chain."""
    log.append("deploy", "df-86-prod", "martin", "nonce-1")
    log.append("rollback", "df-86-prod", "gerdi", "nonce-2")

    # Insert a fake block in the middle
    lines = log.log_path.read_text(encoding="utf-8").splitlines()
    fake = {
        "block_index": 1,  # collides with real index 1
        "timestamp": 0,
        "action": "fake",
        "resource": "fake",
        "requester": "fake",
        "approver_token_nonce": "fake",
        "prev_hash": "0" * 64,
        "block_hash": "f" * 64,
    }
    lines.insert(1, json.dumps(fake, sort_keys=True, separators=(",", ":")))
    log.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert log.verify_chain() is False


def test_empty_field_rejected(log: AuditLog) -> None:
    with pytest.raises(ValueError):
        log.append("", "df-86-prod", "martin", "nonce-1")
