from __future__ import annotations

from typing import Any

import pytest

from df_89.patterns.m19_lateral_inhibition import LateralInhibitionNetwork


class MemoryKnowledgeStore:
    def __init__(self) -> None:
        self.methodik: list[dict[str, Any]] = []

    def add_methodik(self, name: str, description: str, confidence: float, status: str = "candidate") -> str:
        self.methodik.append({"name": name, "description": description, "confidence": confidence, "status": status})
        return name


def connected_pair(weight: float = 0.3) -> LateralInhibitionNetwork:
    network = LateralInhibitionNetwork(inhibition_weight=weight, decay_rate=0.0)
    network.add_cell("strong")
    network.add_cell("weak")
    network.connect("strong", "weak")
    return network


def test_add_cell_initializes_with_zero_activity() -> None:
    network = LateralInhibitionNetwork()
    network.add_cell("c1")
    assert network.cells["c1"].activity == 0.0
    assert network.cells["c1"].suppressed_by == set()


def test_activate_increases_activity() -> None:
    network = LateralInhibitionNetwork()
    network.add_cell("c1")
    network.activate("c1", 0.8)
    assert network.cells["c1"].activity == pytest.approx(0.8)


def test_tick_applies_lateral_inhibition() -> None:
    network = connected_pair()
    network.activate("strong", 0.9)
    network.activate("weak", 0.6)
    result = network.tick()
    assert result["strong"] == pytest.approx(0.9)
    assert result["weak"] == pytest.approx(0.33)
    assert network.cells["weak"].suppressed_by == {"strong"}


def test_tick_applies_decay() -> None:
    network = LateralInhibitionNetwork(decay_rate=0.2)
    network.add_cell("c1", initial_activity=1.0)
    first = network.tick()["c1"]
    second = network.tick()["c1"]
    assert first == pytest.approx(0.8)
    assert second == pytest.approx(0.64)


def test_winners_returns_active_cells() -> None:
    network = LateralInhibitionNetwork(activation_threshold=0.5)
    network.add_cell("c1", 0.6)
    network.add_cell("c2", 0.5)
    network.add_cell("c3", 0.9)
    assert network.winners() == ["c1", "c3"]


def test_self_inhibition_raises() -> None:
    network = LateralInhibitionNetwork()
    network.add_cell("c1")
    with pytest.raises(ValueError, match="self-inhibition"):
        network.connect("c1", "c1")


def test_zero_inhibition_weight_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        LateralInhibitionNetwork(inhibition_weight=0.0)


def test_suppression_audit_records_events() -> None:
    events: list[tuple[str, str, float]] = []
    store = MemoryKnowledgeStore()
    network = LateralInhibitionNetwork(audit_callback=lambda s, t, a: events.append((s, t, a)), knowledge_store=store)
    network.add_cell("source", 0.9)
    network.add_cell("target", 0.7)
    network.connect("source", "target", weight=0.4)
    network.tick()
    assert network.suppression_audit() == [("source", "target", pytest.approx(0.36))]
    assert events == [("source", "target", pytest.approx(0.36))]
    assert "suppressor=source" in store.methodik[0]["description"]


def test_anti_herding_prevents_concurrent_winners() -> None:
    network = LateralInhibitionNetwork(decay_rate=0.0)
    for cell_id in ("c1", "c2", "c3"):
        network.add_cell(cell_id, 0.8)
    for source in ("c1", "c2", "c3"):
        for target in ("c1", "c2", "c3"):
            if source != target:
                network.connect(source, target)
    network.tick()
    assert network.winners() == ["c1"]


def test_strong_center_weak_surround_pattern() -> None:
    network = LateralInhibitionNetwork(inhibition_weight=0.45, decay_rate=0.0)
    network.add_cell("center", 0.9)
    network.add_cell("north", 0.7)
    network.add_cell("south", 0.7)
    network.connect("center", "north", distance=1.0)
    network.connect("center", "south", distance=1.0)
    network.connect("north", "center", distance=4.0)
    network.connect("south", "center", distance=4.0)
    result = network.tick()
    assert network.winners() == ["center"]
    assert result["center"] > result["north"]
    assert result["center"] > result["south"]
