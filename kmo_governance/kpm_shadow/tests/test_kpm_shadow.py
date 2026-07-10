# [CRUX-MK]
"""Tests fuer W70-CROWN AP-K4 (Shadow-Mode-Daemon) + AP-K5 (Cash-Quote-Monitor).

Abdeckung per Auftrag: Ledger-Append + Idempotenz pro Tag, K16-Mutex,
kein-Broker-grep (K_0-Beweis), Offline-graceful, Monitor-Replay-0-Fehlrate
ueber die komplette Backtest-Historie, Alarm-Pfad.

K_0: reine Paper-Mathematik-Tests, kein Echtgeld-Codepfad.
"""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import List

import pytest

from kmo_governance.kpm_backtest.data_loader import MIN_TRADING_DAYS, PriceBar, load_dax
from kmo_governance.kpm_shadow import shadow_mode_daemon as smd
from kmo_governance.kpm_shadow import cash_quota_monitor as cqm

MODULE_DIR = Path(smd.__file__).resolve().parent

# --- Fixture-Helfer ---------------------------------------------------------------


def make_bars(n: int = 40, start_close: float = 100.0) -> List[PriceBar]:
    """Deterministische synthetische EOD-Bars (leichter Aufwaertsdrift)."""
    bars: List[PriceBar] = []
    d = date(2026, 1, 5)
    close = start_close
    for i in range(n):
        while d.weekday() >= 5:  # nur Werktage
            d += timedelta(days=1)
        close = close * (1.0 + (0.001 if i % 3 else -0.0005))
        bars.append((d, close, close * 1.005, close * 0.995, close))
        d += timedelta(days=1)
    return bars


# --- AP-K4: Ledger (Append-only + Idempotenz + Pflicht-Felder) ---------------------


def test_ledger_first_append_writes_header_and_entry(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    entry = smd.build_ledger_entry(make_bars(), data_refresh="offline-cache")
    assert smd.append_entry(entry, ledger_path=ledger) == "appended"
    rows = smd.read_ledger(ledger)
    assert len(rows) == 2
    assert rows[0]["type"] == "header"
    # 3-Monats-Shadow-Uhr: Start dokumentiert im Header (AP-K4-Pflicht)
    assert rows[0]["shadow_clock_start"] == entry["date"]
    assert "3-Monats-Shadow-Uhr" in rows[0]["shadow_clock_note"]
    assert rows[1]["type"] == "entry"


def test_ledger_idempotent_pro_tag(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    entry = smd.build_ledger_entry(make_bars())
    assert smd.append_entry(entry, ledger_path=ledger) == "appended"
    assert smd.append_entry(entry, ledger_path=ledger) == "duplicate"
    entries = [r for r in smd.read_ledger(ledger) if r["type"] == "entry"]
    assert len(entries) == 1  # kein Duplikat, append-only


def test_ledger_entry_pflichtfelder_und_paper_mode():
    entry = smd.build_ledger_entry(make_bars())
    for feld in ("date", "close", "decision", "exposure", "dd_state",
                 "regime_flag", "crux"):
        assert feld in entry, f"Pflicht-Feld fehlt: {feld}"
    assert entry["crux"] == "[CRUX-MK]"
    assert entry["mode"] == "PAPER"
    assert 0.0 <= float(entry["exposure"]) <= 1.0
    assert entry["dd_state"] in ("normal", "soft-brake", "hard-cap",
                                 "absolute-no-go", "cooldown")
    assert entry["regime_flag"] in ("normal", "high-vola", "regime-break")


def test_ledger_entry_nutzt_neuesten_close():
    bars = make_bars()
    entry = smd.build_ledger_entry(bars)
    assert entry["date"] == bars[-1][0].isoformat()
    assert entry["close"] == pytest.approx(bars[-1][4])


# --- AP-K4: K16-Spawn-Mutex ---------------------------------------------------------


def test_k16_mutex_blockt_zweite_instanz(tmp_path):
    smd.acquire_lock(root=tmp_path)
    with pytest.raises(smd.K16Locked):
        smd.acquire_lock(root=tmp_path)
    assert smd.release_lock(root=tmp_path) is True
    # nach Release wieder frei
    smd.acquire_lock(root=tmp_path)
    smd.release_lock(root=tmp_path)


def test_k16_mutex_schreibt_pid_und_reclaimed_stale(tmp_path):
    lock = smd.acquire_lock(root=tmp_path)
    assert (lock / "pid").read_text() == str(os.getpid())
    # Lock kuenstlich altern lassen (> Stale-Schwelle) => Reclaim statt Veto
    alt = 1_000_000.0
    os.utime(lock, (alt, alt))
    lock2 = smd.acquire_lock(root=tmp_path)
    assert lock2 == lock
    smd.release_lock(root=tmp_path)


# --- AP-K4: K_0-Beweis — kein Broker-/Order-/Trading-API-Import ---------------------

ERLAUBTE_IMPORTS = {
    "__future__", "argparse", "ast", "json", "logging", "os", "re",
    "subprocess", "sys", "datetime", "pathlib", "typing", "dataclasses",
    "kmo_governance", "pytest",
}

BROKER_TOKENS = re.compile(
    r"^\s*(?:import|from)\s+(?:ib_insync|ibapi|ccxt|alpaca|alpaca_trade_api|"
    r"binance|oanda|quickfix|MetaTrader5|metatrader5|robin_stocks|etrade|"
    r"degiro|trading212|kraken|coinbase|broker\w*)",
    re.IGNORECASE | re.MULTILINE,
)

ORDER_API_CALLS = re.compile(
    r"(?:place_order|submit_order|create_order|send_order|execute_order|"
    r"cancel_order|market_order|limit_order)\s*\(",
)


def _alle_modul_sourcen() -> List[tuple]:
    return [(p, p.read_text(encoding="utf-8"))
            for p in sorted(MODULE_DIR.glob("*.py"))]


def test_no_broker_imports_ast_allowlist():
    """AST-Beweis: JEDES importierte Top-Level-Modul ist stdlib oder kmo_governance."""
    for path, source in _alle_modul_sourcen():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tops = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                tops = [(node.module or "").split(".")[0]] if node.level == 0 else []
            else:
                continue
            for top in tops:
                assert top in ERLAUBTE_IMPORTS, (
                    f"K_0-VERSTOSS: nicht-erlaubter Import '{top}' in {path.name}"
                )


def test_no_broker_grep_und_keine_order_api_calls():
    """grep-Beweis per Auftrag: kein Broker-Import, kein Order-API-Call-Muster."""
    for path, source in _alle_modul_sourcen():
        assert not BROKER_TOKENS.search(source), f"Broker-Import-Muster in {path.name}"
        assert not ORDER_API_CALLS.search(source), f"Order-API-Call-Muster in {path.name}"


# --- AP-K4: Offline-graceful ----------------------------------------------------------


def test_load_bars_offline_graceful_bei_netzfehler(monkeypatch):
    """refresh_cache wirft (Netz down) => Fallback auf Cache, kein Crash."""
    fixture = make_bars()

    def kaputtes_refresh(**kwargs):
        raise OSError("Netz nicht erreichbar (simuliert)")

    monkeypatch.setattr(smd, "refresh_cache", kaputtes_refresh)
    monkeypatch.setattr(smd, "load_dax", lambda **kw: fixture)
    bars = smd.load_bars(refresh=True)
    assert bars == fixture  # graceful: Cache-Stand traegt


def test_main_no_refresh_schreibt_ledger_und_ist_idempotent(tmp_path, monkeypatch, capsys):
    fixture = make_bars()
    monkeypatch.setattr(smd, "load_dax", lambda **kw: fixture)
    # Alarm-Senke fuer den integrierten Monitor-Check umleiten (kein KKS-Write im Test)
    monkeypatch.setattr(cqm, "ALERTS_PATH", tmp_path / "alerts.jsonl")
    ledger = tmp_path / "ledger.jsonl"
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(smd, "LOCK_ROOT", lock_root)

    assert smd.main(["--no-refresh", "--ledger", str(ledger)]) == 0
    out1 = json.loads(capsys.readouterr().out.strip())
    assert out1["status"] == "appended"
    assert out1["mode"] == "PAPER"
    assert out1["cash_alarm"] is False

    assert smd.main(["--no-refresh", "--ledger", str(ledger)]) == 0
    out2 = json.loads(capsys.readouterr().out.strip())
    assert out2["status"] == "duplicate"
    entries = [r for r in smd.read_ledger(ledger) if r["type"] == "entry"]
    assert len(entries) == 1


def test_main_k16_veto_exit_code(tmp_path, monkeypatch):
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(smd, "LOCK_ROOT", lock_root)
    smd.acquire_lock(root=lock_root)  # fremde "Instanz" haelt den Lock
    try:
        assert smd.main(["--no-refresh", "--ledger", str(tmp_path / "l.jsonl")]) == 3
    finally:
        smd.release_lock(root=lock_root)


# --- AP-K5: Cash-Quote-Monitor --------------------------------------------------------


def test_cash_quota_konstante_und_quote_mathe():
    assert cqm.CASH_QUOTA_ALARM_PCT == 47.0
    assert cqm.cash_quote_pct(0.0) == pytest.approx(100.0)
    assert cqm.cash_quote_pct(0.40) == pytest.approx(60.0)  # Variante-D-Strukturgrenze
    assert cqm.cash_quote_pct(1.0) == pytest.approx(0.0)


def test_monitor_alarm_pfad_bei_synthetischem_verstoss(tmp_path):
    alerts = tmp_path / "kpm-shadow-alerts.jsonl"
    entry = {"date": "2026-07-10", "exposure": 0.60}  # Cash 40% < 47%
    alarm = cqm.check_entry(entry, alerts_path=alerts)
    assert alarm is not None
    zeilen = alerts.read_text(encoding="utf-8").strip().splitlines()
    assert len(zeilen) == 1
    rec = json.loads(zeilen[0])
    assert rec["alert"] == "cash-quote-breach"
    assert rec["cash_quote_pct"] == pytest.approx(40.0)
    assert rec["threshold_pct"] == 47.0
    assert rec["crux"] == "[CRUX-MK]"


def test_monitor_kein_alarm_ueber_schwelle(tmp_path):
    alerts = tmp_path / "alerts.jsonl"
    assert cqm.check_entry({"date": "2026-07-10", "exposure": 0.40},
                           alerts_path=alerts) is None
    assert cqm.check_entry({"date": "2026-07-10", "exposure": 0.021},
                           alerts_path=alerts) is None
    assert not alerts.exists()  # keine Alarm-Zeile geschrieben


def test_check_ledger_findet_verstoss_in_gecraftetem_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    zeilen = [
        {"type": "header", "shadow_clock_start": "2026-07-10"},
        {"type": "entry", "date": "2026-07-09", "exposure": 0.021},
        {"type": "entry", "date": "2026-07-10", "exposure": 0.55},  # Verstoss
    ]
    ledger.write_text("\n".join(json.dumps(z) for z in zeilen) + "\n", encoding="utf-8")
    alerts = tmp_path / "alerts.jsonl"
    alarms = cqm.check_ledger(ledger, alerts_path=alerts)
    assert len(alarms) == 1
    assert alarms[0]["date"] == "2026-07-10"


def test_replay_synthetische_bars_null_fehlrate():
    reports = cqm.replay_backtest(bars=make_bars(60))
    assert len(reports) == 2
    for rep in reports:
        assert rep.missed_alarms == 0
        assert rep.fehlrate == 0.0
        assert rep.alarms == rep.breaches  # Monitor alarmiert exakt jeden Breach


def test_replay_komplette_backtest_historie_null_fehlrate():
    """AP-K5-Done-Kriterium: kompletter Backtest-Zeitraum, Fehlrate 0."""
    bars = load_dax()
    reports = cqm.replay_backtest(bars=bars)
    for rep in reports:
        assert rep.total_days == len(bars) - 1
        assert rep.total_days >= MIN_TRADING_DAYS - 1  # >= 5.000 Handelstage
        assert rep.missed_alarms == 0, f"Fehlrate > 0 in Profil {rep.profile}"
        assert rep.fehlrate == 0.0
        # Variante-D-Strukturgrenze: Exposure nie > 40% => Cash nie < 60%
        assert rep.max_exposure <= 0.40 + 1e-9
        assert rep.min_cash_quote_pct >= 60.0 - 1e-6
        assert rep.breaches == 0  # regelkonforme Variante-D: kein Breach moeglich
