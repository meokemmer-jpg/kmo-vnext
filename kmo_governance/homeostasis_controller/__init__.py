# [CRUX-MK]
"""Homeostasis Controller (Welle-25 Phase-18).

Bio-Aequivalent: Thermoregulation (Hypothalamus-basiert).
Setpoint-basierte Feedback-Regelung fuer System-Health-Metriken: Setpoint-Deviation
triggert Cooling-Mechanismen ueber Schwellen oder Heating-Mechanismen unter Schwellen.
PID-aehnliche Feedback-Regelung mit Rolling-Average-Smoothing.
"""
from .homeostasis_controller import (
    CorrectiveAction,
    HomeostasisController,
    HomeostasisDecision,
    HomeostasisState,
    MetricSample,
)

__all__ = [
    "CorrectiveAction",
    "HomeostasisController",
    "HomeostasisDecision",
    "HomeostasisState",
    "MetricSample",
]

# CRUX-MK
