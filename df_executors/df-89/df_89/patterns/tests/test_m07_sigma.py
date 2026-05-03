"""CRUX-MK tests for M-07 Sigma-Faktor-Switch."""

import pytest

from df_89.patterns.m07_sigma import Mode, ModeSwitch, SigmaFactor


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_sigma(mode: Mode, concentration: float, affinity_K: float = 1.0) -> SigmaFactor:
    return SigmaFactor(mode=mode, concentration=concentration, affinity_K=affinity_K)


def add_pair(
    switch: ModeSwitch,
    first: tuple[Mode, float],
    second: tuple[Mode, float],
) -> None:
    switch.add_sigma(make_sigma(*first))
    switch.add_sigma(make_sigma(*second))


def test_compute_dominance_normalizes_to_1() -> None:
    switch = ModeSwitch()
    switch.add_sigma(make_sigma(Mode.NORMAL, 2.0))
    switch.add_sigma(make_sigma(Mode.DEGRADED, 1.0))
    switch.add_sigma(make_sigma(Mode.RECOVERY, 1.0))

    dominance = switch.compute_dominance()

    assert sum(dominance.values()) == pytest.approx(1.0)
    assert dominance[Mode.NORMAL] == pytest.approx(0.5)


def test_mode_switch_with_hysteresis() -> None:
    switch = ModeSwitch(theta_on=0.60, theta_off=0.40)
    add_pair(switch, (Mode.NORMAL, 0.55), (Mode.DEGRADED, 0.45))
    assert switch.tick() is Mode.NORMAL

    switch = ModeSwitch(theta_on=0.60, theta_off=0.40)
    add_pair(switch, (Mode.NORMAL, 0.35), (Mode.DEGRADED, 0.65))
    assert switch.tick(owner="test") is Mode.DEGRADED

    switch._sigmas.clear()
    add_pair(switch, (Mode.NORMAL, 0.45), (Mode.DEGRADED, 0.55))
    assert switch.tick(owner="test") is Mode.DEGRADED


def test_no_switch_within_cooldown() -> None:
    clock = ManualClock()
    switch = ModeSwitch(min_dwell_time_s=10.0, _clock=clock)
    add_pair(switch, (Mode.NORMAL, 0.2), (Mode.DEGRADED, 0.8))

    assert switch.tick(owner="cooldown-test") is Mode.NORMAL
    clock.advance(10.0)
    assert switch.tick(owner="cooldown-test") is Mode.DEGRADED


def test_observer_notification_on_change() -> None:
    events: list[tuple[Mode, Mode]] = []
    switch = ModeSwitch()
    switch.register_observer(lambda old, new: events.append((old, new)))
    add_pair(switch, (Mode.NORMAL, 0.2), (Mode.RECOVERY, 0.8))

    switch.tick()
    assert events == [(Mode.NORMAL, Mode.RECOVERY)]


def test_observer_not_called_on_stay() -> None:
    events: list[tuple[Mode, Mode]] = []
    switch = ModeSwitch()
    switch.register_observer(lambda old, new: events.append((old, new)))
    add_pair(switch, (Mode.NORMAL, 0.55), (Mode.DEGRADED, 0.45))

    switch.tick()
    assert events == []


def test_invalid_hysteresis_raises() -> None:
    with pytest.raises(ValueError, match="theta_on"):
        ModeSwitch(theta_on=0.40, theta_off=0.40)


def test_panic_mode_takes_priority() -> None:
    switch = ModeSwitch(theta_on=0.60, theta_off=0.40)
    switch.add_sigma(make_sigma(Mode.NORMAL, 0.50, affinity_K=1.0))
    switch.add_sigma(make_sigma(Mode.PANIC, 0.10, affinity_K=0.1))

    dominance = switch.compute_dominance()

    assert dominance[Mode.PANIC] > dominance[Mode.NORMAL]
    assert switch.tick(owner="watchdog") is Mode.PANIC


def test_owner_tag_recorded() -> None:
    switch = ModeSwitch()
    add_pair(switch, (Mode.NORMAL, 0.2), (Mode.PANIC, 0.8))

    switch.tick(owner="sentinel")
    assert switch.audit_trail[-1].owner == "sentinel"
    assert switch.audit_trail[-1].current is Mode.PANIC
