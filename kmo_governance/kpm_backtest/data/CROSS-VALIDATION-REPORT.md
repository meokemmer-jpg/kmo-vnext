# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-08T16:10:06+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5249 (2006-01-02 bis 2026-09-08)
  - Luecken > 5 Handelstage: 0
  - SHA256: 3454d66cf558a76ac80f745c640d1fbab08ce7f0ab5c48706cb9c00939b66e2d
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5251 (2006-01-02 bis 2026-09-08)
  - Luecken > 5 Handelstage: 0
  - SHA256: 16c054ec25baa0ee44bd59db7c5b702b75e39a48d6df7e955a0371885437de67

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5248 Handelstage (2006-01-02 bis 2026-09-08)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
