# [CRUX-MK]
"""Failover-Router (Welle-19 Phase-13.1)."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class NodeStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class FailoverState(str, Enum):
    PRIMARY = "primary"
    FAILED_OVER = "failed_over"
    RECOVERING = "recovering"


@dataclass(frozen=True)
class RouteDecision:
    """Route decision with reason."""

    target_node_id: str
    state: FailoverState
    reason: str
    timestamp: float


class FailoverRouter:
    """Active-Standby-Failover-Router.

    Pre: primary_node_id non-empty, at least 1 standby
    Post: thread-safe; auto-failover when primary DOWN; manual recover
    """

    def __init__(
        self,
        primary_node_id: str,
        standby_node_ids: list[str],
        health_threshold: int = 3,
    ) -> None:
        if not primary_node_id:
            raise ValueError("primary_node_id required")
        if not standby_node_ids:
            raise ValueError("at least 1 standby required")
        if health_threshold <= 0:
            raise ValueError("health_threshold must be > 0")
        self.primary_node_id = primary_node_id
        self.standby_node_ids = list(standby_node_ids)
        self.health_threshold = int(health_threshold)
        self._node_status: dict[str, NodeStatus] = {primary_node_id: NodeStatus.HEALTHY}
        for s in standby_node_ids:
            self._node_status[s] = NodeStatus.HEALTHY
        self._fail_counts: dict[str, int] = {primary_node_id: 0}
        for s in standby_node_ids:
            self._fail_counts[s] = 0
        self._state = FailoverState.PRIMARY
        self._active_node = primary_node_id
        self._decisions: list[RouteDecision] = []
        self._lock = threading.RLock()

    @property
    def state(self) -> FailoverState:
        with self._lock:
            return self._state

    @property
    def active_node(self) -> str:
        with self._lock:
            return self._active_node

    def record_health(self, node_id: str, healthy: bool) -> None:
        with self._lock:
            if node_id not in self._node_status:
                raise ValueError(f"unknown node_id: {node_id}")
            if healthy:
                self._fail_counts[node_id] = 0
                if self._node_status[node_id] != NodeStatus.HEALTHY:
                    self._node_status[node_id] = NodeStatus.HEALTHY
            else:
                self._fail_counts[node_id] += 1
                if self._fail_counts[node_id] >= self.health_threshold:
                    self._node_status[node_id] = NodeStatus.DOWN
                else:
                    self._node_status[node_id] = NodeStatus.DEGRADED

    def route(self) -> RouteDecision:
        """Decide active node based on health."""
        with self._lock:
            primary_status = self._node_status[self.primary_node_id]

            if primary_status == NodeStatus.DOWN:
                # Failover to first healthy standby
                for standby in self.standby_node_ids:
                    if self._node_status[standby] == NodeStatus.HEALTHY:
                        self._active_node = standby
                        self._state = FailoverState.FAILED_OVER
                        decision = RouteDecision(
                            target_node_id=standby,
                            state=FailoverState.FAILED_OVER,
                            reason=f"primary {self.primary_node_id} DOWN, failover to {standby}",
                            timestamp=time.time(),
                        )
                        self._decisions.append(decision)
                        return decision
                # All standbys also down
                decision = RouteDecision(
                    target_node_id=self.primary_node_id,
                    state=self._state,
                    reason="all nodes DOWN, route-to-primary as fallback",
                    timestamp=time.time(),
                )
                self._decisions.append(decision)
                return decision

            # Primary OK or recovering
            if (
                self._state == FailoverState.FAILED_OVER
                and primary_status == NodeStatus.HEALTHY
            ):
                self._state = FailoverState.RECOVERING
                decision = RouteDecision(
                    target_node_id=self._active_node,
                    state=FailoverState.RECOVERING,
                    reason=f"primary recovered, in RECOVERING state (manual promote needed)",
                    timestamp=time.time(),
                )
                self._decisions.append(decision)
                return decision

            decision = RouteDecision(
                target_node_id=self.primary_node_id,
                state=FailoverState.PRIMARY,
                reason="primary healthy",
                timestamp=time.time(),
            )
            self._decisions.append(decision)
            self._active_node = self.primary_node_id
            return decision

    def promote_to_primary(self) -> RouteDecision:
        """Manually promote: switch back to primary after recovery."""
        with self._lock:
            if self._node_status[self.primary_node_id] != NodeStatus.HEALTHY:
                raise RuntimeError("primary not healthy, cannot promote")
            self._state = FailoverState.PRIMARY
            self._active_node = self.primary_node_id
            decision = RouteDecision(
                target_node_id=self.primary_node_id,
                state=FailoverState.PRIMARY,
                reason="manual promote-to-primary",
                timestamp=time.time(),
            )
            self._decisions.append(decision)
            return decision

    def get_node_statuses(self) -> dict[str, NodeStatus]:
        with self._lock:
            return dict(self._node_status)

    def get_decisions(self) -> list[RouteDecision]:
        with self._lock:
            return list(self._decisions)


# CRUX-MK
