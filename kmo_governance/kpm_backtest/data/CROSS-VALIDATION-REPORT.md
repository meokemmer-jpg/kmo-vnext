# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-07-16T16:10:02+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5211 (2006-01-02 bis 2026-07-16)
  - Luecken > 5 Handelstage: 0
  - SHA256: 6e57effbc6c4f583126f21284d99f0ba860491659fe45343c81121f9df3159ac
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5213 (2006-01-02 bis 2026-07-16)
  - Luecken > 5 Handelstage: 0
  - SHA256: b2c12b307b7bf2fbd9ab9861e626a3fd558854f568b0d7c45b3d8d3aff773c6e

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5210 Handelstage (2006-01-02 bis 2026-07-16)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
