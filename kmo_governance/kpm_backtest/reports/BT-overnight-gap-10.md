# BT-Overnight-Gap-10 — 10%-Gap mit ehrlicher Gap-Fill-Exekution [CRUX-MK]

> **K_0-DISCLAIMER:** Paper-Mathematik auf historischen/synthetischen Kursen. KEIN Echtgeld, KEIN Broker-Zugang, KEINE Order, KEINE Anlageempfehlung. Engine-Status ALPHA-NOT-K0-READY. Echtgeld ausschliesslich Martin-Phronesis (K_0-Sperr-Liste, `~/.claude/rules/kpm-sizing.md`). [CRUX-MK]

**Szenario:** Overnight-Gap -10% (Open = Vortages-Close × 0.90), synthetischer Pfad Seed 20260710. Stop-Exekution: `gap_fill_stop_price` — Open unter Stop ⇒ Fill zum OPEN (Gap-Preis), nie zum Stop-Preis.

**Exakte Mathematik:** `dd_after = dd_before + fraction × gap × (1 − dd_before)`

## Analytische Gap-Matrix (dd_before × fraction)

| dd vor Gap | Fraction | dd nach Gap | Im Gap uebersprungene Linien | Slippage ueber Linie | Bremsen gehalten? |
|---|---|---|---|---|---|
| 0.00% | 2.10% | 0.21% | — | — | JA |
| 0.00% | 16.00% | 1.60% | — | — | JA |
| 0.00% | 25.00% | 2.50% | — | — | JA |
| 0.00% | 40.00% | 4.00% | — | — | JA |
| 14.50% | 2.10% | 14.68% | — | — | JA |
| 14.50% | 16.00% | 15.87% | soft-brake | soft-brake: +0.87% | **NEIN (Gap-Fill)** |
| 14.50% | 25.00% | 16.64% | soft-brake | soft-brake: +1.64% | **NEIN (Gap-Fill)** |
| 14.50% | 40.00% | 17.92% | soft-brake | soft-brake: +2.92% | **NEIN (Gap-Fill)** |
| 19.50% | 2.10% | 19.67% | — | — | JA |
| 19.50% | 16.00% | 20.79% | hard-cap | hard-cap: +0.79% | **NEIN (Gap-Fill)** |
| 19.50% | 25.00% | 21.51% | hard-cap | hard-cap: +1.51% | **NEIN (Gap-Fill)** |
| 19.50% | 40.00% | 22.72% | hard-cap | hard-cap: +2.72% | **NEIN (Gap-Fill)** |
| 23.00% | 2.10% | 23.16% | — | — | JA |
| 23.00% | 16.00% | 24.23% | — | — | JA |
| 23.00% | 25.00% | 24.93% | — | — | JA |
| 23.00% | 40.00% | 26.08% | absolute-no-go | absolute-no-go: +1.08% | **NEIN (Gap-Fill)** |

## Befund (EHRLICH, keine Schoenrechnung)

- **7 von 16 Faellen: Bremsen im Gap VERSAGT** — die Linie wird
  uebersprungen, der Stop fuellt zum Gap-Preis. Software-Bremsen koennen ein
  Overnight-Gap prinzipbedingt NICHT am Schwellenwert stoppen.
- Die Ueberschreitung ist beziffert und BEGRENZT: max. `fraction × gap × (1 − dd_before)`.
  Worst-Case im getesteten Raster: 2.92% ueber der jeweiligen Linie.
- 'Unbedingte Absicherung' ist mit Software-Bremsen NICHT herstellbar (Board-Claim
  B-K3 in diesem Punkt BERECHTIGT). Haltbar ist nur die quantifizierte Aussage:
  Worst-Case-Zusatzschaden = max_Exposure × max_Gap (z.B. 25% × 10% = 2.50%-Punkte DD).

## Patch-Vorschlag (TODO — NICHT eingebaut, Martin-Phronesis K_0)

- **Overnight-Exposure-Cap:** separates, niedrigeres Fraction-Limit fuer über Nacht
  gehaltene Positionen (z.B. overnight_fraction_cap ≤ 0.10 ⇒ 10%-Gap kostet max.
  1.0%-Punkt DD). Aenderung an `rules/kpm-sizing.md` + Engine = Verfassungs-/
  K_0-nahe Aenderung ⇒ Decision-Card + Martin-Phronesis, KEIN Auto-Einbau.

## Pfad-Lauf durch die Engine (EOD-Modell, beide Profile)

| Metrik | pilot-conservative | aggressive-max |
|---|---|---|
| Max-Drawdown | 0.23% | 1.89% |
| Tage Soft-Brake | 0 | 0 |
| Tage Hard-Cap | 0 | 0 |
| No-Go-Verletzungen (Tage) | 0 | 0 |
| Max Fraction | 2.10% | 16.00% |
| End-Equity (EUR) | 99,794 | 98,319 |

Hinweis: Im Pfad-Lauf trifft der Gap die am Vortag entschiedene Fraction voll
(Close-to-Close-Marking) — konsistent mit der analytischen Matrix. Der
Determinismus-Beweis laeuft in `tests/test_backtest.py`.

[CRUX-MK]
