# [CRUX-MK]
"""DAX-EOD-Daten-Ingestion fuer KPM-Backtests (W70-CROWN AP-K2).

Zwei KEYLESS-Quellen (kein API-Key, kein Scraping-Framework, nur stdlib):
    Quelle 1 (primaer):   stooq.com CSV-Endpoint
                          https://stooq.com/q/d/l/?s=^dax&i=d
    Quelle 2 (sekundaer): Yahoo Finance v8 Chart-JSON-Endpoint (^GDAXI)
                          https://query1.finance.yahoo.com/v8/finance/chart/^GDAXI

Design:
- Lokaler CSV-Cache in kpm_backtest/data/ (committed — Reproduzierbarkeit).
  Header-Kommentarzeilen dokumentieren Quelle + Abrufdatum.
- `load_dax()` liest OFFLINE aus dem Cache (kein Netz-Call im Normalbetrieb).
- Netz-Abruf nur explizit via `refresh_cache()` bzw. CLI `--refresh`.
- Kreuzvalidierung auf Ueberlapp-Datumsbereich: mittlere relative
  Close-Abweichung < 0.5 % (Toleranz per W70-crown.md AP-K2).
- Qualitaets-Checks: Luecken > 5 Handelstage werden geflaggt;
  0-/Negativ-Preise sind harter Fehler (ValueError).

K_0-DISCLAIMER (Verfassungsrang, ~/.claude/rules/kpm-sizing.md):
Dieses Modul liefert NUR historische Kursdaten und Qualitaetsreports.
Es trifft KEINE Anlageentscheidung, gibt KEINE Empfehlung, hat KEINEN
Broker-Zugang und fuehrt KEINE Order aus. Echtgeld-Nutzung ist ausserhalb
des Scopes und ausschliesslich Martin-Phronesis (K_0-Sperr-Liste).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

__all__ = [
    "PriceBar",
    "QualityReport",
    "CrossValidationReport",
    "STOOQ_URL",
    "YAHOO_URL",
    "MIN_START_DATE",
    "MIN_TRADING_DAYS",
    "CROSS_VALIDATION_TOLERANCE_PCT",
    "GAP_FLAG_TRADING_DAYS",
    "parse_stooq_csv",
    "parse_yahoo_json",
    "fetch_stooq",
    "fetch_yahoo",
    "quality_check",
    "cross_validate",
    "write_cache",
    "read_cache",
    "load_dax",
    "refresh_cache",
]

logger = logging.getLogger(__name__)

# (date, open, high, low, close) — EOD-Bar, Preise in Indexpunkten
PriceBar = Tuple[date, float, float, float, float]

# Quelle 1: stooq.com — keyless CSV, DAX Performance Index EOD
STOOQ_URL: str = "https://stooq.com/q/d/l/?s=%5Edax&i=d"
STOOQ_SOURCE_LABEL: str = "stooq.com CSV (https://stooq.com/q/d/l/?s=^dax&i=d)"

# Quelle 2: Yahoo Finance v8 Chart-API — keyless JSON, Symbol ^GDAXI
YAHOO_URL: str = (
    "https://query1.finance.yahoo.com/v8/finance/chart/%5EGDAXI"
    "?range=max&interval=1d&events=history"
)
YAHOO_SOURCE_LABEL: str = "Yahoo Finance v8 chart JSON (^GDAXI, range=max, interval=1d)"

# Yahoo blockt Requests ohne Browser-artigen User-Agent (HTTP 429/403)
HTTP_USER_AGENT: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) kpm-backtest/1.0"

# Spec AP-K2: Datenbereich 2006-heute
MIN_START_DATE: date = date(2006, 1, 2)

# Done-Kriterium AP-K2: mindestens 5.000 Handelstage im Cache
MIN_TRADING_DAYS: int = 5000

# Kreuzvalidierungs-Toleranz: mittlere relative Close-Abweichung in Prozent
CROSS_VALIDATION_TOLERANCE_PCT: float = 0.5

# Qualitaets-Check: Luecke > 5 Handelstage (geschaetzt via Wochentage) => Flag
GAP_FLAG_TRADING_DAYS: int = 5

# HTTP-Timeout in Sekunden fuer die (seltenen) Refresh-Abrufe
FETCH_TIMEOUT_S: float = 30.0

# Default-Cache-Verzeichnis (committed im kmo-Repo)
DATA_DIR: Path = Path(__file__).resolve().parent / "data"
CACHE_PRIMARY: str = "dax_stooq.csv"
CACHE_SECONDARY: str = "dax_yahoo.csv"
REPORT_FILENAME: str = "CROSS-VALIDATION-REPORT.md"


@dataclass(frozen=True)
class QualityReport:
    """Ergebnis der Qualitaets-Checks ueber eine EOD-Serie."""

    n_rows: int
    first_date: Optional[date]
    last_date: Optional[date]
    # Luecken: (vorheriges Datum, naechstes Datum, geschaetzte fehlende Handelstage)
    gaps: List[Tuple[date, date, int]] = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)


@dataclass(frozen=True)
class CrossValidationReport:
    """Kreuzvalidierung zweier EOD-Serien auf dem Ueberlapp-Datumsbereich."""

    n_overlap: int
    overlap_start: Optional[date]
    overlap_end: Optional[date]
    mean_abs_close_deviation_pct: float
    max_abs_close_deviation_pct: float
    tolerance_pct: float

    @property
    def passed(self) -> bool:
        return self.n_overlap > 0 and self.mean_abs_close_deviation_pct < self.tolerance_pct


# ---------------------------------------------------------------------------
# Parsing (rein, offline-testbar)
# ---------------------------------------------------------------------------

def parse_stooq_csv(text: str, min_start: date = MIN_START_DATE) -> List[PriceBar]:
    """Parst stooq-CSV (Date,Open,High,Low,Close,Volume) zu PriceBars ab min_start.

    Zeilen mit fehlenden/unparsbaren OHLC-Feldern werden uebersprungen (geloggt).
    """
    rows: List[PriceBar] = []
    reader = csv.DictReader(io.StringIO(text))
    for rec in reader:
        try:
            d = datetime.strptime(rec["Date"].strip(), "%Y-%m-%d").date()
            bar = (
                d,
                float(rec["Open"]),
                float(rec["High"]),
                float(rec["Low"]),
                float(rec["Close"]),
            )
        except (KeyError, TypeError, ValueError):
            logger.debug("stooq: unparsbare Zeile uebersprungen: %r", rec)
            continue
        if d >= min_start:
            rows.append(bar)
    rows.sort(key=lambda b: b[0])
    return rows


def parse_yahoo_json(text: str, min_start: date = MIN_START_DATE) -> List[PriceBar]:
    """Parst Yahoo-v8-Chart-JSON zu PriceBars ab min_start.

    Timestamps sind UTC-Epochen; Handelstage mit null-Quotes werden uebersprungen.
    """
    payload = json.loads(text)
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []

    rows: List[PriceBar] = []
    for i, ts in enumerate(timestamps):
        o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, lo, c):
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if d >= min_start:
            rows.append((d, float(o), float(h), float(lo), float(c)))
    # Yahoo liefert gelegentlich Duplikat-Timestamps am aktuellen Tag: letzter gewinnt
    dedup: Dict[date, PriceBar] = {b[0]: b for b in rows}
    return sorted(dedup.values(), key=lambda b: b[0])


# ---------------------------------------------------------------------------
# Fetch (nur via refresh_cache / CLI; in Tests IMMER gemockt)
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout_s: float = FETCH_TIMEOUT_S) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (feste URLs)
        return resp.read().decode("utf-8", errors="replace")


def fetch_stooq(http_get: Callable[[str], str] = _http_get) -> List[PriceBar]:
    """Live-Abruf Quelle 1 (stooq). `http_get` injizierbar fuer Tests."""
    return parse_stooq_csv(http_get(STOOQ_URL))


def fetch_yahoo(http_get: Callable[[str], str] = _http_get) -> List[PriceBar]:
    """Live-Abruf Quelle 2 (Yahoo v8 chart). `http_get` injizierbar fuer Tests."""
    return parse_yahoo_json(http_get(YAHOO_URL))


# ---------------------------------------------------------------------------
# Qualitaets-Checks
# ---------------------------------------------------------------------------

def _weekdays_between(a: date, b: date) -> int:
    """Anzahl Wochentage (Mo-Fr) strikt zwischen a und b (Proxy fuer Handelstage)."""
    n = 0
    cur = a + timedelta(days=1)
    while cur < b:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return n


def quality_check(rows: List[PriceBar]) -> QualityReport:
    """Prueft eine EOD-Serie: 0-/Negativ-Preise (harter Fehler), Luecken (Flag).

    Raises:
        ValueError: bei nicht-positiven Preisen oder unsortierten/duplizierten Daten.
    """
    prev: Optional[PriceBar] = None
    gaps: List[Tuple[date, date, int]] = []
    for bar in rows:
        d, o, h, lo, c = bar
        if min(o, h, lo, c) <= 0.0:
            raise ValueError(f"Nicht-positiver Preis am {d.isoformat()}: {bar}")
        if prev is not None:
            if d <= prev[0]:
                raise ValueError(f"Datumsfolge nicht strikt aufsteigend bei {d.isoformat()}")
            missing = _weekdays_between(prev[0], d)
            if missing > GAP_FLAG_TRADING_DAYS:
                gaps.append((prev[0], d, missing))
        prev = bar
    for g in gaps:
        logger.warning("Daten-Luecke geflaggt: %s -> %s (~%d Handelstage fehlen)", *[
            g[0].isoformat(), g[1].isoformat(), g[2]
        ])
    return QualityReport(
        n_rows=len(rows),
        first_date=rows[0][0] if rows else None,
        last_date=rows[-1][0] if rows else None,
        gaps=gaps,
    )


# ---------------------------------------------------------------------------
# Kreuzvalidierung
# ---------------------------------------------------------------------------

def cross_validate(
    primary: List[PriceBar],
    secondary: List[PriceBar],
    tolerance_pct: float = CROSS_VALIDATION_TOLERANCE_PCT,
) -> CrossValidationReport:
    """Vergleicht Close-Preise beider Quellen auf dem Ueberlapp-Datumsbereich.

    Abweichung pro Tag: |c1 - c2| / mittel(c1, c2) * 100 [Prozent].
    """
    close_a = {b[0]: b[4] for b in primary}
    close_b = {b[0]: b[4] for b in secondary}
    overlap = sorted(set(close_a) & set(close_b))
    if not overlap:
        return CrossValidationReport(0, None, None, float("nan"), float("nan"), tolerance_pct)
    devs = []
    for d in overlap:
        c1, c2 = close_a[d], close_b[d]
        devs.append(abs(c1 - c2) / ((c1 + c2) / 2.0) * 100.0)
    return CrossValidationReport(
        n_overlap=len(overlap),
        overlap_start=overlap[0],
        overlap_end=overlap[-1],
        mean_abs_close_deviation_pct=sum(devs) / len(devs),
        max_abs_close_deviation_pct=max(devs),
        tolerance_pct=tolerance_pct,
    )


# ---------------------------------------------------------------------------
# Cache (CSV mit Kommentar-Header: Quelle + Abrufdatum)
# ---------------------------------------------------------------------------

def write_cache(rows: List[PriceBar], path: Path, source_label: str,
                retrieved_at: Optional[str] = None) -> None:
    """Schreibt PriceBars als CSV mit '#'-Header (Quelle, Abrufdatum, Zeilenzahl)."""
    retrieved = retrieved_at or datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(f"# source: {source_label}\n")
        fh.write(f"# retrieved: {retrieved}\n")
        fh.write(f"# rows: {len(rows)} (gefiltert >= {MIN_START_DATE.isoformat()})\n")
        fh.write("# K_0: nur Daten, keine Anlageentscheidung [CRUX-MK]\n")
        writer = csv.writer(fh)
        writer.writerow(["Date", "Open", "High", "Low", "Close"])
        for d, o, h, lo, c in rows:
            writer.writerow([d.isoformat(), f"{o:.4f}", f"{h:.4f}", f"{lo:.4f}", f"{c:.4f}"])


def read_cache(path: Path) -> List[PriceBar]:
    """Liest eine mit write_cache geschriebene CSV (ignoriert '#'-Kommentare)."""
    with path.open("r", encoding="utf-8") as fh:
        text = "".join(line for line in fh if not line.startswith("#"))
    rows: List[PriceBar] = []
    for rec in csv.DictReader(io.StringIO(text)):
        rows.append((
            datetime.strptime(rec["Date"], "%Y-%m-%d").date(),
            float(rec["Open"]), float(rec["High"]), float(rec["Low"]), float(rec["Close"]),
        ))
    rows.sort(key=lambda b: b[0])
    return rows


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Oeffentliche Loader-API (offline, gegen Cache)
# ---------------------------------------------------------------------------

def load_dax(data_dir: Path = DATA_DIR) -> List[PriceBar]:
    """Laedt DAX-EOD 2006-heute aus dem lokalen Primaer-Cache (OFFLINE, kein Netz).

    Returns:
        Liste von (date, open, high, low, close), aufsteigend sortiert.

    Raises:
        FileNotFoundError: wenn der Cache fehlt (dann: `--refresh` ausfuehren).
        ValueError: bei 0-/Negativ-Preisen oder kaputter Datumsfolge.

    Post-Condition: Qualitaets-Checks gelaufen; Luecken > 5 Handelstage sind
    als Warning geloggt (Report via `quality_check(load_dax())` reproduzierbar).
    """
    cache = data_dir / CACHE_PRIMARY
    if not cache.exists():
        raise FileNotFoundError(
            f"Kein Daten-Cache unter {cache}. Einmalig ausfuehren: "
            f"python3 -m kmo_governance.kpm_backtest.data_loader --refresh"
        )
    rows = read_cache(cache)
    quality_check(rows)  # raises bei harten Fehlern, loggt Gap-Flags
    return rows


# ---------------------------------------------------------------------------
# Refresh (der EINZIGE Pfad mit echten Netz-Calls)
# ---------------------------------------------------------------------------

def refresh_cache(data_dir: Path = DATA_DIR,
                  http_get: Callable[[str], str] = _http_get) -> CrossValidationReport:
    """Echter Abruf beider Quellen, Cache-Write, Kreuzvalidierungs-Report.

    Fallback-Logik (ehrlich, per AP-K2): faellt Quelle 2 aus, wird Quelle 1
    trotzdem gecacht und der Report dokumentiert den Ausfall explizit.
    """
    retrieved = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    primary = fetch_stooq(http_get)
    q1 = quality_check(primary)
    if q1.n_rows < MIN_TRADING_DAYS:
        raise ValueError(
            f"Quelle 1 liefert nur {q1.n_rows} Handelstage (< {MIN_TRADING_DAYS})"
        )
    write_cache(primary, data_dir / CACHE_PRIMARY, STOOQ_SOURCE_LABEL, retrieved)

    secondary: List[PriceBar] = []
    secondary_error: Optional[str] = None
    try:
        secondary = fetch_yahoo(http_get)
        quality_check(secondary)
        write_cache(secondary, data_dir / CACHE_SECONDARY, YAHOO_SOURCE_LABEL, retrieved)
    except Exception as exc:  # ehrlicher Ausfall-Report statt Silent-Fail
        secondary_error = f"{type(exc).__name__}: {exc}"
        logger.error("Quelle 2 (Yahoo) nicht verfuegbar: %s", secondary_error)

    report = cross_validate(primary, secondary)
    _write_report_md(data_dir, report, q1,
                     quality_check(secondary) if secondary else None,
                     retrieved, secondary_error)
    return report


def _write_report_md(data_dir: Path, cv: CrossValidationReport, q1: QualityReport,
                     q2: Optional[QualityReport], retrieved: str,
                     secondary_error: Optional[str]) -> None:
    lines = [
        "# Kreuzvalidierungs-Report DAX-EOD [CRUX-MK]",
        "",
        f"- Abrufdatum (UTC): {retrieved}",
        f"- Quelle 1 (primaer): {STOOQ_SOURCE_LABEL}",
        f"  - Handelstage: {q1.n_rows} ({q1.first_date} bis {q1.last_date})",
        f"  - Luecken > {GAP_FLAG_TRADING_DAYS} Handelstage: {len(q1.gaps)}",
        f"  - SHA256: {_sha256_of(data_dir / CACHE_PRIMARY)}",
    ]
    if q2 is not None:
        lines += [
            f"- Quelle 2 (sekundaer): {YAHOO_SOURCE_LABEL}",
            f"  - Handelstage: {q2.n_rows} ({q2.first_date} bis {q2.last_date})",
            f"  - Luecken > {GAP_FLAG_TRADING_DAYS} Handelstage: {len(q2.gaps)}",
            f"  - SHA256: {_sha256_of(data_dir / CACHE_SECONDARY)}",
            "",
            "## Kreuzvalidierung (Ueberlapp-Datumsbereich, Close-to-Close)",
            f"- Ueberlapp: {cv.n_overlap} Handelstage ({cv.overlap_start} bis {cv.overlap_end})",
            f"- Mittlere abs. Abweichung: {cv.mean_abs_close_deviation_pct:.4f} % "
            f"(Toleranz < {cv.tolerance_pct} %)",
            f"- Max. abs. Abweichung: {cv.max_abs_close_deviation_pct:.4f} %",
            f"- Verdict: {'PASS' if cv.passed else 'FAIL'}",
        ]
    else:
        lines += [
            "- Quelle 2 (sekundaer): AUSGEFALLEN — EHRLICH GEMELDET",
            f"  - Fehler: {secondary_error}",
            "  - Fallback: 1 Live-Quelle + dieser dokumentierte Zustand (per AP-K2)",
        ]
    lines += [
        "",
        "K_0-Disclaimer: Nur Daten. Keine Anlageentscheidung, kein Broker-Zugang.",
        "",
        "[CRUX-MK]",
    ]
    (data_dir / REPORT_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _main() -> int:
    parser = argparse.ArgumentParser(description="KPM DAX-EOD Daten-Ingestion (AP-K2)")
    parser.add_argument("--refresh", action="store_true",
                        help="Echter Netz-Abruf beider Quellen + Cache + Report")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.refresh:
        cv = refresh_cache()
        print(f"Kreuzvalidierung: n={cv.n_overlap} mean={cv.mean_abs_close_deviation_pct:.4f}% "
              f"max={cv.max_abs_close_deviation_pct:.4f}% passed={cv.passed}")
        return 0 if cv.n_overlap == 0 or cv.passed else 1
    rows = load_dax()
    q = quality_check(rows)
    print(f"Cache: {q.n_rows} Handelstage ({q.first_date} bis {q.last_date}), "
          f"Luecken-Flags: {len(q.gaps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
