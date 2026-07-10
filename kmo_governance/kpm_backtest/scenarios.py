# [CRUX-MK]
"""Synthetische Stress-Szenarien fuer KPM Variante-D (W70-CROWN AP-K3, Teil b).

Zwei Pflicht-Szenarien per Spec + `rules/kpm-sizing.md` Implementation-Checks:

  1. 40%-REGIMEBRUCH: ruhige Phase, dann 60-Tage-Kollaps auf exakt -40%.
     Testet: feuert der RegimeBreakDetector? Wann greifen Soft-Brake (15%) /
     Hard-Cap (20%)? Wird die 25%-No-Go-Linie des PORTFOLIOS verletzt?

  2. 10%-OVERNIGHT-GAP mit GAP-FILL-EXEKUTION — DER EHRLICHE TEIL:
     Ein Stop bei der 15%-Drawdown-Linie fuellt bei einem Overnight-Gap
     NICHT zum Stop-Preis, sondern ZUM GAP-PREIS (Open). Software-Bremsen
     koennen ein Gap nicht abfangen; sie begrenzen nur die Folgezeit.
     Exakte Mathematik:

         dd_after = dd_before + fraction * gap * (1 - dd_before)

     Die Ueberschreitung der Brems-Linie (Slippage) betraegt
     `dd_after - linie` und skaliert linear mit der gehaltenen Fraction.
     Wenn die Bremsen im Gap versagen, ist das ERGEBNIS und wird
     dokumentiert — Patch-Vorschlag (Overnight-Exposure-Cap) ist ein
     TODO fuer Martin-Phronesis, KEIN Auto-Einbau.

DETERMINISMUS: Alle Pfade nutzen `random.Random(SCENARIO_SEED)` — zwei
Aufrufe liefern bit-identische Bars.

K_0-DISCLAIMER: Paper-Mathematik, synthetische Kurse. KEIN Echtgeld,
KEINE Empfehlung, KEIN Broker-Zugang. Engine ALPHA-NOT-K0-READY.
Echtgeld ausschliesslich Martin-Phronesis (K_0-Sperr-Liste).
"""

from __future__ import annotations

import argparse
import logging
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from kmo_governance.kpm_backtest.backtest_runner import (
    PROFILES,
    REPORTS_DIR,
    BacktestResult,
    K0_DISCLAIMER_MD,
    render_report,
    run_backtest,
)
from kmo_governance.kpm_backtest.data_loader import PriceBar
from kmo_governance.kpm_sizing_engine.drawdown_governance import DEFAULT_THRESHOLDS

__all__ = [
    "SCENARIO_SEED",
    "SYNTHETIC_START_DATE",
    "SYNTHETIC_START_PRICE",
    "REGIME_BREAK_TOTAL_DECLINE",
    "OVERNIGHT_GAP_PCT",
    "GapStressCase",
    "generate_calm_bars",
    "generate_regime_break_40",
    "generate_overnight_gap_10",
    "gap_fill_stop_price",
    "dd_after_overnight_gap",
    "run_gap_stress_cases",
    "render_gap_report",
    "render_regime_break_report",
    "write_stress_reports",
]

logger = logging.getLogger(__name__)

# --- Benannte Konstanten --------------------------------------------------------
SCENARIO_SEED: int = 20260710            # fixierter Seed (Datum W70-Kickoff)
SYNTHETIC_START_DATE: date = date(2030, 1, 7)  # bewusst Zukunft = klar synthetisch (Montag)
SYNTHETIC_START_PRICE: float = 10_000.0  # Indexpunkte
CALM_DAILY_VOL: float = 0.008            # dezimal, ruhige Phase
CALM_DAILY_DRIFT: float = 0.0002         # dezimal
REGIME_BREAK_TOTAL_DECLINE: float = 0.40  # Spec: 40%-Regimebruch
REGIME_BREAK_CRASH_DAYS: int = 60
REGIME_BREAK_CALM_DAYS: int = 250
CRASH_DAILY_VOL: float = 0.025           # erhoehte Vol im Bruch
OVERNIGHT_GAP_PCT: float = 0.10          # Spec: 10%-Overnight-Gap
GAP_CALM_DAYS: int = 80
GAP_INTRADAY_CLOSE_FACTOR: float = 0.995  # Gap-Tag schliesst leicht unter Open
POST_GAP_FLAT_DAYS: int = 10

SOFT_BRAKE_LINE: float = DEFAULT_THRESHOLDS.soft_brake       # 0.15
HARD_CAP_LINE: float = DEFAULT_THRESHOLDS.hard_cap           # 0.20
NO_GO_LINE: float = DEFAULT_THRESHOLDS.absolute_no_go        # 0.25
CASCADE_LINES: Tuple[Tuple[str, float], ...] = (
    ("soft-brake", SOFT_BRAKE_LINE),
    ("hard-cap", HARD_CAP_LINE),
    ("absolute-no-go", NO_GO_LINE),
)


def _next_business_day(d: date) -> date:
    d = d + timedelta(days=1)
    while d.weekday() >= 5:  # Sa/So
        d += timedelta(days=1)
    return d


def _bar_from_closes(day: date, prev_close: float, close: float) -> PriceBar:
    """Baut eine plausible OHLC-Bar aus zwei Closes (Open = prev Close)."""
    o = prev_close
    hi = max(o, close) * 1.001
    lo = min(o, close) * 0.999
    return (day, o, hi, lo, close)


def generate_calm_bars(
    rng: random.Random,
    n_days: int,
    start_day: date,
    start_price: float,
    daily_vol: float = CALM_DAILY_VOL,
    daily_drift: float = CALM_DAILY_DRIFT,
) -> List[PriceBar]:
    """Ruhige Phase: kleine gauss'sche Tages-Returns. Deterministisch via rng.

    Pre: n_days >= 1, start_price > 0.
    """
    bars: List[PriceBar] = []
    day = start_day
    prev = start_price
    for _ in range(n_days):
        r = daily_drift + rng.gauss(0.0, daily_vol)
        close = max(prev * (1.0 + r), 0.01)
        bars.append(_bar_from_closes(day, prev, close))
        prev = close
        day = _next_business_day(day)
    return bars


def generate_regime_break_40(
    seed: int = SCENARIO_SEED,
    calm_days: int = REGIME_BREAK_CALM_DAYS,
    crash_days: int = REGIME_BREAK_CRASH_DAYS,
    total_decline: float = REGIME_BREAK_TOTAL_DECLINE,
) -> List[PriceBar]:
    """Synthetischer 40%-Regimebruch: calm_days ruhig, dann crash_days Kollaps.

    Post (exakt, testbar): letzter Close == (1 - total_decline) * Close am Ende
    der ruhigen Phase (Rescaling der Crash-Phase, Toleranz float-epsilon).
    Zwei Aufrufe mit gleichem Seed sind bit-identisch.
    """
    rng = random.Random(seed)
    calm = generate_calm_bars(rng, calm_days, SYNTHETIC_START_DATE, SYNTHETIC_START_PRICE)
    anchor = calm[-1][4]

    # Roh-Crash: negativer Log-Drift + hohe Vol
    log_drift = math.log(1.0 - total_decline) / crash_days
    raw_closes: List[float] = []
    prev = anchor
    for _ in range(crash_days):
        r = math.expm1(log_drift + rng.gauss(0.0, CRASH_DAILY_VOL))
        prev = max(prev * (1.0 + r), 0.01)
        raw_closes.append(prev)
    # Geometrisches Rescaling: Endpunkt EXAKT auf anchor*(1-total_decline)
    target = anchor * (1.0 - total_decline)
    raw_end = raw_closes[-1]
    scale = (target / raw_end)
    rescaled = [c * scale ** ((i + 1) / crash_days) for i, c in enumerate(raw_closes)]

    bars = list(calm)
    day = _next_business_day(calm[-1][0])
    prev = anchor
    for close in rescaled:
        bars.append(_bar_from_closes(day, prev, close))
        prev = close
        day = _next_business_day(day)
    return bars


def generate_overnight_gap_10(
    seed: int = SCENARIO_SEED,
    calm_days: int = GAP_CALM_DAYS,
    gap: float = OVERNIGHT_GAP_PCT,
) -> Tuple[List[PriceBar], int]:
    """Synthetischer 10%-Overnight-Gap-Pfad.

    Aufbau: ruhige Phase, dann EIN Gap-Tag (Open exakt = prev_close*(1-gap)),
    danach POST_GAP_FLAT_DAYS ruhige Tage.

    Returns:
        (bars, gap_index) — gap_index = Position der Gap-Bar in bars.

    Post (exakt, testbar): bars[gap_index][1] == bars[gap_index-1][4] * (1-gap).
    """
    rng = random.Random(seed)
    calm = generate_calm_bars(rng, calm_days, SYNTHETIC_START_DATE, SYNTHETIC_START_PRICE)
    prev_close = calm[-1][4]
    day = _next_business_day(calm[-1][0])

    gap_open = prev_close * (1.0 - gap)
    gap_close = gap_open * GAP_INTRADAY_CLOSE_FACTOR
    gap_bar: PriceBar = (day, gap_open, gap_open * 1.001, gap_close * 0.999, gap_close)

    bars = list(calm) + [gap_bar]
    gap_index = len(bars) - 1
    post = generate_calm_bars(
        rng, POST_GAP_FLAT_DAYS, _next_business_day(day), gap_close, daily_drift=0.0
    )
    bars += post
    return bars, gap_index


# --- Gap-Fill-Exekution (der ehrliche Kern) --------------------------------------


def gap_fill_stop_price(stop_price: float, open_price: float) -> float:
    """EHRLICHE Stop-Exekution bei Gap-Down.

    Ein Stop-Verkauf loest aus, sobald der Markt <= stop_price handelt.
    Oeffnet der Markt UNTER dem Stop (Gap durch den Stop), ist der erste
    handelbare Preis das Open — der Fill ist das Open, NICHT der Stop-Preis.

    Pre: stop_price > 0, open_price > 0.
    Post: returns min(stop_price, open_price)-Semantik fuer Gap-Down:
          open <= stop -> open (Gap-Fill), sonst stop (regulaerer Fill).
    """
    if stop_price <= 0 or open_price <= 0:
        raise ValueError("gap_fill_stop_price: Preise muessen > 0 sein")
    return open_price if open_price <= stop_price else stop_price


def dd_after_overnight_gap(dd_before: float, fraction: float, gap: float) -> float:
    """Exakter Portfolio-Drawdown NACH einem Overnight-Gap (vor jeder Bremse).

    Herleitung: equity_open = equity_prev * (1 - fraction*gap);
    dd_after = 1 - equity_open/peak = dd_before + fraction*gap*(1 - dd_before).

    Pre: 0 <= dd_before < 1; 0 <= fraction <= 1; 0 <= gap < 1.
    Post: dd_after in [dd_before, 1).
    """
    if not (0.0 <= dd_before < 1.0 and 0.0 <= fraction <= 1.0 and 0.0 <= gap < 1.0):
        raise ValueError("dd_after_overnight_gap: Inputs ausserhalb Definitionsbereich")
    return dd_before + fraction * gap * (1.0 - dd_before)


@dataclass(frozen=True)
class GapStressCase:
    """Ein analytischer Gap-Fall: haelt die Brems-Linie oder fuellt sie im Gap?"""

    dd_before: float
    fraction: float
    gap: float
    dd_after: float
    lines_crossed_in_gap: Tuple[str, ...]   # Linien, die im Gap uebersprungen wurden
    slippage_beyond_line: Dict[str, float]  # dd_after - linie, pro uebersprungener Linie
    brakes_held: bool                       # True nur wenn KEINE Linie im Gap uebersprungen


def run_gap_stress_cases(
    dd_before_cases: Sequence[float] = (0.0, 0.145, 0.195, 0.23),
    fractions: Sequence[float] = (0.021, 0.16, 0.25, 0.40),
    gap: float = OVERNIGHT_GAP_PCT,
) -> List[GapStressCase]:
    """Analytische Gap-Matrix: dd_before x fraction.

    dd_before-Faelle: 0% (frisch), 14.5% (knapp vor Soft-Brake), 19.5% (knapp
    vor Hard-Cap), 23% (Zone vor No-Go). Fractions: typisches Pilot-Profil
    (~2.1%), Aggressive-Max (16%), Pilot-Cap (25%), theoretisches
    Variante-D-Fraction-Maximum (40%).

    Post: deterministisch, reine Mathematik.
    """
    cases: List[GapStressCase] = []
    for dd0 in dd_before_cases:
        for f in fractions:
            dd1 = dd_after_overnight_gap(dd0, f, gap)
            crossed = tuple(
                name for name, line in CASCADE_LINES if dd0 < line <= dd1
            )
            slippage = {name: dd1 - line for name, line in CASCADE_LINES if name in crossed}
            cases.append(
                GapStressCase(
                    dd_before=dd0,
                    fraction=f,
                    gap=gap,
                    dd_after=dd1,
                    lines_crossed_in_gap=crossed,
                    slippage_beyond_line=slippage,
                    brakes_held=len(crossed) == 0,
                )
            )
    return cases


# --- Reports ----------------------------------------------------------------------


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def render_regime_break_report(results: Dict[str, BacktestResult]) -> str:
    """Report BT-regimebruch-40: nutzt das Standard-Rendering + Detektor-Befund."""
    extra = [
        "## Szenario-Definition",
        "",
        f"- Synthetischer Pfad: {REGIME_BREAK_CALM_DAYS} ruhige Tage, dann"
        f" {REGIME_BREAK_CRASH_DAYS} Tage Kollaps auf exakt -{REGIME_BREAK_TOTAL_DECLINE*100:.0f}%"
        f" (Seed {SCENARIO_SEED}, Daten klar synthetisch, Start {SYNTHETIC_START_DATE}).",
        "- Prueffrage (rules/kpm-sizing.md Implementation-Check 2): erkennt der",
        "  RegimeBreakDetector den Bruch, und begrenzt die Cascade den Portfolio-Schaden",
        "  gegenueber dem 40%-Index-Kollaps?",
        "",
        "## Befund (ehrlich)",
        "",
    ]
    for name, res in results.items():
        detector_fired = res.days_regime_break > 0
        extra.append(
            f"- **{name}:** Detektor gefeuert: {'JA' if detector_fired else 'NEIN'} "
            f"({res.days_regime_break} Tage regime-break, {res.days_high_vola} Tage high-vola); "
            f"Portfolio-Max-DD {_pct(res.max_drawdown)} vs. Index -40.00%; "
            f"No-Go-Verletzungen: {res.no_go_violations}."
        )
    extra += [
        "",
        "Interpretation: Die Cascade begrenzt den Schaden NUR ueber die kleine Fraction",
        "und die Level-Multiplier — sie kann Tagesverluste auf gehaltener Position nicht",
        "verhindern, nur Folge-Exposure kappen. Der Regime-Gate (Fraction 0 bei Break)",
        "wirkt erst NACH Detektion (Fenster-Latenz des Varianz-Ratio-Tests).",
    ]
    return render_report(
        title="BT-Regimebruch-40 — synthetischer 40%-Kollaps (Stress)",
        window_desc=f"synthetisch, {REGIME_BREAK_CALM_DAYS}+{REGIME_BREAK_CRASH_DAYS} Tage, "
        f"Seed {SCENARIO_SEED}",
        results=results,
        data_provenance="synthetischer Pfad (`scenarios.generate_regime_break_40`), KEINE Echt-Daten",
        extra_md="\n".join(extra),
    )


def render_gap_report(
    cases: Sequence[GapStressCase],
    path_results: Dict[str, BacktestResult],
) -> str:
    """Report BT-overnight-gap-10: analytische Gap-Matrix + Pfad-Lauf.

    Kernaussage wird NICHT geglaettet: wo der Gap eine Brems-Linie ueberspringt,
    fuellt der Stop zum Gap-Preis — Slippage wird beziffert.
    """
    failed = [c for c in cases if not c.brakes_held]
    lines: List[str] = [
        "# BT-Overnight-Gap-10 — 10%-Gap mit ehrlicher Gap-Fill-Exekution [CRUX-MK]",
        "",
        K0_DISCLAIMER_MD,
        "",
        f"**Szenario:** Overnight-Gap -{OVERNIGHT_GAP_PCT*100:.0f}% (Open = Vortages-Close × 0.90), "
        f"synthetischer Pfad Seed {SCENARIO_SEED}. Stop-Exekution: `gap_fill_stop_price` — "
        "Open unter Stop ⇒ Fill zum OPEN (Gap-Preis), nie zum Stop-Preis.",
        "",
        "**Exakte Mathematik:** `dd_after = dd_before + fraction × gap × (1 − dd_before)`",
        "",
        "## Analytische Gap-Matrix (dd_before × fraction)",
        "",
        "| dd vor Gap | Fraction | dd nach Gap | Im Gap uebersprungene Linien | Slippage ueber Linie | Bremsen gehalten? |",
        "|---|---|---|---|---|---|",
    ]
    for c in cases:
        crossed = ", ".join(c.lines_crossed_in_gap) or "—"
        slip = (
            ", ".join(f"{k}: +{_pct(v)}" for k, v in c.slippage_beyond_line.items()) or "—"
        )
        held = "JA" if c.brakes_held else "**NEIN (Gap-Fill)**"
        lines.append(
            f"| {_pct(c.dd_before)} | {_pct(c.fraction)} | {_pct(c.dd_after)} | {crossed} | {slip} | {held} |"
        )

    lines += [
        "",
        "## Befund (EHRLICH, keine Schoenrechnung)",
        "",
        f"- **{len(failed)} von {len(cases)} Faellen: Bremsen im Gap VERSAGT** — die Linie wird",
        "  uebersprungen, der Stop fuellt zum Gap-Preis. Software-Bremsen koennen ein",
        "  Overnight-Gap prinzipbedingt NICHT am Schwellenwert stoppen.",
        "- Die Ueberschreitung ist beziffert und BEGRENZT: max. `fraction × gap × (1 − dd_before)`.",
        "  Worst-Case im getesteten Raster: "
        + _pct(max((max(c.slippage_beyond_line.values()) for c in failed), default=0.0))
        + " ueber der jeweiligen Linie.",
        "- 'Unbedingte Absicherung' ist mit Software-Bremsen NICHT herstellbar (Board-Claim",
        "  B-K3 in diesem Punkt BERECHTIGT). Haltbar ist nur die quantifizierte Aussage:",
        f"  Worst-Case-Zusatzschaden = max_Exposure × max_Gap (z.B. 25% × 10% = 2.50%-Punkte DD).",
        "",
        "## Patch-Vorschlag (TODO — NICHT eingebaut, Martin-Phronesis K_0)",
        "",
        "- **Overnight-Exposure-Cap:** separates, niedrigeres Fraction-Limit fuer über Nacht",
        "  gehaltene Positionen (z.B. overnight_fraction_cap ≤ 0.10 ⇒ 10%-Gap kostet max.",
        "  1.0%-Punkt DD). Aenderung an `rules/kpm-sizing.md` + Engine = Verfassungs-/",
        "  K_0-nahe Aenderung ⇒ Decision-Card + Martin-Phronesis, KEIN Auto-Einbau.",
        "",
        "## Pfad-Lauf durch die Engine (EOD-Modell, beide Profile)",
        "",
        "| Metrik | " + " | ".join(path_results.keys()) + " |",
        "|---|" + "---|" * len(path_results),
    ]

    def row(label: str, fn) -> str:
        return f"| {label} | " + " | ".join(fn(r) for r in path_results.values()) + " |"

    lines += [
        row("Max-Drawdown", lambda r: _pct(r.max_drawdown)),
        row("Tage Soft-Brake", lambda r: str(r.days_soft_brake)),
        row("Tage Hard-Cap", lambda r: str(r.days_hard_cap)),
        row("No-Go-Verletzungen (Tage)", lambda r: str(r.no_go_violations)),
        row("Max Fraction", lambda r: _pct(r.max_fraction)),
        row("End-Equity (EUR)", lambda r: f"{r.final_equity:,.0f}"),
        "",
        "Hinweis: Im Pfad-Lauf trifft der Gap die am Vortag entschiedene Fraction voll",
        "(Close-to-Close-Marking) — konsistent mit der analytischen Matrix. Der",
        "Determinismus-Beweis laeuft in `tests/test_backtest.py`.",
        "",
        "[CRUX-MK]",
    ]
    return "\n".join(lines) + "\n"


def write_stress_reports(reports_dir: Path = REPORTS_DIR) -> List[Path]:
    """Erzeugt beide Stress-Reports mit Ist-Zahlen (Echt-Lauf, deterministisch).

    Post: BT-regimebruch-40.md + BT-overnight-gap-10.md geschrieben.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    out: List[Path] = []

    rb_bars = generate_regime_break_40()
    rb_results = {name: run_backtest(rb_bars, cfg) for name, cfg in PROFILES.items()}
    p1 = reports_dir / "BT-regimebruch-40.md"
    p1.write_text(render_regime_break_report(rb_results), encoding="utf-8")
    out.append(p1)

    gap_bars, _gap_index = generate_overnight_gap_10()
    gap_results = {name: run_backtest(gap_bars, cfg) for name, cfg in PROFILES.items()}
    cases = run_gap_stress_cases()
    p2 = reports_dir / "BT-overnight-gap-10.md"
    p2.write_text(render_gap_report(cases, gap_results), encoding="utf-8")
    out.append(p2)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="KPM Stress-Szenarien (Paper, K_0-safe)")
    parser.parse_args(argv)
    for p in write_stress_reports():
        print(f"[STRESS] {p}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
