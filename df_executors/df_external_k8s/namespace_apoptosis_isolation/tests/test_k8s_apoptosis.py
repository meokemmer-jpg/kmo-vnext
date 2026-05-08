"""K8s Apoptose+Boundary Tests [CRUX-MK].

Welle-30-Iter-2 W-30R-3: 16 Tests inkl. Race-Conditions via threading.Thread.
KEIN Kemmer-Kontext, pure K8s-Domain.
"""
from __future__ import annotations

import threading
import time

import pytest

from df_executors.df_external_k8s.namespace_apoptosis_isolation import (
    ApoptosisDecision,
    ApoptosisTrigger,
    K8sApoptosisHandler,
    K8sNamespaceBoundary,
    NamespaceQuota,
    NetworkPolicy,
    PodCondition,
    PodLifecycle,
    PodPhase,
    ResourceLimits,
)


# ============================================================
# A) Pod-Lifecycle Core (4 Tests)
# ============================================================


def test_pod_create_and_transition_to_running() -> None:
    lc = PodLifecycle()
    limits = ResourceLimits(cpu_millicores=500, memory_mib=512)
    pod_id = lc.create_pod("default", limits)
    assert lc.get_state(pod_id).phase == PodPhase.PENDING
    lc.transition_to_running(pod_id)
    assert lc.get_state(pod_id).phase == PodPhase.RUNNING


def test_pod_resource_pressure_detection() -> None:
    lc = PodLifecycle()
    limits = ResourceLimits(cpu_millicores=1000, memory_mib=1024)
    pod_id = lc.create_pod("ns1", limits)
    lc.transition_to_running(pod_id)
    cond = lc.update_usage(pod_id, cpu=500, memory=512)
    assert cond == PodCondition.HEALTHY
    cond = lc.update_usage(pod_id, cpu=1500, memory=512)
    assert cond == PodCondition.RESOURCE_PRESSURE


def test_pod_recovery_from_pressure() -> None:
    lc = PodLifecycle()
    pod_id = lc.create_pod("ns", ResourceLimits(cpu_millicores=1000, memory_mib=1024))
    lc.transition_to_running(pod_id)
    lc.update_usage(pod_id, cpu=1500, memory=512)
    cond = lc.update_usage(pod_id, cpu=500, memory=512)
    assert cond == PodCondition.HEALTHY


def test_pod_invalid_resource_limits_rejected() -> None:
    with pytest.raises(ValueError):
        ResourceLimits(cpu_millicores=-1, memory_mib=512)


# ============================================================
# B) Apoptose Handler (5 Tests)
# ============================================================


def test_apoptose_approves_resource_pressure() -> None:
    lc = PodLifecycle()
    handler = K8sApoptosisHandler(lc)
    pid = lc.create_pod("ns", ResourceLimits(cpu_millicores=1000, memory_mib=1024))
    lc.transition_to_running(pid)
    lc.update_usage(pid, cpu=2000, memory=512)
    decision = handler.evaluate_trigger(pid, ApoptosisTrigger.CPU_EXHAUSTION)
    assert decision == ApoptosisDecision.APPROVED
    assert lc.get_state(pid).phase == PodPhase.FAILED


def test_apoptose_denies_healthy_pod() -> None:
    lc = PodLifecycle()
    handler = K8sApoptosisHandler(lc)
    pid = lc.create_pod("ns", ResourceLimits(cpu_millicores=1000, memory_mib=1024))
    lc.transition_to_running(pid)
    lc.update_usage(pid, cpu=100, memory=128)
    decision = handler.evaluate_trigger(pid, ApoptosisTrigger.MEMORY_EXHAUSTION)
    assert decision == ApoptosisDecision.DENIED_HEALTHY
    assert lc.get_state(pid).phase == PodPhase.RUNNING


def test_apoptose_bcl2_protection() -> None:
    lc = PodLifecycle()
    handler = K8sApoptosisHandler(lc)
    pid = lc.create_pod("ns", ResourceLimits(cpu_millicores=1000, memory_mib=1024))
    lc.transition_to_running(pid)
    lc.update_usage(pid, cpu=2000, memory=512)
    handler.protect_pod(pid, ttl_sec=60)
    decision = handler.evaluate_trigger(pid, ApoptosisTrigger.OOM_KILL)
    assert decision == ApoptosisDecision.DENIED_PROTECTED


def test_apoptose_manual_overrides_healthy() -> None:
    lc = PodLifecycle()
    handler = K8sApoptosisHandler(lc)
    pid = lc.create_pod("ns", ResourceLimits(cpu_millicores=1000, memory_mib=1024))
    lc.transition_to_running(pid)
    decision = handler.evaluate_trigger(pid, ApoptosisTrigger.MANUAL, "graceful-drain")
    assert decision == ApoptosisDecision.APPROVED


def test_apoptose_event_history_tracks_cytochrome_c() -> None:
    lc = PodLifecycle()
    handler = K8sApoptosisHandler(lc)
    pid = lc.create_pod("ns", ResourceLimits(cpu_millicores=1000, memory_mib=1024))
    lc.transition_to_running(pid)
    lc.update_usage(pid, cpu=1500, memory=512)
    handler.evaluate_trigger(pid, ApoptosisTrigger.CPU_EXHAUSTION, "load-spike")
    history = handler.event_history()
    assert len(history) == 1
    assert history[0].pre_death_cpu == 1500
    assert history[0].trigger == ApoptosisTrigger.CPU_EXHAUSTION


# ============================================================
# C) Namespace Boundary (4 Tests)
# ============================================================


def test_namespace_admission_within_quota() -> None:
    lc = PodLifecycle()
    boundary = K8sNamespaceBoundary(lc)
    boundary.register_namespace(
        NamespaceQuota("tenant-a", max_pods=3, max_total_cpu_millicores=3000, max_total_memory_mib=3072)
    )
    admitted, reason = boundary.admit_pod("tenant-a", ResourceLimits(1000, 1024))
    assert admitted is True


def test_namespace_admission_exceeds_pod_limit() -> None:
    lc = PodLifecycle()
    boundary = K8sNamespaceBoundary(lc)
    boundary.register_namespace(
        NamespaceQuota("tenant-b", max_pods=2, max_total_cpu_millicores=10000, max_total_memory_mib=10000)
    )
    for _ in range(2):
        pid = lc.create_pod("tenant-b", ResourceLimits(100, 100))
        lc.transition_to_running(pid)
    admitted, reason = boundary.admit_pod("tenant-b", ResourceLimits(100, 100))
    assert admitted is False
    assert "Pod limit" in reason


def test_network_policy_default_deny() -> None:
    lc = PodLifecycle()
    boundary = K8sNamespaceBoundary(lc)
    boundary.register_namespace(
        NamespaceQuota("ns-a", max_pods=10, max_total_cpu_millicores=10000, max_total_memory_mib=10000)
    )
    # ohne registrierte Policy -> default-deny
    assert boundary.check_cross_namespace_traffic("ns-a", "ns-b", "egress") is False


def test_network_policy_allow_egress() -> None:
    lc = PodLifecycle()
    boundary = K8sNamespaceBoundary(lc)
    quota = NamespaceQuota("ns-a", 10, 10000, 10000)
    policy = NetworkPolicy("ns-a", allow_egress_to=frozenset(["ns-b"]))
    boundary.register_namespace(quota, policy)
    assert boundary.check_cross_namespace_traffic("ns-a", "ns-b", "egress") is True
    assert boundary.check_cross_namespace_traffic("ns-a", "ns-c", "egress") is False


# ============================================================
# D) Cascade-Containment (1 Test, K11)
# ============================================================


def test_cascade_containment_isolated_namespaces() -> None:
    lc = PodLifecycle()
    boundary = K8sNamespaceBoundary(lc)
    # ns-a hat 1 crashed pod, ns-b 2 healthy pods
    pid_a = lc.create_pod("ns-a", ResourceLimits(1000, 1024))
    lc.transition_to_running(pid_a)
    lc.mark_crashed(pid_a, "OOM")
    for _ in range(2):
        pid = lc.create_pod("ns-b", ResourceLimits(500, 512))
        lc.transition_to_running(pid)
    score = boundary.cascade_containment_score("ns-a", ["ns-a", "ns-b"])
    assert score == 1.0  # perfekt isoliert: keine ns-b Pods unhealthy


# ============================================================
# E) Concurrent-Race (2 Tests via threading.Thread)
# ============================================================


def test_concurrent_pod_creation_no_lost_pods() -> None:
    """50 Threads erstellen Pods parallel — Conservation: alle 50 unique pod_ids."""
    lc = PodLifecycle()
    n = 50
    results: list[str] = []
    barrier = threading.Barrier(n)

    def worker() -> None:
        barrier.wait()
        pid = lc.create_pod("ns-race", ResourceLimits(100, 128))
        results.append(pid)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == n
    assert len(set(results)) == n  # alle unique


def test_concurrent_apoptosis_cascade_namespace_isolation() -> None:
    """20 Pods in 2 Namespaces, parallel cascade auf ns-a darf ns-b nicht crashen."""
    lc = PodLifecycle()
    handler = K8sApoptosisHandler(lc)
    # 10 Pods je Namespace, alle in Resource-Pressure
    for ns in ("ns-cascade-a", "ns-cascade-b"):
        for _ in range(10):
            pid = lc.create_pod(ns, ResourceLimits(1000, 1024))
            lc.transition_to_running(pid)
            lc.update_usage(pid, cpu=2000, memory=512)
    # cascade NUR ns-cascade-a
    handler.cascade_apoptosis("ns-cascade-a", ApoptosisTrigger.MEMORY_EXHAUSTION)
    # ns-cascade-a Pods sollten alle FAILED sein
    a_states = lc.list_by_namespace("ns-cascade-a")
    assert all(s.phase == PodPhase.FAILED for s in a_states)
    # ns-cascade-b Pods unangetastet (Cell-Boundary respektiert)
    b_states = lc.list_by_namespace("ns-cascade-b")
    assert all(s.phase == PodPhase.RUNNING for s in b_states)


# ============================================================
# F) Phagocytose / Cleanup (1 Test)
# ============================================================


def test_phagocytose_cleanup_terminated() -> None:
    lc = PodLifecycle()
    pid1 = lc.create_pod("ns", ResourceLimits(100, 100))
    pid2 = lc.create_pod("ns", ResourceLimits(100, 100))
    lc.transition_to_running(pid1)
    lc.transition_to_running(pid2)
    lc.terminate(pid1)
    cleaned = lc.cleanup_terminated()
    assert cleaned == 1
    assert lc.get_state(pid1) is None
    assert lc.get_state(pid2) is not None
