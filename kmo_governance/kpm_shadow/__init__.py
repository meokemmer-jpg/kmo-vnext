# [CRUX-MK]
"""kpm_shadow: Shadow-Mode-Daemon + Cash-Quote-Monitor (W70-CROWN AP-K4 + AP-K5).

PAPER ONLY. Kein Broker-Zugang, kein Echtgeld, keine Order-Ausfuehrung —
grep-beweisbar (siehe tests/test_kpm_shadow.py::test_no_broker_imports).
Echtgeld ist ausschliesslich Martin-Phronesis (K_0-Sperr-Liste,
~/.claude/rules/kpm-sizing.md).
"""

from .shadow_mode_daemon import (
    LEDGER_PATH,
    LOCK_NAME,
    SHADOW_PROFILE,
    K16Locked,
    acquire_lock,
    append_entry,
    build_ledger_entry,
    load_bars,
    release_lock,
)
from .cash_quota_monitor import (
    ALERTS_PATH,
    CASH_QUOTA_ALARM_PCT,
    MonitorReport,
    cash_quote_pct,
    check_entry,
    check_ledger,
    replay_backtest,
)

__all__ = [
    "LEDGER_PATH",
    "LOCK_NAME",
    "SHADOW_PROFILE",
    "K16Locked",
    "acquire_lock",
    "append_entry",
    "build_ledger_entry",
    "load_bars",
    "release_lock",
    "ALERTS_PATH",
    "CASH_QUOTA_ALARM_PCT",
    "MonitorReport",
    "cash_quote_pct",
    "check_entry",
    "check_ledger",
    "replay_backtest",
]
