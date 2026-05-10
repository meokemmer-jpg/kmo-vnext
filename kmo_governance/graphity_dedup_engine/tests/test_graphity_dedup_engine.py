from __future__ import annotations

import hashlib
import threading
from dataclasses import FrozenInstanceError

import pytest

from kmo_governance.graphity_dedup_engine import DEFAULT_TTL_SECONDS, GraphityDedupEngine


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_first_registration_is_not_duplicate() -> None:
    engine = GraphityDedupEngine()
    result = engine.check_and_register("a1", "topic", b"payload")

    assert result.duplicate is False
    assert result.author_id == "a1"
    assert result.manuscript_topic == "topic"


def test_second_identical_registration_is_duplicate() -> None:
    engine = GraphityDedupEngine()

    first = engine.check_and_register("a1", "topic", b"payload")
    second = engine.check_and_register("a1", "topic", b"payload")

    assert second.duplicate is True
    assert second.key == first.key
    assert second.registered_at == first.registered_at


def test_different_author_is_not_duplicate() -> None:
    engine = GraphityDedupEngine()

    engine.check_and_register("a1", "topic", b"payload")
    result = engine.check_and_register("a2", "topic", b"payload")

    assert result.duplicate is False


def test_different_topic_is_not_duplicate() -> None:
    engine = GraphityDedupEngine()

    engine.check_and_register("a1", "topic-a", b"payload")
    result = engine.check_and_register("a1", "topic-b", b"payload")

    assert result.duplicate is False


def test_different_payload_is_not_duplicate() -> None:
    engine = GraphityDedupEngine()

    engine.check_and_register("a1", "topic", b"payload-a")
    result = engine.check_and_register("a1", "topic", b"payload-b")

    assert result.duplicate is False


def test_payload_hash_is_sha256_of_payload() -> None:
    engine = GraphityDedupEngine()
    payload = b"manuscript bytes"

    result = engine.check_and_register("a1", "topic", payload)

    assert result.payload_hash == hashlib.sha256(payload).hexdigest()


def test_key_is_sha256_of_author_topic_and_payload_hash() -> None:
    engine = GraphityDedupEngine()
    result = engine.check_and_register("author", "topic", b"payload")

    expected = hashlib.sha256(
        "\x1f".join(("author", "topic", result.payload_hash)).encode("utf-8")
    ).hexdigest()

    assert result.key == expected


def test_ttl_defaults_to_604800_seconds() -> None:
    engine = GraphityDedupEngine()

    assert engine.ttl_seconds == DEFAULT_TTL_SECONDS == 604800


def test_expired_entry_can_be_registered_again() -> None:
    clock = Clock()
    engine = GraphityDedupEngine(ttl_seconds=10, time_fn=clock)

    first = engine.check_and_register("a1", "topic", b"payload")
    clock.advance(11)
    second = engine.check_and_register("a1", "topic", b"payload")

    assert second.duplicate is False
    assert second.key == first.key
    assert second.registered_at != first.registered_at


def test_sweep_expired_removes_expired_entries() -> None:
    clock = Clock()
    engine = GraphityDedupEngine(ttl_seconds=10, time_fn=clock)

    engine.check_and_register("a1", "topic", b"payload")
    clock.advance(10)

    assert engine._sweep_expired() == 1
    assert engine.active_count() == 0


def test_lru_eviction_removes_oldest_entry() -> None:
    engine = GraphityDedupEngine(max_entries=2)

    first = engine.check_and_register("a1", "topic", b"payload-1")
    engine.check_and_register("a1", "topic", b"payload-2")
    engine.check_and_register("a1", "topic", b"payload-3")

    assert first.key not in engine._entries
    assert engine.active_count() == 2


def test_lru_duplicate_access_refreshes_entry() -> None:
    engine = GraphityDedupEngine(max_entries=2)

    first = engine.check_and_register("a1", "topic", b"payload-1")
    second = engine.check_and_register("a1", "topic", b"payload-2")
    engine.check_and_register("a1", "topic", b"payload-1")
    engine.check_and_register("a1", "topic", b"payload-3")

    assert first.key in engine._entries
    assert second.key not in engine._entries


def test_str_payload_raises_type_error() -> None:
    engine = GraphityDedupEngine()

    with pytest.raises(TypeError):
        engine.check_and_register("a1", "topic", "payload")  # type: ignore[arg-type]


def test_empty_author_raises_value_error() -> None:
    engine = GraphityDedupEngine()

    with pytest.raises(ValueError):
        engine.check_and_register("", "topic", b"payload")


def test_empty_topic_raises_value_error() -> None:
    engine = GraphityDedupEngine()

    with pytest.raises(ValueError):
        engine.check_and_register("a1", " ", b"payload")


def test_empty_payload_raises_value_error() -> None:
    engine = GraphityDedupEngine()

    with pytest.raises(ValueError):
        engine.check_and_register("a1", "topic", b"")


def test_result_is_frozen() -> None:
    engine = GraphityDedupEngine()
    result = engine.check_and_register("a1", "topic", b"payload")

    with pytest.raises(FrozenInstanceError):
        result.duplicate = True  # type: ignore[misc]


def test_engine_uses_rlock() -> None:
    engine = GraphityDedupEngine()

    with engine._lock:
        assert engine.active_count() == 0


def test_concurrent_identical_registration_has_single_winner() -> None:
    engine = GraphityDedupEngine()
    results = []

    def register() -> None:
        results.append(engine.check_and_register("a1", "topic", b"payload"))

    threads = [threading.Thread(target=register) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(not result.duplicate for result in results) == 1
    assert sum(result.duplicate for result in results) == 19
    assert engine.active_count() == 1
