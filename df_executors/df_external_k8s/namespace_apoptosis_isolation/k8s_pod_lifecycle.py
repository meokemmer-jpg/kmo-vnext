"""K8s Pod Lifecycle State-Machine [CRUX-MK].

Welle-30-Iter-2 W-30R-3: Pod-State-Tracking fuer Apoptose-Trigger-Detection.
Externe Domain (Kubernetes), KEIN Kemmer-Kontext.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PodPhase(Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    UNKNOWN = "Unknown"


class PodCondition(Enum):
    HEALTHY = "Healthy"
    RESOURCE_PRESSURE = "ResourcePressure"
    CRASHED = "Crashed"
    TERMINATED = "Terminated"


@dataclass(frozen=True)
class ResourceLimits:
    """Pflicht-Resource-Limits per K8s ResourceQuota Spec."""

    cpu_millicores: int
    memory_mib: int

    def __post_init__(self) -> None:
        if self.cpu_millicores < 0 or self.memory_mib < 0:
            raise ValueError("Resource limits must be non-negative")


@dataclass
class PodResourceUsage:
    cpu_millicores: int = 0
    memory_mib: int = 0
    last_updated: float = field(default_factory=time.time)


@dataclass
class PodState:
    pod_id: str
    namespace: str
    phase: PodPhase
    condition: PodCondition
    limits: ResourceLimits
    usage: PodResourceUsage
    created_at: float
    crashed_at: Optional[float] = None
    crash_reason: Optional[str] = None


class PodLifecycle:
    """Pod-State-Machine mit Thread-Safety. Mock-K8s-Client (kein echter cluster-connect)."""

    def __init__(self) -> None:
        self._pods: dict[str, PodState] = {}
        self._lock = threading.RLock()

    def create_pod(self, namespace: str, limits: ResourceLimits) -> str:
        if not namespace:
            raise ValueError("Namespace must be non-empty")
        pod_id = f"pod-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._pods[pod_id] = PodState(
                pod_id=pod_id,
                namespace=namespace,
                phase=PodPhase.PENDING,
                condition=PodCondition.HEALTHY,
                limits=limits,
                usage=PodResourceUsage(),
                created_at=time.time(),
            )
        return pod_id

    def transition_to_running(self, pod_id: str) -> None:
        with self._lock:
            pod = self._require_pod(pod_id)
            if pod.phase != PodPhase.PENDING:
                raise ValueError(
                    f"Pod must be Pending to transition to Running, got {pod.phase.value}"
                )
            pod.phase = PodPhase.RUNNING

    def update_usage(self, pod_id: str, cpu: int, memory: int) -> PodCondition:
        if cpu < 0 or memory < 0:
            raise ValueError("Usage must be non-negative")
        with self._lock:
            pod = self._require_pod(pod_id)
            pod.usage = PodResourceUsage(cpu_millicores=cpu, memory_mib=memory)
            cpu_over = pod.limits.cpu_millicores > 0 and cpu > pod.limits.cpu_millicores
            mem_over = pod.limits.memory_mib > 0 and memory > pod.limits.memory_mib
            if cpu_over or mem_over:
                pod.condition = PodCondition.RESOURCE_PRESSURE
            elif pod.condition == PodCondition.RESOURCE_PRESSURE:
                pod.condition = PodCondition.HEALTHY
            return pod.condition

    def mark_crashed(self, pod_id: str, reason: str) -> None:
        with self._lock:
            pod = self._require_pod(pod_id)
            pod.phase = PodPhase.FAILED
            pod.condition = PodCondition.CRASHED
            pod.crashed_at = time.time()
            pod.crash_reason = reason

    def terminate(self, pod_id: str) -> None:
        with self._lock:
            pod = self._require_pod(pod_id)
            pod.phase = (
                PodPhase.SUCCEEDED
                if pod.condition == PodCondition.HEALTHY
                else PodPhase.FAILED
            )
            pod.condition = PodCondition.TERMINATED

    def get_state(self, pod_id: str) -> Optional[PodState]:
        with self._lock:
            return self._pods.get(pod_id)

    def list_by_namespace(self, namespace: str) -> list[PodState]:
        with self._lock:
            return [p for p in self._pods.values() if p.namespace == namespace]

    def cleanup_terminated(self) -> int:
        """Phagocytose-aequivalent: kubelet-Garbage-Collection von terminated pods."""
        with self._lock:
            terminated = [
                pid for pid, p in self._pods.items() if p.condition == PodCondition.TERMINATED
            ]
            for pid in terminated:
                del self._pods[pid]
            return len(terminated)

    def _require_pod(self, pod_id: str) -> PodState:
        pod = self._pods.get(pod_id)
        if not pod:
            raise KeyError(f"Pod {pod_id} not found")
        return pod
