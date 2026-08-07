# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-08-06T16:10:05+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5226 (2006-01-02 bis 2026-08-06)
  - Luecken > 5 Handelstage: 0
  - SHA256: 9da1a7e91f4cd6a9d167f7e04f1a7198e624e44021a0fcf2e2668a1b6075406c
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5228 (2006-01-02 bis 2026-08-06)
  - Luecken > 5 Handelstage: 0
  - SHA256: e061cc74f4b41e4f1d282e6eee6e90986f631053e9cdb2169a677cbdd074d197

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5225 Handelstage (2006-01-02 bis 2026-08-06)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
