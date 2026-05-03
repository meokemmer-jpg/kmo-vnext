"""Tests for sleep_cycles [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.2: Zirkadian + Off-Peak.
"""

from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import pytest

_KMO_ROOT = Path(__file__).resolve().parents[3]
if str(_KMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_KMO_ROOT))

from kmo_governance.sleep_cycles import (  # noqa: E402
    CycleType,
    SleepCyclesEngine,
    SleepWindow,
    default_schedule_for_hotel,
)


# ---------- SleepWindow validation ----------


def test_sleep_window_validates_hours():
    SleepWindow(start_hour=2, end_hour=6)  # ok
    with pytest.raises(ValueError):
        SleepWindow(start_hour=24, end_hour=6)
    with pytest.raises(ValueError):
        SleepWindow(start_hour=2, end_hour=-1)
    with pytest.raises(ValueError):
        SleepWindow(start_hour=2, end_hour=6, weekday=7)


def test_sleep_window_same_day():
    w = SleepWindow(start_hour=2, end_hour=6)
    assert w.contains(dt.datetime(2026, 5, 3, 3, 0)) is True
    assert w.contains(dt.datetime(2026, 5, 3, 6, 0)) is False  # exclusive end
    assert w.contains(dt.datetime(2026, 5, 3, 1, 59)) is False


def test_sleep_window_cross_midnight():
    w = SleepWindow(start_hour=22, end_hour=6)
    assert w.contains(dt.datetime(2026, 5, 3, 23, 0)) is True
    assert w.contains(dt.datetime(2026, 5, 3, 1, 0)) is True
    assert w.contains(dt.datetime(2026, 5, 3, 12, 0)) is False


def test_sleep_window_weekday_filter():
    w = SleepWindow(start_hour=2, end_hour=6, weekday=6)  # Sunday only
    sunday_2am = dt.datetime(2026, 5, 3, 3, 0)  # 2026-05-03 was a Sunday
    assert sunday_2am.weekday() == 6
    assert w.contains(sunday_2am) is True
    monday_2am = dt.datetime(2026, 5, 4, 3, 0)
    assert w.contains(monday_2am) is False


# ---------- Engine: should_sleep_now ----------


def _at_local(year, month, day, hour, minute=0, tz_offset=1.0) -> float:
    """Return UNIX-timestamp for local-time year-month-day-hour:minute @ tz_offset.

    Constructed via timezone-aware UTC datetime (no system-tz interference).
    """
    # Local hour = UTC hour + tz_offset, so UTC = local - tz_offset
    utc_aware = dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc) \
                 - dt.timedelta(hours=tz_offset)
    return utc_aware.timestamp()


def test_should_sleep_now_inside_window():
    fake_now = {"t": _at_local(2026, 5, 3, 3, 0, tz_offset=1.0)}  # 03:00 local
    eng = SleepCyclesEngine(clock=lambda: fake_now["t"], timezone_offset_hours=1.0)
    eng.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))
    assert eng.should_sleep_now() is True


def test_should_sleep_now_outside_window():
    fake_now = {"t": _at_local(2026, 5, 3, 12, 0, tz_offset=1.0)}  # 12:00 local
    eng = SleepCyclesEngine(clock=lambda: fake_now["t"], timezone_offset_hours=1.0)
    eng.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))
    assert eng.should_sleep_now() is False


def test_should_sleep_now_no_windows_returns_false():
    eng = SleepCyclesEngine()
    assert eng.should_sleep_now() is False


# ---------- in_window per cycle type ----------


def test_in_window_per_cycle_type():
    fake_now = {"t": _at_local(2026, 5, 3, 3, 0, tz_offset=1.0)}  # Sun 03:00
    eng = SleepCyclesEngine(clock=lambda: fake_now["t"], timezone_offset_hours=1.0)
    eng.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))
    eng.add_window(CycleType.WEEKLY, SleepWindow(start_hour=2, end_hour=6, weekday=6))

    assert eng.in_window(CycleType.DAILY) is True
    assert eng.in_window(CycleType.WEEKLY) is True
    assert eng.in_window(CycleType.MONTHLY) is False  # no monthly window registered


# ---------- Cleanup-Callbacks (glymphatic) ----------


def test_glymphatic_cleanup_invokes_callbacks():
    eng = SleepCyclesEngine()
    counters = {"cb1": 0, "cb2": 0}

    def cb1() -> int:
        counters["cb1"] += 1
        return 5  # pruned 5 items

    def cb2() -> int:
        counters["cb2"] += 1
        return 3  # pruned 3 items

    eng.register_cleanup_callback(cb1)
    eng.register_cleanup_callback(cb2)

    result = eng.trigger_glymphatic_cleanup()
    assert result.success is True
    assert result.items_pruned == 8
    assert counters == {"cb1": 1, "cb2": 1}


def test_glymphatic_cleanup_handles_callback_exception():
    eng = SleepCyclesEngine()

    def bad_cb() -> int:
        raise RuntimeError("boom")

    eng.register_cleanup_callback(bad_cb)
    result = eng.trigger_glymphatic_cleanup()
    assert result.success is False
    assert "boom" in (result.error or "")


# ---------- Memory Consolidation (REM-Sleep) ----------


def test_memory_consolidation_invokes_callbacks():
    eng = SleepCyclesEngine()
    eng.register_consolidation_callback(lambda: 10)
    eng.register_consolidation_callback(lambda: 20)
    result = eng.memory_consolidation()
    assert result.success is True
    assert result.items_processed == 30


# ---------- Monthly action: idempotence per calendar month ----------


def test_monthly_action_runs_once_per_month():
    fake_now = {"t": _at_local(2026, 5, 3, 3, 0, tz_offset=0.0)}
    eng = SleepCyclesEngine(clock=lambda: fake_now["t"], timezone_offset_hours=0.0)
    eng.register_monthly_callback(lambda: 5)

    # First call this month: runs
    r1 = eng.trigger_monthly_action()
    assert r1 is not None
    assert r1.items_pruned == 5

    # Second call same month: skipped
    r2 = eng.trigger_monthly_action()
    assert r2 is None

    # Advance to next month: runs again
    fake_now["t"] = _at_local(2026, 6, 1, 3, 0, tz_offset=0.0)
    r3 = eng.trigger_monthly_action()
    assert r3 is not None


# ---------- Cortisol Awakening Response (CAR) ----------


def test_cortisol_awakening_response_curve():
    eng = SleepCyclesEngine()
    # At t=0: factor=0
    assert eng.cortisol_awakening_response(0.0) == pytest.approx(0.0)
    # At t=tau (1800s): factor ~ 1 - exp(-1) ≈ 0.632
    assert eng.cortisol_awakening_response(1800.0) == pytest.approx(1 - math.exp(-1))
    # At t -> infinity: factor -> 1
    assert eng.cortisol_awakening_response(100_000.0) == pytest.approx(1.0, abs=1e-3)


def test_cortisol_awakening_response_validates_inputs():
    eng = SleepCyclesEngine()
    with pytest.raises(ValueError):
        eng.cortisol_awakening_response(-1.0)
    with pytest.raises(ValueError):
        eng.cortisol_awakening_response(60.0, tau_seconds=0)


# ---------- default_schedule_for_hotel ----------


def test_default_schedule_for_hotel_provides_daily_and_weekly():
    eng = default_schedule_for_hotel(timezone_offset_hours=1.0)
    assert len(eng.windows(CycleType.DAILY)) == 1
    assert len(eng.windows(CycleType.WEEKLY)) == 1
    daily = eng.windows(CycleType.DAILY)[0]
    assert daily.start_hour == 2 and daily.end_hour == 6
    weekly = eng.windows(CycleType.WEEKLY)[0]
    assert weekly.weekday == 6  # Sunday


# ---------- Integration: Cleanup runs in window ----------


def test_full_cycle_callbacks_fire_in_window():
    fake_now = {"t": _at_local(2026, 5, 3, 3, 0, tz_offset=1.0)}
    eng = SleepCyclesEngine(clock=lambda: fake_now["t"], timezone_offset_hours=1.0)
    eng.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))

    items_pruned_via_cb = {"n": 0}

    def cleanup_cb() -> int:
        items_pruned_via_cb["n"] += 7
        return 7

    eng.register_cleanup_callback(cleanup_cb)

    if eng.should_sleep_now():
        result = eng.trigger_glymphatic_cleanup()
        assert result.success is True
        assert items_pruned_via_cb["n"] == 7


# ---------- Action history audit ----------


# ---------- Patch F4 (Welle-9-delta Cross-LLM Finding #4 "DST-Hardening") ----------


def test_f4_zoneinfo_handles_dst_transition_spring():
    """F4: 2026-03-29 02:00 CET -> 03:00 CEST (DST-spring-forward).

    A sleep-window 02:00-06:00 should respect actual local-time after DST jump.
    """
    try:
        from zoneinfo import ZoneInfo  # noqa: F401
    except ImportError:
        pytest.skip("zoneinfo not available")

    # 2026-03-29: spring-forward day in Europe/Berlin (02:00 -> 03:00)
    # At UTC 03:30 (= local 05:30 CEST), should be inside 02-06 window
    utc_tz = dt.timezone.utc
    utc_after_dst = dt.datetime(2026, 3, 29, 3, 30, tzinfo=utc_tz)
    fake_now = {"t": utc_after_dst.timestamp()}

    eng = SleepCyclesEngine(
        clock=lambda: fake_now["t"],
        timezone_name="Europe/Berlin",
    )
    eng.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))
    # After DST: UTC 03:30 = local 05:30 CEST -> in window
    assert eng.should_sleep_now() is True


def test_f4_zoneinfo_handles_dst_transition_fall():
    """F4: 2026-10-25 03:00 CEST -> 02:00 CET (DST-fall-back, ambiguous hour).

    UTC 01:30 = local 02:30 CEST = local 02:30 CET (ambiguous).
    Both fall in window 02-06.
    """
    try:
        from zoneinfo import ZoneInfo  # noqa: F401
    except ImportError:
        pytest.skip("zoneinfo not available")

    utc_tz = dt.timezone.utc
    utc_at_fall = dt.datetime(2026, 10, 25, 1, 30, tzinfo=utc_tz)
    fake_now = {"t": utc_at_fall.timestamp()}

    eng = SleepCyclesEngine(
        clock=lambda: fake_now["t"],
        timezone_name="Europe/Berlin",
    )
    eng.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))
    assert eng.should_sleep_now() is True


def test_f4_invalid_timezone_name_falls_back():
    """F4: invalid IANA-name falls back to manual offset, doesn't crash."""
    eng = SleepCyclesEngine(
        timezone_offset_hours=2.0,
        timezone_name="Invalid/NotARealZone",
    )
    # Should fall back: zoneinfo set to None, manual offset used
    assert eng._zoneinfo is None


def test_f4_no_timezone_name_uses_manual_offset():
    """F4: backwards-compat — when timezone_name=None, manual offset is used."""
    eng = SleepCyclesEngine(timezone_offset_hours=3.0)
    assert eng._zoneinfo is None
    # _now_local should still produce manual-offset result
    assert eng._tz_offset_hours == 3.0


def test_f4_zoneinfo_winter_local_correct():
    """F4: ZoneInfo gives correct CET (UTC+1) in winter."""
    try:
        from zoneinfo import ZoneInfo  # noqa: F401
    except ImportError:
        pytest.skip("zoneinfo not available")

    # 2026-01-15 12:00 UTC = 13:00 CET local
    utc_winter = dt.datetime(2026, 1, 15, 12, 0, tzinfo=dt.timezone.utc)
    fake_now = {"t": utc_winter.timestamp()}

    eng = SleepCyclesEngine(
        clock=lambda: fake_now["t"],
        timezone_name="Europe/Berlin",
    )
    local = eng._now_local()
    assert local.hour == 13  # CET = UTC+1


def test_action_history_records_all():
    eng = SleepCyclesEngine()
    eng.register_cleanup_callback(lambda: 3)
    eng.register_consolidation_callback(lambda: 7)

    eng.trigger_glymphatic_cleanup()
    eng.memory_consolidation()
    history = eng.action_history()
    assert len(history) == 2
    assert history[0].cycle_type == CycleType.DAILY
    assert history[0].items_pruned == 3
    assert history[1].cycle_type == CycleType.WEEKLY
    assert history[1].items_processed == 7
