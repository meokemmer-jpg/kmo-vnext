# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-07-21T16:10:01+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5214 (2006-01-02 bis 2026-07-21)
  - Luecken > 5 Handelstage: 0
  - SHA256: a7295ff4f2a61aea529659ddecc7072a43defd56e0fa98f31de45cdcad6f6029
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5216 (2006-01-02 bis 2026-07-21)
  - Luecken > 5 Handelstage: 0
  - SHA256: 9db8bfb24356c13606168af1c02b4c76fed21be2fae8a3912ea4120ede3dda6e

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5213 Handelstage (2006-01-02 bis 2026-07-21)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
