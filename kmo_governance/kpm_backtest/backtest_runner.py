# [CRUX-MK]
"""KPM-Backtest-Harness (W70-CROWN AP-K3, Teil a: Krisen-Fenster + Gesamtlauf).

Faehrt die Variante-D-Sizing-Engine (`kpm_sizing_engine.KPMVarianteDDecisionEngine`)
taeglich ueber die DAX-EOD-Historie (`kpm_backtest.data_loader.load_dax`, 5.207
Handelstage offline-Cache) und protokolliert das Drawdown-Cascade-Verhalten:

  - Max-Drawdown pro Fenster
  - Zeit (Handelstage) unter Soft-Brake (15%) / Hard-Cap (20%) / No-Go (25%)
  - Verletzungen der 25%-No-Go-Linie (Tage mit Drawdown >= 25%)
  - Cascade-Trigger-Zeitpunkte (erster Eintritt je Level)
  - Gate-Reject-Zaehler (Kelly / Drawdown / HIVE / Regime)

EXEKUTIONS-MODELL (ehrlich dokumentiert, keine Schoenrechnung):
  - EOD-Modell: Die Entscheidung am Close von Tag t-1 bestimmt die Exposure
    fuer Tag t. Equity wird Close-to-Close markiert.
  - Konsequenz: Die Drawdown-Bremsen greifen erst am NAECHSTEN Close. Ein
    Overnight-Gap trifft die volle gehaltene Fraction, BEVOR irgendeine
    Software-Bremse reagieren kann. Diese Luecke wird NICHT versteckt —
    sie wird in `scenarios.py` (Gap-Fill-Exekution) explizit vermessen.
  - Nach Absolute-No-Go (25%) ist der Lauf de-facto beendet (Fraction 0,
    Equity bleibt flach, Drawdown erholt sich nie). Das ist die Semantik
    des "harten Stops" der Rule — kein Auto-Restart wird simuliert.

DETERMINISMUS: Dieser Runner enthaelt KEINE Zufallsquelle. Alle Inputs
(Kurse, HIVE-Signale, Edge-Parameter) sind fix. `SCENARIO_SEED` (in
scenarios.py) fixiert die synthetischen Stress-Pfade. Zwei Laeufe mit
identischen Inputs liefern bit-identische Records.

K_0-DISCLAIMER (Verfassungsrang, ~/.claude/rules/kpm-sizing.md):
Dies ist PAPER-MATHEMATIK auf historischen Kursen. KEIN Echtgeld, KEIN
Broker-Zugang, KEINE Order-Ausfuehrung, KEINE Anlageempfehlung. Echtgeld
ist ausschliesslich Martin-Phronesis (K_0-Sperr-Liste). Status der Engine:
ALPHA-NOT-K0-READY.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from kmo_governance.kpm_backtest.data_loader import PriceBar, load_dax
from kmo_governance.kpm_sizing_engine.decision_engine import (
    DecisionEngineConfig,
    KPMVarianteDDecisionEngine,
    TradeOpportunity,
)
from kmo_governance.kpm_sizing_engine.drawdown_governance import (
    DEFAULT_THRESHOLDS,
    DrawdownGovernance,
    DrawdownLevel,
)
from kmo_governance.kpm_sizing_engine.hive_governance_gate import HIVEGovernanceGate
from kmo_governance.kpm_sizing_engine.regime_break_detector import (
    HIGH_VOLA_RATIO_THRESHOLD,
    MIN_RETURN_OBSERVATIONS,
    MIN_WINDOW,
    RegimeBreakDetector,
)

__all__ = [
    "BacktestConfig",
    "DailyRecord",
    "LevelEvent",
    "BacktestResult",
    "CRISIS_WINDOWS",
    "PROFILES",
    "REPORTS_DIR",
    "INITIAL_EQUITY_EUR",
    "REGIME_DETECTION_WINDOW",
    "CONSTANT_HIVE_SCORE",
    "slice_window",
    "run_backtest",
    "render_report",
    "run_and_render_crisis_reports",
]

logger = logging.getLogger(__name__)

REPORTS_DIR: Path = Path(__file__).resolve().parent / "reports"

# --- Benannte Konstanten (keine Magic Numbers) --------------------------------
INITIAL_EQUITY_EUR: float = 100_000.0     # Paper-Startkapital pro Lauf (EUR)
REGIME_DETECTION_WINDOW: int = 60         # Handelstage Trailing-Fenster (per Engine-Default)
CONSTANT_HIVE_SCORE: float = 0.60         # fix im "maintain"-Band (0.5 deleverage / 0.7 leverage)
NO_GO_LINE: float = DEFAULT_THRESHOLDS.absolute_no_go  # 0.25 — die 25%-No-Go-Linie

# Konstante Team-Signale fuer das HIVE-Gate (Backtest hat keine echten
# Team-Signale — Wert liegt bewusst im "maintain"-Band, ehrlich im Report benannt).
CONSTANT_TEAM_SIGNALS: Tuple[Tuple[float, ...], ...] = (
    (1.0, 0.0, -1.0),
    (0.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
)

# Krisen-Fenster (Kalender-Slices auf die EOD-Historie; None = offene Grenze)
CRISIS_WINDOWS: Dict[str, Tuple[Optional[date], Optional[date]]] = {
    "2008": (date(2008, 1, 1), date(2009, 3, 31)),    # Finanzkrise inkl. Maerz-2009-Tief
    "2020": (date(2020, 1, 1), date(2020, 12, 31)),   # COVID-Crash + Erholung
    "2022": (date(2022, 1, 1), date(2022, 12, 31)),   # Zins-/Ukraine-Baer
    "gesamt": (None, None),                            # volle Historie 2006-2026
}


@dataclass(frozen=True)
class BacktestConfig:
    """Parameter eines Backtest-Laufs. Alle Werte deterministisch, kein RNG.

    Pre: 0 < win_probability < 1; win_amount, loss_amount > 0;
         initial_equity > 0; regime_window >= MIN_WINDOW.
    """

    profile: str = "pilot-conservative"
    initial_equity: float = INITIAL_EQUITY_EUR
    win_probability: float = 0.55   # Paper-Edge: f* = 0.10 bei 1:1
    win_amount: float = 1.0
    loss_amount: float = 1.0
    edge_confidence: Literal["high", "medium"] = "medium"
    trinity_variant: Literal["conservative", "aggressive", "contrarian"] = "conservative"
    pilot_mode: bool = True
    regime_window: int = REGIME_DETECTION_WINDOW
    current_hive: float = CONSTANT_HIVE_SCORE


# Zwei Exposure-Profile pro Fenster — ehrlich beide zeigen:
# das kleine Pilot-Profil loest die Bremsen kaum aus (Exposure ~3%),
# das Max-Profil zeigt, was die Cascade unter Variante-D-Maximum tut.
PROFILES: Dict[str, BacktestConfig] = {
    # f* = 0.10, Kontext normal-medium 0.30, Trinity conservative 0.7 -> ~2.1% Fraction
    "pilot-conservative": BacktestConfig(),
    # f* = (0.60*2 - 0.40)/2 = 0.40, Kontext normal-high 0.40, Trinity aggressive 1.0,
    # Pilot-Cap AUS -> 16% Fraction (realistisches Variante-D-Maximum bei starkem Edge)
    "aggressive-max": BacktestConfig(
        profile="aggressive-max",
        win_probability=0.60,
        win_amount=2.0,
        loss_amount=1.0,
        edge_confidence="high",
        trinity_variant="aggressive",
        pilot_mode=False,
    ),
}


@dataclass(frozen=True)
class DailyRecord:
    """Ein Handelstag im Backtest (Zustand NACH Close-Marking)."""

    day: date
    close: float
    daily_return: float       # Close-to-Close, dezimal
    fraction: float           # gehaltene Fraction WAEHREND dieses Tages
    equity: float             # EUR nach Close-Marking
    drawdown: float           # Peak-to-Current, dezimal, nach Close
    level: DrawdownLevel      # Cascade-Level nach Close
    rejected: bool            # Entscheidung fuer diesen Tag war Reject
    reject_gate: str          # "", "kelly", "drawdown", "hive", "regime"
    regime: str               # "normal" | "high-vola" | "regime-break"


@dataclass(frozen=True)
class LevelEvent:
    """Erster Eintritt in ein Cascade-Level (Trigger-Zeitpunkt)."""

    day: date
    level: DrawdownLevel
    drawdown: float


@dataclass(frozen=True)
class BacktestResult:
    """Aggregierte Metriken eines Laufs (plus vollstaendige Tages-Records)."""

    config: BacktestConfig
    records: List[DailyRecord]
    start: date
    end: date
    trading_days: int
    max_drawdown: float
    max_drawdown_date: Optional[date]
    days_soft_brake: int
    days_hard_cap: int
    days_no_go: int
    no_go_violations: int          # Tage mit drawdown >= 25% (No-Go-Linie verletzt)
    worst_no_go_breach: float      # max(drawdown - 0.25), 0 wenn nie verletzt
    final_equity: float
    total_return: float            # dezimal, auf initial_equity
    buy_and_hold_return: float     # dezimal, Index Close-zu-Close (Vergleichsanker)
    level_events: List[LevelEvent]
    reject_counts: Dict[str, int]
    days_regime_break: int
    days_high_vola: int
    max_fraction: float
    mean_fraction: float


def slice_window(
    bars: Sequence[PriceBar], start: Optional[date], end: Optional[date]
) -> List[PriceBar]:
    """Kalender-Slice auf die Bar-Liste (inklusive Grenzen; None = offen).

    Pre: bars aufsteigend sortiert.
    Post: Teilfolge, Reihenfolge erhalten.
    """
    out = [b for b in bars if (start is None or b[0] >= start) and (end is None or b[0] <= end)]
    return out


def _classify_regime(trailing_returns: Sequence[float], window: int) -> str:
    """Regime-Klassifikation auf Trailing-Returns (deterministisch).

    Mapping per RegimeBreakDetector: break_detected -> "regime-break";
    ratio > HIGH_VOLA_RATIO_THRESHOLD -> "high-vola"; sonst "normal".
    Bei zu wenig Daten (< MIN_RETURN_OBSERVATIONS = 30) konservativ "normal".
    """
    n = len(trailing_returns)
    eff_window = min(window, n)
    if n < MIN_RETURN_OBSERVATIONS or eff_window < MIN_WINDOW:
        return "normal"
    detector = RegimeBreakDetector(trailing_returns)
    res = detector.detect_regime_break(window=eff_window)
    if res.break_detected:
        return "regime-break"
    if res.ratio is not None and res.ratio > HIGH_VOLA_RATIO_THRESHOLD:
        return "high-vola"
    return "normal"


def _reject_gate(rationale: str, gates_drawdown: bool, gates_hive: bool, gates_regime: bool) -> str:
    """Ordnet einen Reject dem verursachenden Gate zu (fuer Zaehler)."""
    if "Kelly-Edge negativ" in rationale:
        return "kelly"
    if not gates_drawdown:
        return "drawdown"
    if not gates_hive:
        return "hive"
    if not gates_regime:
        return "regime"
    return "other"


def run_backtest(bars: Sequence[PriceBar], config: BacktestConfig) -> BacktestResult:
    """Taeglicher Variante-D-Sizing-Lauf ueber ein Kursfenster.

    Pre: len(bars) >= 2, bars aufsteigend, Closes > 0 (per data_loader garantiert).
    Post: deterministisch — identische Inputs liefern identische Records.

    Raises:
        ValueError: bei leerem/zu kurzem Fenster.
    """
    if len(bars) < 2:
        raise ValueError(f"run_backtest: Fenster zu kurz ({len(bars)} Bars, min 2)")

    closes = [b[4] for b in bars]
    dd_gov = DrawdownGovernance(config.initial_equity)
    hive_gate = HIVEGovernanceGate(CONSTANT_TEAM_SIGNALS)
    engine = KPMVarianteDDecisionEngine(
        dd_gov,
        hive_gate,
        DecisionEngineConfig(
            pilot_mode=config.pilot_mode,
            withdrawal_phase=False,
            trinity_variant=config.trinity_variant,
        ),
    )

    equity = config.initial_equity
    records: List[DailyRecord] = []
    level_events: List[LevelEvent] = []
    seen_levels: set = set()
    reject_counts: Dict[str, int] = {"kelly": 0, "drawdown": 0, "hive": 0, "regime": 0, "other": 0}
    returns: List[float] = []
    max_dd = 0.0
    max_dd_date: Optional[date] = None
    fractions: List[float] = []

    for t in range(1, len(bars)):
        day = bars[t][0]
        r_t = closes[t] / closes[t - 1] - 1.0

        # Entscheidung basiert NUR auf Information bis Close t-1 (kein Look-Ahead).
        trailing = returns[-config.regime_window:]
        regime = _classify_regime(trailing, config.regime_window)

        decision = engine.decide_trade_size(
            TradeOpportunity(
                asset="DAX",
                win_probability=config.win_probability,
                win_amount=config.win_amount,
                loss_amount=config.loss_amount,
                notional=equity,
            ),
            current_hive=config.current_hive,
            regime=regime,  # type: ignore[arg-type]
            market_signal="neutral",
            edge_confidence=config.edge_confidence,
        )
        fraction = decision.fraction if not decision.rejected else 0.0
        gate = ""
        if decision.rejected:
            gate = _reject_gate(
                decision.rationale,
                decision.gates.drawdown_passed,
                decision.gates.hive_passed,
                decision.gates.regime_passed,
            )
            reject_counts[gate] += 1

        # Close-to-Close-Marking (EOD-Modell — Gap-Ehrlichkeit siehe scenarios.py)
        equity = equity * (1.0 + fraction * r_t)
        engine.record_equity(equity)
        dd = dd_gov.current_drawdown()
        level = dd_gov.enforce_level().level

        if dd > max_dd:
            max_dd = dd
            max_dd_date = day
        if level != "normal" and level not in seen_levels:
            seen_levels.add(level)
            level_events.append(LevelEvent(day=day, level=level, drawdown=dd))

        records.append(
            DailyRecord(
                day=day,
                close=closes[t],
                daily_return=r_t,
                fraction=fraction,
                equity=equity,
                drawdown=dd,
                level=level,
                rejected=decision.rejected,
                reject_gate=gate,
                regime=regime,
            )
        )
        returns.append(r_t)
        fractions.append(fraction)

    no_go_days = [rec for rec in records if rec.drawdown >= NO_GO_LINE]
    return BacktestResult(
        config=config,
        records=records,
        start=bars[0][0],
        end=bars[-1][0],
        trading_days=len(records),
        max_drawdown=max_dd,
        max_drawdown_date=max_dd_date,
        days_soft_brake=sum(1 for rec in records if rec.level == "soft-brake"),
        days_hard_cap=sum(1 for rec in records if rec.level == "hard-cap"),
        days_no_go=sum(1 for rec in records if rec.level == "absolute-no-go"),
        no_go_violations=len(no_go_days),
        worst_no_go_breach=max((rec.drawdown - NO_GO_LINE) for rec in no_go_days) if no_go_days else 0.0,
        final_equity=equity,
        total_return=equity / config.initial_equity - 1.0,
        buy_and_hold_return=closes[-1] / closes[0] - 1.0,
        level_events=level_events,
        reject_counts=reject_counts,
        days_regime_break=sum(1 for rec in records if rec.regime == "regime-break"),
        days_high_vola=sum(1 for rec in records if rec.regime == "high-vola"),
        max_fraction=max(fractions) if fractions else 0.0,
        mean_fraction=sum(fractions) / len(fractions) if fractions else 0.0,
    )


# --- Report-Rendering ----------------------------------------------------------

K0_DISCLAIMER_MD: str = (
    "> **K_0-DISCLAIMER:** Paper-Mathematik auf historischen/synthetischen Kursen. "
    "KEIN Echtgeld, KEIN Broker-Zugang, KEINE Order, KEINE Anlageempfehlung. "
    "Engine-Status ALPHA-NOT-K0-READY. Echtgeld ausschliesslich Martin-Phronesis "
    "(K_0-Sperr-Liste, `~/.claude/rules/kpm-sizing.md`). [CRUX-MK]"
)


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def render_report(
    title: str,
    window_desc: str,
    results: Dict[str, BacktestResult],
    data_provenance: str,
    extra_md: str = "",
) -> str:
    """Rendert einen Fenster-Report (mehrere Profile) als Markdown.

    Post: enthaelt immer K_0-Disclaimer, Determinismus-Zeile, Max-Drawdown,
    Soft-Brake/Hard-Cap-Zeiten und No-Go-Verletzungen pro Profil.
    """
    lines: List[str] = [
        f"# {title} [CRUX-MK]",
        "",
        K0_DISCLAIMER_MD,
        "",
        f"**Fenster:** {window_desc}",
        f"**Daten:** {data_provenance}",
        "**Determinismus:** Runner ohne RNG; synthetische Pfade mit fixiertem Seed "
        "(`scenarios.SCENARIO_SEED`). Reproduzierbar via "
        "`python3 -m kmo_governance.kpm_backtest.backtest_runner`.",
        "",
        "## Kern-Metriken",
        "",
        "| Metrik | " + " | ".join(results.keys()) + " |",
        "|---|" + "---|" * len(results),
    ]

    def row(label: str, fn) -> str:
        return f"| {label} | " + " | ".join(fn(r) for r in results.values()) + " |"

    lines += [
        row("Handelstage", lambda r: str(r.trading_days)),
        row("Max-Drawdown", lambda r: _pct(r.max_drawdown)),
        row("Max-DD-Datum", lambda r: str(r.max_drawdown_date or "—")),
        row("Zeit unter Soft-Brake (Tage)", lambda r: str(r.days_soft_brake)),
        row("Zeit unter Hard-Cap (Tage)", lambda r: str(r.days_hard_cap)),
        row("Zeit unter No-Go (Tage)", lambda r: str(r.days_no_go)),
        row("**Verletzungen 25%-No-Go-Linie (Tage)**", lambda r: f"**{r.no_go_violations}**"),
        row("Schlimmste No-Go-Ueberschreitung", lambda r: _pct(r.worst_no_go_breach)),
        row("Max Fraction (Exposure)", lambda r: _pct(r.max_fraction)),
        row("Mittlere Fraction", lambda r: _pct(r.mean_fraction)),
        row("End-Equity (EUR, Start 100k)", lambda r: f"{r.final_equity:,.0f}"),
        row("Gesamt-Return Portfolio", lambda r: _pct(r.total_return)),
        row("Buy-and-Hold Index (Anker)", lambda r: _pct(r.buy_and_hold_return)),
        row("Tage Regime-Break aktiv", lambda r: str(r.days_regime_break)),
        row("Tage High-Vola", lambda r: str(r.days_high_vola)),
        row("Rejects: Drawdown-Gate", lambda r: str(r.reject_counts["drawdown"])),
        row("Rejects: Regime-Gate", lambda r: str(r.reject_counts["regime"])),
        "",
        "## Cascade-Trigger-Zeitpunkte (erster Eintritt je Level)",
        "",
    ]
    for name, res in results.items():
        lines.append(f"**{name}:**")
        if not res.level_events:
            lines.append("- (keine Cascade-Stufe ausgeloest — Exposure zu klein, "
                         "ehrlich dokumentiert, kein Beweis der Bremsen in diesem Profil)")
        for ev in res.level_events:
            lines.append(f"- {ev.day}: `{ev.level}` bei Drawdown {_pct(ev.drawdown)}")
        lines.append("")

    lines += ["## Ehrlichkeits-Sektion (Modell-Grenzen)", ""]
    for name, res in results.items():
        rb_share = res.days_regime_break / res.trading_days if res.trading_days else 0.0
        if rb_share > 0.10:
            lines.append(
                f"- **Regime-Gate dominiert ({name}):** an {res.days_regime_break} von "
                f"{res.trading_days} Tagen ({_pct(rb_share)}) war die Exposure 0, weil der "
                "Varianz-Ratio-Detektor 'regime-break' meldete. Der niedrige Max-Drawdown "
                "belegt primaer Regime-Gate + kleine Fraction — er ist KEIN Lasttest der "
                "Drawdown-Cascade. Die Cascade selbst ist unter Last bewiesen in "
                "`tests/test_backtest.py` (Trigger-Reihenfolge, No-Go-Zaehlung) und in "
                "`BT-overnight-gap-10.md` (Gap-Versagen beziffert)."
            )
    lines += [
        "- **EOD-Modell:** Bremsen wirken erst am naechsten Close. Overnight-Gaps treffen",
        "  die volle gehaltene Fraction VOR jeder Bremse — quantifiziert in",
        "  `BT-overnight-gap-10.md` (Gap-Fill-Exekution zum Gap-Preis, nicht zum Stop-Preis).",
        "- **HIVE konstant 0.60 (maintain):** Der Backtest hat keine echten Team-Signale;",
        "  das HIVE-Gate ist hier bewusst neutralisiert und wird NICHT als validiert behauptet.",
        "- **Paper-Edge synthetisch:** win_probability/win/loss sind gesetzte Parameter,",
        "  keine gemessene Prognose-Guete. Der Test validiert die BREMSEN, nicht den Edge.",
        "- **Nach No-Go ist der Lauf beendet** (Fraction 0 dauerhaft) — per Rule 'harter Stop'.",
        "",
    ]
    if extra_md:
        lines += [extra_md, ""]
    lines.append("[CRUX-MK]")
    return "\n".join(lines) + "\n"


def run_and_render_crisis_reports(
    scenario: str,
    bars: Optional[Sequence[PriceBar]] = None,
    reports_dir: Path = REPORTS_DIR,
) -> Path:
    """Fahre ein Krisen-Fenster (oder 'gesamt') mit beiden Profilen, schreibe Report.

    Pre: scenario in CRISIS_WINDOWS.
    Post: Report-Datei `BT-<scenario>.md` geschrieben; Pfad returned.
    """
    if scenario not in CRISIS_WINDOWS:
        raise ValueError(f"Unbekanntes Szenario '{scenario}' (bekannt: {sorted(CRISIS_WINDOWS)})")
    if bars is None:
        bars = load_dax()
    start, end = CRISIS_WINDOWS[scenario]
    window = slice_window(bars, start, end)
    results = {name: run_backtest(window, cfg) for name, cfg in PROFILES.items()}
    titles = {
        "2008": "BT-2008 — Finanzkrise (Variante-D-Backtest)",
        "2020": "BT-2020 — COVID-Crash (Variante-D-Backtest)",
        "2022": "BT-2022 — Zins-/Ukraine-Baer (Variante-D-Backtest)",
        "gesamt": "BT-Gesamt — DAX 2006-2026 (Variante-D-Backtest)",
    }
    md = render_report(
        title=titles[scenario],
        window_desc=f"{window[0][0]} bis {window[-1][0]} ({len(window)} Bars, Kalender-Slice "
        f"{start or 'offen'}..{end or 'offen'})",
        results=results,
        data_provenance=(
            "DAX-EOD Offline-Cache (`kpm_backtest/data/dax_yahoo.csv`, 5.207 Handelstage, "
            "Yahoo ^GDAXI, kreuzvalidiert gegen Onvista <0.5%, siehe "
            "`data/CROSS-VALIDATION-REPORT.md`)"
        ),
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"BT-{scenario}.md"
    out.write_text(md, encoding="utf-8")
    logger.info("Report geschrieben: %s", out)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="KPM Variante-D Backtest-Runner (Paper, K_0-safe)")
    parser.add_argument(
        "--scenario",
        default="all",
        choices=sorted(CRISIS_WINDOWS) + ["all"],
        help="Krisen-Fenster oder 'all' (alle 4 inkl. gesamt)",
    )
    args = parser.parse_args(argv)
    bars = load_dax()
    scenarios = sorted(CRISIS_WINDOWS) if args.scenario == "all" else [args.scenario]
    for sc in scenarios:
        path = run_and_render_crisis_reports(sc, bars=bars)
        print(f"[BT] {sc}: {path}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
