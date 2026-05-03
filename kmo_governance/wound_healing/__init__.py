"""KMO Wound-Healing Module [CRUX-MK].

Welle-9α Phase-1 Modul 2.3: 4-Phase Recovery-Lifecycle nach Saga-FAILED.

Public API:
    from kmo_governance.wound_healing import (
        WoundHealingLifecycle, HealingPhase, HealingContext,
        HealingMetrics, PhaseTransitionError,
        ALLOWED_TRANSITIONS,
    )
"""

from .healing_metrics import HealingMetrics
from .phase_transitions import PhaseTransitionError, validate_transition
from .wound_healing_lifecycle import (
    ALLOWED_TRANSITIONS,
    HealingContext,
    HealingPhase,
    WoundHealingLifecycle,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "HealingContext",
    "HealingMetrics",
    "HealingPhase",
    "PhaseTransitionError",
    "WoundHealingLifecycle",
    "validate_transition",
]

# CRUX-MK
