"""Download NSE cash-market bhavcopy into the `cache/` directory that
`ros/data/nse_bhavcopy_ingest.py` reads.

SOURCE LIMIT: this module touches exactly one source, NSE's public bhavcopy
archive (nsearchives.nseindia.com). No login, no key, no other site.

It writes one pickle per trading day, `cache/YYYY-MM-DD.pkl`, with the columns
the ingest module expects:

    DATE, SYMBOL, SERIES, ISIN, OPEN, HIGH, LOW, CLOSE, PREV, QTY, VAL, TRADES

Main-board rows only (ISIN starting `INE`, SERIES in EQ/BE/BZ), as the ingest
module documents. Two archive formats exist and both are handled:

    old     cm02JAN2023bhav.csv.zip              (to about 2024-07)
    UDiFF   BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip   (from 2024-07-08)

The cut-over date is only used to choose which URL to try first; a 404 falls
through to the other format, and a date that 404s on both is recorded as a
non-trading day in `cache/_nontrading.txt` so a re-run does not ask again.

Polite by construction: one session, one request at a time, a delay between
dates, back-off on 403/429, resumable (existing pickles are skipped), and
nothing is retried forever. Prices are RAW (unadjusted).

usage:
    python -m ros.data.nse_bhavcopy_download --years 5
    python -m ros.data.nse_bhavcopy_download --start 2021-10-01 --end 2021-10-15 --delay 1.0
"""
from __future__ import annotations

import argparse
import io
import os
import time
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

import pandas as pd
import requests

RAW_COLS = ["DATE", "SYMBOL", "SERIES", "ISIN", "OPEN", "HIGH", "LOW", "CLOSE",
            "PREV", "QTY", "VAL", "TRADES"]
UDIFF_FROM = date(2024, 7, 8)
SERIES_KEEP = ("EQ", "BE", "BZ")
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
NONTRADING_FILE = "_nontrading.txt"

_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def url_old(d: date) -> str:
    mon = _MON[d.month - 1]
    return (f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{d.year}/{mon}/"
            f"cm{d.day:02d}{mon}{d.year}bhav.csv.zip")


def url_udiff(d: date) -> str:
    return f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def parse_old(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), index_col=False)
    out = pd.DataFrame({
        "DATE": pd.to_datetime(df["TIMESTAMP"], format="%d-%b-%Y"),
        "SYMBOL": df["SYMBOL"], "SERIES": df["SERIES"], "ISIN": df["ISIN"],
        "OPEN": df["OPEN"], "HIGH": df["HIGH"], "LOW": df["LOW"], "CLOSE": df["CLOSE"],
        "PREV": df["PREVCLOSE"], "QTY": df["TOTTRDQTY"], "VAL": df["TOTTRDVAL"],
        "TRADES": df["TOTALTRADES"]})
    return out


def parse_udiff(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), index_col=False)
    out = pd.DataFrame({
        "DATE": pd.to_datetime(df["TradDt"]),
        "SYMBOL": df["TckrSymb"], "SERIES": df["SctySrs"], "ISIN": df["ISIN"],
        "OPEN": df["OpnPric"], "HIGH": df["HghPric"], "LOW": df["LwPric"], "CLOSE": df["ClsPric"],
        "PREV": df["PrvsClsgPric"], "QTY": df["TtlTradgVol"], "VAL": df["TtlTrfVal"],
        "TRADES": df["TtlNbOfTxsExctd"]})
    return out


def keep_mainboard(df: pd.DataFrame) -> pd.DataFrame:
    """Main-board equity only: ISIN starts INE and SERIES in EQ/BE/BZ."""
    m = df["ISIN"].astype(str).str.startswith("INE") & df["SERIES"].isin(SERIES_KEEP)
    out = df[m].copy()
    for c in ("OPEN", "HIGH", "LOW", "CLOSE", "PREV", "QTY", "VAL", "TRADES"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out[RAW_COLS].reset_index(drop=True)


def _read_zip_csv(content: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(content))
    return z.read(z.namelist()[0]).decode("utf8", "ignore")


def fetch_day(d: date, session: requests.Session) -> Tuple[str, Optional[pd.DataFrame]]:
    """('ok', frame) | ('nontrading', None) | ('error', None).

    'nontrading' only when BOTH formats answer 404; any 403, 429, timeout or other
    status is an 'error' so a transient block is never recorded as a holiday.
    """
    order = [(url_udiff, parse_udiff), (url_old, parse_old)] if d >= UDIFF_FROM else \
            [(url_old, parse_old), (url_udiff, parse_udiff)]
    saw_404 = 0
    for url_fn, parse_fn in order:
        status = None
        for k in range(3):
            try:
                r = session.get(url_fn(d), headers=HEADERS, timeout=30)
            except requests.RequestException:
                time.sleep(2 * (k + 1))
                continue
            status = r.status_code
            if status == 200:
                try:
                    frame = keep_mainboard(parse_fn(_read_zip_csv(r.content)))
                except Exception:
                    return "error", None
                return ("ok", frame) if len(frame) else ("error", None)
            if status == 404:
                break
            time.sleep(10 * (k + 1))      # 403 / 429 / 5xx: back off, retry
        if status == 404:
            saw_404 += 1
    return ("nontrading", None) if saw_404 == len(order) else ("error", None)


def _load_nontrading(cache_dir: str) -> set:
    p = os.path.join(cache_dir, NONTRADING_FILE)
    return set(open(p, encoding="utf-8").read().split()) if os.path.exists(p) else set()


def download_range(start: date, end: date, cache_dir: str = "cache", delay: float = 0.8,
                   session: Optional[requests.Session] = None, max_errors: int = 25) -> dict:
    """Fetch every missing weekday in [start, end]. Resumable. Stops after `max_errors`
    consecutive-ish failures so a block is noticed instead of hammered."""
    os.makedirs(cache_dir, exist_ok=True)
    s = session or requests.Session()
    nontrading = _load_nontrading(cache_dir)
    done = {"ok": 0, "skipped_existing": 0, "nontrading": 0, "error": 0}
    errors = 0
    d = start
    while d <= end:
        iso = d.isoformat()
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        if os.path.exists(os.path.join(cache_dir, f"{iso}.pkl")):
            done["skipped_existing"] += 1
        elif iso in nontrading:
            done["nontrading"] += 1
        else:
            status, frame = fetch_day(d, s)
            if status == "ok":
                frame.to_pickle(os.path.join(cache_dir, f"{iso}.pkl"))
                done["ok"] += 1
                errors = 0
            elif status == "nontrading":
                with open(os.path.join(cache_dir, NONTRADING_FILE), "a", encoding="utf-8") as f:
                    f.write(iso + "\n")
                nontrading.add(iso)
                done["nontrading"] += 1
            else:
                done["error"] += 1
                errors += 1
                if errors >= max_errors:
                    print(f"stopping: {errors} errors in a row; the archive may be blocking this client")
                    break
            time.sleep(delay)
        d += timedelta(days=1)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--years", type=float, default=5.0, help="look back this many years from --end (default 5)")
    ap.add_argument("--start", help="YYYY-MM-DD (overrides --years)")
    ap.add_argument("--end", help="YYYY-MM-DD (default today)")
    ap.add_argument("--delay", type=float, default=0.8)
    a = ap.parse_args()
    end = datetime.strptime(a.end, "%Y-%m-%d").date() if a.end else date.today()
    start = datetime.strptime(a.start, "%Y-%m-%d").date() if a.start else end - timedelta(days=int(365.25 * a.years))
    print(f"NSE bhavcopy {start} -> {end} into {a.cache}/")
    print(download_range(start, end, a.cache, a.delay))


if __name__ == "__main__":
    main()
