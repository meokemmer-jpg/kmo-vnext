# [CRUX-MK]
"""KPM-Pre-Production-Canary Implementation (Welle-45 Phase-38 + W48-P5)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CanaryStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class CanaryDeployment:
    deployment_id: str
    strategy_id: str
    baseline_strategy_id: str
    capital_pct: float
    started_at: float
    status: CanaryStatus
    drift_score: float = 0.0
    decision_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.deployment_id:
            raise ValueError("deployment_id must be non-empty")
        if not self.strategy_id or not self.baseline_strategy_id:
            raise ValueError("strategy_id + baseline_strategy_id must be non-empty")
        if not 0.0 < self.capital_pct <= 1.0:
            raise ValueError("capital_pct must be in (0.0, 1.0]")


class KPMPreProductionCanary:
    """Strategy-Canary-Deploy mit Auto-Rollback bei Drift.

    Pre:
      - rollback_threshold_pct in [0, 100]
      - promote_min_runs >= 1
    """

    def __init__(
        self,
        rollback_threshold_pct: float = 5.0,
        promote_min_runs: int = 10,
        promote_threshold_pct: float = 2.0,
    ) -> None:
        if not 0 <= rollback_threshold_pct <= 100:
            raise ValueError("rollback_threshold_pct in [0, 100]")
        if promote_min_runs < 1:
            raise ValueError("promote_min_runs >= 1")
        self._rollback_pct = rollback_threshold_pct
        self._promote_min_runs = promote_min_runs
        self._promote_pct = promote_threshold_pct
        self._lock = threading.RLock()
        self._deployments: dict[str, CanaryDeployment] = {}
        self._performance: dict[str, list[float]] = {}  # PnL-pct samples per deployment

    def deploy_canary(
        self,
        strategy_id: str,
        baseline_strategy_id: str,
        capital_pct: float = 0.01,
    ) -> CanaryDeployment:
        if not 0.0 < capital_pct <= 1.0:
            raise ValueError("capital_pct must be in (0.0, 1.0]")
        # W48-P5 (V20-Race-Risk): UUID-suffix verhindert Same-MS-Kollision
        deployment_id = f"canary-{strategy_id}-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"
        with self._lock:
            d = CanaryDeployment(
                deployment_id=deployment_id,
                strategy_id=strategy_id,
                baseline_strategy_id=baseline_strategy_id,
                capital_pct=capital_pct,
                started_at=time.time(),
                status=CanaryStatus.ACTIVE,
            )
            self._deployments[deployment_id] = d
            self._performance[deployment_id] = []
            return d

    def record_performance(
        self,
        deployment_id: str,
        canary_pnl_pct: float,
        baseline_pnl_pct: float,
    ) -> CanaryDeployment:
        """Record PnL-comparison + auto-decide promote/rollback.

        Pre: deployment_id in self._deployments
        """
        with self._lock:
            if deployment_id not in self._deployments:
                raise ValueError(f"deployment {deployment_id} not registered")
            d = self._deployments[deployment_id]
            if d.status != CanaryStatus.ACTIVE:
                return d  # already promoted/rolled back, no-op
            drift = (baseline_pnl_pct - canary_pnl_pct)  # positive = canary worse
            self._performance[deployment_id].append(drift)
            avg_drift = sum(self._performance[deployment_id]) / len(self._performance[deployment_id])
            run_count = len(self._performance[deployment_id])

            # Auto-Rollback Decision
            if avg_drift >= self._rollback_pct:
                new_d = CanaryDeployment(
                    deployment_id=d.deployment_id,
                    strategy_id=d.strategy_id,
                    baseline_strategy_id=d.baseline_strategy_id,
                    capital_pct=d.capital_pct,
                    started_at=d.started_at,
                    status=CanaryStatus.ROLLED_BACK,
                    drift_score=avg_drift,
                    decision_reason=f"avg_drift={avg_drift:.2f}%>={self._rollback_pct:.2f}%",
                )
                self._deployments[deployment_id] = new_d
                return new_d
            # Auto-Promote Decision
            if run_count >= self._promote_min_runs and avg_drift <= -self._promote_pct:
                new_d = CanaryDeployment(
                    deployment_id=d.deployment_id,
                    strategy_id=d.strategy_id,
                    baseline_strategy_id=d.baseline_strategy_id,
                    capital_pct=d.capital_pct,
                    started_at=d.started_at,
                    status=CanaryStatus.PROMOTED,
                    drift_score=avg_drift,
                    decision_reason=f"avg_drift={avg_drift:.2f}% beats baseline by {abs(avg_drift):.2f}%",
                )
                self._deployments[deployment_id] = new_d
                return new_d
            # Update drift_score, keep ACTIVE
            new_d = CanaryDeployment(
                deployment_id=d.deployment_id,
                strategy_id=d.strategy_id,
                baseline_strategy_id=d.baseline_strategy_id,
                capital_pct=d.capital_pct,
                started_at=d.started_at,
                status=CanaryStatus.ACTIVE,
                drift_score=avg_drift,
            )
            self._deployments[deployment_id] = new_d
            return new_d

    def get_deployment(self, deployment_id: str) -> Optional[CanaryDeployment]:
        with self._lock:
            return self._deployments.get(deployment_id)

    def list_active(self) -> tuple[CanaryDeployment, ...]:
        with self._lock:
            return tuple(d for d in self._deployments.values() if d.status == CanaryStatus.ACTIVE)


# CRUX-MK
