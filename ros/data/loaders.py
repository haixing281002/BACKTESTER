"""Data loaders. One loader per source format; each returns a tidy wide frame
(DatetimeIndex x series) plus a provenance dict.

Adding a new source = adding a loader here and a DataCapability in the registry.
No engine code changes.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_nse_factor_workbook(
    path: str,
    sheet: str | int = 0,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Load an NSE index workbook (factor sleeves or broad-market indices).

    Layout handled: a banner row of index names, a row of field names, one
    shared Date column, and blank spacer columns between series. Each index
    may occupy either a single field column ('Close' only -- the original
    factor-sleeve export) or a block of several field columns (Open/High/Low/
    Close/PE/PB -- the richer broad-market and factor export). The parser
    locates the date column and the name/field rows by content rather than by
    fixed offsets, so a re-export with shifted columns still loads, and within
    a multi-field block it always prefers 'Close' (the one field guaranteed to
    span the full history; Open/High/Low/PE/PB are frequently populated only
    for a recent window and are dropped rather than silently mislabelled).

    Some exports append an unrelated recap table lower in the sheet, in the
    same columns, after a run of blank rows. Rows are bounded to the
    contiguous run of valid dates in the shared Date column, so that trailing
    debris is never read as data.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None)

    # locate the header row: the row containing a cell equal to 'Date'
    date_row = date_col = None
    for r in range(min(12, len(raw))):
        for c in range(raw.shape[1]):
            v = raw.iat[r, c]
            if isinstance(v, str) and v.strip().lower() == "date":
                date_row, date_col = r, c
                break
        if date_row is not None:
            break
    if date_row is None:
        raise ValueError(f"{path}: could not locate a 'Date' header cell")

    # index names sit on the row above the field row
    name_row = date_row - 1
    series: Dict[str, pd.Series] = {}
    field_names: Dict[str, str] = {}
    all_dates = pd.to_datetime(raw.iloc[date_row + 1:, date_col], errors="coerce")

    # bound to the contiguous run of valid dates starting right after the
    # header, so a recap table appended lower in the sheet is never read.
    valid = all_dates.notna().to_numpy()
    n_rows = 0
    while n_rows < len(valid) and valid[n_rows]:
        n_rows += 1
    if n_rows == 0:
        raise ValueError(f"{path}: no valid dates found under the 'Date' header")
    dates = all_dates.iloc[:n_rows]

    ncols = raw.shape[1]
    c = 0
    while c < ncols:
        if c == date_col:
            c += 1
            continue
        nm = raw.iat[name_row, c] if name_row >= 0 else None
        if not isinstance(nm, str) or not nm.strip():
            c += 1
            continue
        name = re.sub(r"\s+", " ", nm.strip())

        # consume the block of field columns belonging to this index: every
        # column up to (but not including) the next named column or the first
        # blank spacer column.
        block_start = c
        c += 1
        while c < ncols:
            next_nm = raw.iat[name_row, c] if name_row >= 0 else None
            if isinstance(next_nm, str) and next_nm.strip():
                break
            fld = raw.iat[date_row, c]
            if not isinstance(fld, str) or not fld.strip():
                c += 1  # consume the spacer column itself
                break
            c += 1
        block_end = c

        field_cols = {}
        for cc in range(block_start, block_end):
            fld = raw.iat[date_row, cc]
            if isinstance(fld, str) and fld.strip():
                field_cols.setdefault(fld.strip().lower(), cc)
        if not field_cols:
            continue
        chosen = "close" if "close" in field_cols else next(iter(field_cols))
        col = field_cols[chosen]

        vals = pd.to_numeric(raw.iloc[date_row + 1: date_row + 1 + n_rows, col],
                              errors="coerce")
        if vals.notna().sum() == 0:
            continue
        series[name] = pd.Series(vals.values, index=dates.values)
        field_names[name] = chosen.title()

    if not series:
        raise ValueError(f"{path}: no numeric series found")

    df = pd.DataFrame(series)
    df.index.name = "date"
    df = df[~df.index.isna()].sort_index()
    df = df[~df.index.duplicated(keep="last")]

    prov = {
        "loader": "load_nse_factor_workbook",
        "path": path,
        "sha256": file_sha256(path),
        "sheet": str(sheet),
        "n_rows": int(len(df)),
        "n_series": int(df.shape[1]),
        "date_min": str(df.index.min().date()),
        "date_max": str(df.index.max().date()),
        "fields": field_names,
        "series": {
            name: {
                "first": str(df[name].dropna().index.min().date()) if df[name].notna().any() else None,
                "last": str(df[name].dropna().index.max().date()) if df[name].notna().any() else None,
                "n_obs": int(df[name].notna().sum()),
                "gaps_inside_coverage": int(
                    df[name].loc[
                        df[name].dropna().index.min(): df[name].dropna().index.max()
                    ].isna().sum()
                ) if df[name].notna().any() else 0,
                "first_value": float(df[name].dropna().iloc[0]) if df[name].notna().any() else None,
            }
            for name in df.columns
        },
    }
    return df, prov


def load_nse_workbook_combined(path: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Load every sheet of an NSE index workbook and combine into one wide frame.

    Some exports (e.g. broad-market indices and factor sleeves) split into
    separate sheets rather than separate files. This loads each sheet with
    `load_nse_factor_workbook` and joins the results on date. A single-sheet
    workbook -- the original factor-sleeve export -- loads exactly as
    `load_nse_factor_workbook` would.

    An index name present on more than one sheet is an error, not a merge:
    two conflicting histories for the same name must never be silently
    combined into one column.
    """
    sheets = pd.ExcelFile(path).sheet_names
    frames: List[pd.DataFrame] = []
    provs: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    for sheet in sheets:
        df, prov = load_nse_factor_workbook(path, sheet=sheet)
        for col in df.columns:
            if col in seen:
                raise ValueError(
                    f"{path}: '{col}' appears on both sheet '{seen[col]}' and "
                    f"'{sheet}' -- two histories for the same index would be "
                    f"silently merged.")
            seen[col] = sheet
        frames.append(df)
        provs.append(prov)

    combined = pd.concat(frames, axis=1).sort_index()
    prov = {
        "loader": "load_nse_workbook_combined",
        "path": path,
        "sha256": file_sha256(path),
        "sheets": [p["sheet"] for p in provs],
        "n_rows": int(len(combined)),
        "n_series": int(combined.shape[1]),
        "date_min": str(combined.index.min().date()),
        "date_max": str(combined.index.max().date()),
        "fields": {k: v for p in provs for k, v in p["fields"].items()},
        "series": {k: v for p in provs for k, v in p["series"].items()},
    }
    return combined, prov


def synthetic_cash_series(
    index: pd.DatetimeIndex,
    annual_rate: float,
    name: str = "CASH_PROXY",
) -> pd.Series:
    """A declared-constant cash accrual series.

    This is a PROXY and the pipeline labels it as one everywhere it is used.
    A constant rate is wrong in level and wrong in shape (it cannot de-risk you
    into a rate-cut cycle), so any result that depends on it must be shown
    under a rate sensitivity sweep before it is believed.
    """
    daily = (1.0 + annual_rate) ** (1.0 / 252.0) - 1.0
    return pd.Series(daily, index=index, name=name)


def audit_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per-series data-quality audit run before any backtest touches the data."""
    rows: List[Dict[str, Any]] = []
    for c in df.columns:
        s = df[c].dropna()
        if s.empty:
            rows.append({"series": c, "n_obs": 0})
            continue
        r = s.pct_change().dropna()
        inside = df[c].loc[s.index.min():s.index.max()]
        rows.append({
            "series": c,
            "n_obs": len(s),
            "first": s.index.min().date(),
            "last": s.index.max().date(),
            "first_value": round(float(s.iloc[0]), 2),
            "gaps": int(inside.isna().sum()),
            "n_zero_ret": int((r == 0).sum()),
            "max_abs_ret": round(float(r.abs().max()), 4),
            "n_gt_20pct": int((r.abs() > 0.20).sum()),
            "n_stale_5d": int((r.rolling(5).apply(lambda x: (x == 0).all(), raw=True) == 1).sum()),
            "neg_or_zero_px": int((s <= 0).sum()),
        })
    return pd.DataFrame(rows)
