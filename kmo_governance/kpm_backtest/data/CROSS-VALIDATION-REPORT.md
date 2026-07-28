# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-07-27T16:10:02+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5217 (2006-01-02 bis 2026-07-27)
  - Luecken > 5 Handelstage: 0
  - SHA256: 9144298011104bcd3a190b8e17cc5e9b4e241698fd2d036a84471e89e6f6a4ca
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5220 (2006-01-02 bis 2026-07-27)
  - Luecken > 5 Handelstage: 0
  - SHA256: 6feb2cd31ec1f141c435b93c9e58a45bd5af181036b0625ac841211a62981d26

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5216 Handelstage (2006-01-02 bis 2026-07-27)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
