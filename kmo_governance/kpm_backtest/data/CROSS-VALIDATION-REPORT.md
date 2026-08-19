# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-08-18T16:10:02+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5234 (2006-01-02 bis 2026-08-18)
  - Luecken > 5 Handelstage: 0
  - SHA256: a5af352a9281344f1a33ea0bc32cf605420956139b57dcd8546ca8e4f8a28f17
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5236 (2006-01-02 bis 2026-08-18)
  - Luecken > 5 Handelstage: 0
  - SHA256: 7c7d49d6d0140c63686b491e879fbbaafdc4c9ace2ec7b8b2a30d28210535b88

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5233 Handelstage (2006-01-02 bis 2026-08-18)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
