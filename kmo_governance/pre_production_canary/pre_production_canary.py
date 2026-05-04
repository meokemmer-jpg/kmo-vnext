"""KMO pre_production_canary [CRUX-MK].

Welle-10 Phase-6.3 SUBAGENT-E: Canary-Deployment SKELETON.

Bio-Aequivalent: Genetic-Drift-Beobachtung. Kleine Population (canary) erprobt
neue Allele (version) unter realen Selektionsbedingungen (production-traffic),
bevor sich Allel in Gesamtpopulation (baseline) ausbreitet. Bei schlechterer
Fitness (error_rate / latency_regression): Auto-Rollback statt Kontamination.

Pattern-Inspiration:
  - Industry-Canary-Deployment (z.B. Spinnaker, Argo Rollouts)
  - kmo_governance/evolution_loop: make_canary() + CanaryGenome (frozen-baseline)
  - kmo_governance/wound_healing: 4-Phase-Lifecycle (here: 4-Step-Rollout)
  - kmo_governance/apoptosis_engine: Trigger-basierte Termination

K11 Cascade-Containment: Canary isoliert neue Version auf kleinen Traffic-Anteil.
K13 Pre-Action-Verification: Pre-Conditions vor Phase-Transitions explizit.

Komponenten:
  - CanaryOutcome (frozen): single observation per version
  - CanaryDecisionRecord (frozen): audit-log entry
  - RolloutStep (frozen): scheduled traffic-step
  - RollbackDecision (frozen): RollbackTrigger output
  - RollbackReason (Enum): rollback-cause classification
  - CanaryDeployment: traffic-split + deterministic routing
  - CanaryHealthMonitor: error-rate + p99-latency in sliding-windows
  - RollbackTrigger: decision engine with cooldown
  - ProgressiveRollout: time-based traffic-step schedule
  - CanaryAuditLog: append-only decision-trail
"""

from __future__ import annotations

import enum
import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


# ---------- Enums ----------


class RollbackReason(str, enum.Enum):
    """Classification of rollback causes."""

    ERROR_RATE_EXCEEDED = "error_rate_exceeded"
    LATENCY_REGRESSION = "latency_regression"
    MANUAL_OVERRIDE = "manual_override"
    NONE = "none"


# ---------- Frozen Dataclasses ----------


@dataclass(frozen=True)
class CanaryOutcome:
    """Single outcome observation for a version.

    Pre: latency_ms >= 0, ts >= 0
    Post: immutable, hashable
    """

    version_id: str
    success: bool
    latency_ms: float
    ts: float


@dataclass(frozen=True)
class RollbackDecision:
    """Output of RollbackTrigger.check_rollback_needed().

    Pre: reason is RollbackReason
    Post: immutable
    """

    rollback: bool
    reason: RollbackReason
    affected_version: Optional[str] = None
    detail: str = ""


@dataclass(frozen=True)
class RolloutStep:
    """Scheduled progressive-rollout step.

    Pre: time_s >= 0, 0 <= percentage <= 100
    Post: immutable
    """

    time_s: float
    percentage: float


@dataclass(frozen=True)
class CanaryDecisionRecord:
    """Audit-log entry. Append-only.

    Pre: action is non-empty string
    Post: immutable
    """

    version_id: str
    action: str
    reason: str
    ts: float


# ---------- CanaryDeployment ----------


class CanaryDeployment:
    """Deterministic traffic-split between baseline + canary versions.

    Routing uses md5(request_id) % 10000 / 100.0 -> percentage in [0.0, 100.0).
    Same request_id always routes to same version (deterministic).

    Pre: traffic_percentage in [0, 100]
    Post: register_canary + register_baseline are idempotent;
          route_request returns version_id consistently
    """

    def __init__(self) -> None:
        self._canaries: dict[str, float] = {}  # version_id -> traffic_percentage
        self._baseline: Optional[str] = None
        self._lock = threading.RLock()

    def register_canary(self, version_id: str, traffic_percentage: float) -> None:
        """Register a canary version with given traffic percentage.

        Pre: 0 < traffic_percentage <= 100, version_id non-empty
        Post: canary entry stored; sum of canary percentages may not exceed 100
        """
        if not version_id:
            raise ValueError("version_id must be non-empty")
        if not (0 < traffic_percentage <= 100):
            raise ValueError("traffic_percentage must be in (0, 100]")
        with self._lock:
            # If updating existing canary, subtract old before checking total
            existing = self._canaries.get(version_id, 0.0)
            other_total = sum(v for k, v in self._canaries.items() if k != version_id)
            if other_total + traffic_percentage > 100.0:
                raise ValueError(
                    f"total canary traffic would exceed 100% "
                    f"(existing other={other_total}, new={traffic_percentage})"
                )
            self._canaries[version_id] = float(traffic_percentage)

    def register_baseline(self, version_id: str) -> None:
        """Register the baseline (stable) version. All non-canary traffic goes here.

        Pre: version_id non-empty
        Post: baseline set
        """
        if not version_id:
            raise ValueError("version_id must be non-empty")
        with self._lock:
            self._baseline = version_id

    def unregister_canary(self, version_id: str) -> None:
        """Remove a canary version (e.g. after rollback)."""
        with self._lock:
            self._canaries.pop(version_id, None)

    def route_request(self, request_id: str) -> str:
        """Route request_id to a version_id via deterministic hash split.

        Pre: baseline registered
        Post: returns canary version_id with prob = its percentage / 100,
              else baseline. Same request_id always returns same version.
        """
        if not request_id:
            raise ValueError("request_id must be non-empty")
        with self._lock:
            if self._baseline is None:
                raise RuntimeError("baseline must be registered before routing")
            # Hash request_id to a value in [0.0, 100.0)
            digest = hashlib.md5(request_id.encode("utf-8")).hexdigest()
            bucket = int(digest[:8], 16) % 10000  # 0-9999
            position = bucket / 100.0  # 0.0 - 99.99
            # Walk through canaries in deterministic order (sorted by version_id)
            cumulative = 0.0
            for version_id in sorted(self._canaries):
                pct = self._canaries[version_id]
                if position < cumulative + pct:
                    return version_id
                cumulative += pct
            return self._baseline

    def get_distribution(self) -> dict[str, float]:
        """Return current distribution {version_id: percentage}.

        Post: sum of all percentages == 100.0 (within float tolerance)
        """
        with self._lock:
            dist: dict[str, float] = {}
            canary_total = 0.0
            for version_id, pct in self._canaries.items():
                dist[version_id] = pct
                canary_total += pct
            if self._baseline is not None:
                dist[self._baseline] = max(0.0, 100.0 - canary_total)
            return dist


# ---------- CanaryHealthMonitor ----------


class CanaryHealthMonitor:
    """Track outcomes per version with sliding-window error-rate + p99-latency.

    Pre: window_capacity > 0
    Post: thread-safe; record_outcome appends, get_*  computes from current window
    """

    def __init__(self, window_capacity: int = 1000) -> None:
        if window_capacity <= 0:
            raise ValueError("window_capacity must be > 0")
        self._window_capacity = int(window_capacity)
        # version_id -> deque[CanaryOutcome]
        self._outcomes: dict[str, deque[CanaryOutcome]] = {}
        self._lock = threading.RLock()

    def record_outcome(
        self,
        version_id: str,
        success: bool,
        latency_ms: float,
        ts: Optional[float] = None,
    ) -> None:
        """Append outcome for version. Drops oldest at window_capacity.

        Pre: latency_ms >= 0
        Post: outcome appended; window stays <= window_capacity
        """
        if not version_id:
            raise ValueError("version_id must be non-empty")
        if latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        outcome = CanaryOutcome(
            version_id=version_id,
            success=bool(success),
            latency_ms=float(latency_ms),
            ts=float(ts if ts is not None else time.time()),
        )
        with self._lock:
            if version_id not in self._outcomes:
                self._outcomes[version_id] = deque(maxlen=self._window_capacity)
            self._outcomes[version_id].append(outcome)

    def get_error_rate(self, version_id: str, window_s: float = 60.0) -> float:
        """Error rate for version in last window_s seconds.

        Pre: window_s > 0
        Post: returns float in [0.0, 1.0]; 0.0 if no observations
        """
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        now = time.time()
        with self._lock:
            outcomes = self._outcomes.get(version_id, deque())
            relevant = [o for o in outcomes if (now - o.ts) <= window_s]
            if not relevant:
                return 0.0
            errors = sum(1 for o in relevant if not o.success)
            return errors / len(relevant)

    def get_p99_latency(self, version_id: str, window_s: float = 60.0) -> float:
        """P99 latency_ms for version in window. 0.0 if no observations.

        Pre: window_s > 0
        Post: returns p99 in ms
        """
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        now = time.time()
        with self._lock:
            outcomes = self._outcomes.get(version_id, deque())
            relevant = [o.latency_ms for o in outcomes if (now - o.ts) <= window_s]
            if not relevant:
                return 0.0
            sorted_lat = sorted(relevant)
            # P99 index: ceil(0.99 * len) - 1, clamped
            idx = max(0, min(len(sorted_lat) - 1, int(0.99 * len(sorted_lat))))
            return sorted_lat[idx]

    def is_healthy(
        self,
        version_id: str,
        error_threshold: float = 0.05,
        window_s: float = 60.0,
    ) -> bool:
        """True if version's error_rate <= error_threshold.

        Pre: 0 <= error_threshold <= 1
        Post: returns bool
        """
        if not (0 <= error_threshold <= 1):
            raise ValueError("error_threshold must be in [0, 1]")
        return self.get_error_rate(version_id, window_s=window_s) <= error_threshold

    def sample_count(self, version_id: str, window_s: float = 60.0) -> int:
        """Number of observations in window."""
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        now = time.time()
        with self._lock:
            outcomes = self._outcomes.get(version_id, deque())
            return sum(1 for o in outcomes if (now - o.ts) <= window_s)


# ---------- RollbackTrigger ----------


class RollbackTrigger:
    """Decision-engine: when should a canary be rolled back?

    Triggers:
      - error_rate > error_threshold       -> ERROR_RATE_EXCEEDED
      - p99_latency > latency_threshold    -> LATENCY_REGRESSION
      - manual override                    -> MANUAL_OVERRIDE
    Cooldown after fired rollback prevents flapping.

    Pre: thresholds in valid ranges; cooldown_s >= 0
    Post: thread-safe; check_rollback_needed returns RollbackDecision
    """

    def __init__(
        self,
        error_threshold: float = 0.05,
        latency_threshold_ms: float = 1000.0,
        cooldown_s: float = 300.0,
        min_samples: int = 10,
    ) -> None:
        if not (0 <= error_threshold <= 1):
            raise ValueError("error_threshold must be in [0, 1]")
        if latency_threshold_ms < 0:
            raise ValueError("latency_threshold_ms must be >= 0")
        if cooldown_s < 0:
            raise ValueError("cooldown_s must be >= 0")
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        self.error_threshold = float(error_threshold)
        self.latency_threshold_ms = float(latency_threshold_ms)
        self.cooldown_s = float(cooldown_s)
        self.min_samples = int(min_samples)
        self._monitor: Optional[CanaryHealthMonitor] = None
        self._last_rollback_ts: dict[str, float] = {}
        self._manual_overrides: dict[str, str] = {}
        self._lock = threading.RLock()

    def register_canary_monitor(self, monitor: CanaryHealthMonitor) -> None:
        """Bind to a CanaryHealthMonitor for metric-checks."""
        if monitor is None:
            raise ValueError("monitor must not be None")
        with self._lock:
            self._monitor = monitor

    def trigger_manual_override(self, version_id: str, reason: str = "manual") -> None:
        """Force rollback of a canary version on next check_rollback_needed."""
        if not version_id:
            raise ValueError("version_id must be non-empty")
        with self._lock:
            self._manual_overrides[version_id] = reason

    def check_rollback_needed(self, version_id: str) -> RollbackDecision:
        """Evaluate rollback decision for version_id.

        Pre: monitor registered
        Post: returns RollbackDecision with reason classification.
              Honors cooldown: returns NONE if last rollback < cooldown_s ago.
        """
        if not version_id:
            raise ValueError("version_id must be non-empty")
        with self._lock:
            if self._monitor is None:
                raise RuntimeError("monitor must be registered before check")
            now = time.time()
            # Cooldown check
            last_ts = self._last_rollback_ts.get(version_id, 0.0)
            if (now - last_ts) < self.cooldown_s and last_ts > 0:
                return RollbackDecision(
                    rollback=False,
                    reason=RollbackReason.NONE,
                    affected_version=version_id,
                    detail=f"cooldown active ({self.cooldown_s - (now - last_ts):.1f}s remaining)",
                )
            # Manual override has highest priority
            if version_id in self._manual_overrides:
                detail = self._manual_overrides.pop(version_id)
                self._last_rollback_ts[version_id] = now
                return RollbackDecision(
                    rollback=True,
                    reason=RollbackReason.MANUAL_OVERRIDE,
                    affected_version=version_id,
                    detail=detail,
                )
            samples = self._monitor.sample_count(version_id)
            if samples < self.min_samples:
                return RollbackDecision(
                    rollback=False,
                    reason=RollbackReason.NONE,
                    affected_version=version_id,
                    detail=f"insufficient samples ({samples}<{self.min_samples})",
                )
            # Error-rate check
            err = self._monitor.get_error_rate(version_id)
            if err > self.error_threshold:
                self._last_rollback_ts[version_id] = now
                return RollbackDecision(
                    rollback=True,
                    reason=RollbackReason.ERROR_RATE_EXCEEDED,
                    affected_version=version_id,
                    detail=f"error_rate={err:.4f} > {self.error_threshold:.4f}",
                )
            # Latency check
            p99 = self._monitor.get_p99_latency(version_id)
            if p99 > self.latency_threshold_ms:
                self._last_rollback_ts[version_id] = now
                return RollbackDecision(
                    rollback=True,
                    reason=RollbackReason.LATENCY_REGRESSION,
                    affected_version=version_id,
                    detail=f"p99={p99:.1f}ms > {self.latency_threshold_ms:.1f}ms",
                )
            return RollbackDecision(
                rollback=False,
                reason=RollbackReason.NONE,
                affected_version=version_id,
                detail="all checks passed",
            )

    def cooldown_remaining_s(self, version_id: str) -> float:
        """Seconds remaining in cooldown. 0.0 if not in cooldown."""
        with self._lock:
            last_ts = self._last_rollback_ts.get(version_id, 0.0)
            if last_ts == 0.0:
                return 0.0
            elapsed = time.time() - last_ts
            return max(0.0, self.cooldown_s - elapsed)


# ---------- ProgressiveRollout ----------


class ProgressiveRollout:
    """Time-based progressive traffic-step schedule.

    schedule = [(time_s, percentage), ...]

    advance() returns the next-due step (based on now - start_ts).
    Steps fire in order; idempotent (each step fires at most once).

    Pre: schedule non-empty, time_s monotonic non-decreasing,
         percentages in [0, 100]
    Post: thread-safe; is_complete() True when last step fired
    """

    def __init__(
        self,
        canary_version_id: str,
        baseline_version_id: str,
        schedule: list[RolloutStep],
        deployment: Optional[CanaryDeployment] = None,
        start_ts: Optional[float] = None,
    ) -> None:
        if not canary_version_id:
            raise ValueError("canary_version_id must be non-empty")
        if not baseline_version_id:
            raise ValueError("baseline_version_id must be non-empty")
        if not schedule:
            raise ValueError("schedule must be non-empty")
        # Validate schedule
        prev_t = -1.0
        for step in schedule:
            if step.time_s < prev_t:
                raise ValueError("schedule time_s must be monotonic non-decreasing")
            if not (0.0 <= step.percentage <= 100.0):
                raise ValueError("schedule percentage must be in [0, 100]")
            prev_t = step.time_s
        self.canary_version_id = canary_version_id
        self.baseline_version_id = baseline_version_id
        self.schedule = list(schedule)
        self.deployment = deployment
        self._start_ts = float(start_ts if start_ts is not None else time.time())
        self._next_step_idx = 0
        self._fired_count = 0
        self._rolled_back = False
        self._lock = threading.RLock()

    def advance(self, now: Optional[float] = None) -> Optional[RolloutStep]:
        """Returns next-due step or None.

        Post: applies step.percentage to deployment if attached;
              increments _next_step_idx
        """
        with self._lock:
            if self._rolled_back:
                return None
            if self._next_step_idx >= len(self.schedule):
                return None
            t_now = now if now is not None else time.time()
            elapsed = t_now - self._start_ts
            step = self.schedule[self._next_step_idx]
            if elapsed < step.time_s:
                return None
            self._next_step_idx += 1
            self._fired_count += 1
            # Apply to deployment if attached
            if self.deployment is not None:
                if step.percentage <= 0.0:
                    self.deployment.unregister_canary(self.canary_version_id)
                else:
                    # Cap at 100% (baseline gets remainder)
                    pct = min(step.percentage, 100.0)
                    self.deployment.register_canary(self.canary_version_id, pct)
            return step

    def is_complete(self) -> bool:
        """True if last step has fired (or rolled back)."""
        with self._lock:
            if self._rolled_back:
                return True
            return self._next_step_idx >= len(self.schedule)

    def rollback_to_baseline(self) -> None:
        """Abort progressive rollout, route 100% to baseline."""
        with self._lock:
            self._rolled_back = True
            if self.deployment is not None:
                self.deployment.unregister_canary(self.canary_version_id)

    def fired_count(self) -> int:
        with self._lock:
            return self._fired_count


# ---------- CanaryAuditLog ----------


class CanaryAuditLog:
    """Append-only audit-log of canary decisions.

    Pre: -
    Post: thread-safe; log_decision appends; get_history returns snapshot
    """

    def __init__(self) -> None:
        self._records: list[CanaryDecisionRecord] = []
        self._lock = threading.RLock()

    def log_decision(
        self,
        version_id: str,
        action: str,
        reason: str,
        ts: Optional[float] = None,
    ) -> None:
        """Append a decision-record.

        Pre: action non-empty
        Post: record appended in arrival-order
        """
        if not action:
            raise ValueError("action must be non-empty")
        rec = CanaryDecisionRecord(
            version_id=str(version_id),
            action=str(action),
            reason=str(reason),
            ts=float(ts if ts is not None else time.time()),
        )
        with self._lock:
            self._records.append(rec)

    def get_history(self) -> list[CanaryDecisionRecord]:
        """Snapshot of all decision-records (immutable copy)."""
        with self._lock:
            return list(self._records)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


# CRUX-MK
