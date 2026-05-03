from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from df_89.patterns.m09_tcs import ResponseRegulator, Sensor


class MemoryStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.failures: list[tuple[str, str]] = []

    def record_processed_event(self, event_id: str, payload: dict[str, Any]) -> None:
        self.events.append((event_id, payload))

    def mark_failure(
        self, tool: str, reason: str, dead_link: bool = False, auth_walled_domain: bool = False
    ) -> str:
        self.failures.append((tool, reason))
        return f"{tool}:{reason}"


def sensor(value: float, seconds: int = 0, sensor_class: str = "temperature") -> Sensor:
    return Sensor(
        signal_value=value,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds),
        source_id="s-1",
        sensor_class=sensor_class,
    )


def test_phosphorylate_increases_state() -> None:
    rr = ResponseRegulator(sensor_class="temperature", theta_on=2.0, theta_off=1.0, k1=0.5)

    rr.phosphorylate(sensor(4.0))

    assert rr.state == pytest.approx(2.0)


def test_dephosphorylate_decays_toward_zero() -> None:
    rr = ResponseRegulator(sensor_class="temperature", theta_on=2.0, theta_off=1.0, state=10.0)

    rr.dephosphorylate(0.25)
    rr.dephosphorylate(1.0)

    assert rr.state == pytest.approx(0.0)


def test_hysteresis_theta_on_gt_theta_off() -> None:
    with pytest.raises(ValueError, match="theta_on"):
        ResponseRegulator(sensor_class="temperature", theta_on=1.0, theta_off=1.0)


def test_actuation_only_above_theta_on() -> None:
    fired: list[str] = []
    rr = ResponseRegulator(
        sensor_class="temperature",
        theta_on=2.0,
        theta_off=1.0,
        actuator=lambda _rr, sig: fired.append(sig.source_id),
    )

    rr.phosphorylate(sensor(1.5))
    assert rr.should_actuate() is False
    rr.phosphorylate(sensor(1.0, seconds=1))

    assert rr.should_actuate() is True
    assert fired == ["s-1"]


def test_no_re_actuation_within_cooldown() -> None:
    fired: list[int] = []
    rr = ResponseRegulator(
        sensor_class="temperature",
        theta_on=1.0,
        theta_off=0.5,
        cooldown_s=10.0,
        actuator=lambda _rr, _sig: fired.append(len(fired)),
    )

    rr.phosphorylate(sensor(2.0, seconds=0))
    assert rr.should_actuate() is True
    rr.state = 0.0
    assert rr.should_actuate() is False
    rr.phosphorylate(sensor(2.0, seconds=5))

    assert rr.should_actuate() is False
    assert fired == [0]


def test_specificity_subscription() -> None:
    rr = ResponseRegulator(sensor_class="temperature", theta_on=1.0, theta_off=0.5)

    rr.phosphorylate(sensor(10.0, sensor_class="pressure"))

    assert rr.state == pytest.approx(0.0)


def test_steady_state_under_constant_signal() -> None:
    rr = ResponseRegulator(sensor_class="temperature", theta_on=100.0, theta_off=90.0, k1=0.3, k2=0.2)

    for i in range(60):
        rr.phosphorylate(sensor(4.0, seconds=i))

    assert rr.state == pytest.approx(6.0, rel=1e-5)


def test_audit_trail_written_to_knowledge_store() -> None:
    store = MemoryStore()
    rr = ResponseRegulator(sensor_class="temperature", theta_on=1.0, theta_off=0.5, knowledge_store=store)

    rr.phosphorylate(sensor(1.0))
    rr.phosphorylate(sensor(1.0, seconds=1))

    assert [event[1]["event"] for event in store.events] == ["phosphorylate", "phosphorylate"]
