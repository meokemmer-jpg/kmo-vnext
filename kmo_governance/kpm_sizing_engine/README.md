# kpm_sizing_engine — KPM Variante-D Sizing (Python-Port) [CRUX-MK]

**Herkunft:** 1:1-Port der TS-Referenz `~/Projects/heylou-v10-foundation/packages/kpm-sizing/`
(`@heylou/kpm-sizing` v0.1.0, Commit-Stand `f4083f4`). Module: numerics, KellyCriterion,
DrawdownGovernance, HIVEGovernanceGate, RegimeBreakDetector, PortfolioOptimizer,
KPMVarianteDDecisionEngine. Fachliche Grundlage: `~/.claude/rules/kpm-sizing.md`
(Variante-D: Kelly-Fraction 0.25–0.40 kontext-adaptiv, Drawdown 15%/20%/25%,
HIVE als Governance-Gate, Regimebruch → Pause).

**Paritäts-Nachweis:** `fixtures/parity_cases.json` — 24 Fälle, Erwartungswerte per
Node/tsx direkt gegen die TS-Referenz gerechnet (kein LLM, kein Ollama).
`tests/test_kpm_sizing_parity.py` prüft auf **|diff| < 1e-6** (6 Nachkommastellen);
dazu 57 portierte Unit-/Grenzfall-Tests. Lauf: `cd ~/Projects/dark-factories/kmo &&
python3 -m pytest kmo_governance/kpm_sizing_engine/tests/ -q`.

**K_0-Disclaimer:** Reine SIZING-MATHEMATIK. KEIN Broker-Zugang, KEIN Echtgeld, keine
Order-Ausführung irgendwo im Code. Status CONDITIONAL / ALPHA-NOT-K0-READY — Echtgeld-Einsatz
ausschließlich via Martin-Phronesis (K_0-Sperr-Liste), Pilot-Pflicht Thomas-First mit
Shadow-Mode 3+ Monate. Keine Investment-Empfehlung.
