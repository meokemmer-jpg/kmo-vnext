# BT-Gesamt — DAX 2006-2026 (Variante-D-Backtest) [CRUX-MK]

> **K_0-DISCLAIMER:** Paper-Mathematik auf historischen/synthetischen Kursen. KEIN Echtgeld, KEIN Broker-Zugang, KEINE Order, KEINE Anlageempfehlung. Engine-Status ALPHA-NOT-K0-READY. Echtgeld ausschliesslich Martin-Phronesis (K_0-Sperr-Liste, `~/.claude/rules/kpm-sizing.md`). [CRUX-MK]

**Fenster:** 2006-01-02 bis 2026-07-10 (5207 Bars, Kalender-Slice offen..offen)
**Daten:** DAX-EOD Offline-Cache (`kpm_backtest/data/dax_yahoo.csv`, 5.207 Handelstage, Yahoo ^GDAXI, kreuzvalidiert gegen Onvista <0.5%, siehe `data/CROSS-VALIDATION-REPORT.md`)
**Determinismus:** Runner ohne RNG; synthetische Pfade mit fixiertem Seed (`scenarios.SCENARIO_SEED`). Reproduzierbar via `python3 -m kmo_governance.kpm_backtest.backtest_runner`.

## Kern-Metriken

| Metrik | pilot-conservative | aggressive-max |
|---|---|---|
| Handelstage | 5206 | 5206 |
| Max-Drawdown | 0.70% | 4.75% |
| Max-DD-Datum | 2009-03-06 | 2009-03-06 |
| Zeit unter Soft-Brake (Tage) | 0 | 0 |
| Zeit unter Hard-Cap (Tage) | 0 | 0 |
| Zeit unter No-Go (Tage) | 0 | 0 |
| **Verletzungen 25%-No-Go-Linie (Tage)** | **0** | **0** |
| Schlimmste No-Go-Ueberschreitung | 0.00% | 0.00% |
| Max Fraction (Exposure) | 2.10% | 16.00% |
| Mittlere Fraction | 1.34% | 9.41% |
| End-Equity (EUR, Start 100k) | 102,903 | 120,461 |
| Gesamt-Return Portfolio | 2.90% | 20.46% |
| Buy-and-Hold Index (Anker) | 360.34% | 360.34% |
| Tage Regime-Break aktiv | 1675 | 1675 |
| Tage High-Vola | 1248 | 1248 |
| Rejects: Drawdown-Gate | 0 | 0 |
| Rejects: Regime-Gate | 1675 | 1675 |

## Cascade-Trigger-Zeitpunkte (erster Eintritt je Level)

**pilot-conservative:**
- (keine Cascade-Stufe ausgeloest — Exposure zu klein, ehrlich dokumentiert, kein Beweis der Bremsen in diesem Profil)

**aggressive-max:**
- (keine Cascade-Stufe ausgeloest — Exposure zu klein, ehrlich dokumentiert, kein Beweis der Bremsen in diesem Profil)

## Ehrlichkeits-Sektion (Modell-Grenzen)

- **Regime-Gate dominiert (pilot-conservative):** an 1675 von 5206 Tagen (32.17%) war die Exposure 0, weil der Varianz-Ratio-Detektor 'regime-break' meldete. Der niedrige Max-Drawdown belegt primaer Regime-Gate + kleine Fraction — er ist KEIN Lasttest der Drawdown-Cascade. Die Cascade selbst ist unter Last bewiesen in `tests/test_backtest.py` (Trigger-Reihenfolge, No-Go-Zaehlung) und in `BT-overnight-gap-10.md` (Gap-Versagen beziffert).
- **Regime-Gate dominiert (aggressive-max):** an 1675 von 5206 Tagen (32.17%) war die Exposure 0, weil der Varianz-Ratio-Detektor 'regime-break' meldete. Der niedrige Max-Drawdown belegt primaer Regime-Gate + kleine Fraction — er ist KEIN Lasttest der Drawdown-Cascade. Die Cascade selbst ist unter Last bewiesen in `tests/test_backtest.py` (Trigger-Reihenfolge, No-Go-Zaehlung) und in `BT-overnight-gap-10.md` (Gap-Versagen beziffert).
- **EOD-Modell:** Bremsen wirken erst am naechsten Close. Overnight-Gaps treffen
  die volle gehaltene Fraction VOR jeder Bremse — quantifiziert in
  `BT-overnight-gap-10.md` (Gap-Fill-Exekution zum Gap-Preis, nicht zum Stop-Preis).
- **HIVE konstant 0.60 (maintain):** Der Backtest hat keine echten Team-Signale;
  das HIVE-Gate ist hier bewusst neutralisiert und wird NICHT als validiert behauptet.
- **Paper-Edge synthetisch:** win_probability/win/loss sind gesetzte Parameter,
  keine gemessene Prognose-Guete. Der Test validiert die BREMSEN, nicht den Edge.
- **Nach No-Go ist der Lauf beendet** (Fraction 0 dauerhaft) — per Rule 'harter Stop'.

[CRUX-MK]
