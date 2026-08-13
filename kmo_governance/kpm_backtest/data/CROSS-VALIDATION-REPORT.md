# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-08-12T16:10:09+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5230 (2006-01-02 bis 2026-08-12)
  - Luecken > 5 Handelstage: 0
  - SHA256: 00f34288f57cfa9fac97e1dc3cc44a4b8da66456ce8424b2e1a6f8839c7301cf
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5232 (2006-01-02 bis 2026-08-12)
  - Luecken > 5 Handelstage: 0
  - SHA256: 4d3e92e22de2534a4e7e57cb8dfdacb74aaa74b399078240432a8c4d05f58c13

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5229 Handelstage (2006-01-02 bis 2026-08-12)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
