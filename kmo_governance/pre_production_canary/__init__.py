"""pre_production_canary package [CRUX-MK].

KMO-vNext Welle-10 Phase-6.3 SUBAGENT-E: Canary-Deployment SKELETON.

Bio-Aequivalent: Genetic-Drift-Beobachtung (kleine Population teste neue Allele
unter realen Selektionsbedingungen, bevor Allel sich in Gesamtpopulation
ausbreitet). Wenn neue Allel-Variante schlechtere Fitness zeigt, wird sie
herausselektiert (Auto-Rollback) bevor sie das Gesamtpopulations-Genom
kontaminiert.

Komponenten:
  - CanaryDeployment: Traffic-Split deterministic per request_id-Hash
  - CanaryHealthMonitor: Error-Rate + p99-Latency in Sliding-Windows
  - RollbackTrigger: Decision-Engine mit Cooldown gegen Flapping
  - ProgressiveRollout: Time-based traffic_steps Schedule
  - CanaryAuditLog: Append-only Decision-Trail
"""

from kmo_governance.pre_production_canary.pre_production_canary import (
    CanaryAuditLog,
    CanaryDecisionRecord,
    CanaryDeployment,
    CanaryHealthMonitor,
    CanaryOutcome,
    ProgressiveRollout,
    RollbackDecision,
    RollbackReason,
    RollbackTrigger,
    RolloutStep,
)

__all__ = [
    "CanaryAuditLog",
    "CanaryDecisionRecord",
    "CanaryDeployment",
    "CanaryHealthMonitor",
    "CanaryOutcome",
    "ProgressiveRollout",
    "RollbackDecision",
    "RollbackReason",
    "RollbackTrigger",
    "RolloutStep",
]

# CRUX-MK
