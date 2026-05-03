"""KMO Multi-Signal-Policy Module [CRUX-MK].

Welle-9γ Phase-3 Modul 3.1: Hill-N-Inputs + Markov-State-Machine + Binary-Approval-Adapter.
"""

from .multi_signal_policy import (
    DEFAULT_TRANSITIONS,
    MultiSignalAggregator,
    PolicyState,
    PolicyStateMachine,
    SignalSpec,
    binary_approval_adapter,
)

__all__ = [
    "DEFAULT_TRANSITIONS",
    "MultiSignalAggregator",
    "PolicyState",
    "PolicyStateMachine",
    "SignalSpec",
    "binary_approval_adapter",
]

# CRUX-MK
