# [CRUX-MK]
"""Tests fuer W70-CROWN AP-K3: backtest_runner + scenarios.

Abdeckung (per Spec): Runner-Determinismus mit Fixture-Preisen,
Krisen-Fenster-Slicing, Gap-Fill-Mathe exakt, Szenario-Generatoren,
Report-Rendering, Cascade-Trigger + No-Go-Zaehlung.

K_0: reine Paper-Mathematik-Tests, kein Echtgeld-Codepfad.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List

import pytest

from kmo_governance.kpm_backtest.backtest_runner import (
    CRISIS_WINDOWS,
    PROFILES,
    BacktestConfig,
    render_report,
    run_backtest,
    slice_window,
)
from kmo_governance.kpm_backtest.data_loader import PriceBar
from kmo_governance.kpm_backtest.scenarios import (
    OVERNIGHT_GAP_PCT,
    SCENARIO_SEED,
    dd_after_overnight_gap,
    gap_fill_stop_price,
    generate_overnight_gap_10,
    generate_regime_break_40,
    render_gap_report,
    run_gap_stress_cases,
)

# --- Fixture-Helfer ---------------------------------------------------------------


def _next_bday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _bars_from_closes(closes: List[float], start: date = date(2031, 1, 6)) -> List[PriceBar]:
    """Deterministische OHLC-Bars aus einer Close-Liste (Open = prev Close)."""
    bars: List[PriceBar] = []
    day = start
    prev = closes[0]
    for c in closes:
        bars.append((day, prev, max(prev, c) * 1.001, min(prev, c) * 0.999, c))
        prev = c
        day = _next_bday(day)
    return bars


def _wiggle_closes(n: int, base: float = 100.0) -> List[float]:
    """Flach mit deterministischem Mini-Wiggle (vermeidet 0-Varianz im Detektor)."""
    return [base + (i % 2) * 0.01 for i in range(n)]


# Test-Profil mit maximal realistischer Variante-D-Fraction (~0.352):
# f* = (0.9*5 - 0.1*1)/5 = 0.88; Kontext normal-high 0.40; Trinity aggressive 1.0.
MAX_FRACTION_CONFIG = BacktestConfig(
    profile="test-max",
    win_probability=0.90,
    win_amount=5.0,
    loss_amount=1.0,
    edge_confidence="high",
    trinity_variant="aggressive",
    pilot_mode=False,
)


# --- Slicing ------------------------------------------------------------------------


def test_slice_window_2008_bounds() -> None:
    day = date(2007, 1, 2)
    bars: List[PriceBar] = []
    close = 100.0
    while day <= date(2010, 12, 30):
        bars.append((day, close, close * 1.001, close * 0.999, close))
        day = _next_bday(day)
    start, end = CRISIS_WINDOWS["2008"]
    window = slice_window(bars, start, end)
    assert window, "2008-Fenster darf nicht leer sein"
    assert window[0][0] >= date(2008, 1, 1)
    assert window[-1][0] <= date(2009, 3, 31)
    assert len(window) < len(bars)


def test_slice_window_open_bounds_returns_all() -> None:
    bars = _bars_from_closes(_wiggle_closes(20))
    assert slice_window(bars, None, None) == bars


# --- Runner: Validierung + Determinismus ---------------------------------------------


def test_run_backtest_rejects_short_window() -> None:
    bars = _bars_from_closes([100.0])
    with pytest.raises(ValueError):
        run_backtest(bars, PROFILES["pilot-conservative"])


def test_runner_deterministic_on_fixture() -> None:
    bars = generate_regime_break_40(seed=SCENARIO_SEED)
    r1 = run_backtest(bars, MAX_FRACTION_CONFIG)
    r2 = run_backtest(bars, MAX_FRACTION_CONFIG)
    assert r1.records == r2.records, "identische Inputs muessen bit-identische Records liefern"
    assert r1.final_equity == r2.final_equity
    assert r1.max_drawdown == r2.max_drawdown


def test_pilot_profile_fraction_small_and_capped() -> None:
    bars = _bars_from_closes(_wiggle_closes(40))
    res = run_backtest(bars, PROFILES["pilot-conservative"])
    assert 0.0 < res.max_fraction <= 0.25, "Pilot-Cap 0.25 (real ~0.021) verletzt"
    assert res.no_go_violations == 0
    assert all(rec.equity > 0 for rec in res.records)


# --- Cascade-Verhalten -----------------------------------------------------------------


def test_cascade_order_soft_brake_before_hard_cap() -> None:
    # 15 ruhige Tage, dann alternierend -8.0%/-7.9% (Varianz > 0 im Detektor-Fenster)
    closes = _wiggle_closes(15)
    prev = closes[-1]
    for i in range(14):
        prev *= 0.92 if i % 2 == 0 else 0.921
        closes.append(prev)
    bars = _bars_from_closes(closes)
    res = run_backtest(bars, MAX_FRACTION_CONFIG)

    levels = [ev.level for ev in res.level_events]
    assert "soft-brake" in levels, f"Soft-Brake nie ausgeloest (Events: {res.level_events})"
    assert "hard-cap" in levels, f"Hard-Cap nie ausgeloest (Events: {res.level_events})"
    soft_day = next(ev.day for ev in res.level_events if ev.level == "soft-brake")
    hard_day = next(ev.day for ev in res.level_events if ev.level == "hard-cap")
    assert soft_day < hard_day, "Cascade-Reihenfolge verletzt (soft muss vor hard kommen)"
    assert res.days_soft_brake > 0 and res.days_hard_cap > 0

    # Nach Hard-Cap (Multiplier 0) darf keine neue Exposure mehr aufgebaut werden.
    hard_idx = next(i for i, rec in enumerate(res.records) if rec.level == "hard-cap")
    assert all(rec.fraction == 0.0 for rec in res.records[hard_idx + 1 :])


def test_no_go_violation_counted_not_hidden() -> None:
    # Einzelner -80%-Tag aus dd=0: dd springt auf ~0.352*0.8 = 28.2% >= 25% (No-Go).
    closes = _wiggle_closes(16)
    closes.append(closes[-1] * 0.20)
    closes += [closes[-1]] * 3  # Folgetage flach — Level bleibt absolute-no-go
    bars = _bars_from_closes(closes)
    res = run_backtest(bars, MAX_FRACTION_CONFIG)

    assert res.no_go_violations >= 1, "No-Go-Verletzung muss gezaehlt werden (keine Schoenrechnung)"
    assert res.worst_no_go_breach > 0.0
    assert res.days_no_go >= 1
    assert res.max_drawdown >= 0.25
    assert res.reject_counts["drawdown"] >= 1, "Folge-Trades muessen am Drawdown-Gate scheitern"
    assert all(rec.equity > 0 for rec in res.records)


# --- Gap-Fill-Mathe (exakt) --------------------------------------------------------------


def test_dd_after_overnight_gap_exact_formula() -> None:
    # geschlossene Form: dd_after = dd0 + f*gap*(1-dd0)
    assert dd_after_overnight_gap(0.0, 0.25, 0.10) == 0.25 * 0.10
    expected = 0.145 + 0.25 * 0.10 * (1 - 0.145)
    assert dd_after_overnight_gap(0.145, 0.25, 0.10) == pytest.approx(expected, abs=1e-15)
    assert dd_after_overnight_gap(0.20, 0.0, 0.10) == 0.20  # keine Exposure -> kein Gap-Schaden


def test_dd_after_overnight_gap_domain_validation() -> None:
    with pytest.raises(ValueError):
        dd_after_overnight_gap(-0.01, 0.25, 0.10)
    with pytest.raises(ValueError):
        dd_after_overnight_gap(0.10, 1.5, 0.10)
    with pytest.raises(ValueError):
        dd_after_overnight_gap(0.10, 0.25, 1.0)


def test_gap_fill_stop_price_honest_execution() -> None:
    # Gap DURCH den Stop: Fill zum Open (Gap-Preis), NICHT zum Stop-Preis.
    assert gap_fill_stop_price(stop_price=95.0, open_price=90.0) == 90.0
    # Kein Gap durch den Stop: regulaerer Fill am Stop.
    assert gap_fill_stop_price(stop_price=95.0, open_price=98.0) == 95.0
    # Open exakt am Stop: erster handelbarer Preis = Open.
    assert gap_fill_stop_price(stop_price=95.0, open_price=95.0) == 95.0
    with pytest.raises(ValueError):
        gap_fill_stop_price(stop_price=0.0, open_price=90.0)


def test_run_gap_stress_cases_matrix() -> None:
    cases = run_gap_stress_cases()
    by_key = {(round(c.dd_before, 3), round(c.fraction, 3)): c for c in cases}

    # dd0=14.5%, f=25%: Gap ueberspringt die Soft-Brake-Linie -> Bremsen versagen ehrlich.
    c = by_key[(0.145, 0.25)]
    assert c.dd_after == pytest.approx(0.166375, abs=1e-12)
    assert "soft-brake" in c.lines_crossed_in_gap
    assert c.brakes_held is False
    assert c.slippage_beyond_line["soft-brake"] == pytest.approx(0.016375, abs=1e-12)

    # dd0=0%, f=2.1% (Pilot-Realitaet): 10%-Gap kostet 0.21%-Punkte -> keine Linie gerissen.
    c2 = by_key[(0.0, 0.021)]
    assert c2.brakes_held is True
    assert c2.lines_crossed_in_gap == ()

    # dd0=19.5%, f=40%: Hard-Cap-Linie wird im Gap uebersprungen.
    c3 = by_key[(0.195, 0.4)]
    assert "hard-cap" in c3.lines_crossed_in_gap
    assert c3.brakes_held is False


# --- Szenario-Generatoren ------------------------------------------------------------------


def test_generate_regime_break_deterministic_and_exact_decline() -> None:
    b1 = generate_regime_break_40()
    b2 = generate_regime_break_40()
    assert b1 == b2, "Seed fixiert -> bit-identische Pfade"
    anchor = b1[249][4]  # letzter Close der ruhigen Phase (250 Tage)
    final = b1[-1][4]
    assert final / anchor == pytest.approx(0.60, rel=1e-9), "Kollaps muss exakt -40% treffen"
    assert len(b1) == 250 + 60
    assert all(bar[4] > 0 for bar in b1)


def test_generate_overnight_gap_exact_gap_open() -> None:
    bars, gap_idx = generate_overnight_gap_10()
    bars2, gap_idx2 = generate_overnight_gap_10()
    assert bars == bars2 and gap_idx == gap_idx2, "Seed fixiert -> deterministisch"
    prev_close = bars[gap_idx - 1][4]
    gap_open = bars[gap_idx][1]
    assert gap_open == pytest.approx(prev_close * (1 - OVERNIGHT_GAP_PCT), rel=1e-15)
    assert bars[gap_idx][4] < prev_close  # Gap-Tag schliesst unter Vortages-Close


# --- Report-Rendering -------------------------------------------------------------------------


def test_render_report_contains_required_metrics() -> None:
    bars = _bars_from_closes(_wiggle_closes(30))
    results = {"pilot-conservative": run_backtest(bars, PROFILES["pilot-conservative"])}
    md = render_report(
        title="BT-Test",
        window_desc="fixture",
        results=results,
        data_provenance="fixture",
    )
    for needle in [
        "Max-Drawdown",
        "Soft-Brake",
        "Hard-Cap",
        "No-Go-Linie",
        "K_0-DISCLAIMER",
        "[CRUX-MK]",
        "Determinismus",
    ]:
        assert needle in md, f"Report-Pflichtelement fehlt: {needle}"


def test_render_gap_report_contains_honest_verdict_and_todo_patch() -> None:
    bars, _ = generate_overnight_gap_10()
    path_results = {"pilot-conservative": run_backtest(bars, PROFILES["pilot-conservative"])}
    md = render_gap_report(run_gap_stress_cases(), path_results)
    assert "NEIN (Gap-Fill)" in md, "Bremsen-Versagen muss ehrlich im Report stehen"
    assert "Overnight-Exposure-Cap" in md, "Patch-Vorschlag muss als TODO drin sein"
    assert "TODO" in md and "NICHT eingebaut" in md, "Patch darf nicht als eingebaut erscheinen"
    assert "K_0-DISCLAIMER" in md
    assert "dd_after = dd_before + fraction" in md
