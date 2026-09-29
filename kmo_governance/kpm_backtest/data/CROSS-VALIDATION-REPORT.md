# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-28T16:10:04+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5263 (2006-01-02 bis 2026-09-28)
  - Luecken > 5 Handelstage: 0
  - SHA256: 6e37b1c6f4dd98b6c9027b985bce0684e131e77f40ce8aea9e0a446377faa4b6
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5265 (2006-01-02 bis 2026-09-28)
  - Luecken > 5 Handelstage: 0
  - SHA256: c2b0eeb9a2da4aaffd83567fc7e003ea2da213bcf5f2bb85fe6efa13b4dd40fa

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5262 Handelstage (2006-01-02 bis 2026-09-28)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
