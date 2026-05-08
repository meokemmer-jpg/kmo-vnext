"""K8s Namespace Apoptosis Isolation [CRUX-MK]

Welle-30-Iter-2 W-30R-3: Bio-Pattern (Apoptose+Cell-Boundary) auf K8s-Pod-Lifecycle
+ Namespace-Resource-Isolation. KEIN Kemmer-Kontext.
"""
from .k8s_pod_lifecycle import (
    PodPhase,
    PodCondition,
    ResourceLimits,
    PodState,
    PodLifecycle,
)
from .k8s_apoptosis_handler import (
    ApoptosisDecision,
    ApoptosisTrigger,
    K8sApoptosisHandler,
)
from .k8s_namespace_boundary import (
    NamespaceQuota,
    NetworkPolicy,
    K8sNamespaceBoundary,
)

__all__ = [
    "PodPhase", "PodCondition", "ResourceLimits", "PodState", "PodLifecycle",
    "ApoptosisDecision", "ApoptosisTrigger", "K8sApoptosisHandler",
    "NamespaceQuota", "NetworkPolicy", "K8sNamespaceBoundary",
]
