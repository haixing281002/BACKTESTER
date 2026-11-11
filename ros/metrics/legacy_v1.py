# Quant AI Researcher
"""Metric code as gate v1 used it. Nothing reports from here.

Two reasons this exists. Gate v1 must stay measurable, so the calibration can compare v1 with v2 on the same synthetic
returns. And a replication target printed in a paper is on that paper's definition: a paper's geometric Sharpe has to be
compared with a geometric Sharpe (ros.validation.research.replication_gap), which is the only live use.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ros.metrics.core import ANN, ann_vol, cagr, max_drawdown


def compounded_cash_cagr(rf_daily: pd.Series, index: pd.DatetimeIndex) -> float:
    rf = rf_daily.reindex(index).fillna(0.0)
    if len(rf) < 2:
        return 0.0
    years = (index[-1] - index[0]).days / 365.25
    total = float(np.prod(1.0 + rf.to_numpy(dtype=float)))
    return total ** (1.0 / years) - 1.0 if years > 0 else float("nan")


def sharpe_geometric(value: pd.Series, returns: pd.Series, rf_daily: pd.Series | None = None) -> float:
    """(CAGR - compounded cash CAGR) / annualised vol: the v1 'card formula'."""
    v = ann_vol(returns)
    if not np.isfinite(v) or v == 0:
        return float("nan")
    rf_cagr = compounded_cash_cagr(rf_daily, value.index) if rf_daily is not None else 0.0
    return float((cagr(value) - rf_cagr) / v)


def oos_summary_v1(result, splits, rf_daily=None) -> pd.DataFrame:
    rows = []
    for lo, hi in splits:
        v, r = result.value.loc[lo:hi], result.returns.loc[lo:hi]
        if len(v) < 60:
            continue
        rf = rf_daily.loc[lo:hi] if rf_daily is not None else None
        rows.append({"window": f"{lo.date()}..{hi.date()}", "n": len(v), "cagr": cagr(v), "vol": ann_vol(r),
                     "sharpe": sharpe_geometric(v, r, rf), "max_dd": max_drawdown(v)})
    return pd.DataFrame(rows)


def stationary_bootstrap_index(n: int, mean_block: int, rng) -> np.ndarray:
    """Index series for one replication, as v1 drew it. Block lengths are Geometric(1/mean_block)."""
    p = 1.0 / mean_block
    idx = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        start = rng.integers(0, n)
        L = rng.geometric(p)
        L = min(L, n - i)
        idx[i:i + L] = (start + np.arange(L)) % n
        i += L
    return idx


def paired_geometric_p(strategy: np.ndarray, bench: np.ndarray, rf_daily: float, idx: np.ndarray, per_year: float) -> float:
    """v1 test 3 on an index matrix: share of draws where the geometric Sharpe gap is at or below zero."""
    n = strategy.shape[0]
    rf_cagr = (1.0 + rf_daily) ** per_year - 1.0

    def draws(x: np.ndarray) -> np.ndarray:
        s = x[idx]
        g = np.exp(np.log1p(s).sum(axis=1) * per_year / n) - 1.0
        return (g - rf_cagr) / (s.std(axis=1, ddof=1) * np.sqrt(per_year))

    return float((draws(strategy) - draws(bench) <= 0).mean())


__all__: list[Any] = ["ANN", "compounded_cash_cagr", "oos_summary_v1", "paired_geometric_p", "sharpe_geometric", "stationary_bootstrap_index"]
