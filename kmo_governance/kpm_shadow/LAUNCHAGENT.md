# com.kemmer.kpm-shadow LaunchAgent [CRUX-MK]

**AP-K4 (W70-CROWN):** taeglicher Shadow-Mode-Lauf werktags 18:10 (nach Xetra-Schluss).
PAPER only — kein Broker-Zugang, kein Echtgeld (K_0, grep-beweisbar via Tests).

- Plist: `~/Library/LaunchAgents/com.kemmer.kpm-shadow.plist`
- Programm: `/opt/homebrew/bin/python3 -m kmo_governance.kpm_shadow.shadow_mode_daemon`
- WorkingDirectory: `~/Projects/dark-factories/kmo`
- Schedule: `StartCalendarInterval` Weekday 1-5, 18:10 (`RunAtLoad=false`)
- Logs: `~/Library/Logs/dark-factories/com.kemmer.kpm-shadow.{log,err.log}`
- Ledger: `kmo_governance/kpm_shadow/ledger.jsonl` (append-only, idempotent pro Tag)
- Alarm-Senke (AP-K5): `<KKS>/branch-hub/audit/kpm-shadow-alerts.jsonl`
- 3-Monats-Shadow-Uhr: gestartet **2026-07-10** (Ledger-Header, per rules/kpm-sizing.md Phase-1)

## Recovery (nach Mac-Crash / Neu-Setup)

```bash
plutil -lint ~/Library/LaunchAgents/com.kemmer.kpm-shadow.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kemmer.kpm-shadow.plist
launchctl print gui/$(id -u)/com.kemmer.kpm-shadow | grep state
```

Bootstrap-Beweis 2026-07-10: `state = not running` (registriert, wartet auf 18:10-Trigger),
`program = /opt/homebrew/bin/python3`.

## Manueller Lauf / Replay

```bash
cd ~/Projects/dark-factories/kmo
/opt/homebrew/bin/python3 -m kmo_governance.kpm_shadow.shadow_mode_daemon            # 1 Shadow-Tag
/opt/homebrew/bin/python3 -m kmo_governance.kpm_shadow.shadow_mode_daemon --no-refresh  # offline
/opt/homebrew/bin/python3 -m kmo_governance.kpm_shadow.cash_quota_monitor            # Replay-Report
```

K16-Spawn-Mutex: mkdir-Lock `/tmp/kpm-shadow.lock` (Stale-Reclaim 6h) + pgrep-Selbstcheck;
zweite Instanz endet mit Exit-Code 3.

[CRUX-MK]
