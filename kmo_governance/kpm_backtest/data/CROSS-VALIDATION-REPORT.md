# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-07-29T16:10:03+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5218 (2006-01-02 bis 2026-07-29)
  - Luecken > 5 Handelstage: 0
  - SHA256: 450eb396215f823f706e79e2c5d874ad2db28db1070521aa69a0dad001d69c80
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5222 (2006-01-02 bis 2026-07-29)
  - Luecken > 5 Handelstage: 0
  - SHA256: 84b2e3d75ca810ecb76bfdb32bb1a9805c50f6cad3d08c0921fcf63cc5aefc74

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5217 Handelstage (2006-01-02 bis 2026-07-29)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
