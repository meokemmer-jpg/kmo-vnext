# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-08-13T16:10:05+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5231 (2006-01-02 bis 2026-08-13)
  - Luecken > 5 Handelstage: 0
  - SHA256: 755ca4ddb5b457f4d238c3f2e56a4772e2469d59baf9977d640760f5da962337
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5233 (2006-01-02 bis 2026-08-13)
  - Luecken > 5 Handelstage: 0
  - SHA256: 183c96aa87aee573b140297c0dd2bcfa06bbc4de3e55d2de60b44928413b664f

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5230 Handelstage (2006-01-02 bis 2026-08-13)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
