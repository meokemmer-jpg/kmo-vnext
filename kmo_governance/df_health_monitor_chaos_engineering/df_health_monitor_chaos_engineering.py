from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4


class DFChaosFault(str, Enum):
    DF_PROCESS_CRASH = "DF_PROCESS_CRASH"
    DF_QUOTA_EXHAUSTED = "DF_QUOTA_EXHAUSTED"
    DF_AUTH_EXPIRED = "DF_AUTH_EXPIRED"
    DF_OUTPUT_CORRUPTED = "DF_OUTPUT_CORRUPTED"
    DF_CRON_TRIGGER_MISSED = "DF_CRON_TRIGGER_MISSED"


class FaultSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DFChaosScenario:
    df_id: str
    fault: DFChaosFault
    severity: FaultSeverity
    scenario_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DFChaosOutcome:
    scenario_id: str
    df_id: str
    fault: DFChaosFault
    severity: FaultSeverity
    success: bool
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict)


class DFHealthMonitorChaosEngineering:
    def __init__(self) -> None:
        self._lock = RLock()
        self._registered_dfs: set[str] = set()
        self._paused = False
        self._outcomes: list[DFChaosOutcome] = []

    def register_df(self, df_id: str) -> None:
        if not df_id or not df_id.strip():
            raise ValueError("df_id must be a non-empty string")

        with self._lock:
            self._registered_dfs.add(df_id)

    def pause_chaos(self, paused: bool = True) -> None:
        with self._lock:
            self._paused = paused

    def inject(self, scenario: DFChaosScenario) -> DFChaosOutcome:
        with self._lock:
            if self._paused:
                outcome = self._failed_outcome(
                    scenario,
                    "chaos injection is paused",
                    {"reason": "paused"},
                )
                self._outcomes.append(outcome)
                return outcome

            if scenario.df_id not in self._registered_dfs:
                outcome = self._failed_outcome(
                    scenario,
                    f"dark factory '{scenario.df_id}' is not registered",
                    {"reason": "unregistered_df"},
                )
                self._outcomes.append(outcome)
                return outcome

            outcome = DFChaosOutcome(
                scenario_id=scenario.scenario_id,
                df_id=scenario.df_id,
                fault=scenario.fault,
                severity=scenario.severity,
                success=True,
                message=self._success_message(scenario),
                metadata=dict(scenario.metadata),
            )
            self._outcomes.append(outcome)
            return outcome

    def get_outcomes(self) -> tuple[DFChaosOutcome, ...]:
        with self._lock:
            return tuple(self._outcomes)

    def _failed_outcome(
        self,
        scenario: DFChaosScenario,
        message: str,
        metadata: Mapping[str, Any],
    ) -> DFChaosOutcome:
        return DFChaosOutcome(
            scenario_id=scenario.scenario_id,
            df_id=scenario.df_id,
            fault=scenario.fault,
            severity=scenario.severity,
            success=False,
            message=message,
            metadata=dict(metadata),
        )

    def _success_message(self, scenario: DFChaosScenario) -> str:
        messages = {
            DFChaosFault.DF_PROCESS_CRASH: "process crash injected",
            DFChaosFault.DF_QUOTA_EXHAUSTED: "quota exhaustion injected",
            DFChaosFault.DF_AUTH_EXPIRED: "auth expiry injected",
            DFChaosFault.DF_OUTPUT_CORRUPTED: "output corruption injected",
            DFChaosFault.DF_CRON_TRIGGER_MISSED: "missed cron trigger injected",
        }
        return messages[scenario.fault]
