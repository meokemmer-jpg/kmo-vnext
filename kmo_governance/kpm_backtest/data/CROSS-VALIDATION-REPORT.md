# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-01T16:10:09+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5244 (2006-01-02 bis 2026-09-01)
  - Luecken > 5 Handelstage: 0
  - SHA256: 02a5de8c0349f0c862fa05ee62591b766955c3734185f60a637a26c0629e0c46
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5246 (2006-01-02 bis 2026-09-01)
  - Luecken > 5 Handelstage: 0
  - SHA256: 3aded40a2026c779edbc347a33fcd9ea7ef702681d43b0f3fcbdbfc2cbd54a42

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5243 Handelstage (2006-01-02 bis 2026-09-01)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
