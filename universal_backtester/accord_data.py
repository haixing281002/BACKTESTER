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

DATA-QUALITY FINDINGS, and how each is actually handled (confirmed by the
fund, 2026-09-24 -- not hypothetical, found by reading these files):

1. The monthly universe file's per-month breadth is NOT continuous.
   2011-2022 grows smoothly (~1450 -> ~1950 names). From July 2023 onward
   it ALTERNATES almost every other month between ~500 names and
   ~2000-2400 names (e.g. Jul'23: 2005, then Oct'23: 501, Nov'23: 2114,
   Dec'23: 501, ...). CONFIRMED (fund, 2026-09-24): the ~500-row months
   ARE a genuine top-500-by-market-rank export, and the ~2000+-row months
   are the same top 500 plus the rest of the universe below it -- both
   carry a correct `Market Rank` column. get_top_n_universe() filters
   EVERY month to `market_rank <= 500`, recovering one consistent NIFTY
   500 proxy across the whole file without discarding any months. Use
   this, not the raw per-month row count, as the universe.
2. The last four sheets (Apr-Jul 2026) are completely empty. Universe
   coverage genuinely ends around March 2026, ~4 months before the price
   panel's own last date (3 Aug 2026). Still unresolved -- no membership
   information exists past March 2026 regardless of the filter above.
3. The sheet SCHEMA itself varies: 135 of 163 sheets have 7 columns
   (Accord Code, Company Name, NDP_Date, NDP_Close, NDP_Mcap, NSE_symbol,
   Market Rank); 36 sheets are missing NSE_symbol and/or NDP_Close. A
   fixed-column parser silently breaks or silently drops data on those.
4. Valuation/profitability carry only `FR_Year End` (e.g. 202503 = fiscal
   year ended March 2025), never an actual results-publication date, by
   themselves. RESOLVED: w_publishing_date_data.xlsx (loaded by
   load_publishing_dates()) carries a real `YR_Result Date` per (Accord
   Code, fiscal year end, C/S basis) for ~65,800 rows / 8,536 companies.
   Pass its path as `publishing_dates_path` to load_accord_fundamentals()
   to join the real date and use it as `known_date`; DEFAULT_REPORTING_LAG_DAYS
   (75 days) remains only as the fallback for the rows with no match or an
   implausible result date (before the fiscal year end, or >1yr after it
   -- both true data errors present in the source, handled by keeping the
   assumption for just those rows rather than trusting a broken date).

Tradable universe: the price panel (1314 securities) is smaller than the
full universe file (~3060 distinct codes ever seen). restrict_to_priced_universe()
intersects a universe frame against the price panel's own codes -- per the
fund's guidance, stock selection and backtesting should draw from this
1314-security, fully-priced set, not the wider universe file on its own.
"""
from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import openpyxl
import pandas as pd

from universal_backtester.data import file_sha256

DEFAULT_REPORTING_LAG_DAYS = 75   # ~2.5 months; used ONLY when a real result date
                                  # (from load_publishing_dates) isn't available for a
                                  # given (accord_code, fiscal_year_end) -- see below.

# HARDCODED backtest window, fund decision (2026-09-24), applies to every
# stock-selection backtest built on this dataset: 31 March 2013 through
# 31 August 2026. Not derived, not left to the model to pick per run.
# Matches the reference "SE Return Analytics" workbook's own window
# exactly (its first monthly return is for April 2013 -- i.e. the day
# BEFORE that, 31 March 2013, is its base/inception date -- and its last
# is for August 2026), and sits inside the Accord price panel's full
# 2012-01-02 to 2026-07-31 coverage with room for a 252-day momentum
# lookback before the window opens.
BACKTEST_START = pd.Timestamp("2013-03-31")
BACKTEST_END = pd.Timestamp("2026-08-31")

TOP_N_NIFTY500_PROXY = 500   # market_rank cutoff used as the NIFTY 500 proxy; applied
                             # per month regardless of how many rows that month's sheet
                             # happens to carry -- see get_top_n_universe().


def load_publishing_dates(path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Real results-publication dates (`YR_Result Date`), one row per
    (Accord Code, fiscal year end, C/S basis). This is the actual date a
    year's numbers became public -- not a guess like
    DEFAULT_REPORTING_LAG_DAYS. Use this to join against
    load_accord_fundamentals()'s output instead of trusting the +75-day
    assumption wherever a real date is available.

    The source sheet has 3 blank rows before its header, and trailing
    rows with no Accord Code (same export-footer pattern as the valuation/
    profitability files) -- both handled the same way as elsewhere in this
    module: dropped by signal (no accord_code), not by a fixed row count,
    with the drop count reported in provenance.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    header_idx = next(i for i, r in enumerate(rows) if r and r[0] == "Sr.No.")
    header = rows[header_idx]
    df = pd.DataFrame(rows[header_idx + 1:], columns=header)
    df = df.rename(columns={
        "Accord Code": "accord_code", "Company Name": "company_name",
        "YR_Date End": "fiscal_year_end", "YR_Year": "fiscal_year",
        "YR_Result Date": "result_date", "CONS_YR_1": "basis",
    })

    n_before = len(df)
    df = df.dropna(subset=["accord_code", "fiscal_year_end"]).copy()
    n_footer_dropped = n_before - len(df)

    df["accord_code"] = df["accord_code"].astype(int)
    fye = df["fiscal_year_end"].astype(int).astype(str)
    df["fiscal_year_end_date"] = (
        pd.to_datetime(fye, format="%Y%m") + pd.offsets.MonthEnd(0))
    df["result_date"] = pd.to_datetime(df["result_date"], errors="coerce")
    df["basis"] = df["basis"].map({"C": "consolidated", "S": "standalone"}).fillna(df["basis"])

    n_no_result_date = int(df["result_date"].isna().sum())
    lag = (df["result_date"] - df["fiscal_year_end_date"]).dt.days
    n_negative_lag = int((lag < 0).sum())          # result date before FYE -- data error
    n_implausible_lag = int((lag > 365).sum())      # >1yr after FYE -- almost certainly wrong

    prov = {
        "loader": "load_publishing_dates", "path": path, "sha256": file_sha256(path),
        "n_rows": int(len(df)), "n_securities": int(df["accord_code"].nunique()),
        "n_footer_rows_dropped": int(n_footer_dropped),
        "n_no_result_date": n_no_result_date,
        "n_negative_lag_dates_suspect": n_negative_lag,
        "n_implausible_lag_over_1yr_suspect": n_implausible_lag,
        "lag_days_median": float(lag.median()) if lag.notna().any() else None,
    }
    return df, prov


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


def load_accord_fundamentals(
    path: str, publishing_dates_path: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Long-format valuation or profitability ratios: one row per (Accord
    Code, fiscal year end, C/S basis). Adds `known_date`, the date the
    year's numbers actually became public.

    Pass `publishing_dates_path` (a file loadable by load_publishing_dates,
    e.g. w_publishing_date_data.xlsx) to join REAL result dates on
    (accord_code, fiscal_year_end_date, basis) -- `known_date` is then the
    real `result_date` wherever a match exists, and only falls back to
    `fiscal_year_end + DEFAULT_REPORTING_LAG_DAYS` for rows with no match
    (reported as `n_known_date_from_assumption` in provenance, versus
    `n_known_date_from_real_date`). Without this argument, every row uses
    the assumption, exactly as before.
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
    df["basis"] = df["basis"].map({"C": "consolidated", "S": "standalone"}).fillna(df["basis"])
    df["known_date"] = df["fiscal_year_end_date"] + pd.Timedelta(days=DEFAULT_REPORTING_LAG_DAYS)
    df["known_date_source"] = "assumed_lag"

    n_from_real_date = 0
    if publishing_dates_path is not None:
        pub, _pub_prov = load_publishing_dates(publishing_dates_path)
        pub_small = pub[["accord_code", "fiscal_year_end_date", "basis", "result_date"]].dropna(
            subset=["result_date"])
        pub_small = pub_small.drop_duplicates(["accord_code", "fiscal_year_end_date", "basis"])
        df = df.merge(pub_small, on=["accord_code", "fiscal_year_end_date", "basis"], how="left")
        matched = df["result_date"].notna()
        # A real result date before the fiscal year end, or absurdly far
        # after it, is a data error in the source file -- keep the
        # assumption for those rows rather than trusting a broken date.
        plausible = matched & (df["result_date"] >= df["fiscal_year_end_date"]) & \
            (df["result_date"] <= df["fiscal_year_end_date"] + pd.Timedelta(days=365))
        df.loc[plausible, "known_date"] = df.loc[plausible, "result_date"]
        df.loc[plausible, "known_date_source"] = "real_result_date"
        n_from_real_date = int(plausible.sum())
        df = df.drop(columns=["result_date"])

    dupes = df.duplicated(["accord_code", "fiscal_year_end", "basis"]).sum()
    prov = {
        "loader": "load_accord_fundamentals", "path": path, "sha256": file_sha256(path),
        "n_rows": int(len(df)), "n_securities": int(df["accord_code"].nunique()),
        "n_footer_rows_dropped": int(n_dropped),
        "fiscal_year_end_range": [str(df["fiscal_year_end_date"].min().date()),
                                  str(df["fiscal_year_end_date"].max().date())],
        "duplicate_code_year_basis_rows": int(dupes),
        "reporting_lag_days_assumed": DEFAULT_REPORTING_LAG_DAYS,
        "publishing_dates_path": publishing_dates_path,
        "n_known_date_from_real_date": n_from_real_date,
        "n_known_date_from_assumption": int(len(df) - n_from_real_date),
    }
    if dupes:
        warnings.warn(f"{path}: {dupes} duplicate (accord_code, fiscal_year_end, basis) rows -- "
                      f"last one wins if you pivot, silently, unless you check this yourself.")
    return df, prov


def load_accord_monthly_universe(path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Point-in-time monthly universe/market-rank file. Tidy long frame:
    columns [month_end, sheet_name, accord_code, company_name, market_rank,
    mcap, close, nse_symbol]. `close`/`nse_symbol` are NaN/None on the ~36
    sheets that don't carry them -- never fabricated.

    Robust to three real irregularities found in this file: sheets with a
    shorter column set, sheets that are completely empty (recorded in
    `prov['empty_sheets']`), and a handful of individual rows whose own
    `NDP_Date` cell is wrong (a different date than every other row on
    that sheet -- a data-entry error, not a second snapshot). `month_end`
    is therefore taken from the SHEET's own name (parsed once, applied to
    every row on it), not from each row's own NDP_Date -- grouping by the
    per-row date instead produces spurious single-row "phantom months"
    wherever one of these bad cells exists (confirmed: ~15 such sheets in
    the real file). `sheet_name` is kept alongside for traceability back
    to the source tab.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    frames: List[pd.DataFrame] = []
    empty_sheets: List[str] = []
    schema_counts: Dict[tuple, int] = {}
    row_counts: List[Tuple[str, int]] = []
    bad_date_sheets: List[Dict[str, Any]] = []
    mislabeled_sheets: List[Dict[str, Any]] = []

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

        # The sheet's own month is the mode of its rows' NDP_Date -- robust
        # to the odd row with a wrong date, since the vast majority of a
        # sheet's rows carry the correct one.
        row_dates = pd.to_datetime(pd.Series(col("NDP_Date")), errors="coerce")
        sheet_month = row_dates.mode().iloc[0] if row_dates.notna().any() else pd.NaT
        n_row_dates_disagreeing = int((row_dates != sheet_month).sum()) if pd.notna(sheet_month) else 0

        frame = pd.DataFrame({
            "month_end": sheet_month,
            "sheet_name": sheet_name,
            "accord_code": pd.array(col("Accord Code"), dtype="Int64"),
            "company_name": col("Company Name"),
            "market_rank": pd.array(col("Market Rank"), dtype="Int64"),
            "mcap": pd.to_numeric(pd.Series(col("NDP_Mcap")), errors="coerce"),
            "close": pd.to_numeric(pd.Series(col("NDP_Close")), errors="coerce") if "NDP_Close" in col_idx else np.nan,
            "nse_symbol": col("NSE_symbol") if "NSE_symbol" in col_idx else None,
        }, index=range(len(data)))
        frames.append(frame)
        if n_row_dates_disagreeing:
            bad_date_sheets.append({"sheet": sheet_name, "n_rows_with_wrong_date": n_row_dates_disagreeing})

        # A sheet whose ENTIRE content is dated to a different month than
        # its own tab name is not a stray-row typo -- it's a whole sheet
        # of duplicate content mislabeled as a distinct month (confirmed:
        # "31-Jul-2023" is entirely the "30-Jun-2023" top-500 snapshot,
        # meaning July 2023 has no real data of its own in this file at
        # all). Detected by parsing the tab name as a date and comparing
        # its month to the sheet's own content month.
        try:
            tab_date = pd.to_datetime(sheet_name, format="%d-%b-%Y")
        except (ValueError, TypeError):
            tab_date = None
        if tab_date is not None and pd.notna(sheet_month) and \
                (tab_date.year, tab_date.month) != (sheet_month.year, sheet_month.month):
            mislabeled_sheets.append({
                "sheet": sheet_name, "sheet_name_implies": str(tab_date.date()),
                "content_is_actually_for": str(sheet_month.date()),
            })
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
        "sheets_with_a_stray_row_date": bad_date_sheets,
        "n_sheets_with_a_stray_row_date": len(bad_date_sheets),
        "mislabeled_sheets": mislabeled_sheets,
        "n_mislabeled_sheets": len(mislabeled_sheets),
    }
    return result, prov


def get_top_n_universe(
    universe_df: pd.DataFrame, n: int = TOP_N_NIFTY500_PROXY,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Filter the monthly universe frame to `market_rank <= n` for every
    month, independent of how many rows that month's sheet happened to
    carry. This is the fix for the file's headline irregularity: the
    ~500-row months are a genuine top-500-by-rank export, and the
    ~2000+-row months are the same top-500 plus everyone else -- taking
    `market_rank <= 500` from EVERY month (confirmed present and correctly
    ordered in both the short and long sheets) recovers one consistent
    NIFTY 500 proxy across the whole file, resolving the alternation
    without discarding any months.

    Still bounded by where the source file itself has real coverage:
    check `diagnose_accord_dataset()`'s "empty universe-file sheets"
    finding for the trailing gap (Apr-Jul 2026 are empty regardless of
    this filter).
    """
    df = universe_df.dropna(subset=["market_rank"]).copy()
    df["market_rank"] = df["market_rank"].astype(int)
    out = df[df["market_rank"] <= n].copy()

    counts = out.groupby("month_end").size()
    prov = {
        "n": n, "n_months": int(counts.shape[0]),
        "rows_per_month_min_max": [int(counts.min()), int(counts.max())] if len(counts) else [0, 0],
        "months_with_fewer_than_n": int((counts < n).sum()),
    }
    return out, prov


def restrict_to_priced_universe(
    universe_df: pd.DataFrame, price_codes,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Constrain a (typically top-N) universe frame to the Accord Codes
    that actually have a price series in price_data_till_03aug2026.xlsx --
    the 1314-security panel. A cross-sectional strategy should rank and
    select only from this intersection: a name in the universe file with
    no matching price series can be ranked but never priced or traded.
    """
    price_codes = set(int(c) for c in price_codes)
    df = universe_df.copy()
    in_panel = df["accord_code"].astype("Int64").isin(price_codes)
    kept, dropped = df[in_panel].copy(), df[~in_panel]
    prov = {
        "n_rows_in": int(len(df)), "n_rows_kept": int(len(kept)),
        "n_rows_dropped_no_price_series": int(len(dropped)),
        "n_codes_dropped_no_price_series": int(dropped["accord_code"].nunique()) if len(dropped) else 0,
    }
    return kept, prov


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
                "severity": "warn" if uni_prov["n_irregular_swings"] else "ok",
                "detail": "RESOLVED by design: confirmed the short months are a genuine top-500 "
                          "export and the long months are the same top-500 plus the rest of the "
                          "universe -- use get_top_n_universe(df, 500) to recover one consistent "
                          f"series instead of the raw row count. first raw swing: "
                          f"{uni_prov['irregular_month_to_month_swings'][:3]}"})
    rows.append({"check": "universe-file schema variants", "value": len(uni_prov["schema_variants"]),
                "severity": "warn" if len(uni_prov["schema_variants"]) > 1 else "ok"})
    rows.append({"check": "sheets whose entire content is dated to a different month than their tab name",
                "value": uni_prov["n_mislabeled_sheets"],
                "severity": "block" if uni_prov["n_mislabeled_sheets"] else "ok",
                "detail": uni_prov["mislabeled_sheets"]})
    rows.append({"check": "sheets with a stray wrong-dated row (minority of rows disagree with the sheet)",
                "value": uni_prov["n_sheets_with_a_stray_row_date"],
                "severity": "warn" if uni_prov["n_sheets_with_a_stray_row_date"] else "ok",
                "detail": uni_prov["sheets_with_a_stray_row_date"][:5]})
    return pd.DataFrame(rows)
