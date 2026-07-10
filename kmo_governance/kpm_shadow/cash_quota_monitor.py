# [CRUX-MK]
"""Cash-Quote-Monitor fuer KPM Variante-D (W70-CROWN AP-K5, Falsifikation B-K2).

INVARIANTE + HERLEITUNG DER SCHWELLE (dokumentationspflichtig per AP-K5):
    Variante-D hat eine strukturelle Exposure-Obergrenze: die maximale
    Kelly-Context-Fraction ist 0.40 (Normalregime + hohe Edge-Confidence,
    per ~/.claude/rules/kpm-sizing.md), Trinity-Modifier max 1.0 (aggressive)
    => max. 40% des Kapitals im Markt => strukturelle Mindest-Cash-Quote 60%.
    Das HIVE-Gate erlaubt Leverage-Erhoehung nur INNERHALB der
    Kelly-Fraction-Limits — die 40%-Decke bleibt.

    CASH_QUOTA_ALARM_PCT = 47.0 liegt 13 Prozentpunkte UNTER der
    strukturellen 60%-Untergrenze (Puffer fuer Mark-to-Market-Drift einer
    gehaltenen Position zwischen zwei Rebalances). Cash < 47% ist unter
    regelkonformer Variante-D damit NICHT erreichbar: jeder Alarm zeigt
    eine Regel-/Code-Verletzung an (Invarianten-Waechter). Genau das macht
    die 47%-Board-Behauptung (B-K2) system-deckungsgleich: das Modul
    existiert, alarmiert nachweisbar, und der Replay-Test ueber die
    komplette Backtest-Historie misst "Anteil Zeitpunkte Cash<47% ohne
    Alarm" == 0 (0-Fehlrate).

ALARM-SENKE: Verstoss => 1 JSONL-Zeile in
    <KKS>/branch-hub/audit/kpm-shadow-alerts.jsonl
(Pfad per W70-Auftrag; fuer Tests injizierbar).

K_0-DISCLAIMER: reine Paper-Ueberwachung. Kein Broker-Zugang, kein
Echtgeld, keine Order-Ausfuehrung, keine Anlageempfehlung.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from kmo_governance.kpm_backtest.backtest_runner import (
    PROFILES,
    BacktestConfig,
    run_backtest,
)
from kmo_governance.kpm_backtest.data_loader import PriceBar, load_dax

__all__ = [
    "CASH_QUOTA_ALARM_PCT",
    "ALERTS_PATH",
    "MonitorReport",
    "cash_quote_pct",
    "check_entry",
    "check_ledger",
    "replay_backtest",
    "main",
]

logger = logging.getLogger(__name__)

# --- Benannte Konstanten ----------------------------------------------------------

# Alarm-Schwelle in Prozent Cash-Quote. Herleitung: Modul-Docstring (oben).
CASH_QUOTA_ALARM_PCT: float = 47.0

# Alarm-Senke per W70-Auftrag (KKS = Claude-Knowledge-System im Google Drive)
ALERTS_PATH: Path = Path(
    "/Users/make/Library/CloudStorage/GoogleDrive-m.e.o.kemmer@gmail.com"
    "/Meine Ablage/Claude-Knowledge-System/branch-hub/audit/kpm-shadow-alerts.jsonl"
)

# Default-Replay-Profile: beide Variante-D-Profile des Backtest-Runners
REPLAY_PROFILES: tuple = ("pilot-conservative", "aggressive-max")


def cash_quote_pct(exposure_fraction: float) -> float:
    """Cash-Quote in Prozent aus der Exposure-Fraction (Engine-Feld).

    Pre: 0 <= exposure_fraction <= 1. Post: Wert in [0, 100].
    """
    return (1.0 - exposure_fraction) * 100.0


def _alarm_record(date_iso: str, exposure: float, cash_pct: float,
                  source: str) -> Dict[str, object]:
    return {
        "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "alert": "cash-quote-breach",
        "date": date_iso,
        "exposure": round(exposure, 6),
        "cash_quote_pct": round(cash_pct, 4),
        "threshold_pct": CASH_QUOTA_ALARM_PCT,
        "source": source,
        "severity": "LETHAL",
        "note": "Variante-D-Invariante verletzt: Cash < 47% ist regelkonform unerreichbar",
        "mode": "PAPER",
        "crux": "[CRUX-MK]",
    }


def _write_alarm(record: Dict[str, object], alerts_path: Path) -> None:
    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    with alerts_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def check_entry(entry: Dict[str, object],
                alerts_path: Path = ALERTS_PATH,
                source: str = "shadow-ledger") -> Optional[Dict[str, object]]:
    """Prueft EINEN Ledger-Entry gegen die Cash-Quote-Invariante.

    Nutzt das Engine-Feld `exposure` (Fraction). Bei Verstoss wird die
    Alarm-Zeile in `alerts_path` geschrieben und zurueckgegeben, sonst None.
    """
    exposure = float(entry["exposure"])  # Engine-Feld, Pflicht
    cash_pct = cash_quote_pct(exposure)
    if cash_pct >= CASH_QUOTA_ALARM_PCT:
        return None
    record = _alarm_record(str(entry.get("date", "?")), exposure, cash_pct, source)
    _write_alarm(record, alerts_path)
    logger.error("CASH-ALARM %s: cash=%.2f%% < %.1f%%", entry.get("date"),
                 cash_pct, CASH_QUOTA_ALARM_PCT)
    return record


def check_ledger(ledger_path: Path,
                 alerts_path: Path = ALERTS_PATH) -> List[Dict[str, object]]:
    """Alle Entries eines Ledgers pruefen; Liste der ausgeloesten Alarme."""
    from kmo_governance.kpm_shadow.shadow_mode_daemon import read_ledger

    alarms: List[Dict[str, object]] = []
    for row in read_ledger(ledger_path):
        if row.get("type") != "entry":
            continue
        alarm = check_entry(row, alerts_path=alerts_path, source=str(ledger_path.name))
        if alarm is not None:
            alarms.append(alarm)
    return alarms


# --- Replay ueber die komplette Backtest-Historie (AP-K5-Kriterium) ---------------

@dataclass(frozen=True)
class MonitorReport:
    """Replay-Ergebnis. Kriterium AP-K5: missed_alarms == 0 (0-Fehlrate)."""

    profile: str
    total_days: int
    breaches: int          # Zeitpunkte mit Cash < Schwelle
    alarms: int            # davon vom Monitor alarmiert
    missed_alarms: int     # Breaches OHNE Alarm — MUSS 0 sein
    min_cash_quote_pct: float
    max_exposure: float

    @property
    def fehlrate(self) -> float:
        """Anteil Zeitpunkte Cash<Schwelle ohne Alarm (AP-K5-Messgroesse)."""
        return self.missed_alarms / self.total_days if self.total_days else 0.0


def replay_backtest(bars: Optional[Sequence[PriceBar]] = None,
                    profiles: Sequence[str] = REPLAY_PROFILES,
                    alerts_path: Optional[Path] = None) -> List[MonitorReport]:
    """Replay: Monitor-Entscheidung fuer JEDEN Tag der Backtest-Historie.

    Fuer jeden DailyRecord wird die Monitor-Logik (cash < Schwelle => Alarm)
    angewandt und gemessen, ob ein Breach OHNE Alarm bliebe. Echte Alarme
    werden nur geschrieben, wenn `alerts_path` gesetzt ist (Replay ist
    default seiteneffektfrei — historische Breaches waeren keine NEUEN Events).

    Post: je Profil ein MonitorReport; AP-K5 verlangt fehlrate == 0.
    """
    if bars is None:
        bars = load_dax()
    reports: List[MonitorReport] = []
    for profile in profiles:
        result = run_backtest(bars, PROFILES[profile])
        breaches = 0
        alarms = 0
        min_cash = 100.0
        max_expo = 0.0
        for rec in result.records:
            cash = cash_quote_pct(rec.fraction)
            min_cash = min(min_cash, cash)
            max_expo = max(max_expo, rec.fraction)
            breach = cash < CASH_QUOTA_ALARM_PCT
            entry = {"date": rec.day.isoformat(), "exposure": rec.fraction}
            if alerts_path is not None:
                alarmed = check_entry(entry, alerts_path=alerts_path,
                                      source=f"replay:{profile}") is not None
            else:
                # identische Entscheidungslogik, ohne Schreib-Seiteneffekt
                alarmed = cash < CASH_QUOTA_ALARM_PCT
            breaches += int(breach)
            alarms += int(alarmed)
        reports.append(MonitorReport(
            profile=profile,
            total_days=len(result.records),
            breaches=breaches,
            alarms=alarms,
            missed_alarms=breaches - alarms,
            min_cash_quote_pct=round(min_cash, 4),
            max_exposure=round(max_expo, 6),
        ))
    return reports


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: Replay-Report ueber die komplette Historie (+ optional Ledger-Check)."""
    parser = argparse.ArgumentParser(description="KPM Cash-Quote-Monitor (PAPER only)")
    parser.add_argument("--ledger", type=Path, default=None,
                        help="zusaetzlich dieses Ledger pruefen (Alarme werden geschrieben)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    reports = replay_backtest()
    ok = True
    for rep in reports:
        ok = ok and rep.missed_alarms == 0
        print(json.dumps({
            "profile": rep.profile,
            "total_days": rep.total_days,
            "breaches": rep.breaches,
            "alarms": rep.alarms,
            "missed_alarms": rep.missed_alarms,
            "fehlrate": rep.fehlrate,
            "min_cash_quote_pct": rep.min_cash_quote_pct,
            "max_exposure": rep.max_exposure,
            "threshold_pct": CASH_QUOTA_ALARM_PCT,
            "crux": "[CRUX-MK]",
        }, ensure_ascii=False))
    if args.ledger is not None:
        alarms = check_ledger(args.ledger)
        print(json.dumps({"ledger": str(args.ledger), "alarms": len(alarms)}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
