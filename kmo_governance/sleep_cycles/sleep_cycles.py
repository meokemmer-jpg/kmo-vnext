"""KMO sleep_cycles Engine [CRUX-MK].

Welle-9-delta Phase-4 Modul 4.2: Zirkadian + Off-Peak-Maintenance.

Bio-Aequivalent: Zirkadiane Rhythmen (24h-Schlaf-Wach-Zyklus + REM-Sleep + glymphatisches
System der Hirn-Reinigung waehrend Tiefschlaf). Memory-Consolidation passiert in REM.
Cortisol Awakening Response (CAR) bringt Koerper sanft zur Aktivitaet vor Aufwachen.

Anorg-Mapping: A-21 Periodische Phasen / Off-Peak-Schedule.

Komponenten:
  - SleepWindow: definiert Zeitfenster pro Hotel-Local-Time
  - SleepCyclesEngine: should_sleep_now(), trigger_glymphatic_cleanup(), memory_consolidation()
  - cortisol_awakening_response (CAR): graduelles Aufwachen vor Peak

Daily-Cycle:  Off-Peak-Window (default 02:00-06:00 local-time)
Weekly-Cycle: Tiefere Maintenance (Sonntag 02:00-06:00 local-time)
Monthly-Cycle: 1. des Monats - Knowledge-Decay-Action

Math:
  cortisol_level(t_to_wake) = exp(-t_to_wake/tau)  (graduelle Aktivierung)
"""

from __future__ import annotations

import datetime as dt
import enum
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    # Patch F4 (Welle-9-delta Cross-LLM Finding #4 "DST-Hardening"):
    # zoneinfo handles DST transitions automatically (Python 3.9+).
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except ImportError:
    ZoneInfo = None  # type: ignore
    _HAS_ZONEINFO = False


# ---------- Cycle Types ----------

class CycleType(str, enum.Enum):
    DAILY = "daily"        # off-peak window each day
    WEEKLY = "weekly"      # deeper maintenance once per week
    MONTHLY = "monthly"    # knowledge-decay action once per month


# ---------- SleepWindow ----------

@dataclass(frozen=True)
class SleepWindow:
    """Time-window in hotel-local-time during which sleep-mode is active.

    Pre: 0 <= start_hour < 24, 0 <= end_hour < 24
    Post: window crosses midnight if end_hour <= start_hour (e.g. 22:00 to 06:00)
    """

    start_hour: int     # local-time hour [0,23]
    end_hour: int       # local-time hour [0,23]
    weekday: Optional[int] = None  # None = all days; 0=Mon, 6=Sun

    def __post_init__(self):
        if not (0 <= self.start_hour <= 23):
            raise ValueError(f"start_hour {self.start_hour} not in [0,23]")
        if not (0 <= self.end_hour <= 23):
            raise ValueError(f"end_hour {self.end_hour} not in [0,23]")
        if self.weekday is not None and not (0 <= self.weekday <= 6):
            raise ValueError(f"weekday {self.weekday} not in [0,6]")

    def contains(self, local_dt: dt.datetime) -> bool:
        """True if local_dt falls within this sleep-window."""
        if self.weekday is not None and local_dt.weekday() != self.weekday:
            return False
        h = local_dt.hour
        if self.start_hour < self.end_hour:
            # Same-day window e.g. 02:00-06:00
            return self.start_hour <= h < self.end_hour
        else:
            # Cross-midnight window e.g. 22:00-06:00
            return h >= self.start_hour or h < self.end_hour


# ---------- Cycle Action Result ----------

@dataclass
class CycleActionResult:
    """Outcome of a sleep-cycle action (cleanup, consolidation, decay)."""

    cycle_type: CycleType
    timestamp: float
    success: bool
    items_processed: int
    items_pruned: int
    error: Optional[str] = None


# ---------- SleepCyclesEngine ----------

class SleepCyclesEngine:
    """Zirkadian-Rhythm-Manager + Off-Peak-Maintenance.

    Pre: at least one daily window registered
    Post:
      - should_sleep_now() returns True if any registered window contains current local time
      - trigger_glymphatic_cleanup() invokes registered cleanup callbacks
      - memory_consolidation() invokes knowledge_decay callbacks
      - cortisol_awakening_response(t_to_wake) returns activation factor [0,1]
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        timezone_offset_hours: float = 0.0,
        timezone_name: Optional[str] = None,
    ) -> None:
        """Patch F4: optional `timezone_name` (IANA-name like "Europe/Berlin") for
        full DST-support. Falls back to manual `timezone_offset_hours` if zoneinfo
        unavailable or no name given.

        Pre: timezone_name resolves to ZoneInfo or None
        Post: _now_local() returns DST-correct local time when timezone_name set
        """
        self._clock = clock
        self._tz_offset_hours = float(timezone_offset_hours)
        self._timezone_name = timezone_name
        self._zoneinfo: Optional[Any] = None
        if timezone_name is not None and _HAS_ZONEINFO:
            try:
                self._zoneinfo = ZoneInfo(timezone_name)
            except Exception:
                # Invalid IANA-name: fallback to manual offset
                self._zoneinfo = None
        self._windows: dict[CycleType, list[SleepWindow]] = {
            CycleType.DAILY: [],
            CycleType.WEEKLY: [],
            CycleType.MONTHLY: [],
        }
        # Registered callbacks (e.g. for cleanup / decay-engine integration)
        self._cleanup_callbacks: list[Callable[[], int]] = []   # returns items_pruned
        self._consolidation_callbacks: list[Callable[[], int]] = []  # returns items_processed
        self._monthly_callbacks: list[Callable[[], int]] = []
        self._action_history: list[CycleActionResult] = []
        self._lock = threading.RLock()
        self._last_monthly_run_month: Optional[tuple[int, int]] = None  # (year, month)

    # ---------- Window registration ----------

    def add_window(self, cycle_type: CycleType, window: SleepWindow) -> None:
        with self._lock:
            self._windows[cycle_type].append(window)

    def windows(self, cycle_type: CycleType) -> list[SleepWindow]:
        with self._lock:
            return list(self._windows[cycle_type])

    # ---------- Local-time helper ----------

    def _now_local(self) -> dt.datetime:
        """Patch F4: returns timezone-aware (or naive-equivalent) local datetime.

        - If ZoneInfo available + timezone_name set: full DST-correct local time
        - Otherwise: manual offset (DST not handled, simple +/-N hours)
        """
        unix_now = self._clock()
        if self._zoneinfo is not None:
            # DST-correct: convert via UTC -> ZoneInfo (handles spring-forward + fall-back)
            return dt.datetime.fromtimestamp(unix_now, tz=dt.timezone.utc).astimezone(
                self._zoneinfo
            ).replace(tzinfo=None)  # naive for backwards-compat with SleepWindow.contains
        # Fallback: manual offset (legacy behavior, no DST)
        return dt.datetime.fromtimestamp(unix_now, tz=dt.timezone.utc).replace(
            tzinfo=None
        ) + dt.timedelta(hours=self._tz_offset_hours)

    # ---------- should_sleep_now ----------

    def should_sleep_now(self) -> bool:
        """True if currently within any registered sleep-window (daily/weekly)."""
        with self._lock:
            now = self._now_local()
            for w in self._windows[CycleType.DAILY]:
                if w.contains(now):
                    return True
            for w in self._windows[CycleType.WEEKLY]:
                if w.contains(now):
                    return True
            return False

    def in_window(self, cycle_type: CycleType) -> bool:
        """Check whether current time is in a window of the given cycle type."""
        with self._lock:
            now = self._now_local()
            return any(w.contains(now) for w in self._windows[cycle_type])

    # ---------- Callback registration ----------

    def register_cleanup_callback(self, cb: Callable[[], int]) -> None:
        """Register a glymphatic-cleanup callback (returns items_pruned)."""
        with self._lock:
            self._cleanup_callbacks.append(cb)

    def register_consolidation_callback(self, cb: Callable[[], int]) -> None:
        """Register a memory-consolidation callback (knowledge_decay use/decay logic)."""
        with self._lock:
            self._consolidation_callbacks.append(cb)

    def register_monthly_callback(self, cb: Callable[[], int]) -> None:
        """Register a monthly action callback (e.g. knowledge_decay.prune)."""
        with self._lock:
            self._monthly_callbacks.append(cb)

    # ---------- Sleep-cycle actions ----------

    def trigger_glymphatic_cleanup(self) -> CycleActionResult:
        """System-weite GC im Sleep-Mode. Invokes all registered cleanup-callbacks."""
        with self._lock:
            total_pruned = 0
            error: Optional[str] = None
            try:
                for cb in self._cleanup_callbacks:
                    total_pruned += cb()
                success = True
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                success = False
            result = CycleActionResult(
                cycle_type=CycleType.DAILY,
                timestamp=self._clock(),
                success=success,
                items_processed=len(self._cleanup_callbacks),
                items_pruned=total_pruned,
                error=error,
            )
            self._action_history.append(result)
            return result

    def memory_consolidation(self) -> CycleActionResult:
        """REM-Sleep-Analog: process consolidation callbacks (knowledge_decay)."""
        with self._lock:
            total_processed = 0
            error: Optional[str] = None
            try:
                for cb in self._consolidation_callbacks:
                    total_processed += cb()
                success = True
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                success = False
            result = CycleActionResult(
                cycle_type=CycleType.WEEKLY,
                timestamp=self._clock(),
                success=success,
                items_processed=total_processed,
                items_pruned=0,
                error=error,
            )
            self._action_history.append(result)
            return result

    def trigger_monthly_action(self) -> Optional[CycleActionResult]:
        """Monthly cycle: invoked at most once per calendar-month.

        Returns None if already-run-this-month.
        """
        with self._lock:
            now = self._now_local()
            current_month = (now.year, now.month)
            if self._last_monthly_run_month == current_month:
                return None
            self._last_monthly_run_month = current_month
            total_pruned = 0
            error: Optional[str] = None
            try:
                for cb in self._monthly_callbacks:
                    total_pruned += cb()
                success = True
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                success = False
            result = CycleActionResult(
                cycle_type=CycleType.MONTHLY,
                timestamp=self._clock(),
                success=success,
                items_processed=len(self._monthly_callbacks),
                items_pruned=total_pruned,
                error=error,
            )
            self._action_history.append(result)
            return result

    # ---------- Cortisol Awakening Response (CAR) ----------

    def cortisol_awakening_response(
        self, time_to_wake_seconds: float, tau_seconds: float = 1800.0
    ) -> float:
        """Activation factor [0,1] approaching wake-time.

        At t=0 (sleep-mode): returns 0
        At time_to_wake=tau: returns ~0.63
        At time_to_wake -> infinity: returns 1.0

        Pre: time_to_wake_seconds >= 0; tau_seconds > 0
        Post: result in [0,1]
        """
        if time_to_wake_seconds < 0:
            raise ValueError("time_to_wake_seconds must be >= 0")
        if tau_seconds <= 0:
            raise ValueError("tau_seconds must be > 0")
        # 1 - exp(-t/tau): rises from 0 to 1
        return 1.0 - math.exp(-time_to_wake_seconds / tau_seconds)

    # ---------- Audit ----------

    def action_history(self) -> list[CycleActionResult]:
        with self._lock:
            return list(self._action_history)


# ---------- Default-Schedule helper ----------

def default_schedule_for_hotel(timezone_offset_hours: float = 1.0) -> SleepCyclesEngine:
    """Convenience-Setup with sensible defaults for an EU-hotel.

    Daily window: 02:00-06:00 local-time (off-peak)
    Weekly window: Sunday 02:00-06:00 (deeper maintenance)
    Monthly: invoked on 1st of each month inside daily window
    """
    eng = SleepCyclesEngine(timezone_offset_hours=timezone_offset_hours)
    eng.add_window(CycleType.DAILY, SleepWindow(start_hour=2, end_hour=6))
    eng.add_window(CycleType.WEEKLY, SleepWindow(start_hour=2, end_hour=6, weekday=6))  # Sunday
    return eng


# CRUX-MK
