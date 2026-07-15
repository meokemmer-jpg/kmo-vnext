# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-07-14T16:10:05+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5209 (2006-01-02 bis 2026-07-14)
  - Luecken > 5 Handelstage: 0
  - SHA256: bf4915fc34fe633e4c802636c587838673f1383a6534e47f6293b86c59c502b0
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5211 (2006-01-02 bis 2026-07-14)
  - Luecken > 5 Handelstage: 0
  - SHA256: 821f07382ea33930ce24dd2386b5c15e525e616d18163fbdde7c87c053d90e2e

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5208 Handelstage (2006-01-02 bis 2026-07-14)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
