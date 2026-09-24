"""Loaders for the Accord Fintech stock-level dataset supplied for this
fund: individual-stock daily prices, annual valuation/profitability
ratios, and a monthly point-in-time universe/market-rank file. All four
join on **Accord Code**, an internal numeric security id used consistently
across all four files (confirmed by inspection: the price panel's column
headers, the fundamentals files' "Accord Code" column, and the monthly
universe file's "Accord Code" column all draw from the same numbering,
e.g. Reliance Industries = 100325, TCS = 132540, in every file).

Do not key anything on NSE_symbol or Company Name -- symbols get reused
and names change; Accord Code is this dataset's stable identifier, the
same discipline this repo's README already states for ISIN.

FOUR REAL, VERIFIED DATA-QUALITY FINDINGS (not hypothetical -- found by
actually reading these files before writing this module):

1. The monthly universe file's per-month breadth is NOT continuous.
   2011-2022 grows smoothly (~1450 -> ~1950 names). From July 2023 onward
   it ALTERNATES almost every other month between ~500 names and
   ~2000-2400 names (e.g. Jul'23: 2005, then Oct'23: 501, Nov'23: 2114,
   Dec'23: 501, ...). This is not a real economic change in coverage --
   it looks like two different extraction processes were interleaved.
   Any "top-N by rank" universe built naively from this file after mid-2023
   will alternate between a genuine top-500 selection and a selection out
   of a much smaller, effectively top-500-only pool every other month,
   which is a real bias, not noise to average away.
2. The last four sheets (Apr-Jul 2026) are completely empty. Universe
   coverage genuinely ends around March 2026, ~4 months before the price
   panel's own last date (3 Aug 2026).
3. The sheet SCHEMA itself varies: 135 of 163 sheets have 7 columns
   (Accord Code, Company Name, NDP_Date, NDP_Close, NDP_Mcap, NSE_symbol,
   Market Rank); 36 sheets are missing NSE_symbol and/or NDP_Close. A
   fixed-column parser silently breaks or silently drops data on those.
4. Valuation/profitability carry only `FR_Year End` (e.g. 202503 = fiscal
   year ended March 2025), never an actual results-publication date.
   Indian companies typically report annual results 1-3 months after
   fiscal year-end. Using FR_Year End as the date a number became known
   is a look-ahead bias -- this repo's own `lag_days >= 1` non-negotiable
   is about exactly this class of mistake, just larger here (months, not
   a day). A `reporting_lag_days` parameter is required below, not
   optional, for exactly this reason.
"""
from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import openpyxl
import pandas as pd

from universal_backtester.data import file_sha256

DEFAULT_REPORTING_LAG_DAYS = 75   # ~2.5 months; a documented assumption, not a fact


def load_accord_price_panel(path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Daily close price panel, columns = Accord Code (as int)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Sheet1"] if "Sheet1" in wb.sheetnames else wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    codes = [int(c) for c in header[1:]]
    dates, data = [], []
    for row in rows:
        if row[0] is None:
            continue
        dates.append(pd.to_datetime(row[0]))
        data.append(row[1:])
    wb.close()
    df = pd.DataFrame(data, index=pd.DatetimeIndex(dates, name="date"), columns=codes)
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    prov = {
        "loader": "load_accord_price_panel", "path": path, "sha256": file_sha256(path),
        "n_securities": int(df.shape[1]), "n_dates": int(df.shape[0]),
        "date_min": str(df.index.min().date()), "date_max": str(df.index.max().date()),
    }
    return df, prov


def load_accord_fundamentals(path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Long-format valuation or profitability ratios: one row per (Accord
    Code, fiscal year end, C/S basis). Adds `known_date`, the (assumed)
    date the year's numbers actually became public -- NOT the same as
    `fiscal_year_end`. See DEFAULT_REPORTING_LAG_DAYS in this module's
    docstring for why this matters and why the lag is a stated assumption.
    """
    df = pd.read_excel(path)
    df = df.rename(columns={"Accord Code": "accord_code", "Company Name": "company_name",
                            "FR_Year End": "fiscal_year_end", "CONS_FR_1": "basis"})
    # The export carries a trailing source/disclaimer footer as blank-ish
    # rows with no Accord Code -- real content, not a parsing failure, so
    # drop by that signal rather than by a fixed row count.
    n_before = len(df)
    df = df.dropna(subset=["accord_code", "fiscal_year_end"]).copy()
    n_dropped = n_before - len(df)
    df["accord_code"] = df["accord_code"].astype(int)
    fye = df["fiscal_year_end"].astype(int).astype(str)
    fy_year = fye.str.slice(0, 4).astype(int)
    fy_month = fye.str.slice(4, 6).astype(int)
    df["fiscal_year_end_date"] = pd.to_datetime(
        dict(year=fy_year, month=fy_month, day=1)) + pd.offsets.MonthEnd(0)
    df["known_date"] = df["fiscal_year_end_date"] + pd.Timedelta(days=DEFAULT_REPORTING_LAG_DAYS)
    df["basis"] = df["basis"].map({"C": "consolidated", "S": "standalone"}).fillna(df["basis"])

    dupes = df.duplicated(["accord_code", "fiscal_year_end", "basis"]).sum()
    prov = {
        "loader": "load_accord_fundamentals", "path": path, "sha256": file_sha256(path),
        "n_rows": int(len(df)), "n_securities": int(df["accord_code"].nunique()),
        "n_footer_rows_dropped": int(n_dropped),
        "fiscal_year_end_range": [str(df["fiscal_year_end_date"].min().date()),
                                  str(df["fiscal_year_end_date"].max().date())],
        "duplicate_code_year_basis_rows": int(dupes),
        "reporting_lag_days_assumed": DEFAULT_REPORTING_LAG_DAYS,
    }
    if dupes:
        warnings.warn(f"{path}: {dupes} duplicate (accord_code, fiscal_year_end, basis) rows -- "
                      f"last one wins if you pivot, silently, unless you check this yourself.")
    return df, prov


def load_accord_monthly_universe(path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Point-in-time monthly universe/market-rank file. Tidy long frame:
    columns [month_end, accord_code, company_name, market_rank, mcap,
    close, nse_symbol]. `close`/`nse_symbol` are NaN/None on the ~36
    sheets that don't carry them -- never fabricated.

    Robust to the two real irregularities found in this file: sheets with
    a shorter column set, and sheets that are completely empty (recorded
    in `prov['empty_sheets']`, not silently skipped without a trace).
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    frames: List[pd.DataFrame] = []
    empty_sheets: List[str] = []
    schema_counts: Dict[tuple, int] = {}
    row_counts: List[Tuple[str, int]] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            header = None
        if header is None or all(v is None for v in header):
            empty_sheets.append(sheet_name)
            row_counts.append((sheet_name, 0))
            continue
        schema_counts[header] = schema_counts.get(header, 0) + 1

        col_idx = {name: i for i, name in enumerate(header) if name}
        data = list(rows_iter)
        row_counts.append((sheet_name, len(data)))
        if not data:
            continue

        def col(name):
            i = col_idx.get(name)
            return [r[i] if i is not None and i < len(r) else None for r in data]

        frame = pd.DataFrame({
            "month_end": pd.to_datetime(col("NDP_Date")),
            "accord_code": pd.array(col("Accord Code"), dtype="Int64"),
            "company_name": col("Company Name"),
            "market_rank": pd.array(col("Market Rank"), dtype="Int64"),
            "mcap": pd.to_numeric(pd.Series(col("NDP_Mcap")), errors="coerce"),
            "close": pd.to_numeric(pd.Series(col("NDP_Close")), errors="coerce") if "NDP_Close" in col_idx else np.nan,
            "nse_symbol": col("NSE_symbol") if "NSE_symbol" in col_idx else None,
        })
        frames.append(frame)
    wb.close()

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # The headline finding: month-to-month row-count swings > 50%, which
    # signal an interleaved/inconsistent extraction, not real turnover.
    irregular_months = []
    prev = None
    for sheet_name, rc in row_counts:
        if prev is not None and prev > 0 and rc > 0 and abs(rc - prev) / prev > 0.5:
            irregular_months.append({"sheet": sheet_name, "prev_rows": prev, "rows": rc})
        if rc > 0:
            prev = rc

    prov = {
        "loader": "load_accord_monthly_universe", "path": path, "sha256": file_sha256(path),
        "n_sheets": len(wb.sheetnames), "n_empty_sheets": len(empty_sheets),
        "empty_sheets": empty_sheets,
        "schema_variants": {str(k): v for k, v in schema_counts.items()},
        "row_counts_min_max": [min(r for _, r in row_counts if r > 0),
                               max(r for _, r in row_counts)] if row_counts else [0, 0],
        "irregular_month_to_month_swings": irregular_months,
        "n_irregular_swings": len(irregular_months),
    }
    return result, prov


def diagnose_accord_dataset(price_path: str, universe_path: str) -> pd.DataFrame:
    """The equivalent of ros/data/master.py's diagnose() for this dataset:
    what would silently flatter or break a backtest built on it, named
    plainly, run before anything else touches the data."""
    price, price_prov = load_accord_price_panel(price_path)
    uni, uni_prov = load_accord_monthly_universe(universe_path)

    price_codes = set(price.columns)
    uni_codes = set(uni["accord_code"].dropna().astype(int).unique()) if len(uni) else set()

    rows = []
    rows.append({"check": "price panel securities", "value": len(price_codes), "severity": "info"})
    rows.append({"check": "universe file securities (ever appeared)", "value": len(uni_codes), "severity": "info"})
    rows.append({"check": "price codes with NO universe-file appearance",
                "value": len(price_codes - uni_codes),
                "severity": "warn" if price_codes - uni_codes else "ok"})
    rows.append({"check": "universe codes never in price panel",
                "value": len(uni_codes - price_codes),
                "severity": "warn" if uni_codes - price_codes else "ok"})
    rows.append({"check": "empty universe-file sheets", "value": uni_prov["n_empty_sheets"],
                "severity": "block" if uni_prov["n_empty_sheets"] else "ok",
                "detail": uni_prov["empty_sheets"]})
    rows.append({"check": "month-to-month coverage swings >50%", "value": uni_prov["n_irregular_swings"],
                "severity": "block" if uni_prov["n_irregular_swings"] else "ok",
                "detail": f"first: {uni_prov['irregular_month_to_month_swings'][:3]}"})
    rows.append({"check": "universe-file schema variants", "value": len(uni_prov["schema_variants"]),
                "severity": "warn" if len(uni_prov["schema_variants"]) > 1 else "ok"})
    return pd.DataFrame(rows)
