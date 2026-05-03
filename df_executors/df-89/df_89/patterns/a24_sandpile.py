"""CRUX-MK A-24: Sandpile SOC backpressure pattern (Welle-11.4)."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable
import math
import time

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

AuditCallback = Callable[[str, str, int], None]
WELLE_VERSION = "11.4-bottleneck-lift"


@dataclass(config=ConfigDict(validate_assignment=True))
class Pile:
    """Single load-pile in sandpile network.

    Pre: pile_id non-blank, height >= 0, threshold > 0. Post: pile invariants hold.
    """

    pile_id: str
    height: int
    threshold: int
    last_avalanche: float = 0.0

    def __post_init__(self) -> None:
        """Pre: pydantic assigned fields. Post: Pile can participate in SOC dynamics."""
        _pile_id(self.pile_id)
        if self.height < 0:
            raise ValueError("height must be non-negative")
        _threshold(self.threshold)
        if self.last_avalanche < 0.0:
            raise ValueError("last_avalanche must be non-negative")


class SandpileNetwork:
    """Self-Organized-Criticality via avalanche-based load-balancing.

    Implements Bak-Tang-Wiesenfeld sandpile dynamics on a directed graph.
    Use-cases:
    - DF-Worker-Backpressure (overflow cascades to neighbors)
    - Bug-Triage-Self-Org (priorities avalanche through queue)
    - Crisis-Response (small disruptions common, big rare = healthy SOC)

    Pre: default_threshold > 0, dissipation in [0, 1].
    Post: append-only avalanche history is initialized.
    """

    def __init__(
        self,
        default_threshold: int = 4,
        dissipation: float = 0.0,
        audit_callback: AuditCallback | None = None,
    ):
        """Pre: threshold and dissipation valid. Post: empty sandpile graph exists."""
        _threshold(default_threshold, name="default_threshold")
        if not 0.0 <= dissipation <= 1.0:
            raise ValueError("dissipation must be in [0, 1]")
        self.default_threshold = default_threshold
        self.dissipation = dissipation
        self.audit_callback = audit_callback
        self.piles: dict[str, Pile] = {}
        self._edges: dict[str, set[str]] = {}
        self._history: list[tuple[float, str, int]] = []
        self._event_count = 0

    def add_pile(self, pile_id: str, threshold: int | None = None) -> None:
        """Pre: pile_id unique and non-blank. Post: pile starts at zero height."""
        pile_id = _pile_id(pile_id)
        if pile_id in self.piles:
            raise ValueError(f"pile already exists: {pile_id}")
        pile_threshold = self.default_threshold if threshold is None else threshold
        self.piles[pile_id] = Pile(pile_id, 0, pile_threshold)
        self._edges.setdefault(pile_id, set())

    def connect(self, source: str, target: str) -> None:
        """Pre: source != target (Self-loop verboten = Cargo-Cult). Post: edge exists."""
        source = _pile_id(source)
        target = _pile_id(target)
        if source == target:
            raise ValueError("self-loop is forbidden: Cargo-Cult-SOC")
        self._pile(source)
        self._pile(target)
        self._edges[source].add(target)

    def add_grain(self, pile_id: str, amount: int = 1) -> list[str]:
        """Add load and return toppled pile ids.

        Pre: pile exists, amount > 0.
        Post: cascading neighbors topple while height >= threshold; event is audited.
        """
        _amount(amount)
        pile = self._pile(pile_id)
        pile.height += amount
        toppled = self._stabilize(start=pile.pile_id)
        if toppled:
            now = time.monotonic()
            root = toppled[0]
            cascade_size = len(toppled)
            self._history.append((now, root, cascade_size))
            for current_id in set(toppled):
                self.piles[current_id].last_avalanche = now
            self._audit(root, cascade_size)
        return toppled

    def avalanche_history(self) -> list[tuple[float, str, int]]:
        """For audit: (timestamp, pile_id, cascade_size) tuples for SOC analysis.

        Pre: avalanches may have occurred. Post: append-only history copy is returned.
        """
        return list(self._history)

    def measure_power_law(self) -> float | None:
        """Returns gradient of log-log avalanche-size distribution.

        Healthy SOC: ~-1.5 (Bak-Tang-Wiesenfeld).
        Pre: avalanche history is append-only and may be sparse.
        Post: returns None if insufficient data (< 5 cascades or uniform sizes).
        """
        if len(self._history) < 5:
            return None
        sizes = [event[2] for event in self._history]
        if max(sizes) == min(sizes):
            return None
        counts = Counter(size for _, _, size in self._history if size > 0)
        points = [(math.log(size), math.log(count)) for size, count in sorted(counts.items())]
        mean_x = sum(x for x, _ in points) / len(points)
        mean_y = sum(y for _, y in points) / len(points)
        denominator = sum((x - mean_x) ** 2 for x, _ in points)
        if denominator == 0.0:
            return None
        return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator

    def reset(self) -> None:
        """Pre: network exists. Post: heights reset; topology and append-only history remain."""
        now = time.monotonic()
        for pile in self.piles.values():
            pile.height = 0
            pile.last_avalanche = now

    def _stabilize(self, start: str) -> list[str]:
        toppled: list[str] = []
        queue: deque[str] = deque([start])
        queued = {start}
        while queue:
            current_id = queue.popleft()
            queued.discard(current_id)
            pile = self.piles[current_id]
            while pile.height >= pile.threshold:
                pile.height -= pile.threshold
                toppled.append(current_id)
                for target_id in self._distributed_targets(current_id, pile.threshold):
                    target = self.piles[target_id]
                    target.height += 1
                    if target.height >= target.threshold and target_id not in queued:
                        queue.append(target_id)
                        queued.add(target_id)
        return toppled

    def _distributed_targets(self, pile_id: str, grains: int) -> list[str]:
        neighbors = sorted(self._edges.get(pile_id, ()))
        if not neighbors:
            return []
        kept = grains - math.floor(grains * self.dissipation)
        if kept <= 0:
            return []
        return [neighbors[index % len(neighbors)] for index in range(kept)]

    def _audit(self, pile_id: str, cascade_size: int) -> None:
        self._event_count += 1
        if self.audit_callback is not None:
            self.audit_callback("avalanche", pile_id, cascade_size)

    def _pile(self, pile_id: str) -> Pile:
        pile_id = _pile_id(pile_id)
        if pile_id not in self.piles:
            raise KeyError(f"unknown pile: {pile_id}")
        return self.piles[pile_id]


def _pile_id(value: str) -> str:
    if not value.strip():
        raise ValueError("pile_id must not be blank")
    return value


def _threshold(value: int, *, name: str = "threshold") -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _amount(value: int) -> None:
    if value <= 0:
        raise ValueError("amount must be positive")


__all__ = ["AuditCallback", "Pile", "SandpileNetwork", "WELLE_VERSION"]
