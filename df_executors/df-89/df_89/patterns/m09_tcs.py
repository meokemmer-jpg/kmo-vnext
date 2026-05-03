"""CRUX-MK M09: Two-Component-System sensor-effector pattern."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator


Actuator = Callable[["ResponseRegulator", "Sensor"], None]


class Sensor(BaseModel):
    """Sensor reading with a specificity tag.

    Pre: signal_value >= 0; source_id and sensor_class are non-empty.
    Post: timestamp is timezone-aware UTC when omitted.
    """

    model_config = ConfigDict(frozen=True)

    signal_value: float = Field(ge=0.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_id: str = Field(min_length=1)
    sensor_class: str = Field(min_length=1)

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


@dataclass
class ResponseRegulator:
    """Mutable response-regulator state for TCS-style decisions.

    Pre: theta_on > theta_off, rates are non-negative, sensor_class is non-empty.
    Post: state follows dR*/dt = k1*S - k2*R* under Euler step dt=1.0s.
    """

    sensor_class: str
    theta_on: float
    theta_off: float
    k1: float = 1.0
    k2: float = 0.1
    cooldown_s: float = 0.0
    actuator: Actuator | None = None
    knowledge_store: Any | None = None
    state: float = 0.0
    active: bool = False
    last_actuation_ts: datetime | None = None
    last_sensor: Sensor | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Pre: fields initialized. Post: invariants enforced."""
        if self.theta_on <= self.theta_off:
            raise ValueError("theta_on must be greater than theta_off")
        if self.k1 < 0.0 or self.k2 < 0.0:
            raise ValueError("k1 and k2 must be non-negative")
        if self.cooldown_s < 0.0:
            raise ValueError("cooldown_s must be non-negative")
        if not self.sensor_class.strip():
            raise ValueError("sensor_class must not be blank")
        if self.state < 0.0:
            raise ValueError("state must be non-negative")

    def phosphorylate(self, signal: Sensor) -> float:
        """Apply one HK/RR phosphorylation step.

        Pre: signal is a Sensor reading.
        Post: matching sensor_class updates state; all calls write audit.
        """
        previous = self.state
        matched = signal.sensor_class == self.sensor_class
        self.last_sensor = signal
        if matched:
            delta = self.k1 * signal.signal_value - self.k2 * self.state
            self.state = max(0.0, self.state + delta)
        self._audit(
            "phosphorylate",
            {
                "source_id": signal.source_id,
                "sensor_class": signal.sensor_class,
                "subscribed_sensor_class": self.sensor_class,
                "matched": matched,
                "signal_value": signal.signal_value,
                "state_before": previous,
                "state_after": self.state,
            },
        )
        return self.state

    def dephosphorylate(self, rate: float) -> float:
        """Decay phosphorylated regulator toward zero.

        Pre: rate is non-negative.
        Post: state is reduced monotonically and never below zero.
        """
        if rate < 0.0:
            raise ValueError("rate must be non-negative")
        previous = self.state
        self.state = max(0.0, self.state - rate * self.state)
        self._audit("dephosphorylate", {"rate": rate, "state_before": previous, "state_after": self.state})
        return self.state

    def should_actuate(self) -> bool:
        """Evaluate hysteretic actuator state and fire on a permitted rising edge.

        Pre: regulator state has been updated from zero or more Sensor readings.
        Post: returns True above theta_on, False below theta_off, else preserves state.
        """
        previous = self.active
        desired = self.active
        if self.state > self.theta_on:
            desired = True
        elif self.state < self.theta_off:
            desired = False

        suppressed = False
        if desired and not previous and self._within_cooldown():
            desired = False
            suppressed = True

        self.active = desired
        fired = desired and not previous
        if fired:
            self._fire_actuator()

        self._audit(
            "should_actuate",
            {
                "state": self.state,
                "theta_on": self.theta_on,
                "theta_off": self.theta_off,
                "previous": previous,
                "result": self.active,
                "fired": fired,
                "suppressed": suppressed,
            },
        )
        return self.active

    def _within_cooldown(self) -> bool:
        if self.cooldown_s <= 0.0 or self.last_actuation_ts is None:
            return False
        now = self._clock()
        return (now - self.last_actuation_ts).total_seconds() < self.cooldown_s

    def _fire_actuator(self) -> None:
        now = self._clock()
        self.last_actuation_ts = now
        if self.actuator is None:
            return
        try:
            fallback = Sensor(
                signal_value=0.0,
                timestamp=now,
                source_id="response-regulator",
                sensor_class=self.sensor_class,
            )
            self.actuator(self, self.last_sensor or fallback)
        except Exception as exc:
            if self.knowledge_store is not None:
                self.knowledge_store.mark_failure("m09_tcs.actuator", f"{type(exc).__name__}: {exc}")
            raise

    def _audit(self, event: str, payload: dict[str, Any]) -> None:
        if self.knowledge_store is None:
            return
        event_id = f"m09_tcs:{event}:{time.time_ns()}"
        self.knowledge_store.record_processed_event(
            event_id,
            {
                "pattern": "m09_tcs",
                "event": event,
                "at": datetime.now(timezone.utc).isoformat(),
                **payload,
            },
        )

    def _clock(self) -> datetime:
        if self.last_sensor is not None:
            return self.last_sensor.timestamp
        return datetime.now(timezone.utc)


__all__ = ["Actuator", "ResponseRegulator", "Sensor"]
