"""The three files this repository reads market data from. Nothing else is a source.

    1. ACE_PRICES_CSV          Ace Equity daily prices for every listed Indian company, 2000 onward
                               (adjusted and unadjusted OHLC, market cap, volume, traded value, PE, P/BV).
                               Keyed by Accord Code. Loader: ros/data/ace.py
    2. NIFTY500_HOLDINGS_XLSX  Quarterly NIFTY 500 constituent snapshots since 2012 (Bloomberg members), with
                               the Nifty 50 / Next 50 / 100 / Midcap 150 / Smallcap 250 split, plus the
                               Accord Code <-> ISIN <-> NSE symbol master (its "Sheet2").
                               Loader: ros/data/nifty500.py (and ros/data/ace.py for the security master)
    3. NSE_INDEX_WORKBOOK      NSE index levels (broad-market and factor sleeves). Benchmark and sleeve history.
                               Loader: ros/data/loaders.py

Each path can be overridden with an environment variable (LIGHTYEAR_ACE_PRICES, LIGHTYEAR_NIFTY500_HOLDINGS,
LIGHTYEAR_INDEX_WORKBOOK), so a second machine points at its own copies without a code change. Derived files
(Parquet caches, the security master) go under data/processed/; data/raw/ is never written.

There is no downloader anywhere in the repository. A run never fetches: if a file is missing the loaders raise
with the path they looked at, and the operator supplies the file.
"""
from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TZ = ZoneInfo("Asia/Kolkata")

ACE_PRICES_CSV = os.environ.get("LIGHTYEAR_ACE_PRICES") or (
    r"C:\Users\harshil.pahuja\Alpha Alternatives Holdings Private Limited\Rohit Rakhecha - Ace_Equity_Prices"
    r"\prices_2000_2026_merged.csv")
NIFTY500_HOLDINGS_XLSX = os.environ.get("LIGHTYEAR_NIFTY500_HOLDINGS") or (
    r"C:\Users\harshil.pahuja\Desktop\20261022 Nifty 500 Historical Holdings since 2013.xlsx")
NSE_INDEX_WORKBOOK = os.environ.get("LIGHTYEAR_INDEX_WORKBOOK") or os.path.join(
    REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx")

PROCESSED_DIR = os.path.join(REPO, "data", "processed")
# Later NIFTY 500 constituent lists (after the workbook's last snapshot) are dropped here, one CSV per
# snapshot date, named YYYY-MM-DD.csv with an `isin` column. See ros/data/nifty500.py.
NIFTY500_UPDATES_DIR = os.path.join(REPO, "data", "raw", "nifty500_updates")

SOURCES = {
    "ace_prices": ("Ace Equity daily prices (all companies, 2000 onward)", ACE_PRICES_CSV),
    "nifty500_holdings": ("NIFTY 500 quarterly constituents + Accord/ISIN/symbol master", NIFTY500_HOLDINGS_XLSX),
    "nse_index_workbook": ("NSE index levels: broad-market and factor sleeves", NSE_INDEX_WORKBOOK),
}


def now_ist() -> dt.datetime:
    return dt.datetime.now(TZ)


def stamp() -> str:
    """ISO timestamp, tz-aware Asia/Kolkata, for provenance records."""
    return now_ist().isoformat(timespec="seconds")


def require(path: str, what: str) -> str:
    """The file, or a FileNotFoundError that says exactly which path was tried and how to point elsewhere."""
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"{what} not found at {path}. Nothing is downloaded: copy the file there, or set the matching "
            f"environment variable (see ros/data/sources.py).")
    return path


def file_signature(path: str) -> str:
    """Cheap identity of a file's bytes: size and mtime. Used to name caches; sha256 is recorded separately."""
    st = os.stat(path)
    return f"{st.st_size}-{st.st_mtime_ns}"


def describe() -> list[dict]:
    """One row per source: present or not, size, last modified (IST). For check_setup and the page."""
    out = []
    for key, (what, path) in SOURCES.items():
        row = {"key": key, "what": what, "path": path, "exists": os.path.isfile(path)}
        if row["exists"]:
            st = os.stat(path)
            row["size_mb"] = round(st.st_size / 1e6, 1)
            row["modified"] = dt.datetime.fromtimestamp(st.st_mtime, TZ).isoformat(timespec="seconds")
        out.append(row)
    return out


if __name__ == "__main__":
    for r in describe():
        flag = "OK     " if r["exists"] else "MISSING"
        extra = f"  {r['size_mb']:,} MB  modified {r['modified']}" if r["exists"] else ""
        print(f"{flag} {r['key']:<20} {r['path']}{extra}")
