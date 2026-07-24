# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-07-23T16:10:03+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5216 (2006-01-02 bis 2026-07-23)
  - Luecken > 5 Handelstage: 0
  - SHA256: 2930be8611f23819f7098c6dd3a407bca7352685a3602ed31201beb6a3fd5d26
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5218 (2006-01-02 bis 2026-07-23)
  - Luecken > 5 Handelstage: 0
  - SHA256: fb12f48ca543cf6d3b98e6f89c78694e561948e8887f4c127275e0ef952d5bec

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5215 Handelstage (2006-01-02 bis 2026-07-23)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
