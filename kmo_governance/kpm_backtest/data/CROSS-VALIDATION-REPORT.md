# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-08-04T16:10:05+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5224 (2006-01-02 bis 2026-08-04)
  - Luecken > 5 Handelstage: 0
  - SHA256: e77d0e1d887e6c71c44fac0a8e4fd05ddd89a0a1659e17f3a2c25ea38e2c24c0
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5226 (2006-01-02 bis 2026-08-04)
  - Luecken > 5 Handelstage: 0
  - SHA256: 5db38fa8e3e84e9354366bcddc61d2dcb529b6ac5b47c6428fad47da46ee4dc8

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5223 Handelstage (2006-01-02 bis 2026-08-04)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
