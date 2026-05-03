"""CRUX-MK M-19: Lateral-Inhibition anti-herding pattern (Welle-11.2)."""

from __future__ import annotations

from collections.abc import Callable
import math
import time
from typing import TYPE_CHECKING

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from df_89.knowledge import KnowledgeStore

AuditCallback = Callable[[str, str, float], None]
WELLE_VERSION = "11.2-bottleneck-lift"


@dataclass(config=ConfigDict(validate_assignment=True))
class Cell:
    """Single agent/resource in lateral-inhibition network.

    Pre: non-empty id, finite activity. Post: activity is clamped to [0, 1].
    """

    cell_id: str
    activity: float
    suppressed_by: set[str] = Field(default_factory=set)
    last_update: float = 0.0

    def __post_init__(self) -> None:
        """Pre: pydantic assigned fields. Post: Cell invariants hold."""
        if not self.cell_id.strip():
            raise ValueError("cell_id must not be blank")
        self.activity = _activity(self.activity)
        if self.last_update < 0.0:
            raise ValueError("last_update must be non-negative")


class LateralInhibitionNetwork:
    """Anti-Herding via lateral inhibition.

    Connects N cells. Active cells inhibit weighted neighbors.
    Use-cases:
    - DF-Spawn-Anti-Herding (verhindert Thundering-Herd)
    - LLM-Dispatch-Anti-Cluster (gleichzeitige Codex-Calls vermeiden)
    - Resource-Allocation (zwei DFs nicht gleichzeitig auf demselben Topic)

    Pre: inhibition_weight > 0, threshold and decay in [0, 1].
    Post: ticks apply linear inhibition, decay, and suppression audit logging.
    """

    def __init__(
        self,
        inhibition_weight: float = 0.3,
        activation_threshold: float = 0.5,
        decay_rate: float = 0.1,
        knowledge_store: "KnowledgeStore | None" = None,
        audit_callback: AuditCallback | None = None,
    ):
        """Pre: numeric params are valid. Post: empty network exists."""
        if inhibition_weight <= 0.0 or not math.isfinite(inhibition_weight):
            raise ValueError("inhibition_weight must be positive")
        if not 0.0 <= activation_threshold <= 1.0:
            raise ValueError("activation_threshold must be in [0, 1]")
        if not 0.0 <= decay_rate <= 1.0:
            raise ValueError("decay_rate must be in [0, 1]")
        self.inhibition_weight = inhibition_weight
        self.activation_threshold = activation_threshold
        self.decay_rate = decay_rate
        self.knowledge_store = knowledge_store
        self.audit_callback = audit_callback
        self.cells: dict[str, Cell] = {}
        self._edges: dict[str, dict[str, float]] = {}
        self._suppression_audit: list[tuple[str, str, float]] = []

    def add_cell(self, cell_id: str, initial_activity: float = 0.0) -> None:
        """Pre: unique cell_id. Post: cell participates in network."""
        if cell_id in self.cells:
            raise ValueError(f"cell already exists: {cell_id}")
        self.cells[cell_id] = Cell(cell_id, initial_activity, last_update=time.monotonic())
        self._edges.setdefault(cell_id, {})

    def connect(self, source_id: str, target_id: str, weight: float | None = None, *, distance: float = 1.0) -> None:
        """Pre: cells exist, no self-edge. Post: directed edge is weighted.

        Strong-Center/Weak-Surround: effective_weight = weight / distance.
        """
        self._cell(source_id)
        self._cell(target_id)
        if source_id == target_id:
            raise ValueError("self-inhibition is forbidden")
        base_weight = self.inhibition_weight if weight is None else weight
        if base_weight <= 0.0 or not math.isfinite(base_weight):
            raise ValueError("edge weight must be positive")
        if distance <= 0.0 or not math.isfinite(distance):
            raise ValueError("distance must be positive")
        self._edges[source_id][target_id] = base_weight / distance

    def activate(self, cell_id: str, level: float) -> None:
        """Pre: cell exists and level is finite. Post: activity is in [0, 1]."""
        cell = self._cell(cell_id)
        cell.activity = _activity(level)
        cell.last_update = time.monotonic()

    def tick(self) -> dict[str, float]:
        """One simulation step. Apply lateral inhibition + decay.

        Pre: cells may be connected. Post: dict[cell_id, new_activity] is returned.
        Math: x_i <- x_i - sum(w_ji * x_j), then decay; ties pick one center.
        """
        previous = {cell_id: cell.activity for cell_id, cell in self.cells.items()}
        suppressions: dict[str, list[tuple[str, float]]] = {cell_id: [] for cell_id in self.cells}
        for source_id, targets in self._edges.items():
            if previous[source_id] <= self.activation_threshold:
                continue
            for target_id, weight in targets.items():
                if _dominates(source_id, target_id, previous):
                    suppressions[target_id].append((source_id, weight * previous[source_id]))

        updated = {
            cell_id: _activity((activity - sum(amount for _, amount in suppressions[cell_id])) * (1.0 - self.decay_rate))
            for cell_id, activity in previous.items()
        }
        self._guard_concurrent_winners(previous, updated)
        self._suppression_audit.clear()
        now = time.monotonic()
        for target_id, events in suppressions.items():
            self.cells[target_id].suppressed_by = {source_id for source_id, _ in events}
            for source_id, amount in events:
                self._audit(source_id, target_id, amount)
        for cell_id, activity in updated.items():
            self.cells[cell_id].activity = activity
            self.cells[cell_id].last_update = now
        return dict(updated)

    def is_active(self, cell_id: str) -> bool:
        """Pre: cell exists. Post: returns activity > activation_threshold."""
        return self._cell(cell_id).activity > self.activation_threshold

    def winners(self) -> list[str]:
        """Pre: network exists. Post: returns sorted currently active cells."""
        return sorted(cell_id for cell_id in self.cells if self.is_active(cell_id))

    def suppression_audit(self) -> list[tuple[str, str, float]]:
        """Pre: tick may have run. Post: returns suppressor/target/amount tuples."""
        return list(self._suppression_audit)

    def _guard_concurrent_winners(self, previous: dict[str, float], updated: dict[str, float]) -> None:
        active = {cell_id for cell_id, value in updated.items() if value > self.activation_threshold}
        while active:
            group = self._connected_active_group(active.pop(), active | set())
            active -= group
            if len(group) <= 1:
                continue
            center = max(group, key=lambda cell_id: (previous[cell_id], -_rank(cell_id)))
            for cell_id in group - {center}:
                updated[cell_id] = min(updated[cell_id], self.activation_threshold)

    def _connected_active_group(self, root: str, active: set[str]) -> set[str]:
        group, frontier = {root}, [root]
        while frontier:
            current = frontier.pop()
            neighbors = {target for target in self._edges.get(current, {}) if target in active}
            neighbors |= {source for source, targets in self._edges.items() if current in targets and source in active}
            for neighbor in neighbors - group:
                group.add(neighbor)
                frontier.append(neighbor)
        return group

    def _audit(self, source_id: str, target_id: str, amount: float) -> None:
        self._suppression_audit.append((source_id, target_id, amount))
        if self.audit_callback is not None:
            self.audit_callback(source_id, target_id, amount)
        if self.knowledge_store is not None:
            self.knowledge_store.add_methodik(
                name=f"m19_lateral_inhibition:{source_id}:{target_id}:{len(self._suppression_audit)}",
                description=f"suppressor={source_id}; target={target_id}; amount={amount:.6f}",
                confidence=0.79,
                status="observed",
            )

    def _cell(self, cell_id: str) -> Cell:
        if cell_id not in self.cells:
            raise KeyError(f"unknown cell: {cell_id}")
        return self.cells[cell_id]


def _activity(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("activity must be finite")
    return max(0.0, min(1.0, value))


def _dominates(source_id: str, target_id: str, values: dict[str, float]) -> bool:
    return values[source_id] > values[target_id] or (values[source_id] == values[target_id] and _rank(source_id) < _rank(target_id))


def _rank(cell_id: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(cell_id))


__all__ = ["Cell", "LateralInhibitionNetwork", "WELLE_VERSION"]
