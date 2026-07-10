# [CRUX-MK]
"""Tests fuer kpm_backtest.data_loader (AP-K2). ALLE Netz-Calls GEMOCKT."""

from __future__ import annotations

import math
from datetime import date

import pytest

from kmo_governance.kpm_backtest import data_loader as dl

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STOOQ_CSV = """Date,Open,High,Low,Close,Volume
2005-12-30,5400.0,5420.0,5390.0,5408.26,0
2006-01-02,5410.0,5470.0,5405.0,5460.68,0
2006-01-03,5462.0,5540.0,5460.0,5523.62,0
2006-01-04,5525.0,5540.0,5500.0,5516.10,0
"""

YAHOO_JSON = """{
  "chart": {"result": [{
    "timestamp": [1136160000, 1136246400, 1136332800],
    "indicators": {"quote": [{
      "open":  [5410.5, 5461.0, null],
      "high":  [5471.0, 5541.0, 5540.0],
      "low":   [5406.0, 5461.0, 5500.0],
      "close": [5461.0, 5524.0, 5516.5]
    }]}
  }], "error": null}
}"""
# 1136160000 = 2006-01-02 UTC; 3. Bar hat null-Open => wird uebersprungen


def _bars(*rows):
    return [(date.fromisoformat(d), o, h, lo, c) for d, o, h, lo, c in rows]


# ---------------------------------------------------------------------------
# 1+2: Parsing
# ---------------------------------------------------------------------------

def test_parse_stooq_csv_filters_min_start_and_sorts():
    rows = dl.parse_stooq_csv(STOOQ_CSV)
    assert len(rows) == 3  # 2005-12-30 rausgefiltert (MIN_START_DATE 2006-01-02)
    assert rows[0] == (date(2006, 1, 2), 5410.0, 5470.0, 5405.0, 5460.68)
    assert [b[0] for b in rows] == sorted(b[0] for b in rows)


def test_parse_yahoo_json_skips_null_quotes():
    rows = dl.parse_yahoo_json(YAHOO_JSON)
    assert len(rows) == 2  # 3. Timestamp hat null-Open
    assert rows[0][0] == date(2006, 1, 2)
    assert rows[1] == (date(2006, 1, 3), 5461.0, 5541.0, 5461.0, 5524.0)


# ---------------------------------------------------------------------------
# 3+4: Kreuzvalidierungs-Mathematik
# ---------------------------------------------------------------------------

def test_cross_validation_math_known_deviation():
    a = _bars(("2006-01-02", 1, 1, 1, 100.0), ("2006-01-03", 1, 1, 1, 200.0))
    b = _bars(("2006-01-03", 1, 1, 1, 202.0), ("2006-01-04", 1, 1, 1, 300.0))
    cv = dl.cross_validate(a, b)
    # Ueberlapp nur 2006-01-03: |200-202| / 201 * 100 = 0.99502...%
    assert cv.n_overlap == 1
    assert cv.overlap_start == cv.overlap_end == date(2006, 1, 3)
    assert math.isclose(cv.mean_abs_close_deviation_pct, 2.0 / 201.0 * 100.0, rel_tol=1e-12)
    assert cv.passed is False  # 0.995% > 0.5% Toleranz


def test_cross_validation_within_tolerance_passes():
    a = _bars(("2006-01-02", 1, 1, 1, 5000.0), ("2006-01-03", 1, 1, 1, 5100.0))
    b = _bars(("2006-01-02", 1, 1, 1, 5001.0), ("2006-01-03", 1, 1, 1, 5099.0))
    cv = dl.cross_validate(a, b)
    assert cv.n_overlap == 2
    assert cv.mean_abs_close_deviation_pct < dl.CROSS_VALIDATION_TOLERANCE_PCT
    assert cv.passed is True
    assert cv.max_abs_close_deviation_pct >= cv.mean_abs_close_deviation_pct


# ---------------------------------------------------------------------------
# 5+6: Luecken-Flagging
# ---------------------------------------------------------------------------

def test_gap_over_5_trading_days_is_flagged():
    # Fr 2006-01-06 -> Mo 2006-01-23: 10 Wochentage fehlen dazwischen
    rows = _bars(("2006-01-06", 1, 2, 1, 1.5), ("2006-01-23", 1, 2, 1, 1.6))
    q = dl.quality_check(rows)
    assert q.has_gaps and len(q.gaps) == 1
    prev_d, next_d, missing = q.gaps[0]
    assert (prev_d, next_d) == (date(2006, 1, 6), date(2006, 1, 23))
    assert missing == 10


def test_weekend_and_short_holiday_not_flagged():
    # Fr -> Mo (Wochenende) und Do -> Di (langes Wochenende, 2 fehlende Tage)
    rows = _bars(
        ("2006-01-05", 1, 2, 1, 1.5),   # Do
        ("2006-01-10", 1, 2, 1, 1.6),   # Di => Fr+Mo fehlen = 2 <= 5
        ("2006-01-13", 1, 2, 1, 1.7),   # Fr
        ("2006-01-16", 1, 2, 1, 1.8),   # Mo => 0 fehlen
    )
    q = dl.quality_check(rows)
    assert not q.has_gaps
    assert q.n_rows == 4 and q.first_date == date(2006, 1, 5)


# ---------------------------------------------------------------------------
# 7: 0-/Negativ-Preise
# ---------------------------------------------------------------------------

def test_zero_or_negative_price_raises():
    with pytest.raises(ValueError, match="Nicht-positiver Preis"):
        dl.quality_check(_bars(("2006-01-02", 5400.0, 5450.0, 0.0, 5420.0)))
    with pytest.raises(ValueError, match="Nicht-positiver Preis"):
        dl.quality_check(_bars(("2006-01-02", -1.0, 5450.0, 5400.0, 5420.0)))


def test_non_monotonic_dates_raise():
    rows = _bars(("2006-01-03", 1, 2, 1, 1.5), ("2006-01-02", 1, 2, 1, 1.6))
    with pytest.raises(ValueError, match="aufsteigend"):
        dl.quality_check(rows)


# ---------------------------------------------------------------------------
# 8+9: Cache-Roundtrip + Offline-Load
# ---------------------------------------------------------------------------

def test_cache_roundtrip_preserves_rows(tmp_path):
    rows = dl.parse_stooq_csv(STOOQ_CSV)
    path = tmp_path / "dax_stooq.csv"
    dl.write_cache(rows, path, "test-source", retrieved_at="2026-07-10T00:00:00+00:00")
    header = path.read_text(encoding="utf-8").splitlines()[:4]
    assert header[0].startswith("# source: test-source")
    assert header[1].startswith("# retrieved: 2026-07-10")
    back = dl.read_cache(path)
    assert len(back) == len(rows)
    for orig, rt in zip(rows, back):
        assert orig[0] == rt[0]
        for x, y in zip(orig[1:], rt[1:]):
            assert math.isclose(x, y, abs_tol=1e-4)


def test_load_dax_offline_from_cache_no_network(tmp_path, monkeypatch):
    def _no_net(*_a, **_k):  # pragma: no cover - darf nie aufgerufen werden
        raise AssertionError("load_dax darf KEINEN Netz-Call machen")

    monkeypatch.setattr(dl, "_http_get", _no_net)
    rows = dl.parse_stooq_csv(STOOQ_CSV)
    dl.write_cache(rows, tmp_path / dl.CACHE_PRIMARY, "test-source")
    loaded = dl.load_dax(data_dir=tmp_path)
    assert [b[0] for b in loaded] == [b[0] for b in rows]


def test_load_dax_missing_cache_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="--refresh"):
        dl.load_dax(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# 10+11: Fetch + Refresh (http_get injiziert = gemockt)
# ---------------------------------------------------------------------------

def _mock_http_get(url: str) -> str:
    if "stooq" in url:
        return STOOQ_CSV
    if "yahoo" in url:
        return YAHOO_JSON
    raise AssertionError(f"unerwartete URL {url}")


def test_fetch_stooq_and_yahoo_with_mocked_http():
    s = dl.fetch_stooq(http_get=_mock_http_get)
    y = dl.fetch_yahoo(http_get=_mock_http_get)
    assert len(s) == 3 and len(y) == 2
    assert s[0][0] == y[0][0] == date(2006, 1, 2)


def test_refresh_cache_mocked_writes_cache_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "MIN_TRADING_DAYS", 3)  # Fixture ist klein
    cv = dl.refresh_cache(data_dir=tmp_path, http_get=_mock_http_get)
    assert (tmp_path / dl.CACHE_PRIMARY).exists()
    assert (tmp_path / dl.CACHE_SECONDARY).exists()
    report = (tmp_path / dl.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "Kreuzvalidierung" in report and "SHA256" in report
    assert cv.n_overlap == 2  # 2006-01-02 + 2006-01-03
    # Fixture-Abweichung: 02.: |5460.68-5461|/5460.84*100 ~ 0.0059%; 03.: ~0.0069%
    assert cv.passed is True


def test_refresh_cache_secondary_down_honest_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "MIN_TRADING_DAYS", 3)

    def _only_stooq(url: str) -> str:
        if "stooq" in url:
            return STOOQ_CSV
        raise OSError("yahoo down")

    cv = dl.refresh_cache(data_dir=tmp_path, http_get=_only_stooq)
    assert (tmp_path / dl.CACHE_PRIMARY).exists()
    assert not (tmp_path / dl.CACHE_SECONDARY).exists()
    assert cv.n_overlap == 0
    report = (tmp_path / dl.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "AUSGEFALLEN" in report and "yahoo down" in report
