# Quant AI Researcher by Harshil Pahuja
"""Shared readers for the NIFTY 500 v2 universe build (branch data/universe-v2-alpha-lab).

Membership comes from the Alpha Lab workbook's "Rebalance weights" sheet (a member on a date = any numeric cell; weights
are dropped, never stored). Dated tickers (ticker_asof) come from the row-level CSV of the same pull, because the workbook
only holds an undated ticker history. Every path has an environment override; nothing under data/raw is written.

The NSE-rebuilt spell file (git 6e09344, data/raw/nifty500/) is read from git, not from disk. It is used as an ISIN bridge
and as a referee in reports; it never adds a name to Alpha Lab's membership.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import subprocess
import sys

import openpyxl
import pandas as pd

HOME = os.path.expanduser("~")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from ros.data import sources

AL_XLSX = sources.ALPHALAB_NIFTY500_XLSX
AL_CSV = sources.ALPHALAB_NIFTY500_CSV
OUT = os.path.join(REPO, "data", "processed", "universe")
REPORTS = os.path.join(OUT, "reports")
NSE_SPELLS_COMMIT = "6e09344"
SIGNATURE = "Quant AI Researcher by Harshil Pahuja"


def write_csv(df: pd.DataFrame, path: str) -> str:
    """CSV whose first line is the signature; read back with read_csv(path, skiprows=1)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# {SIGNATURE}\n")
        df.to_csv(fh, index=False)
    return path


def md_table(df: pd.DataFrame) -> str:
    """A Markdown table without the optional tabulate dependency."""
    cols = [str(c) for c in df.columns]
    body = [" | ".join("" if pd.isna(v) else str(v) for v in row) for row in df.itertuples(index=False)]
    sep = chr(10)
    return sep.join(["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|", *("| " + b + " |" for b in body)])


def read_rebalance_membership(path: str = AL_XLSX) -> pd.DataFrame:
    """Long frame: date, barrid, one row per member per weight-update date. Weights are read only to test 'numeric'."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = wb["Rebalance weights"].iter_rows(values_only=True)
        header = next(rows)
        dates = {i: pd.Timestamp(c) for i, c in enumerate(header) if isinstance(c, (dt.datetime, dt.date))}
        out = []
        for r in rows:
            if not isinstance(r[0], str):          # the Total and Names rows have a blank Barrid
                continue
            out += [(d, r[0]) for i, d in dates.items() if isinstance(r[i], (int, float)) and not isinstance(r[i], bool)]
    finally:
        wb.close()
    return pd.DataFrame(out, columns=["date", "barrid"]).sort_values(["date", "barrid"]).reset_index(drop=True)


def read_names_ever(path: str = AL_XLSX) -> pd.DataFrame:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(wb["Names ever"].iter_rows(values_only=True))
    finally:
        wb.close()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    return df[df["Barrid"].notna()].rename(columns={"Barrid": "barrid", "Latest ticker": "latest_ticker",
                                                     "Ticker history (oldest > newest)": "history"})


def read_daily(path: str = AL_CSV) -> pd.DataFrame:
    """date, barrid, ticker_asof for every trading day. The weight column is not loaded."""
    return pd.read_csv(path, usecols=["date", "barrid", "ticker_asof"], parse_dates=["date"], keep_default_na=False)


def read_nse_spells() -> pd.DataFrame:
    """NSE-rebuilt spells as committed at 6e09344: symbol valid during the spell, isin, start_date, end_date (exclusive)."""
    raw = subprocess.run(["git", "show", f"{NSE_SPELLS_COMMIT}:data/raw/nifty500/nifty500_membership.csv"], cwd=REPO,
                         capture_output=True, check=True).stdout
    df = pd.read_csv(io.BytesIO(raw), keep_default_na=False)
    for c in ("start_date", "end_date", "last_day_in_index"):
        df[c] = pd.to_datetime(df[c].replace("", None))
    return df
