# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-08-31T16:10:11+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5243 (2006-01-02 bis 2026-08-31)
  - Luecken > 5 Handelstage: 0
  - SHA256: 1980b03db21619e62bb01770e0e61936ffae1f9f524840aaabb6107395357bc7
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5245 (2006-01-02 bis 2026-08-31)
  - Luecken > 5 Handelstage: 0
  - SHA256: d9effd447e51fdf6fd91c53ee35bc618556ef3d1bae6f65b836ee3c7d4cc386a

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5242 Handelstage (2006-01-02 bis 2026-08-31)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
