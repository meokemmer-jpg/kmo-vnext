"""K8s Namespace Boundary [CRUX-MK].

Welle-30-Iter-2 W-30R-3: ResourceQuota + NetworkPolicy als Cell-Boundary.
Multi-Tenancy-Isolation per Namespace.

Domain-Mapping:
  Cell-Membrane -> Namespace-Boundary
  Tight-Junction -> NetworkPolicy (allow/deny)
  Membrane-Receptor -> ResourceQuota (Pod-Limits)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional

from .k8s_pod_lifecycle import PodLifecycle, ResourceLimits


@dataclass(frozen=True)
class NamespaceQuota:
    """Pflicht-Quota pro Namespace (analog K8s ResourceQuota)."""

    namespace: str
    max_pods: int
    max_total_cpu_millicores: int
    max_total_memory_mib: int

    def __post_init__(self) -> None:
        if self.max_pods <= 0:
            raise ValueError("max_pods must be positive")
        if self.max_total_cpu_millicores <= 0 or self.max_total_memory_mib <= 0:
            raise ValueError("max_total_cpu/memory must be positive")


@dataclass(frozen=True)
class NetworkPolicy:
    """Allow/Deny-Liste fuer Cross-Namespace-Communication (analog K8s NetworkPolicy)."""

    namespace: str
    allow_egress_to: frozenset[str] = field(default_factory=frozenset)
    allow_ingress_from: frozenset[str] = field(default_factory=frozenset)

    def can_egress_to(self, target_namespace: str) -> bool:
        return target_namespace in self.allow_egress_to or target_namespace == self.namespace

    def can_ingress_from(self, source_namespace: str) -> bool:
        return source_namespace in self.allow_ingress_from or source_namespace == self.namespace


class K8sNamespaceBoundary:
    """Namespace-Isolation-Manager.

    K11 Cascade-Containment: Pod-Crash in namespace_a triggert NICHT namespace_b.
    """

    def __init__(self, lifecycle: PodLifecycle) -> None:
        self._lifecycle = lifecycle
        self._quotas: dict[str, NamespaceQuota] = {}
        self._policies: dict[str, NetworkPolicy] = {}
        self._lock = threading.RLock()

    def register_namespace(
        self,
        quota: NamespaceQuota,
        policy: Optional[NetworkPolicy] = None,
    ) -> None:
        with self._lock:
            self._quotas[quota.namespace] = quota
            if policy is not None:
                if policy.namespace != quota.namespace:
                    raise ValueError("Policy namespace must match quota namespace")
                self._policies[quota.namespace] = policy

    def admit_pod(
        self,
        namespace: str,
        limits: ResourceLimits,
    ) -> tuple[bool, str]:
        """Admission-Check: passt Pod in Namespace-Quota?"""
        with self._lock:
            quota = self._quotas.get(namespace)
            if not quota:
                return False, f"Namespace {namespace} not registered"

            current_pods = self._lifecycle.list_by_namespace(namespace)
            active_pods = [p for p in current_pods if p.condition.value != "Terminated"]

            if len(active_pods) >= quota.max_pods:
                return False, f"Pod limit exceeded ({quota.max_pods})"

            current_cpu = sum(p.limits.cpu_millicores for p in active_pods)
            current_mem = sum(p.limits.memory_mib for p in active_pods)

            if current_cpu + limits.cpu_millicores > quota.max_total_cpu_millicores:
                return False, "Total CPU quota exceeded"
            if current_mem + limits.memory_mib > quota.max_total_memory_mib:
                return False, "Total memory quota exceeded"

            return True, "Admitted"

    def check_cross_namespace_traffic(
        self,
        source_namespace: str,
        target_namespace: str,
        direction: str = "egress",
    ) -> bool:
        """NetworkPolicy-Check: erlaubt Cross-Namespace-Communication?"""
        if direction not in ("egress", "ingress"):
            raise ValueError("Direction must be 'egress' or 'ingress'")
        with self._lock:
            if direction == "egress":
                policy = self._policies.get(source_namespace)
                if not policy:
                    return False  # default-deny ohne Policy
                return policy.can_egress_to(target_namespace)
            else:
                policy = self._policies.get(target_namespace)
                if not policy:
                    return False
                return policy.can_ingress_from(source_namespace)

    def cascade_containment_score(
        self,
        crashed_namespace: str,
        peer_namespaces: list[str],
    ) -> float:
        """K11 Cascade-Containment-Metrik: 1.0 = perfekt isoliert.

        Score = 1.0 - (peer_pods_unhealthy / peer_pods_total).
        """
        peer_total = 0
        peer_unhealthy = 0
        for ns in peer_namespaces:
            if ns == crashed_namespace:
                continue
            for state in self._lifecycle.list_by_namespace(ns):
                peer_total += 1
                if state.condition.value not in ("Healthy", "Terminated"):
                    peer_unhealthy += 1
        if peer_total == 0:
            return 1.0
        return 1.0 - (peer_unhealthy / peer_total)
