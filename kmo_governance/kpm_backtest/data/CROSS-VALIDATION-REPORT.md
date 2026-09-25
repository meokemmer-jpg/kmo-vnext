# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-24T16:10:05+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5260 (2006-01-02 bis 2026-09-24)
  - Luecken > 5 Handelstage: 0
  - SHA256: 6fb7b031405bf0d05c4581468e8d8546ae870243264f587bc43a8abf708ac7f1
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5263 (2006-01-02 bis 2026-09-24)
  - Luecken > 5 Handelstage: 0
  - SHA256: 5e01c3bbeb9675e619657a57ddfeeb4130b56806e1904e4833ce9a9e2d570ba7

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5259 Handelstage (2006-01-02 bis 2026-09-24)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
