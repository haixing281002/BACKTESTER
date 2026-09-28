"""The full NIFTY 500 decile deep-dive: partition the point-in-time top-500
universe into 10 equal-COUNT buckets by market cap (~50 names each) at every
rebalance, and backtest each bucket separately -- not just the top and
bottom deciles (SMALL/BIG), all ten. Recomputed fresh at every rebalance as
membership changes, exactly like the top-500 universe itself (no year is
special-cased; "every year" happens automatically because it's every month).

WHY: the top/bottom-decile pair answers "is there a size effect at the
extremes". The full 10-decile spread answers the sharper question a fund
actually wants -- is the relationship monotonic across the whole market-cap
range, or is it concentrated in (say) decile 1 alone with deciles 2-9 flat?
That distinction is invisible from a two-leg SMALL/BIG comparison.

No AI/API step anywhere here -- market-cap sort only, deterministic, same
inputs produce the same buckets and the same backtest results every time.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from universal_backtester.allocators import build_allocator
from universal_backtester.engine import Backtester, BacktestResult
from universal_backtester.metrics import cagr, ann_vol, max_drawdown


def compute_decile_membership(
    mcap: pd.DataFrame, eligible: pd.DataFrame, n_deciles: int = 10,
) -> Dict[int, pd.DataFrame]:
    """Decile 1 = smallest `1/n_deciles` of that day's ELIGIBLE names by
    market cap, decile `n_deciles` = largest. Buckets are equal by COUNT,
    not by mcap value (matches this repo's existing quantile-cut convention
    for SMALL/BIG, extended to every decile). A name not eligible that day
    (outside the top-500 universe, or excluded by the liquidity floor) gets
    no decile at all -- False in every bucket, never guessed into one.

    Returns {1: bool DataFrame, ..., n_deciles: bool DataFrame}, same shape
    and index/columns as `mcap`.
    """
    m = mcap.where(eligible.reindex_like(mcap).fillna(False))
    rank_pct = m.rank(axis=1, pct=True, method="first")
    bucket = np.ceil(rank_pct * n_deciles)
    bucket = bucket.clip(lower=1, upper=n_deciles)
    return {k: (bucket == k).fillna(False) for k in range(1, n_deciles + 1)}


def run_decile_backtests(
    price_window: pd.DataFrame,
    assets: List[str],
    mcap_daily: pd.DataFrame,
    decile_masks: Dict[int, pd.DataFrame],
    spread_bps: float,
    lag_days: int,
    rebalance: str = "monthly",
    warmup: int = 60,
    min_names: int = 10,
) -> Dict[int, BacktestResult]:
    """One Backtester run per decile, equal-weighted across everyone
    IN that decile that day (quantile=1.0 against a membership mask already
    restricted to the decile -- a name that migrates to a different decile
    is sold at cost on the day it's learned, the same discipline this repo
    already applies to a name leaving the top-500 universe)."""
    results: Dict[int, BacktestResult] = {}
    for k, mask in decile_masks.items():
        bt = Backtester(prices=price_window, assets=assets, spread_bps=spread_bps,
                        lag_days=lag_days, allow_cash=True, membership=mask)
        alloc = build_allocator("cross_sectional", assets, quantile=1.0, weighting="equal",
                                ascending=False, min_names=min_names)
        results[k] = bt.run(allocator=alloc, rebalance=rebalance, alpha=mcap_daily,
                            name=f"Decile {k}", warmup=warmup)
    return results


def summarize_deciles(
    decile_results: Dict[int, BacktestResult],
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    cash_rate: float = 0.06,
) -> pd.DataFrame:
    """One row per decile: cagr, vol, sharpe, max_dd -- the table a fund
    reads to check whether the size effect is monotonic across all ten
    buckets or concentrated at one end."""
    rows = []
    for k in sorted(decile_results):
        r = decile_results[k]
        v = r.value
        if start is not None:
            v = v.loc[v.index >= start]
        if end is not None:
            v = v.loc[v.index <= end]
        ret = v.pct_change(fill_method=None).fillna(0.0)
        vol = ann_vol(ret)
        c = cagr(v)
        rows.append({
            "decile": k, "n_obs": len(v),
            "start": str(v.index.min().date()) if len(v) else "",
            "end": str(v.index.max().date()) if len(v) else "",
            "cagr": c, "vol": vol,
            "sharpe": (c - cash_rate) / vol if vol and vol > 0 else float("nan"),
            "max_dd": max_drawdown(v),
        })
    return pd.DataFrame(rows)


def write_decile_membership_log(
    path: str,
    decile_masks: Dict[int, pd.DataFrame],
    rebalance_dates: pd.DatetimeIndex,
    mcap: pd.DataFrame,
    name_lookup: Optional[dict] = None,
) -> pd.DataFrame:
    """The universe, named: one row per (rebalance date, Accord Code,
    company name, market cap, decile). This is the actual answer to "which
    stocks are in this strategy's universe and where do they rank" -- not a
    description of the rule, the real, dated membership it produced."""
    name_lookup = name_lookup or {}
    dates = [d for d in rebalance_dates if d in mcap.index]
    rows = []
    for d in dates:
        mcap_row = mcap.loc[d]
        for k, mask in decile_masks.items():
            if d not in mask.index:
                continue
            for asset in mask.columns[mask.loc[d].to_numpy(dtype=bool)]:
                rows.append({
                    "date": d, "accord_code": asset,
                    "name": name_lookup.get(asset, ""),
                    "mcap": float(mcap_row.get(asset, float("nan"))),
                    "decile": k,
                })
    out = pd.DataFrame(rows, columns=["date", "accord_code", "name", "mcap", "decile"])
    out = out.sort_values(["date", "decile", "mcap"], ascending=[True, True, False])
    out.to_csv(path, index=False)
    return out


def write_decile_summary_workbook(path: str, summary: pd.DataFrame,
                                  benchmark_rows: Optional[pd.DataFrame] = None) -> None:
    """A plain, readable workbook version of the decile summary table --
    the same numbers as the CSV, formatted as percentages, so this can sit
    next to the SE Return Analytics workbook without needing Excel formulas
    of its own (the underlying numbers are already fully computed)."""
    import openpyxl
    from openpyxl.styles import Font, Alignment

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Decile Summary"

    combined = summary.copy()
    if benchmark_rows is not None and not benchmark_rows.empty:
        combined = pd.concat([summary, benchmark_rows], ignore_index=True, sort=False)

    ws.cell(row=1, column=1,
            value="Decile 10 = cheapest by composite value score, decile 1 = most expensive. "
                  "cagr/vol/max_dd are fractions formatted as %; sharpe is a plain ratio, not a percent.")
    ws.cell(row=1, column=1).font = Font(italic=True, size=9)
    ws.cell(row=1, column=1).alignment = Alignment(wrap_text=True)
    ws.row_dimensions[1].height = 28
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)

    headers = ["decile", "start", "end", "n_obs", "cagr", "vol", "sharpe", "max_dd"]
    for col, h in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=col, value=h)
        cell.font = Font(bold=True)

    pct_cols = {"cagr", "vol", "max_dd"}
    for r, row in enumerate(combined.to_dict("records"), start=3):
        for c, h in enumerate(headers, start=1):
            val = row.get(h, "")
            cell = ws.cell(row=r, column=c, value=val)
            if h in pct_cols and isinstance(val, (int, float)) and not pd.isna(val):
                cell.number_format = "0.00%"
            elif h == "sharpe" and isinstance(val, (int, float)) and not pd.isna(val):
                cell.number_format = "0.00"

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 12
    ws.freeze_panes = "A3"

    wb.save(path)
