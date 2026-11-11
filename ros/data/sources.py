# Quant AI Researcher
"""The three files this repository reads market data from. Nothing else is a source.

    1. ACE_PRICES_CSV          Ace Equity daily prices for the companies Ace covers, 2000 onward (not every listed company)
                               (adjusted and unadjusted OHLC, market cap, volume, traded value, PE, P/BV).
                               Keyed by Accord Code. Loader: ros/data/ace.py
    2. NIFTY500_HOLDINGS_XLSX  Quarterly NIFTY 500 constituent snapshots since 2012 (Bloomberg members), with
                               the Nifty 50 / Next 50 / 100 / Midcap 150 / Smallcap 250 split, plus the
                               Accord Code <-> ISIN <-> NSE symbol master (its "Sheet2").
                               Loader: ros/data/nifty500.py (and ros/data/ace.py for the security master)
    3. NSE_INDEX_WORKBOOK      NSE index levels (broad-market and factor sleeves). Benchmark and sleeve history.
                               Loader: ros/data/loaders.py

Each path comes from an environment variable (LIGHTYEAR_ACE_PRICES, LIGHTYEAR_NIFTY500_HOLDINGS,
LIGHTYEAR_INDEX_WORKBOOK) or, failing that, from the matching key in the gitignored config/local.yaml (see
config/local.example.yaml and SETUP.md). No machine's own paths are written in the code. Derived files
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

LOCAL_CONFIG = os.path.join(REPO, "config", "local.yaml")


def _local_config() -> dict:
    if not os.path.isfile(LOCAL_CONFIG):
        return {}
    import yaml
    with open(LOCAL_CONFIG, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


_LOCAL = _local_config()


def _path(env: str, key: str, default: str = "") -> str:
    """Environment variable, else config/local.yaml, else the default ("" = not configured)."""
    return os.environ.get(env) or _LOCAL.get(key) or default


ACE_PRICES_CSV = _path("LIGHTYEAR_ACE_PRICES", "ace_prices")
NIFTY500_HOLDINGS_XLSX = _path("LIGHTYEAR_NIFTY500_HOLDINGS", "nifty500_holdings")
NSE_INDEX_WORKBOOK = _path("LIGHTYEAR_INDEX_WORKBOOK", "nse_index_workbook", os.path.join(
    REPO, "data", "raw", "NSE_Broad_Factor_Indices_Historical_Data.xlsx"))

PROCESSED_DIR = os.path.join(REPO, "data", "processed")
# BUILD-TIME source for the NIFTY 500 universe v2 (data/processed/universe/, loader ros.data.nifty500 with
# membership_source "nifty500_members_v2"): the Alpha Lab constituents pull of 2026-10-30. Read only by
# scripts/universe_v2/*; a run reads the derived spells CSV and never this file.
ALPHALAB_NIFTY500_XLSX = _path("LIGHTYEAR_ALPHALAB_XLSX", "alphalab_nifty500_xlsx")
ALPHALAB_NIFTY500_CSV = _path("LIGHTYEAR_ALPHALAB_CSV", "alphalab_nifty500_csv")
BUILD_SOURCES = {
    "alphalab_nifty500_xlsx": ("Alpha Lab NIFTY 500 constituents workbook (universe v2 build only)", ALPHALAB_NIFTY500_XLSX),
    "alphalab_nifty500_csv": ("Alpha Lab NIFTY 500 row-level pull, dated tickers (universe v2 build only)", ALPHALAB_NIFTY500_CSV),
}
# Later NIFTY 500 constituent lists (after the workbook's last snapshot) are dropped here, one CSV per
# snapshot date, named YYYY-MM-DD.csv with an `isin` column. See ros/data/nifty500.py.
NIFTY500_UPDATES_DIR = os.path.join(REPO, "data", "raw", "nifty500_updates")

SOURCES = {
    "ace_prices": ("Ace Equity daily prices (the companies Ace covers, 2000 onward)", ACE_PRICES_CSV),
    "nifty500_holdings": ("NIFTY 500 quarterly constituents + Accord/ISIN/symbol master", NIFTY500_HOLDINGS_XLSX),
    "nse_index_workbook": ("NSE index levels: broad-market and factor sleeves", NSE_INDEX_WORKBOOK),
}


def now_ist() -> dt.datetime:
    return dt.datetime.now(TZ)


def stamp() -> str:
    """ISO 8601 timestamp for provenance records: stored in UTC with its offset (shown in IST where displayed)."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def require(path: str, what: str) -> str:
    """The file, or a FileNotFoundError that says exactly which path was tried and how to point elsewhere."""
    if not path:
        raise FileNotFoundError(
            f"{what} is not configured. Set its environment variable or its key in config/local.yaml "
            f"(see SETUP.md and config/local.example.yaml).")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"{what} not found at {path}. Nothing is downloaded: copy the file there, or set the matching "
            f"environment variable or config/local.yaml key (see SETUP.md).")
    return path


def file_signature(path: str) -> str:
    """Cheap identity of a file's bytes: size and mtime. Used to name caches; sha256 is recorded separately."""
    st = os.stat(path)
    return f"{st.st_size}-{st.st_mtime_ns}"


def describe(include_build: bool = False) -> list[dict]:
    """One row per source: present or not, size, last modified (IST). For check_setup and the page.
    `include_build` adds the build-time sources of derived universes (not needed to run)."""
    out = []
    items = list(SOURCES.items()) + (list(BUILD_SOURCES.items()) if include_build else [])
    for key, (what, path) in items:
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
