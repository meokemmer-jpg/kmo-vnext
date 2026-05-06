"""KMO backpressure_engine [CRUX-MK].

Welle-13 Phase-8 SUBAGENT-L: Adaptive rate limiting + queue overflow prevention.

Bio-Aequivalent: Baroreflex (Druck-Sensoren -> reflexive Kapazitaets-Anpassung).

Pattern-Inspiration:
  - mock_hotel_server.MockRateLimiter (statisches Token-Bucket)
  - abs_tier_engine.HormonePool (Dynamic-Adjustment)
  - sigma_switch (Schmitt-Trigger Hysterese)
"""

from __future__ import annotations

from kmo_governance.backpressure_engine.backpressure_engine import (
    AdaptiveCapacity,
    BackpressureController,
    ControllerDecision,
    Decision,
    PressureSensor,
    PressureSignal,
    QueueOverflowGuard,
    SignalType,
)

__all__ = [
    "AdaptiveCapacity",
    "BackpressureController",
    "ControllerDecision",
    "Decision",
    "PressureSensor",
    "PressureSignal",
    "QueueOverflowGuard",
    "SignalType",
]
