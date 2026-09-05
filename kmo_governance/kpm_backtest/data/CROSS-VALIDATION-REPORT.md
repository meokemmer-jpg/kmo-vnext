# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-04T16:10:02+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5247 (2006-01-02 bis 2026-09-04)
  - Luecken > 5 Handelstage: 0
  - SHA256: b0d6f76f2da7a8af7d8c9985221d994d426b63dfba731bd636b1a78ed27b5848
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5249 (2006-01-02 bis 2026-09-04)
  - Luecken > 5 Handelstage: 0
  - SHA256: 6063d60eeee225e1b98634ef2f944fc56ddaf8286ece66574d2e3b8ad56e995d

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5246 Handelstage (2006-01-02 bis 2026-09-04)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
