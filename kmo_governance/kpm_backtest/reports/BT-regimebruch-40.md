# BT-Regimebruch-40 — synthetischer 40%-Kollaps (Stress) [CRUX-MK]

> **K_0-DISCLAIMER:** Paper-Mathematik auf historischen/synthetischen Kursen. KEIN Echtgeld, KEIN Broker-Zugang, KEINE Order, KEINE Anlageempfehlung. Engine-Status ALPHA-NOT-K0-READY. Echtgeld ausschliesslich Martin-Phronesis (K_0-Sperr-Liste, `~/.claude/rules/kpm-sizing.md`). [CRUX-MK]

**Fenster:** synthetisch, 250+60 Tage, Seed 20260710
**Daten:** synthetischer Pfad (`scenarios.generate_regime_break_40`), KEINE Echt-Daten
**Determinismus:** Runner ohne RNG; synthetische Pfade mit fixiertem Seed (`scenarios.SCENARIO_SEED`). Reproduzierbar via `python3 -m kmo_governance.kpm_backtest.backtest_runner`.

## Kern-Metriken

| Metrik | pilot-conservative | aggressive-max |
|---|---|---|
| Handelstage | 309 | 309 |
| Max-Drawdown | 0.64% | 4.78% |
| Max-DD-Datum | 2031-03-10 | 2031-03-10 |
| Zeit unter Soft-Brake (Tage) | 0 | 0 |
| Zeit unter Hard-Cap (Tage) | 0 | 0 |
| Zeit unter No-Go (Tage) | 0 | 0 |
| **Verletzungen 25%-No-Go-Linie (Tage)** | **0** | **0** |
| Schlimmste No-Go-Ueberschreitung | 0.00% | 0.00% |
| Max Fraction (Exposure) | 2.10% | 16.00% |
| Mittlere Fraction | 1.82% | 13.70% |
| End-Equity (EUR, Start 100k) | 99,459 | 95,928 |
| Gesamt-Return Portfolio | -0.54% | -4.07% |
| Buy-and-Hold Index (Anker) | -47.22% | -47.22% |
| Tage Regime-Break aktiv | 38 | 38 |
| Tage High-Vola | 17 | 17 |
| Rejects: Drawdown-Gate | 0 | 0 |
| Rejects: Regime-Gate | 38 | 38 |

## Cascade-Trigger-Zeitpunkte (erster Eintritt je Level)

**pilot-conservative:**
- (keine Cascade-Stufe ausgeloest — Exposure zu klein, ehrlich dokumentiert, kein Beweis der Bremsen in diesem Profil)

**aggressive-max:**
- (keine Cascade-Stufe ausgeloest — Exposure zu klein, ehrlich dokumentiert, kein Beweis der Bremsen in diesem Profil)

## Ehrlichkeits-Sektion (Modell-Grenzen)

- **Regime-Gate dominiert (pilot-conservative):** an 38 von 309 Tagen (12.30%) war die Exposure 0, weil der Varianz-Ratio-Detektor 'regime-break' meldete. Der niedrige Max-Drawdown belegt primaer Regime-Gate + kleine Fraction — er ist KEIN Lasttest der Drawdown-Cascade. Die Cascade selbst ist unter Last bewiesen in `tests/test_backtest.py` (Trigger-Reihenfolge, No-Go-Zaehlung) und in `BT-overnight-gap-10.md` (Gap-Versagen beziffert).
- **Regime-Gate dominiert (aggressive-max):** an 38 von 309 Tagen (12.30%) war die Exposure 0, weil der Varianz-Ratio-Detektor 'regime-break' meldete. Der niedrige Max-Drawdown belegt primaer Regime-Gate + kleine Fraction — er ist KEIN Lasttest der Drawdown-Cascade. Die Cascade selbst ist unter Last bewiesen in `tests/test_backtest.py` (Trigger-Reihenfolge, No-Go-Zaehlung) und in `BT-overnight-gap-10.md` (Gap-Versagen beziffert).
- **EOD-Modell:** Bremsen wirken erst am naechsten Close. Overnight-Gaps treffen
  die volle gehaltene Fraction VOR jeder Bremse — quantifiziert in
  `BT-overnight-gap-10.md` (Gap-Fill-Exekution zum Gap-Preis, nicht zum Stop-Preis).
- **HIVE konstant 0.60 (maintain):** Der Backtest hat keine echten Team-Signale;
  das HIVE-Gate ist hier bewusst neutralisiert und wird NICHT als validiert behauptet.
- **Paper-Edge synthetisch:** win_probability/win/loss sind gesetzte Parameter,
  keine gemessene Prognose-Guete. Der Test validiert die BREMSEN, nicht den Edge.
- **Nach No-Go ist der Lauf beendet** (Fraction 0 dauerhaft) — per Rule 'harter Stop'.

## Szenario-Definition

- Synthetischer Pfad: 250 ruhige Tage, dann 60 Tage Kollaps auf exakt -40% (Seed 20260710, Daten klar synthetisch, Start 2030-01-07).
- Prueffrage (rules/kpm-sizing.md Implementation-Check 2): erkennt der
  RegimeBreakDetector den Bruch, und begrenzt die Cascade den Portfolio-Schaden
  gegenueber dem 40%-Index-Kollaps?

## Befund (ehrlich)

- **pilot-conservative:** Detektor gefeuert: JA (38 Tage regime-break, 17 Tage high-vola); Portfolio-Max-DD 0.64% vs. Index -40.00%; No-Go-Verletzungen: 0.
- **aggressive-max:** Detektor gefeuert: JA (38 Tage regime-break, 17 Tage high-vola); Portfolio-Max-DD 4.78% vs. Index -40.00%; No-Go-Verletzungen: 0.

Interpretation: Die Cascade begrenzt den Schaden NUR ueber die kleine Fraction
und die Level-Multiplier — sie kann Tagesverluste auf gehaltener Position nicht
verhindern, nur Folge-Exposure kappen. Der Regime-Gate (Fraction 0 bei Break)
wirkt erst NACH Detektion (Fenster-Latenz des Varianz-Ratio-Tests).

[CRUX-MK]
