# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-16T16:10:03+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5255 (2006-01-02 bis 2026-09-16)
  - Luecken > 5 Handelstage: 0
  - SHA256: 57a17554d8f0b7d618d5f11626de53e4fa3b7fd32f35e1d652ec76e4b0e003c1
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5257 (2006-01-02 bis 2026-09-16)
  - Luecken > 5 Handelstage: 0
  - SHA256: db27aba5f1063723908bbcf84c8d073e8b1c115383db04be7ae3afad0d435ed1

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5254 Handelstage (2006-01-02 bis 2026-09-16)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
