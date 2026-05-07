"""Tests for KMO Lease Manager [CRUX-MK].

Covers: happy-path, concurrent-acquire (race), TTL-expiry, heartbeat, STOP.flag, decorator.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

import pytest

from kmo_lease_manager import (
    DEFAULT_TTL_SEC,
    LeaseInfo,
    LeaseManager,
    ResourceType,
)
from kmo_lease_decorator import LeaseAcquireFailed, with_lease


# --------------------------- Fixtures ---------------------------------------


@pytest.fixture
def mgr(tmp_path: Path) -> LeaseManager:
    """Isolated LeaseManager per test (own SQLite + STOP-flag dir in tmp)."""
    db = tmp_path / "leases.db"
    flag_dir = tmp_path / "stop-flags"
    flag_dir.mkdir(parents=True, exist_ok=True)
    schema_src = Path(__file__).resolve().parent.parent / "schema.sql"
    return LeaseManager(db_path=db, stop_flag_dir=flag_dir, schema_path=schema_src)


# --------------------------- 1. Happy-Path ----------------------------------


def test_acquire_and_release_happy(mgr: LeaseManager) -> None:
    token = mgr.acquire(ResourceType.DF, "df-86", holder="holder-A", ttl_sec=60)
    assert token is not None and len(token) == 36  # UUID4

    info = mgr.is_locked(ResourceType.DF, "df-86")
    assert info is not None
    assert info.holder == "holder-A"
    assert info.resource_type == "DF"

    assert mgr.release(token) is True
    assert mgr.is_locked(ResourceType.DF, "df-86") is None


def test_release_unknown_token_returns_false(mgr: LeaseManager) -> None:
    assert mgr.release("non-existent-token") is False


def test_acquire_with_metadata_persists(mgr: LeaseManager) -> None:
    token = mgr.acquire(
        ResourceType.PORT,
        "8080",
        holder="webserver",
        ttl_sec=60,
        metadata={"pid": 4242, "purpose": "test"},
    )
    assert token is not None
    info = mgr.get_by_token(token)
    assert info is not None
    assert info.metadata == {"pid": 4242, "purpose": "test"}


# --------------------------- 2. Concurrent-Acquire (Race) -------------------


def test_concurrent_acquire_only_one_winner(mgr: LeaseManager) -> None:
    """N threads race on same resource: exactly one acquires, others get None."""
    n = 10
    results: List[str | None] = []
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        barrier.wait()  # synchronize start
        results.append(
            mgr.acquire(ResourceType.DF, "race-target", holder=f"holder-{i}", ttl_sec=60)
        )

    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(worker, range(n)))

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1, f"expected exactly 1 winner, got {len(winners)}"
    assert len(losers) == n - 1


def test_second_acquire_blocked_when_active(mgr: LeaseManager) -> None:
    t1 = mgr.acquire(ResourceType.DF, "df-x", holder="A", ttl_sec=60)
    t2 = mgr.acquire(ResourceType.DF, "df-x", holder="B", ttl_sec=60)
    assert t1 is not None
    assert t2 is None
    mgr.release(t1)
    t3 = mgr.acquire(ResourceType.DF, "df-x", holder="C", ttl_sec=60)
    assert t3 is not None


# --------------------------- 3. TTL-Expiry + force_release_stale ------------


def test_ttl_expiry_and_force_release_stale(mgr: LeaseManager) -> None:
    # ttl_sec=1 -> expires almost immediately
    token = mgr.acquire(ResourceType.API_TOKEN, "nlm", holder="A", ttl_sec=1)
    assert token is not None
    time.sleep(1.2)

    # is_locked treats expired-but-not-yet-cleaned as not-locked
    assert mgr.is_locked(ResourceType.API_TOKEN, "nlm") is None

    released = mgr.force_release_stale()
    assert token in released

    # Now another holder can acquire
    new_token = mgr.acquire(ResourceType.API_TOKEN, "nlm", holder="B", ttl_sec=60)
    assert new_token is not None and new_token != token


def test_acquire_auto_releases_stale_lease(mgr: LeaseManager) -> None:
    """If stale lease blocks acquire, the manager force-releases it and retries once."""
    stale_token = mgr.acquire(ResourceType.DF, "auto-release", holder="OLD", ttl_sec=1)
    assert stale_token is not None
    time.sleep(1.2)

    # New holder should succeed because acquire() auto-cleans stale
    new_token = mgr.acquire(ResourceType.DF, "auto-release", holder="NEW", ttl_sec=60)
    assert new_token is not None
    assert new_token != stale_token


# --------------------------- 4. Heartbeat-Renewal ---------------------------


def test_heartbeat_renews_ttl(mgr: LeaseManager) -> None:
    token = mgr.acquire(ResourceType.DF, "df-hb", holder="A", ttl_sec=2)
    assert token is not None
    info_before = mgr.get_by_token(token)
    assert info_before is not None
    expires_before = info_before.expires_at

    time.sleep(0.5)
    assert mgr.heartbeat(token, ttl_sec=10) is True

    info_after = mgr.get_by_token(token)
    assert info_after is not None
    assert info_after.expires_at > expires_before
    assert info_after.last_heartbeat > info_before.last_heartbeat


def test_heartbeat_unknown_token_returns_false(mgr: LeaseManager) -> None:
    assert mgr.heartbeat("does-not-exist") is False


# --------------------------- 5. STOP.flag-Respect ---------------------------


def test_stop_flag_blocks_acquire(mgr: LeaseManager) -> None:
    flag = mgr.stop_flag_dir / "STOP-df-stop.flag"
    flag.write_text("emergency stop")

    token = mgr.acquire(ResourceType.DF, "df-stop", holder="A", ttl_sec=60)
    assert token is None
    assert mgr.respect_stop_flag("df-stop") is True

    flag.unlink()
    assert mgr.respect_stop_flag("df-stop") is False
    token2 = mgr.acquire(ResourceType.DF, "df-stop", holder="A", ttl_sec=60)
    assert token2 is not None


# --------------------------- 6. Decorator-Pattern ---------------------------


def test_decorator_acquires_and_releases(mgr: LeaseManager) -> None:
    calls: List[str] = []

    @with_lease(
        manager=mgr,
        resource_type=ResourceType.DF,
        resource_id_func=lambda *a, **kw: "dec-df",
        holder_func=lambda *a, **kw: "dec-holder",
        ttl_sec=60,
        heartbeat_interval_sec=30,
    )
    def my_task() -> str:
        calls.append("ran")
        info = mgr.is_locked(ResourceType.DF, "dec-df")
        assert info is not None and info.holder == "dec-holder"
        return "ok"

    assert my_task() == "ok"
    assert calls == ["ran"]
    # Lease released after function returns
    assert mgr.is_locked(ResourceType.DF, "dec-df") is None


def test_decorator_releases_on_exception(mgr: LeaseManager) -> None:
    @with_lease(
        manager=mgr,
        resource_type=ResourceType.DF,
        resource_id_func=lambda *a, **kw: "dec-err",
        ttl_sec=60,
        heartbeat_interval_sec=30,
    )
    def boom() -> None:
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        boom()
    assert mgr.is_locked(ResourceType.DF, "dec-err") is None


def test_decorator_raises_when_busy(mgr: LeaseManager) -> None:
    busy = mgr.acquire(ResourceType.DF, "dec-busy", holder="X", ttl_sec=60)
    assert busy is not None

    @with_lease(
        manager=mgr,
        resource_type=ResourceType.DF,
        resource_id_func=lambda *a, **kw: "dec-busy",
        ttl_sec=60,
        heartbeat_interval_sec=30,
        raise_on_acquire_fail=True,
    )
    def needs_lease() -> None:
        pytest.fail("should not be called")

    with pytest.raises(LeaseAcquireFailed):
        needs_lease()


def test_decorator_returns_none_when_busy_and_no_raise(mgr: LeaseManager) -> None:
    busy = mgr.acquire(ResourceType.DF, "dec-noraise", holder="X", ttl_sec=60)
    assert busy is not None

    @with_lease(
        manager=mgr,
        resource_type=ResourceType.DF,
        resource_id_func=lambda *a, **kw: "dec-noraise",
        ttl_sec=60,
        heartbeat_interval_sec=30,
        raise_on_acquire_fail=False,
    )
    def needs_lease() -> str:
        return "should-not-run"

    assert needs_lease() is None


# --------------------------- 7. Validation / TypeErrors ---------------------


def test_acquire_rejects_invalid_resource_type(mgr: LeaseManager) -> None:
    with pytest.raises(TypeError):
        mgr.acquire("DF", "x", holder="h")  # type: ignore[arg-type]


def test_acquire_rejects_empty_strings(mgr: LeaseManager) -> None:
    with pytest.raises(ValueError):
        mgr.acquire(ResourceType.DF, "", holder="h")
    with pytest.raises(ValueError):
        mgr.acquire(ResourceType.DF, "x", holder="")


def test_acquire_rejects_zero_ttl(mgr: LeaseManager) -> None:
    with pytest.raises(ValueError):
        mgr.acquire(ResourceType.DF, "x", holder="h", ttl_sec=0)


# --------------------------- 8. Diagnostics ---------------------------------


def test_list_active_returns_only_non_expired(mgr: LeaseManager) -> None:
    long_token = mgr.acquire(ResourceType.DF, "df-long", holder="A", ttl_sec=60)
    short_token = mgr.acquire(ResourceType.PORT, "8888", holder="B", ttl_sec=1)
    assert long_token and short_token

    time.sleep(1.2)
    active = mgr.list_active()
    active_ids = {l.lease_id for l in active}
    assert long_token in active_ids
    assert short_token not in active_ids


# CRUX-MK
