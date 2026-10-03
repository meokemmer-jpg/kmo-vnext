# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-10-02T16:10:04+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5267 (2006-01-02 bis 2026-10-02)
  - Luecken > 5 Handelstage: 0
  - SHA256: d0fe58f985cc11a0f1f87c0a7829add107aaaa93eef1c2610876fd019ebc4b99
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5269 (2006-01-02 bis 2026-10-02)
  - Luecken > 5 Handelstage: 0
  - SHA256: 9d41147bacd74ec4c8751c1ae80b8e57e5468cebf9f3a360c7c37b811a7285f5

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5266 Handelstage (2006-01-02 bis 2026-10-02)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
