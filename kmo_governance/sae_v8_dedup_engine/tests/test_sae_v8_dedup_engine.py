# [CRUX-MK]
"""Tests fuer SAE-v8-Dedup-Engine (Welle-42 Phase-35, DEMO-only)."""
from __future__ import annotations

import time

import pytest

from kmo_governance.sae_v8_dedup_engine import (
    SAEv8DedupEngine,
    SlotVoteDedupResult,
)


def test_init_validation() -> None:
    SAEv8DedupEngine()  # default OK
    with pytest.raises(ValueError):
        SAEv8DedupEngine(ttl_s=0)
    with pytest.raises(ValueError):
        SAEv8DedupEngine(max_active_keys=0)


def test_first_submission_not_duplicate() -> None:
    e = SAEv8DedupEngine()
    r = e.check_and_register("slot-1", "RECEPTION", b"vote-payload-x")
    assert r.is_duplicate is False
    assert r.vote_hash != ""


def test_second_identical_submission_is_duplicate() -> None:
    e = SAEv8DedupEngine()
    e.check_and_register("slot-1", "RECEPTION", b"vote-x")
    r = e.check_and_register("slot-1", "RECEPTION", b"vote-x")
    assert r.is_duplicate is True


def test_different_payload_not_duplicate() -> None:
    e = SAEv8DedupEngine()
    e.check_and_register("slot-1", "RECEPTION", b"vote-A")
    r = e.check_and_register("slot-1", "RECEPTION", b"vote-B")
    assert r.is_duplicate is False


def test_different_slot_not_duplicate() -> None:
    e = SAEv8DedupEngine()
    e.check_and_register("slot-1", "RECEPTION", b"vote-x")
    r = e.check_and_register("slot-2", "RECEPTION", b"vote-x")
    assert r.is_duplicate is False


def test_different_agent_class_not_duplicate() -> None:
    e = SAEv8DedupEngine()
    e.check_and_register("slot-1", "RECEPTION", b"vote-x")
    r = e.check_and_register("slot-1", "REVENUE_MGMT", b"vote-x")
    assert r.is_duplicate is False


def test_ttl_expiry_re_register_allowed() -> None:
    e = SAEv8DedupEngine(ttl_s=0.05)
    e.check_and_register("slot-1", "RECEPTION", b"vote-x")
    time.sleep(0.1)
    r = e.check_and_register("slot-1", "RECEPTION", b"vote-x")
    assert r.is_duplicate is False  # expired -> re-registered


def test_validation_empty_fields() -> None:
    e = SAEv8DedupEngine()
    with pytest.raises(ValueError):
        e.check_and_register("", "RECEPTION", b"x")
    with pytest.raises(ValueError):
        e.check_and_register("slot", "", b"x")


def test_validation_payload_not_bytes() -> None:
    e = SAEv8DedupEngine()
    with pytest.raises(TypeError):
        e.check_and_register("slot", "RECEPTION", "string-not-bytes")  # type: ignore[arg-type]


def test_result_frozen_immutability() -> None:
    e = SAEv8DedupEngine()
    r = e.check_and_register("slot-1", "RECEPTION", b"x")
    with pytest.raises(Exception):
        r.is_duplicate = True  # type: ignore[misc]


def test_active_keys_count_grows_then_expires() -> None:
    e = SAEv8DedupEngine(ttl_s=0.05)
    e.check_and_register("s1", "C", b"x")
    e.check_and_register("s2", "C", b"x")
    assert e.active_keys_count() == 2
    time.sleep(0.1)
    assert e.active_keys_count() == 0


def test_max_active_keys_lru_eviction() -> None:
    e = SAEv8DedupEngine(max_active_keys=2)
    e.check_and_register("s1", "C", b"x1")
    e.check_and_register("s2", "C", b"x2")
    e.check_and_register("s3", "C", b"x3")  # evicts oldest
    assert e.active_keys_count() == 2


def test_ttl_remaining_decreases() -> None:
    """ttl_remaining_s wird kleiner bei zweitem identischen Call."""
    e = SAEv8DedupEngine(ttl_s=2.0)
    e.check_and_register("s1", "C", b"x")
    time.sleep(0.05)
    r = e.check_and_register("s1", "C", b"x")
    assert r.is_duplicate is True
    assert r.ttl_remaining_s < 2.0


def test_vote_hash_deterministic_for_same_payload() -> None:
    """Same payload bytes always produce same SHA256 hash."""
    e = SAEv8DedupEngine()
    r1 = e.check_and_register("s1", "C", b"x")
    r2 = e.check_and_register("s2", "C", b"x")
    assert r1.vote_hash == r2.vote_hash  # same payload, different slots


# CRUX-MK
