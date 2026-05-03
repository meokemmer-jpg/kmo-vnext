from __future__ import annotations

import pytest

from df_89.patterns.a24_sandpile import SandpileNetwork


def test_add_pile_initializes_with_zero_height() -> None:
    network = SandpileNetwork()
    network.add_pile("worker-1")
    assert network.piles["worker-1"].height == 0
    assert network.piles["worker-1"].threshold == 4


def test_add_grain_below_threshold_no_avalanche() -> None:
    network = SandpileNetwork(default_threshold=3)
    network.add_pile("queue")
    assert network.add_grain("queue", 2) == []
    assert network.piles["queue"].height == 2


def test_add_grain_at_threshold_triggers_avalanche() -> None:
    network = SandpileNetwork(default_threshold=3)
    network.add_pile("queue")
    assert network.add_grain("queue", 3) == ["queue"]
    assert network.piles["queue"].height == 0


def test_avalanche_distributes_to_neighbors() -> None:
    network = SandpileNetwork(default_threshold=2)
    for pile_id in ("source", "left", "right"):
        network.add_pile(pile_id)
    network.connect("source", "left")
    network.connect("source", "right")
    assert network.add_grain("source", 2) == ["source"]
    assert network.piles["source"].height == 0
    assert network.piles["left"].height == 1
    assert network.piles["right"].height == 1


def test_dissipation_loses_grains() -> None:
    network = SandpileNetwork(default_threshold=4, dissipation=0.5)
    for pile_id in ("source", "n1", "n2", "n3", "n4"):
        network.add_pile(pile_id)
    for target in ("n1", "n2", "n3", "n4"):
        network.connect("source", target)
    network.add_grain("source", 4)
    assert sum(pile.height for pile in network.piles.values()) == 2
    assert sorted(pile.height for pile in network.piles.values()) == [0, 0, 0, 1, 1]


def test_self_loop_raises() -> None:
    network = SandpileNetwork()
    network.add_pile("queue")
    with pytest.raises(ValueError, match="self-loop"):
        network.connect("queue", "queue")


def test_zero_threshold_raises() -> None:
    with pytest.raises(ValueError, match="default_threshold"):
        SandpileNetwork(default_threshold=0)


def test_negative_grain_raises() -> None:
    network = SandpileNetwork()
    network.add_pile("queue")
    with pytest.raises(ValueError, match="amount"):
        network.add_grain("queue", -1)


def test_avalanche_history_records_events() -> None:
    events: list[tuple[str, str, int]] = []
    network = SandpileNetwork(
        default_threshold=2,
        audit_callback=lambda event_type, pile_id, amount: events.append((event_type, pile_id, amount)),
    )
    network.add_pile("queue")
    assert network.add_grain("queue", 2) == ["queue"]
    first_history = network.avalanche_history()
    assert len(first_history) == 1
    assert first_history[0][1:] == ("queue", 1)
    assert events == [("avalanche", "queue", 1)]

    first_history.clear()
    network.add_grain("queue", 2)
    assert len(network.avalanche_history()) == 2


def test_power_law_returns_none_when_insufficient_data() -> None:
    network = SandpileNetwork(default_threshold=2)
    network.add_pile("queue")

    assert network.measure_power_law() is None
    network.add_grain("queue", 2)
    network.add_grain("queue", 2)
    assert len(network.avalanche_history()) == 2
    assert network.measure_power_law() is None


def test_power_law_emerges_after_many_grains() -> None:
    network = SandpileNetwork(default_threshold=4, dissipation=0.25)
    for pile_id in ("center", "north", "south", "east", "west", "sink"):
        network.add_pile(pile_id)
    for target in ("north", "south", "east", "west"):
        network.connect("center", target)
        network.connect(target, "sink")

    for index in range(260):
        network.add_grain("center", (index % 7) + 1)

    assert len(network.avalanche_history()) > 50
    gradient = network.measure_power_law()
    assert gradient is not None
    assert gradient < 0.0
