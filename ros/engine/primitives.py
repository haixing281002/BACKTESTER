"""Signal primitives -- the small, audited vocabulary a Strategy Card may use.

Every primitive is causal by construction: a value dated t uses only data up to
and including t. The backtester additionally applies the card's `lag_days` on top,
so a signal computed on a close can be forced to trade on a later close.

Registering a primitive is the ONLY place new paper logic may enter the system,
and each one is a few lines that a reviewer can read in full.
"""
from __future__ import annotations

from typing import Callable, Dict

import numpy as np
import pandas as pd

_REGISTRY: Dict[str, Callable] = {}


def primitive(name: str):
    def deco(fn):
        if name in _REGISTRY:
            raise ValueError(f"primitive '{name}' already registered")
        _REGISTRY[name] = fn
        fn.primitive_name = name
        return fn
    return deco


def get_primitive(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"unknown primitive '{name}'. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def list_primitives():
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
@primitive("simple_returns")
def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Close-to-close simple returns."""
    return prices.pct_change()


@primitive("trailing_vol")
def trailing_vol(returns: pd.DataFrame, window: int, ann: int = 252) -> pd.DataFrame:
    """Annualised trailing standard deviation over `window` observations.

    Uses the sample (ddof=1) estimator and requires a full window, so early dates
    are NaN rather than silently computed off two points.
    """
    return returns.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(ann)


@primitive("portfolio_trailing_vol")
def portfolio_trailing_vol(returns: pd.DataFrame, weights, window: int,
                           ann: int = 252) -> pd.Series:
    """Annualised trailing vol of a FIXED-weight combination of assets.

    This is the paper's sigma_t for a volatility-controlled benchmark: the vol of
    the benchmark portfolio's own return series, not a weighted average of asset vols.
    """
    w = np.asarray(weights, dtype=float)
    port = returns.to_numpy(dtype=float) @ w
    s = pd.Series(port, index=returns.index)
    return s.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(ann)


@primitive("ewma_return")
def ewma_return(returns: pd.DataFrame, halflife: int, scale: int = 1) -> pd.DataFrame:
    """Exponentially weighted mean of past returns, scaled to a horizon.

    `scale` puts a daily mean onto an h-day scale (the paper uses 21 for one month).
    """
    return returns.ewm(halflife=halflife, min_periods=halflife).mean() * scale


@primitive("rolling_cov")
def rolling_cov(returns: pd.DataFrame, window: int, ann: int = 252):
    """Annualised rolling covariance matrices, as {timestamp: ndarray}.

    Returned as a dict rather than a panel because the optimiser consumes one
    matrix per rebalance date and the full panel is large and mostly unused.
    """
    out = {}
    cols = list(returns.columns)
    arr = returns.to_numpy(dtype=float)
    idx = returns.index
    for i in range(window, len(idx) + 1):
        block = arr[i - window:i]
        if np.isnan(block).any():
            continue
        out[idx[i - 1]] = np.cov(block, rowvar=False, ddof=1) * ann
    return out, cols


@primitive("total_return_momentum")
def total_return_momentum(prices: pd.DataFrame, window: int, skip: int = 0) -> pd.DataFrame:
    """Trailing total return over `window` days, optionally skipping the most
    recent `skip` days (the standard 12-1 momentum construction)."""
    shifted = prices.shift(skip)
    return shifted / shifted.shift(window) - 1.0


@primitive("vol_scaled_momentum")
def vol_scaled_momentum(prices: pd.DataFrame, window: int, vol_window: int,
                        ann: int = 252) -> pd.DataFrame:
    """Trailing return divided by trailing volatility -- the paper's feature
    'the 252-day trailing return divided by its trailing volatility'."""
    rets = prices.pct_change()
    mom = prices / prices.shift(window) - 1.0
    vol = rets.rolling(vol_window, min_periods=vol_window).std(ddof=1) * np.sqrt(ann)
    return mom / vol.replace(0.0, np.nan)


@primitive("zscore")
def zscore(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Rolling cross-sectional-free time-series z-score."""
    mu = df.rolling(window, min_periods=window).mean()
    sd = df.rolling(window, min_periods=window).std(ddof=1)
    return (df - mu) / sd.replace(0.0, np.nan)


@primitive("cross_sectional_rank")
def cross_sectional_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Rank across columns on each date, scaled to [0, 1]. For cross-sectional papers."""
    return df.rank(axis=1, pct=True)


@primitive("vol_ratio")
def vol_ratio(returns: pd.DataFrame, short: int, long: int, ann: int = 252) -> pd.DataFrame:
    """log(short-window vol) - log(long-window vol): the paper's volatility feature."""
    sv = returns.rolling(short, min_periods=short).std(ddof=1) * np.sqrt(ann)
    lv = returns.rolling(long, min_periods=long).std(ddof=1) * np.sqrt(ann)
    return np.log(sv.replace(0.0, np.nan)) - np.log(lv.replace(0.0, np.nan))
