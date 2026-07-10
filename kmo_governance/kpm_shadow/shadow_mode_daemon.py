# [CRUX-MK]
"""Shadow-Mode-Daemon fuer KPM Variante-D (W70-CROWN AP-K4).

Ablauf (1x taeglich, werktags 18:10 via LaunchAgent com.kemmer.kpm-shadow):
  1. K16-Spawn-Mutex (mkdir-Lock + pgrep-Selbstcheck, Pattern per
     ~/.claude/rules/df-akzeptanz-kriterien.md K16, Reuse aus
     _df_common/k16_mutex_master + cfl_engine).
  2. Neuesten DAX-Close ziehen: `data_loader.refresh_cache()` (Netz);
     bei JEDEM Netz-Fehler graceful OFFLINE-Fallback auf den lokalen Cache
     (`load_dax()`) — der Daemon liefert dann eine Entscheidung auf dem
     letzten gecachten Close und markiert `data_refresh: "offline-cache"`.
  3. Variante-D-Sizing-Entscheidung der Engine berechnen — deterministisch
     ueber den kompletten Backtest-Pfad (`backtest_runner.run_backtest`,
     Profil `pilot-conservative`): der letzte DailyRecord IST der heutige
     Shadow-Zustand (Equity-Pfad, Drawdown-Cascade, Regime — kein separater
     State-File, kein Drift zwischen Backtest und Shadow).
  4. Append-only-Ledger `kpm_shadow/ledger.jsonl` (1 Entry pro Handelstag,
     idempotent: existiert der Tag schon, wird NICHT dupliziert).
  5. Cash-Quote-Monitor (AP-K5) prueft den neuen Eintrag sofort.

LEDGER-HEADER (Zeile 1): dokumentiert den Start der 3-Monats-Shadow-Uhr
per ~/.claude/rules/kpm-sizing.md Phase-1 (Shadow-Mode 3+ Monate Paper
VOR jedem Real-Capital-Gedanken). Uhr-Start = Datum des ersten Laufs.

K_0-DISCLAIMER (Verfassungsrang): PAPER ONLY. Dieses Modul hat KEINEN
Broker-Zugang, importiert KEINE Trading-/Order-API, fuehrt KEINE Order aus
und gibt KEINE Anlageempfehlung. Echtgeld ist technisch unmoeglich ohne
neuen Code und ausschliesslich Martin-Phronesis (K_0-Sperr-Liste).
Engine-Status: ALPHA-NOT-K0-READY.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from kmo_governance.kpm_backtest.backtest_runner import PROFILES, run_backtest
from kmo_governance.kpm_backtest.data_loader import PriceBar, load_dax, refresh_cache

__all__ = [
    "LEDGER_PATH",
    "LOCK_NAME",
    "LOCK_ROOT",
    "STALE_LOCK_THRESHOLD_S",
    "SHADOW_PROFILE",
    "K16Locked",
    "acquire_lock",
    "release_lock",
    "other_instances_running",
    "load_bars",
    "build_ledger_entry",
    "append_entry",
    "read_ledger",
    "main",
]

logger = logging.getLogger(__name__)

# --- Benannte Konstanten (keine Magic Numbers) --------------------------------

# Append-only Paper-Ledger (per Auftrag W70 AP-K4: kpm_shadow/ledger.jsonl)
LEDGER_PATH: Path = Path(__file__).resolve().parent / "ledger.jsonl"

# K16-Mutex: mkdir-Lock unter /tmp (Pattern k16_mutex_master / rules K16)
LOCK_NAME: str = "kpm-shadow"
LOCK_ROOT: Path = Path("/tmp")
STALE_LOCK_THRESHOLD_S: int = 21600  # 6h, per rules/df-akzeptanz-kriterien.md K16

# Shadow-Profil: Thomas-First Pilot (rules/kpm-sizing.md Phase-1)
SHADOW_PROFILE: str = "pilot-conservative"

# Exit-Code bei K16-Veto (Konvention der existierenden DFs, z.B. cfl_engine)
EXIT_K16_VETO: int = 3

# pgrep-Muster fuer den Selbstcheck (Prozess-Ebene, zusaetzlich zum Lock)
PGREP_PATTERN: str = "shadow_mode_daemon"
PGREP_TIMEOUT_S: float = 5.0


class K16Locked(RuntimeError):
    """Zweite Instanz laeuft bereits (K16-Spawn-Mutex-Veto)."""


# --- K16-Spawn-Mutex (mkdir atomic + Stale-Reclaim + pgrep-Selbstcheck) --------

def _lock_dir(name: str = LOCK_NAME, root: Path = LOCK_ROOT) -> Path:
    return root / f"{name}.lock"


def _is_stale(lock_dir: Path, threshold_s: int = STALE_LOCK_THRESHOLD_S) -> bool:
    """Lock aelter als threshold_s Sekunden => stale (Auto-Reclaim erlaubt)."""
    try:
        age_s = datetime.now(tz=timezone.utc).timestamp() - lock_dir.stat().st_mtime
    except FileNotFoundError:
        return False
    return age_s > threshold_s


def acquire_lock(
    name: str = LOCK_NAME,
    root: Path = LOCK_ROOT,
    stale_threshold_s: int = STALE_LOCK_THRESHOLD_S,
) -> Path:
    """Atomarer mkdir-Lock (K16). Stale-Locks (> 6h) werden reclaimed.

    Raises:
        K16Locked: wenn eine frische zweite Instanz den Lock haelt.
    """
    lock = _lock_dir(name, root)
    if lock.is_dir() and _is_stale(lock, stale_threshold_s):
        logger.warning("K16: stale Lock (%s) — reclaim", lock)
        _remove_lock(lock)
    try:
        lock.mkdir()  # atomar: genau EIN Prozess gewinnt
    except FileExistsError:
        raise K16Locked(f"K16-VETO: Lock {lock} wird gehalten") from None
    (lock / "pid").write_text(str(os.getpid()), encoding="utf-8")
    return lock


def _remove_lock(lock: Path) -> None:
    pid_file = lock / "pid"
    if pid_file.exists():
        pid_file.unlink()
    lock.rmdir()


def release_lock(name: str = LOCK_NAME, root: Path = LOCK_ROOT) -> bool:
    """Lock freigeben. True wenn ein Lock entfernt wurde."""
    lock = _lock_dir(name, root)
    if not lock.is_dir():
        return False
    _remove_lock(lock)
    return True


def other_instances_running(pattern: str = PGREP_PATTERN) -> bool:
    """pgrep-Selbstcheck (K16 Engine-Layer): laeuft eine ANDERE Instanz?

    Graceful: bei pgrep-Fehler/Timeout wird False geliefert (Lock-Layer
    bleibt die primaere Absicherung).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=PGREP_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("K16: pgrep-Selbstcheck nicht verfuegbar — Lock-Layer traegt")
        return False
    my_pid = os.getpid()
    pids = [int(p) for p in result.stdout.split() if p.strip().isdigit()]
    return any(p != my_pid for p in pids)


# --- Daten + Entscheidung -------------------------------------------------------

def load_bars(refresh: bool = True, data_dir: Optional[Path] = None) -> List[PriceBar]:
    """Kurs-Historie laden: optional Netz-Refresh, IMMER Offline-Fallback.

    Post: aufsteigend sortierte EOD-Bars aus dem lokalen Cache; bei
    Netz-Fehler bleibt der letzte Cache-Stand die Quelle (graceful offline).
    """
    kwargs = {} if data_dir is None else {"data_dir": data_dir}
    if refresh:
        try:
            refresh_cache(**kwargs)
            logger.info("Daten-Refresh OK (Yahoo+Onvista)")
        except Exception as exc:  # noqa: BLE001 — jeder Netz-Fehler ist non-fatal
            logger.warning("Refresh fehlgeschlagen (%s) — Offline-Fallback auf Cache", exc)
    return load_dax(**kwargs)


def build_ledger_entry(bars: Sequence[PriceBar], profile: str = SHADOW_PROFILE,
                       data_refresh: str = "refreshed") -> Dict[str, object]:
    """Variante-D-Entscheidung fuer den NEUESTEN Close als Ledger-Entry.

    Deterministisch: kompletter Backtest-Pfad (run_backtest), letzter
    DailyRecord = heutiger Shadow-Zustand. Kein separater Equity-State.

    Pre: len(bars) >= 2. Post: JSON-serialisierbares Dict mit den
    Pflicht-Feldern date/close/decision/exposure/dd_state/regime_flag/crux.
    """
    result = run_backtest(bars, PROFILES[profile])
    rec = result.records[-1]
    decision = f"reject:{rec.reject_gate}" if rec.rejected else "accept"
    return {
        "type": "entry",
        "date": rec.day.isoformat(),
        "close": rec.close,
        "decision": decision,
        "exposure": round(rec.fraction, 6),
        "cash_quote_pct": round((1.0 - rec.fraction) * 100.0, 4),
        "dd_state": rec.level,
        "drawdown": round(rec.drawdown, 6),
        "regime_flag": rec.regime,
        "equity_paper_eur": round(rec.equity, 2),
        "profile": profile,
        "trading_days_in_path": result.trading_days,
        "data_refresh": data_refresh,
        "mode": "PAPER",
        "recorded_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "crux": "[CRUX-MK]",
    }


# --- Append-only-Ledger ----------------------------------------------------------

def _header_line(first_entry_date: str) -> Dict[str, object]:
    return {
        "type": "header",
        "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "shadow_clock_start": first_entry_date,
        "shadow_clock_note": (
            "3-Monats-Shadow-Uhr per ~/.claude/rules/kpm-sizing.md Phase-1 "
            "startet mit diesem ersten Ledger-Eintrag. PAPER ONLY — kein "
            "Echtgeld vor Ablauf + Martin-Phronesis (K_0-Sperr-Liste)."
        ),
        "ledger_semantics": "append-only; 1 Entry pro Handelstag; idempotent",
        "engine": "kpm_sizing_engine.KPMVarianteDDecisionEngine (Variante-D)",
        "profile": SHADOW_PROFILE,
        "mode": "PAPER",
        "crux": "[CRUX-MK]",
    }


def read_ledger(ledger_path: Path = LEDGER_PATH) -> List[Dict[str, object]]:
    """Alle JSONL-Zeilen des Ledgers (Header + Entries)."""
    if not ledger_path.exists():
        return []
    rows: List[Dict[str, object]] = []
    with ledger_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_entry(entry: Dict[str, object], ledger_path: Path = LEDGER_PATH) -> str:
    """Append-only + idempotent pro Handelstag.

    Returns: "appended" | "duplicate" (Entry fuer dieses Datum existiert).
    Post: Ledger hat genau einen Header (Zeile 1) und max 1 Entry pro Datum.
    """
    rows = read_ledger(ledger_path)
    existing_dates = {r.get("date") for r in rows if r.get("type") == "entry"}
    if entry["date"] in existing_dates:
        logger.info("Ledger: Entry fuer %s existiert bereits — idempotent skip", entry["date"])
        return "duplicate"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        if not rows:
            fh.write(json.dumps(_header_line(str(entry["date"])), ensure_ascii=False) + "\n")
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return "appended"


# --- CLI / Daemon-Einstieg -------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """1 Daemon-Lauf: Lock -> Daten -> Entscheidung -> Ledger -> Cash-Monitor."""
    parser = argparse.ArgumentParser(description="KPM Shadow-Mode-Daemon (PAPER only)")
    parser.add_argument("--no-refresh", action="store_true",
                        help="kein Netz-Abruf, nur Offline-Cache")
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--profile", default=SHADOW_PROFILE, choices=sorted(PROFILES))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        # LOCK_ROOT bewusst als Call-Time-Global (testbar via monkeypatch)
        acquire_lock(name=LOCK_NAME, root=LOCK_ROOT)
    except K16Locked as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_K16_VETO
    try:
        if other_instances_running():
            print("K16-VETO: andere shadow_mode_daemon-Instanz laeuft (pgrep)", file=sys.stderr)
            return EXIT_K16_VETO
        refresh = not args.no_refresh
        bars = load_bars(refresh=refresh)
        entry = build_ledger_entry(
            bars, profile=args.profile,
            data_refresh="refreshed" if refresh else "offline-cache",
        )
        status = append_entry(entry, ledger_path=args.ledger)

        # AP-K5: Cash-Quote-Invariante pro neuem Eintrag pruefen
        from kmo_governance.kpm_shadow.cash_quota_monitor import check_entry
        alarm = check_entry(entry)

        print(json.dumps({
            "status": status,
            "date": entry["date"],
            "close": entry["close"],
            "decision": entry["decision"],
            "exposure": entry["exposure"],
            "cash_quote_pct": entry["cash_quote_pct"],
            "dd_state": entry["dd_state"],
            "regime_flag": entry["regime_flag"],
            "cash_alarm": alarm is not None,
            "mode": "PAPER",
            "crux": "[CRUX-MK]",
        }, ensure_ascii=False))
        return 0
    finally:
        release_lock(name=LOCK_NAME, root=LOCK_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
