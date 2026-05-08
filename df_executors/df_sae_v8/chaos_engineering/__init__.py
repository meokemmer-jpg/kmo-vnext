"""SAE-v8 Chaos-Engineering [CRUX-MK].

Welle-30 W-30-2: Bio-Apoptose+Cell-Boundary-Pattern adaptiert fuer SAE-v8
Hotel-AI-Operations Robustheits-Pruefung.

K_0-Schutz: Mock-only. KEINE echte SAE-Slot-Aktivierung.

Public API:
    SaeChaosOrchestrator, ChaosCampaign, ExperimentResult,
    SaeFailureInjector, FailureMode, MockSlot, SlotVariant, InjectionEvent,
    SaeRobustnessMetrics, RobustnessReport, BoundedVetoOutcome.
"""

from .sae_chaos_orchestrator import (
    ChaosCampaign,
    DEFAULT_RECOVERY_TIMEOUT_SEC,
    ExperimentResult,
    SaeChaosOrchestrator,
)
from .sae_failure_injector import (
    DEFAULT_TOKEN_BUDGET,
    FailureMode,
    InjectionEvent,
    MockSlot,
    SaeFailureInjector,
    SlotVariant,
)
from .sae_robustness_metrics import (
    BoundedVetoOutcome,
    DEFAULT_CASCADE_RADIUS_LIMIT,
    RobustnessReport,
    SaeRobustnessMetrics,
)

__all__ = [
    "BoundedVetoOutcome", "ChaosCampaign", "DEFAULT_CASCADE_RADIUS_LIMIT",
    "DEFAULT_RECOVERY_TIMEOUT_SEC", "DEFAULT_TOKEN_BUDGET", "ExperimentResult",
    "FailureMode", "InjectionEvent", "MockSlot", "RobustnessReport",
    "SaeChaosOrchestrator", "SaeFailureInjector", "SaeRobustnessMetrics",
    "SlotVariant",
]

# CRUX-MK
