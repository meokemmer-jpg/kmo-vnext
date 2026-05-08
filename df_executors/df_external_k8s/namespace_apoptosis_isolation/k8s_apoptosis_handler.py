"""K8s Apoptosis Handler [CRUX-MK].

Welle-30-Iter-2 W-30R-3: Kontrollierter Pod-Crash bei Resource-Exhaustion.
Bio-Pattern: Apoptose-Cascade (programmierter Zelltod fuer Tissue-Health).

Domain-Mapping:
  Apoptose-Trigger -> Resource-Exhaustion (CPU/Memory > Limit)
  Cytochrome-c-Release -> Pod-Crash-Snapshot
  Phagocytose -> Garbage-Collection / kubelet-cleanup
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .k8s_pod_lifecycle import PodCondition, PodLifecycle, PodState


class ApoptosisTrigger(Enum):
    CPU_EXHAUSTION = "CPUExhaustion"
    MEMORY_EXHAUSTION = "MemoryExhaustion"
    HEARTBEAT_TIMEOUT = "HeartbeatTimeout"
    OOM_KILL = "OOMKill"
    MANUAL = "Manual"


class ApoptosisDecision(Enum):
    APPROVED = "Approved"
    DENIED_PROTECTED = "DeniedProtected"
    DENIED_HEALTHY = "DeniedHealthy"


@dataclass(frozen=True)
class ApoptosisEvent:
    """Cytochrome-c-Snapshot-aequivalent: Pre-Death-Forensik."""

    pod_id: str
    namespace: str
    trigger: ApoptosisTrigger
    decision: ApoptosisDecision
    timestamp: float
    pre_death_cpu: int
    pre_death_memory: int
    reason: str


class K8sApoptosisHandler:
    """Apoptose-Cascade-Orchestrator mit Bcl-2-aequivalentem Protection-Layer.

    K_0-Schutz: dieser Handler crasht NUR Mock-Pods im PodLifecycle.
    KEIN echter K8s-Cluster-Aufruf.
    """

    def __init__(
        self,
        lifecycle: PodLifecycle,
        heartbeat_timeout_sec: float = 30.0,
    ) -> None:
        self._lifecycle = lifecycle
        self._heartbeat_timeout_sec = heartbeat_timeout_sec
        self._protected: dict[str, float] = {}  # pod_id -> protection-expiry-timestamp
        self._events: list[ApoptosisEvent] = []
        self._lock = threading.RLock()

    def protect_pod(self, pod_id: str, ttl_sec: float = 60.0) -> None:
        """Bcl-2-Anti-Apoptose: TTL-basierte Protection vor Crash."""
        if ttl_sec <= 0:
            raise ValueError("TTL must be positive")
        with self._lock:
            self._protected[pod_id] = time.time() + ttl_sec

    def is_protected(self, pod_id: str) -> bool:
        with self._lock:
            expiry = self._protected.get(pod_id)
            if expiry is None:
                return False
            if time.time() > expiry:
                del self._protected[pod_id]
                return False
            return True

    def evaluate_trigger(
        self,
        pod_id: str,
        trigger: ApoptosisTrigger,
        reason: str = "",
    ) -> ApoptosisDecision:
        """Apoptose-Cascade-Decision: trigger -> approved/denied."""
        with self._lock:
            state = self._lifecycle.get_state(pod_id)
            if not state:
                raise KeyError(f"Pod {pod_id} not found")

            if self.is_protected(pod_id):
                decision = ApoptosisDecision.DENIED_PROTECTED
            elif (
                trigger != ApoptosisTrigger.MANUAL
                and state.condition == PodCondition.HEALTHY
            ):
                decision = ApoptosisDecision.DENIED_HEALTHY
            else:
                decision = ApoptosisDecision.APPROVED

            self._events.append(
                ApoptosisEvent(
                    pod_id=pod_id,
                    namespace=state.namespace,
                    trigger=trigger,
                    decision=decision,
                    timestamp=time.time(),
                    pre_death_cpu=state.usage.cpu_millicores,
                    pre_death_memory=state.usage.memory_mib,
                    reason=reason,
                )
            )

            if decision == ApoptosisDecision.APPROVED:
                self._lifecycle.mark_crashed(
                    pod_id, f"{trigger.value}: {reason}".strip(": ")
                )

            return decision

    def detect_resource_apoptosis_candidates(self, namespace: str) -> list[str]:
        """Detektiere Pods im RESOURCE_PRESSURE-Zustand fuer Apoptose-Trigger."""
        candidates: list[str] = []
        for state in self._lifecycle.list_by_namespace(namespace):
            if state.condition == PodCondition.RESOURCE_PRESSURE:
                candidates.append(state.pod_id)
        return candidates

    def cascade_apoptosis(
        self,
        namespace: str,
        trigger: ApoptosisTrigger = ApoptosisTrigger.MEMORY_EXHAUSTION,
    ) -> dict[str, ApoptosisDecision]:
        """Multi-Pod-Apoptose-Cascade pro Namespace (Cell-Boundary-Pflicht)."""
        candidates = self.detect_resource_apoptosis_candidates(namespace)
        results: dict[str, ApoptosisDecision] = {}
        for pid in candidates:
            results[pid] = self.evaluate_trigger(
                pid, trigger, reason=f"cascade:{trigger.value}"
            )
        return results

    def event_history(self, namespace: Optional[str] = None) -> list[ApoptosisEvent]:
        with self._lock:
            if namespace is None:
                return list(self._events)
            return [e for e in self._events if e.namespace == namespace]

    def cleanup_expired_protections(self) -> int:
        with self._lock:
            now = time.time()
            expired = [pid for pid, exp in self._protected.items() if now > exp]
            for pid in expired:
                del self._protected[pid]
            return len(expired)
