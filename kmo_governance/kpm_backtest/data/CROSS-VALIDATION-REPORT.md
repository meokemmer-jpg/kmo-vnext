# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-08-03T16:10:03+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5223 (2006-01-02 bis 2026-08-03)
  - Luecken > 5 Handelstage: 0
  - SHA256: 4a308a9891f9f795ac4f69faba040474fa35936822487b24f0c42c3f6407a476
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5225 (2006-01-02 bis 2026-08-03)
  - Luecken > 5 Handelstage: 0
  - SHA256: c9ba38509fbdb2a0d71b4abb467b8c30a6da4eaa48cd7cfd8bfb484d6699fcb3

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5222 Handelstage (2006-01-02 bis 2026-08-03)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
