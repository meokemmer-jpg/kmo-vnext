# [CRUX-MK]
"""KPM-Pre-Production-Canary (Welle-45 Phase-38, 27. Multi-Domain-Lift).

Bio-Aequivalent: Genetic-Drift-Detection auf Trading-Strategy-Canary-Deploy.
Pattern: Vor Full-Production-Deploy laeuft Strategy parallel als Canary mit
Mini-Lambda (e.g. 1% des Capital), Performance-Drift wird gegen baseline
gemessen, bei Drift > threshold: Auto-Rollback.

Public API:
    from kmo_governance.kpm_pre_production_canary import (
        CanaryStatus,
        CanaryDeployment,
        KPMPreProductionCanary,
    )

CRUX-MK
"""
from .kpm_pre_production_canary import (
    CanaryDeployment,
    CanaryStatus,
    KPMPreProductionCanary,
)

__all__ = [
    "CanaryDeployment",
    "CanaryStatus",
    "KPMPreProductionCanary",
]

# CRUX-MK
