"""KMO Sandpile-SOC Load-Redistribution [CRUX-MK].

Welle-9β Phase-2 Modul 2.2 (Sub-Pattern): Self-Organized Criticality (Bak-Tang-Wiesenfeld).
Bei Last > Z_crit: redistribuiert load/4 auf 4-Nachbar-DFs.

Bio-Aequivalent: Lastverteilung in lebenden Geweben (Druck-Gradient).
Anorg-Mapping (Welle-9.1b): A-24 Sandpile-SOC.

Lastverteilung-Math:
    if load(df) > Z_crit:
        for neighbor in 4_neighbors:
            load(neighbor) += redistribute_amount  # default load/4
        load(df) -= 4 * redistribute_amount
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .blackboard_store import BlackboardStore


DEFAULT_Z_CRIT: float = 4.0


@dataclass(frozen=True)
class AvalancheEvent:
    """Record of a single avalanche redistribution."""

    df_id: str
    load_before: float
    load_after: float
    redistributed_to: tuple
    redistribute_amount: float


class SandpileLoadDistributor:
    """4-neighbor topology load redistributor with SOC-trigger.

    Pre-Conditions:
        - topology: dict[df_id, list[neighbor_df_id, ...]] (use 4 neighbors per spec)
        - z_crit > 0
    Post-Conditions:
        - increment_load is atomic
        - on threshold-crossing: avalanche fires + load redistributes
        - cascade-avalanches detected (recursion)
    """

    def __init__(
        self,
        topology: dict[str, list[str]],
        z_crit: float = DEFAULT_Z_CRIT,
        blackboard: Optional["BlackboardStore"] = None,
        tissue_id: Optional[str] = None,
        df_id_self: Optional[str] = None,
    ) -> None:
        if z_crit <= 0:
            raise ValueError("z_crit must be > 0")
        if blackboard is not None and (not tissue_id or not df_id_self):
            raise ValueError(
                "blackboard checkpointing requires tissue_id + df_id_self"
            )
        self.topology = topology
        self.z_crit = float(z_crit)
        # Patch C3 (Gemini-Finding): optional persistence to BlackboardStore.
        # Without checkpointing: Sandpile-Amnesie at process-crash. With: avalanche-events
        # are append-only logged in BlackboardStore so SOC-history survives restarts.
        self.blackboard = blackboard
        self.tissue_id = tissue_id
        self.df_id_self = df_id_self
        self._lock = threading.RLock()
        self._loads: defaultdict = defaultdict(float)
        self.avalanche_log: list[AvalancheEvent] = []

    def increment_load(self, df_id: str, amount: float = 1.0) -> list[AvalancheEvent]:
        """Add load to df. If threshold crossed: cascade redistribution.

        Returns list of avalanche events triggered (may be empty or chain).
        """
        if amount < 0:
            raise ValueError("amount must be >= 0")
        if df_id not in self.topology:
            raise KeyError(f"df_id {df_id!r} not in topology")
        with self._lock:
            self._loads[df_id] += float(amount)
            return self._cascade(df_id)

    def get_load(self, df_id: str) -> float:
        with self._lock:
            return self._loads[df_id]

    def total_load(self) -> float:
        with self._lock:
            return sum(self._loads.values())

    def reset(self) -> None:
        with self._lock:
            self._loads.clear()
            self.avalanche_log.clear()

    def _cascade(self, df_id: str) -> list[AvalancheEvent]:
        """Fire avalanche if df.load > z_crit. Recurse for chain-reactions."""
        events: list[AvalancheEvent] = []
        # BFS-style: process all over-threshold dfs until system stable
        queue = [df_id]
        seen: set[str] = set()
        while queue:
            current = queue.pop(0)
            if self._loads[current] <= self.z_crit:
                continue
            neighbors = self.topology.get(current, [])
            if not neighbors:
                # Boundary df (no neighbors): no redistribution possible
                continue
            redistribute_amount = self._loads[current] / len(neighbors)
            load_before = self._loads[current]
            for n in neighbors:
                self._loads[n] += redistribute_amount
                if self._loads[n] > self.z_crit and n not in seen:
                    queue.append(n)
                    seen.add(n)
            self._loads[current] = 0.0  # avalanche flushes
            event = AvalancheEvent(
                df_id=current,
                load_before=load_before,
                load_after=0.0,
                redistributed_to=tuple(neighbors),
                redistribute_amount=redistribute_amount,
            )
            events.append(event)
            self.avalanche_log.append(event)
            # Patch C3: Persist avalanche to BlackboardStore (if configured).
            if self.blackboard is not None and self.tissue_id and self.df_id_self:
                try:
                    self.blackboard.append(
                        tissue_id=self.tissue_id,
                        topic=f"sandpile-avalanche:{current}",
                        written_by_df=self.df_id_self,
                        payload={
                            "df_id": current,
                            "load_before": load_before,
                            "load_after": 0.0,
                            "redistributed_to": list(neighbors),
                            "redistribute_amount": redistribute_amount,
                        },
                        ttl_sec=86400,  # 24h TTL for SOC-history
                    )
                except Exception:
                    # Persistence is best-effort; avalanche-flow must not break on DB error
                    pass
        return events

    def restore_state_from_blackboard(
        self, since_seq: int = 0, limit: int = 1000
    ) -> int:
        """Re-apply avalanche-events from blackboard to reconstruct SOC-history.

        Patch C3: After process-restart, replay sandpile-avalanche events to
        restore avalanche_log (statistics-only; current loads remain reset).

        Returns count of events restored.
        """
        if self.blackboard is None or not self.tissue_id:
            return 0
        events = self.blackboard.read_since(
            self.tissue_id, since_seq=since_seq, limit=limit
        )
        restored = 0
        with self._lock:
            for ev in events:
                if not ev.topic.startswith("sandpile-avalanche:"):
                    continue
                p = ev.payload or {}
                self.avalanche_log.append(
                    AvalancheEvent(
                        df_id=p.get("df_id", ""),
                        load_before=float(p.get("load_before", 0)),
                        load_after=float(p.get("load_after", 0)),
                        redistributed_to=tuple(p.get("redistributed_to", [])),
                        redistribute_amount=float(p.get("redistribute_amount", 0)),
                    )
                )
                restored += 1
        return restored


# CRUX-MK
