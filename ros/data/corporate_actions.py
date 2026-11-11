# Quant AI Researcher
"""Demergers: the corporate action the Ace Equity file does not adjust for.

On a demerger the parent's price falls by the value handed to holders as spin-off shares, but Ace's adjustment factor
does not change, so the parent's adjusted series shows a crash that did not happen to a holder. This module fixes that
the way a split is fixed: every adjusted open/high/low/close of the parent BEFORE the ex-date is multiplied by

    factor = parent's raw OPEN on the ex-date / parent's raw CLOSE on the session before

(the ex-date open is NSE's special pre-open price discovery for the parent ex the spin-off). Where that open is not a
discovered price -- it differs by more than STALE_OPEN_TOLERANCE from the close-to-close ratio, as on five 2013-2016
ex-dates such as ADANIENT 2015 (open ratio 0.90, close ratio 0.17) -- the ex-date CLOSE / cum-date close is used instead
and the row says so (operator's ruling 2026-11-11). Raw (unadjusted) prices are
left alone; whole-share counts still use them. Decided by the operator on 2026-11-11: the companies' filed cost-of-
acquisition splits are book-value tax figures (RAYMOND 2024 kept 99.47% of cost yet fell 36.6%), so they are kept only
as a reference column.

Files:
    data/reference/demergers_sourced.csv   tracked: events, ex-dates, ISINs, ratios, cost splits and source URLs
                                           (research, no prices). First line is the signature.
    data/processed/corporate_actions/demergers.csv
                                           derived (gitignored): the factor for each event, built from the Ace file
                                           by build_table(); rebuilt when the sourced table or the Ace cache changes.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from ros.data import sources

REPO = sources.REPO
SOURCED = os.path.join(REPO, "data", "reference", "demergers_sourced.csv")
SIGNATURE = "Quant AI Researcher"
PRICE_FIELDS = ("open", "high", "low", "close")
METHOD = "raw ex-date open / raw cum-date close (operator's ruling 2026-11-11)"
METHOD_FALLBACK = "raw ex-date close / raw cum-date close: the ex-date open was not a discovered price"
STALE_OPEN_TOLERANCE = 0.10


class CorporateActionError(RuntimeError):
    pass


def table_path(ace_out_dir: str | None = None) -> str:
    """Beside the Ace cache it is derived from: data/processed/corporate_actions/demergers.csv by default."""
    if ace_out_dir is None:
        return os.path.join(sources.PROCESSED_DIR, "corporate_actions", "demergers.csv")
    return os.path.join(os.path.dirname(os.path.abspath(ace_out_dir)), "corporate_actions", "demergers.csv")


def sourced_events(path: str | None = None) -> pd.DataFrame:
    """The demergers in the sourced table (status CONFIRMED or PARTIAL), one row per (parent ISIN, ex-date)."""
    p = path or SOURCED
    if not os.path.isfile(p):
        raise CorporateActionError(f"sourced demerger table not found at {p}")
    d = pd.read_csv(p, skiprows=1, dtype=str)
    d = d[d["status"].isin(["CONFIRMED", "PARTIAL"])].copy()
    d["ex_date"] = pd.to_datetime(d["ex_date"])
    if d["parent_isin"].isna().any() or d.duplicated(["parent_isin", "ex_date"]).any():
        raise CorporateActionError("every demerger needs a parent ISIN and appears once per ex-date")
    return d.sort_values(["ex_date", "parent_isin"]).reset_index(drop=True)


def factor_for(ex_open: float, ex_close: float, cum_close: float) -> tuple[float, str, str]:
    """(factor, method, problem) for one event: the ex-date open ratio, or the close ratio when the open is stale."""
    factor, method = ex_open / cum_close, METHOD
    if np.isfinite(ex_close) and abs((ex_open / cum_close) / (ex_close / cum_close) - 1) > STALE_OPEN_TOLERANCE:
        factor, method = ex_close / cum_close, METHOD_FALLBACK
    if not 0 < factor < 1:
        return np.nan, method, f"factor {factor:.4f} is not between 0 and 1: not applied"
    return factor, method, ""


def build_table(sourced: str | None = None, out: str | None = None, path: str | None = None,
                out_dir: str | None = None) -> pd.DataFrame:
    """Compute each event's factor from the Ace raw prices and write the derived table."""
    from ros.data import ace
    ev = sourced_events(sourced)
    raw = ace.load_long(["unadj_open", "unadj_close"], path=path, out_dir=out_dir, demergers=False)
    raw = raw[raw["isin"].isin(set(ev["parent_isin"]))]
    rows = []
    for e in ev.itertuples():
        s = raw[raw["isin"] == e.parent_isin].set_index("date").sort_index()
        on = s.loc[s.index == e.ex_date]
        before = s.loc[s.index < e.ex_date]
        if on.empty or before.empty or not np.isfinite(on["unadj_open"].iloc[0]) or not np.isfinite(before["unadj_close"].iloc[-1]):
            factor, cum_date, ex_open, cum_close, why, method = np.nan, None, np.nan, np.nan, "no Ace price on the ex-date or before", ""
        else:
            ex_open, cum_close = float(on["unadj_open"].iloc[0]), float(before["unadj_close"].iloc[-1])
            cum_date = before.index[-1]
            factor, method, why = factor_for(ex_open, float(on["unadj_close"].iloc[0]), cum_close)
        rows.append({"parent_isin": e.parent_isin, "parent_symbol": e.parent_symbol, "ex_date": e.ex_date.date(),
                     "cum_date": cum_date.date() if cum_date is not None else None, "ex_open_raw": ex_open,
                     "cum_close_raw": cum_close, "factor": factor, "method": method,
                     "cost_split_parent_pct": e.cost_split_parent_pct, "source_status": e.status, "problem": why})
    t = pd.DataFrame(rows)
    out = out or table_path(out_dir)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# {SIGNATURE}\n")
        t.to_csv(fh, index=False)
    return t


def load_table(ace_path: str | None = None, ace_out_dir: str | None = None, build_if_missing: bool = True) -> pd.DataFrame:
    """The derived factors (applied events only), for the Ace file and cache given (the defaults: the repo's).
    Rebuilt when absent, or older than the sourced table or the Ace cache."""
    from ros.data import ace
    p = table_path(ace_out_dir)
    prices = ace._cache_paths(ace_path, ace_out_dir)["prices"]
    newest_input = max(os.path.getmtime(SOURCED), os.path.getmtime(prices))
    if not os.path.isfile(p) or os.path.getmtime(p) < newest_input:
        if not build_if_missing:
            raise CorporateActionError(f"demerger table missing or stale at {p}; run ros.data.corporate_actions.build_table()")
        build_table(out=p, path=ace_path, out_dir=ace_out_dir)
    t = pd.read_csv(p, skiprows=1, parse_dates=["ex_date"])
    return t[t["factor"].notna()][["parent_isin", "ex_date", "factor"]].reset_index(drop=True)


def apply(df: pd.DataFrame, table: pd.DataFrame, fields=PRICE_FIELDS) -> pd.DataFrame:
    """Back-adjust a long (date, isin, fields...) frame: each parent's adjusted prices before its ex-date times factor.
    Several demergers of one parent compound. Raw (unadj_*) columns are never touched."""
    cols = [f for f in fields if f in df.columns]
    if not cols or table.empty or "isin" not in df.columns:
        return df
    out = df.copy()
    mult = pd.Series(1.0, index=out.index)
    for e in table.itertuples():
        hit = (out["isin"] == e.parent_isin) & (out["date"] < e.ex_date)
        mult[hit] *= e.factor
    out[cols] = out[cols].mul(mult, axis=0)
    return out


def new_listing_near(company_name: str, date, listings: pd.DataFrame, days: int = 150) -> bool:
    """Did a security whose name starts with the same word list on Ace within `days` after `date`?"""
    word = (str(company_name or "").split() or [""])[0].lower().strip(".,()")
    if len(word) < 4:
        return False
    first = pd.to_datetime(listings["first_date"])
    near = listings[(first > pd.Timestamp(date)) & (first <= pd.Timestamp(date) + pd.Timedelta(days=days))]
    return bool(near["company_name"].str.lower().str.startswith(word).any())


def probable_unadjusted_action(ret: float, factor_changed: bool, new_listing_within_150d: bool,
                               known_demerger: bool, threshold: float = -0.25) -> bool:
    """The gap check's flag: a big one-day drop with no factor change and a new listing soon after, which is not in
    the demerger table, is probably an unadjusted corporate action rather than a crash."""
    return bool(ret <= threshold and not factor_changed and new_listing_within_150d and not known_demerger)


if __name__ == "__main__":
    t = build_table()
    print(t.to_string(max_colwidth=40))
    print(f"\n{int(t['factor'].notna().sum())} of {len(t)} demergers applied; written to {table_path()}")
