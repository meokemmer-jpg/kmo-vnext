# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-02T16:10:06+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5245 (2006-01-02 bis 2026-09-02)
  - Luecken > 5 Handelstage: 0
  - SHA256: a069ec9c98fa6e00e627d0db49cceceeed0e18d07a6e014c6e1740a644475eee
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5247 (2006-01-02 bis 2026-09-02)
  - Luecken > 5 Handelstage: 0
  - SHA256: f372ea892f79f8d64c84a2e89c5d09d7cd33b1af146e5fe83d73ccec0c125abf

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5244 Handelstage (2006-01-02 bis 2026-09-02)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
