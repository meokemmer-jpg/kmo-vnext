# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-07-22T16:10:01+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5215 (2006-01-02 bis 2026-07-22)
  - Luecken > 5 Handelstage: 0
  - SHA256: 2327d101a5045a0ca5143cf8b8a9aa78d9ab2a3e8f23d12d58fcca2ced42756a
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5217 (2006-01-02 bis 2026-07-22)
  - Luecken > 5 Handelstage: 0
  - SHA256: 1d3a8b4a2b212f2f644134f488ec1b65dc0d13913727c10593421bdba3e1d281

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5214 Handelstage (2006-01-02 bis 2026-07-22)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
