# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-10T16:10:02+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5251 (2006-01-02 bis 2026-09-10)
  - Luecken > 5 Handelstage: 0
  - SHA256: bd38802eee40c56bb473d72dc202f2890534b8af3e7da175bc1c1fa3034dc50c
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5253 (2006-01-02 bis 2026-09-10)
  - Luecken > 5 Handelstage: 0
  - SHA256: 79f7f5dd6726d4d717cdd45db70b0e2865b2ee35637fdabf46ae7a2d17d24ce6

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5250 Handelstage (2006-01-02 bis 2026-09-10)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
