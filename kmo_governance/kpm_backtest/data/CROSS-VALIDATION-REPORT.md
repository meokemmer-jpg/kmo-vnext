# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]

- Abrufdatum (UTC): 2026-09-07T16:10:08+00:00
- Hinweis Quellen-Wahl: stooq.com (Spec-Vorschlag) war zum Abrufzeitpunkt
  durch eine JavaScript-Proof-of-Work-Bot-Challenge gated und wurde NICHT
  umgangen. Ersatz-Quellen: Yahoo (primaer) + Onvista (sekundaer).
- Quelle 1 (primaer): Yahoo Finance v8 chart JSON (^GDAXI, period1=2006-01-01, interval=1d)
  - Handelstage: 5248 (2006-01-02 bis 2026-09-07)
  - Luecken > 5 Handelstage: 0
  - SHA256: 38a95356e4d45857af4afa0defc945e7e5635e79a4cc1a5fe0c25fc4bcd92741
- Quelle 2 (sekundaer): Onvista EOD-history JSON (DAX INDEX 20735, Xetra, Jahres-Slices range=Y1)
  - Handelstage: 5250 (2006-01-02 bis 2026-09-07)
  - Luecken > 5 Handelstage: 0
  - SHA256: 7b0f22b17e5638e74347f1abffe0eea3af81d97ab417a1eb1276f153f4e5a361

## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)
- Ueberlapp: 5247 Handelstage (2006-01-02 bis 2026-09-07)
- Mittlere abs. Abweichung: 0.0001 % (Toleranz < 0.5 %)
- Max. abs. Abweichung: 0.2199 %
- Verdict: PASS

K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.

[CRUX-MK]
