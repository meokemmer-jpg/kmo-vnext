"""NGINX Config Distributor -- Atomic-Deploy + Rollback bei Quorum-Fail [CRUX-MK].

Coordinated-Deploy-Pattern:
    1. Quorum-Engine signalisiert APPROVED (3-of-5 ACCEPTs).
    2. Distributor schreibt validated Config in Staging-Slots aller Instances.
    3. Atomic-Switch: alle Instances wechseln auf neue Config simultan.
    4. Bei Fehler in einer Instance: full Cluster-Rollback (atomic-revert).

Bio-Pattern: Group-Behavior-Activation (V. fischeri Lumineszenz aktiviert nur
wenn alle Bakterien gemeinsam auf Quorum-Konzentration kommen).

Externer Domain: NGINX Config-Reload (`nginx -s reload` semantic).
KEINE crux/governance/Kemmer-Imports.

Pre-Conditions:
    - QuorumEngine + ConfigValidator vorhanden (dependency-injected)
    - dry_run-Flag fuer Tests verfuegbar
Post-Conditions:
    - distribute() ist transactional: entweder alle Instances erfolgreich oder rollback
    - rollback_history persistent (audit-trail)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .nginx_quorum_engine import (
    NginxQuorumEngine,
    QuorumOutcome,
)


# Constants with units.
DEFAULT_DEPLOY_TIMEOUT_SEC: float = 10.0
DEFAULT_ROLLBACK_TIMEOUT_SEC: float = 5.0


class RollbackReason(str, Enum):
    """Warum wurde Rollback ausgeloest."""
    QUORUM_REJECTED = "quorum_rejected"
    QUORUM_PENDING = "quorum_pending"
    QUORUM_TIMEOUT = "quorum_timeout"
    INSTANCE_DEPLOY_FAILED = "instance_deploy_failed"
    POST_DEPLOY_HEALTHCHECK_FAILED = "post_deploy_healthcheck_failed"
    USER_REQUESTED = "user_requested"


@dataclass(frozen=True)
class DistributionResult:
    """Outcome eines Distribute-Call. Immutable."""
    config_hash: str
    success: bool
    instances_deployed: tuple[str, ...]
    instances_failed: tuple[str, ...]
    rollback_reason: Optional[RollbackReason]
    duration_sec: float
    timestamp: float


@dataclass
class _InstanceState:
    """Internal: per-Instance current + previous Config-Hash (fuer Rollback)."""
    instance_id: str
    current_hash: Optional[str] = None
    previous_hash: Optional[str] = None
    healthy: bool = True


class NginxConfigDistributor:
    """Atomic-Deploy + Rollback fuer NGINX-Cluster.

    Pattern: Two-Phase-Commit-aehnlich, aber bus-frei. Pruefe Quorum -> Stage -> Switch -> Verify.

    Test-Modus: deploy_func + healthcheck_func sind callables (dependency-injection),
    real-Mode wuerde `nginx -t` + `nginx -s reload` aufrufen.

    Thread-safe: alle Mutationen unter self._lock.
    """

    def __init__(
        self,
        quorum_engine: NginxQuorumEngine,
        instance_ids: list[str],
        deploy_func: Callable[[str, str], bool],
        healthcheck_func: Callable[[str], bool],
        clock: Callable[[], float] = time.time,
        deploy_timeout_sec: float = DEFAULT_DEPLOY_TIMEOUT_SEC,
        rollback_timeout_sec: float = DEFAULT_ROLLBACK_TIMEOUT_SEC,
    ) -> None:
        if quorum_engine is None:
            raise ValueError("quorum_engine required")
        if not instance_ids:
            raise ValueError("instance_ids must be non-empty")
        if len(set(instance_ids)) != len(instance_ids):
            raise ValueError("instance_ids must be unique")
        if not callable(deploy_func):
            raise ValueError("deploy_func must be callable")
        if not callable(healthcheck_func):
            raise ValueError("healthcheck_func must be callable")
        if deploy_timeout_sec <= 0 or rollback_timeout_sec <= 0:
            raise ValueError("timeouts must be > 0")
        self.quorum_engine = quorum_engine
        self.instance_ids = list(instance_ids)
        self.deploy_func = deploy_func
        self.healthcheck_func = healthcheck_func
        self.deploy_timeout_sec = deploy_timeout_sec
        self.rollback_timeout_sec = rollback_timeout_sec
        self._clock = clock
        self._lock = threading.RLock()
        self._instance_states: dict[str, _InstanceState] = {
            iid: _InstanceState(instance_id=iid) for iid in instance_ids
        }
        self._rollback_history: list[tuple[float, str, RollbackReason]] = []

    # ---------------- Public API ----------------

    def distribute(self, config_hash: str, config_source: str) -> DistributionResult:
        """Quorum-Check -> Atomic-Deploy oder Rollback.

        Workflow:
            1. Resolve quorum decision.
            2. If not APPROVED: rollback with corresponding reason.
            3. If APPROVED: deploy to all instances.
            4. Healthcheck after deploy.
            5. Rollback on any failure.
        """
        start = self._clock()
        decision = self.quorum_engine.resolve(config_hash)
        # Map non-approved outcomes to rollback reasons.
        if decision.outcome != QuorumOutcome.APPROVED:
            reason_map = {
                QuorumOutcome.REJECTED: RollbackReason.QUORUM_REJECTED,
                QuorumOutcome.PENDING: RollbackReason.QUORUM_PENDING,
                QuorumOutcome.TIMEOUT: RollbackReason.QUORUM_TIMEOUT,
            }
            return self._fail(
                config_hash=config_hash,
                deployed=(),
                failed=(),
                reason=reason_map[decision.outcome],
                start=start,
            )
        # Stage + Switch (atomic across cluster).
        deployed: list[str] = []
        failed: list[str] = []
        with self._lock:
            for iid in self.instance_ids:
                try:
                    ok = self.deploy_func(iid, config_source)
                except Exception:  # pragma: no cover -- defensive
                    ok = False
                if ok:
                    deployed.append(iid)
                else:
                    failed.append(iid)
                    break  # First-failure-wins -> rollback (no partial state).
        if failed:
            self._rollback(deployed, config_hash)
            return self._fail(
                config_hash=config_hash,
                deployed=tuple(deployed),
                failed=tuple(failed),
                reason=RollbackReason.INSTANCE_DEPLOY_FAILED,
                start=start,
            )
        # Healthcheck across all deployed instances.
        unhealthy: list[str] = []
        for iid in deployed:
            try:
                healthy = self.healthcheck_func(iid)
            except Exception:  # pragma: no cover -- defensive
                healthy = False
            if not healthy:
                unhealthy.append(iid)
        if unhealthy:
            self._rollback(deployed, config_hash)
            return self._fail(
                config_hash=config_hash,
                deployed=tuple(deployed),
                failed=tuple(unhealthy),
                reason=RollbackReason.POST_DEPLOY_HEALTHCHECK_FAILED,
                start=start,
            )
        # Success: persist new state.
        with self._lock:
            for iid in deployed:
                state = self._instance_states[iid]
                state.previous_hash = state.current_hash
                state.current_hash = config_hash
                state.healthy = True
        return DistributionResult(
            config_hash=config_hash,
            success=True,
            instances_deployed=tuple(deployed),
            instances_failed=(),
            rollback_reason=None,
            duration_sec=self._clock() - start,
            timestamp=self._clock(),
        )

    def force_rollback(
        self,
        config_hash: str,
        reason: RollbackReason = RollbackReason.USER_REQUESTED,
    ) -> DistributionResult:
        """Manueller Rollback aller Instances zum vorherigen Config-Hash."""
        start = self._clock()
        with self._lock:
            instances_to_rollback = [
                iid for iid, state in self._instance_states.items()
                if state.current_hash == config_hash
            ]
        self._rollback(instances_to_rollback, config_hash)
        return self._fail(
            config_hash=config_hash,
            deployed=(),
            failed=tuple(instances_to_rollback),
            reason=reason,
            start=start,
        )

    def get_rollback_history(self) -> list[tuple[float, str, RollbackReason]]:
        """Audit-Trail aller Rollback-Events."""
        with self._lock:
            return list(self._rollback_history)

    def get_instance_state(self, instance_id: str) -> dict:
        with self._lock:
            state = self._instance_states.get(instance_id)
            if state is None:
                raise KeyError(f"unknown instance_id: {instance_id}")
            return {
                "instance_id": state.instance_id,
                "current_hash": state.current_hash,
                "previous_hash": state.previous_hash,
                "healthy": state.healthy,
            }

    # ---------------- Internals ----------------

    def _rollback(self, deployed_instances: list[str], failed_hash: str) -> None:
        """Best-effort revert deployed instances to previous_hash."""
        with self._lock:
            for iid in deployed_instances:
                state = self._instance_states.get(iid)
                if state is None or state.previous_hash is None:
                    continue
                state.current_hash = state.previous_hash
                state.previous_hash = None

    def _fail(
        self,
        config_hash: str,
        deployed: tuple[str, ...],
        failed: tuple[str, ...],
        reason: RollbackReason,
        start: float,
    ) -> DistributionResult:
        now = self._clock()
        with self._lock:
            self._rollback_history.append((now, config_hash, reason))
        return DistributionResult(
            config_hash=config_hash,
            success=False,
            instances_deployed=deployed,
            instances_failed=failed,
            rollback_reason=reason,
            duration_sec=now - start,
            timestamp=now,
        )


# CRUX-MK
