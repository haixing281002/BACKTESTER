"""Official point-in-time NIFTY 500 membership, 18 Apr 2013 onwards.

The file is data/raw/nifty500/nifty500_membership.csv: one row per membership spell, rebuilt from NSE's
own documents (month-end constituent files, IndexInclExcl.xls, every NSE Indices press release) and checked
against 128 NSE snapshots. Its README says how, and what disagrees.

    from ros.data.nifty500 import members_on, membership_panel
    members_on("2024-03-28")                       # DataFrame: symbol, isin, company_name
    membership_panel(dates, columns=isins)          # dates x ISIN booleans, the engine's `membership=`

A row is in the index on day d when start_date <= d < end_date (NSE's effective date convention:
"effective March 28 (close of March 27)" means a member from the 28th). `symbol` is the NSE symbol valid
during that row, so it matches that day's bhavcopy; key anything durable on `isin`.

Two entry types are left out by default, because a strategy cannot or should not hold them:
  demerger_placeholder  NSE's zero-price stand-in for a company being demerged (DUMMYxxx); not tradable.
  demerger_temporary    the spun-off company for the few days NSE keeps it after listing (e.g. JIOFIN, Aug 2023).
"""
from __future__ import annotations

import os
from collections.abc import Iterable

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMBERSHIP_CSV = os.path.join(REPO, "data", "raw", "nifty500", "nifty500_membership.csv")
FIRST_DATE = pd.Timestamp("2013-04-18")
TRADABLE = ("regular",)


def load_membership(path: str = MEMBERSHIP_CSV, entry_types: Iterable[str] | None = TRADABLE) -> pd.DataFrame:
    """The spells, with start_date / end_date as Timestamps (end_date NaT = still a member)."""
    m = pd.read_csv(path, parse_dates=["start_date", "end_date"], keep_default_na=False, na_values={"end_date": [""]})
    if entry_types is not None:
        m = m[m["entry_type"].isin(list(entry_types))]
    return m.reset_index(drop=True)


def _check_date(d) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize()
    if d < FIRST_DATE:
        raise ValueError(f"NIFTY 500 membership starts {FIRST_DATE.date()}; {d.date()} is before it")
    return d


def members_on(d, m: pd.DataFrame | None = None) -> pd.DataFrame:
    """Members in force at the close of day d."""
    d = _check_date(d)
    m = load_membership() if m is None else m
    x = m[(m["start_date"] <= d) & (m["end_date"].isna() | (m["end_date"] > d))]
    return x[["symbol", "isin", "company_name"]].reset_index(drop=True)


def membership_panel(dates: Iterable, columns: Iterable[str] | None = None, key: str = "isin",
                     m: pd.DataFrame | None = None) -> pd.DataFrame:
    """dates x `key` (isin or symbol) booleans, True where the security was a member that day.

    Pass `columns` to align with a price panel; members missing from `columns` are dropped (callers that care
    should count them: a member with no price is a data gap, not a non-member)."""
    m = load_membership() if m is None else m
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates))).normalize()
    if len(idx) and idx.min() < FIRST_DATE:
        raise ValueError(f"NIFTY 500 membership starts {FIRST_DATE.date()}; panel starts {idx.min().date()}")
    cols = pd.Index(m[key].unique()) if columns is None else pd.Index(columns)
    out = pd.DataFrame(False, index=idx, columns=cols)
    end = m["end_date"].fillna(pd.Timestamp.max)
    for k, s, e in zip(m[key], m["start_date"], end):
        if k in out.columns:
            out.loc[(idx >= s) & (idx < e), k] = True
    return out


def change_dates(m: pd.DataFrame | None = None) -> pd.DatetimeIndex:
    """Every date the membership changed (starts and ends), sorted."""
    m = load_membership() if m is None else m
    return pd.DatetimeIndex(sorted(set(m["start_date"]) | set(m["end_date"].dropna())))
