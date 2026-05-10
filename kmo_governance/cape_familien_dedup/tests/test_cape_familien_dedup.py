# [CRUX-MK]
"""Tests fuer Cape-Familien-Dedup (Welle-46 Phase-39)."""
from __future__ import annotations

import time

import pytest

from kmo_governance.cape_familien_dedup import (
    CapeFamilienDedup,
    FamilienDecisionDedupResult,
)


def test_init_validation() -> None:
    CapeFamilienDedup()
    with pytest.raises(ValueError):
        CapeFamilienDedup(ttl_s=0)


def test_first_decision_not_duplicate() -> None:
    d = CapeFamilienDedup()
    r = d.check_and_register("martin", "cape_relocation_pacing", b"phase-2")
    assert r.is_duplicate is False


def test_repeated_decision_is_duplicate() -> None:
    d = CapeFamilienDedup()
    d.check_and_register("martin", "cape_pacing", b"x")
    r = d.check_and_register("martin", "cape_pacing", b"x")
    assert r.is_duplicate is True


def test_different_payload_not_duplicate() -> None:
    d = CapeFamilienDedup()
    d.check_and_register("martin", "cape_pacing", b"phase-2")
    r = d.check_and_register("martin", "cape_pacing", b"phase-3")
    assert r.is_duplicate is False


def test_different_topic_not_duplicate() -> None:
    d = CapeFamilienDedup()
    d.check_and_register("martin", "cape", b"x")
    r = d.check_and_register("martin", "school", b"x")
    assert r.is_duplicate is False


def test_different_member_not_duplicate() -> None:
    d = CapeFamilienDedup()
    d.check_and_register("martin", "cape", b"x")
    r = d.check_and_register("gerdi", "cape", b"x")
    assert r.is_duplicate is False


def test_ttl_expiry() -> None:
    d = CapeFamilienDedup(ttl_s=0.05)
    d.check_and_register("martin", "cape", b"x")
    time.sleep(0.1)
    r = d.check_and_register("martin", "cape", b"x")
    assert r.is_duplicate is False


def test_validation_empty_fields() -> None:
    d = CapeFamilienDedup()
    with pytest.raises(ValueError):
        d.check_and_register("", "topic", b"x")
    with pytest.raises(ValueError):
        d.check_and_register("m", "", b"x")
    with pytest.raises(TypeError):
        d.check_and_register("m", "t", "string")  # type: ignore[arg-type]


def test_active_count() -> None:
    d = CapeFamilienDedup()
    d.check_and_register("a", "t", b"x")
    d.check_and_register("b", "t", b"x")
    assert d.active_count() == 2


def test_max_active_eviction() -> None:
    d = CapeFamilienDedup(max_active=2)
    d.check_and_register("a", "t", b"x1")
    d.check_and_register("a", "t", b"x2")
    d.check_and_register("a", "t", b"x3")
    assert d.active_count() == 2


def test_result_frozen() -> None:
    d = CapeFamilienDedup()
    r = d.check_and_register("m", "t", b"x")
    with pytest.raises(Exception):
        r.is_duplicate = True  # type: ignore[misc]


# CRUX-MK
