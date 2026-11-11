# Quant AI Researcher
"""What a backtest does on a day a stock has no price (operator's rule, 2026-11-11). Shared by every stock-level engine.

For each (date, security), from the raw price panel (NaN = no price that day) and the sourced delisting list:

    TRADED      a price exists: the stock can be ranked, bought and sold that day.
    HOLD        no price, not delisted, at most SUSPENSION_SESSIONS sessions since the last price: a held position stays
                at its last close, nothing trades that day, a pending order rolls to the next day it trades, the stock
                is left out of that signal's ranking, and it is NOT sold because of the missing price.
    SUSPENDED   the same, but more than SUSPENSION_SESSIONS sessions without a price and no delisting on record: still
                valued at the last close, and flagged (listed in the run's Notes).
    DELISTED    no price on or after a CONFIRMED delisting's effective date (data/reference/delistings_sourced.csv:
                delisted voluntarily or compulsorily, merged into another company, or ended by a scheme): the position
                exits at the last available close, flagged.
    NOT_LISTED  before the first price: nothing can be held.

Only a sourced filing date makes a delisting "confirmed" (operator's ruling 2026-11-11); an Ace series that simply stops
is a suspension, never an exit.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DELISTINGS = os.path.join(REPO, "data", "reference", "delistings_sourced.csv")
SUSPENSION_SESSIONS = 20
CONFIRMED_TYPES = ("DELISTED_VOLUNTARY", "DELISTED_COMPULSORY", "MERGED_INTO", "SCHEME_OTHER")

NOT_LISTED, TRADED, HOLD, SUSPENDED, DELISTED = -1, 0, 1, 2, 3
NAMES = {NOT_LISTED: "not listed", TRADED: "traded", HOLD: "hold (no price)", SUSPENDED: "suspended", DELISTED: "delisted"}


def load_delistings(path: str | None = None) -> pd.DataFrame:
    """Confirmed delistings with an effective date: isin, effective_date, type, acquirer_symbol, swap_ratio."""
    p = path or DELISTINGS
    if not os.path.isfile(p):
        raise FileNotFoundError(f"sourced delisting list not found at {p}")
    d = pd.read_csv(p, skiprows=1, dtype=str)
    d = d[d["type"].isin(CONFIRMED_TYPES) & d["effective_date"].notna() & d["isin"].notna()].copy()
    d["effective_date"] = pd.to_datetime(d["effective_date"])
    return (d.sort_values("effective_date").drop_duplicates("isin", keep="first")
            [["isin", "effective_date", "type", "acquirer_symbol", "swap_ratio"]].reset_index(drop=True))


def states(close: pd.DataFrame, delistings: pd.DataFrame | None = None,
           suspension_sessions: int = SUSPENSION_SESSIONS) -> pd.DataFrame:
    """dates x securities of the state codes above, from a RAW price panel (no forward fill)."""
    has = close.notna()
    listed = has.cummax()
    miss = (~has).astype(int)
    run = miss.cumsum() - miss.cumsum().where(has).ffill().fillna(0)        # sessions since the last price
    out = pd.DataFrame(TRADED, index=close.index, columns=close.columns)
    out[~has & listed & (run <= suspension_sessions)] = HOLD
    out[~has & listed & (run > suspension_sessions)] = SUSPENDED
    out[~listed] = NOT_LISTED
    if delistings is not None and len(delistings):
        for e in delistings.itertuples():
            if e.isin in out.columns:
                hit = (out.index >= e.effective_date) & (~has[e.isin]).to_numpy() & listed[e.isin].to_numpy()
                out.loc[hit, e.isin] = DELISTED
    return out.astype(int)


def flagged_events(state: pd.DataFrame, held: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per suspension spell and per delisting: isin, kind, first and last date, sessions. With `held` (a
    dates x securities boolean of positions), only spells the book actually sat through."""
    rows = []
    for kind, code in (("suspended", SUSPENDED), ("delisted", DELISTED)):
        m = state.eq(code)
        if held is not None:
            m &= held.reindex_like(m).fillna(False).astype(bool)
        for isin in m.columns[m.any()]:
            s = m[isin].to_numpy()
            starts = np.flatnonzero(s & ~np.r_[False, s[:-1]])
            ends = np.flatnonzero(s & ~np.r_[s[1:], False])
            for a, b in zip(starts, ends, strict=True):
                rows.append({"isin": isin, "kind": kind, "first": state.index[a].date(), "last": state.index[b].date(),
                             "sessions": int(b - a + 1)})
    return pd.DataFrame(rows, columns=["isin", "kind", "first", "last", "sessions"])
