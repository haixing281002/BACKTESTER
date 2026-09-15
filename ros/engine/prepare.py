"""Turn a Strategy Card plus a snapshot into the causal inputs an allocator needs.

Generic by design: it inspects the allocator's `requires` tuple and builds only
what that template asks for. A new template that needs a new input adds one branch
here; no card and no other template changes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ros.engine.primitives import (
    ewma_return, portfolio_trailing_vol, rolling_cov, simple_returns,
    total_return_momentum)


def strategic_vector(spec, assets: List[str]) -> np.ndarray:
    """Resolve a strategic-weight spec to a vector. Accepts 'equal', a dict, or a list."""
    if spec == "equal" or spec is None:
        return np.ones(len(assets)) / len(assets)
    if isinstance(spec, dict):
        return np.array([float(spec[a]) for a in assets])
    v = np.asarray(spec, dtype=float)
    if v.shape != (len(assets),):
        raise ValueError(f"strategic weights shape {v.shape} != {(len(assets),)}")
    return v


def build_signal_inputs(
    prices: pd.DataFrame,
    assets: List[str],
    lookback: int,
    strategic_weights,
    alpha_halflife: Optional[int] = None,
    alpha_scale: int = 21,
    alpha_source: str = "ewma",
    alpha_window: Optional[int] = None,
    alpha_skip: int = 0,
    ann: int = 252,
) -> Dict[str, Any]:
    """Compute sigma_bench, covariance matrices and the EWMA momentum alpha.

    Everything here is causal: each value dated t uses returns up to and including
    t. The backtester then shifts by (1 + lag_days) before any of it is traded on.
    """
    px = prices[assets]
    rets = simple_returns(px)
    w_tgt = strategic_vector(strategic_weights, assets)

    sigma_bench = portfolio_trailing_vol(rets, w_tgt, window=lookback, ann=ann)
    cov, cov_cols = rolling_cov(rets, window=lookback, ann=ann)

    # Expected-return estimate. Adding a new paper's forecast means adding one
    # branch here plus one primitive -- never a change to the engine or a template.
    alpha = None
    if alpha_source == "ewma" and alpha_halflife:
        # EWMA of past daily returns on the rebalance-horizon scale. This is the
        # paper's "simple Markowitz" forecast: trailing-return momentum only.
        alpha = ewma_return(rets, halflife=alpha_halflife, scale=alpha_scale)
    elif alpha_source == "momentum" and alpha_window:
        # Trailing total return over a window, optionally skipping the most recent
        # days (the classic 12-1 construction). Used by time-series momentum cards.
        alpha = total_return_momentum(px, window=alpha_window, skip=alpha_skip)
    elif alpha_source not in ("ewma", "momentum", "none"):
        raise ValueError(f"unknown alpha_source '{alpha_source}'")

    return {"returns": rets, "sigma_bench": sigma_bench, "cov": cov,
            "cov_cols": cov_cols, "alpha": alpha, "w_tgt": w_tgt}
