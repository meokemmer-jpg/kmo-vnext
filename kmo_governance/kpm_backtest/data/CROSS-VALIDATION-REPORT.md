# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-29T16:10:04+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5264 (2006-01-02 bis 2026-09-29)
  - Luecken > 5 Handelstage: 0
  - SHA256: 379a47e82aac9df86e024de1cbb99eb4b6b62c852d4ff2d2235a13625aa6b3e6
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5266 (2006-01-02 bis 2026-09-29)
  - Luecken > 5 Handelstage: 0
  - SHA256: 0a1125b4f4b0c75d2193137a58878c5677dc657d274d5e89edd01508dca0a92e

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5263 Handelstage (2006-01-02 bis 2026-09-29)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
