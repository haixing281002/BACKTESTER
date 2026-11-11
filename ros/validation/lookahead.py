# Quant AI Researcher
"""Two look-ahead checks every stock-level run carries (Wave 2, item 5), both able to FAIL.

truncation_check  a signal computed on prices up to date t only must equal the full-history signal at t.
scramble_check    perturb every price after a cut-off date and re-run: every result up to the cut-off must be
                  bit-identical. A run that reads tomorrow's price anywhere changes before the cut-off.

Each check is tested against a planted one-day leak (tests/test_lookahead_checks.py), so a check that cannot see a
leak is caught: a tripwire that never trips proves nothing.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def truncation_check(signal_fn: Callable[[pd.DataFrame], pd.DataFrame], prices: pd.DataFrame,
                     dates) -> dict:
    """signal_fn(prices) -> dates x securities. For each date, recompute on prices.loc[:date] and compare."""
    full = signal_fn(prices)
    same = 0
    for t in dates:
        part = signal_fn(prices.loc[:t])
        same += int(np.allclose(full.loc[t].to_numpy(dtype=float), part.loc[t].to_numpy(dtype=float), equal_nan=True))
    return {"passed": same == len(dates), "detail": f"{same}/{len(dates)} dates identical with every later price deleted"}


def scramble_after(prices: pd.DataFrame, cutoff, rng: np.random.Generator, scale: float = 0.3) -> pd.DataFrame:
    """A copy with every price strictly after `cutoff` multiplied by random noise (positive, up to +/- scale)."""
    out = prices.copy()
    late = out.index > pd.Timestamp(cutoff)
    noise = np.exp(rng.uniform(-scale, scale, size=(int(late.sum()), out.shape[1])))
    out.loc[late] = out.loc[late].to_numpy(dtype=float) * noise
    return out


def scramble_check(run_fn: Callable[[pd.DataFrame], pd.DataFrame | pd.Series], prices: pd.DataFrame, cutoff,
                   rng: np.random.Generator) -> dict:
    """run_fn(prices) -> what the run DECIDES each day (weights, holdings) and its NAV, indexed by date. Up to and
    including `cutoff` none of it may change. Compare decisions, not NAV alone: a one-day leak at the cut-off changes
    the decision taken that day, which earns its first return only after it."""
    base = run_fn(prices)
    pert = run_fn(scramble_after(prices, cutoff, rng))
    a = base.loc[:pd.Timestamp(cutoff)].to_numpy(dtype=float)
    b = pert.loc[:pd.Timestamp(cutoff)].to_numpy(dtype=float)
    ok = bool(np.array_equal(np.nan_to_num(a, nan=-9e99), np.nan_to_num(b, nan=-9e99)))
    moved = bool(not np.allclose(base.to_numpy(dtype=float), pert.to_numpy(dtype=float), equal_nan=True))
    return {"passed": ok, "detail": (f"up to {pd.Timestamp(cutoff).date()}: {'bit-identical' if ok else 'CHANGED'}; "
                                      f"after it the run {'moved' if moved else 'did not move (perturbation too weak?)'}")}
