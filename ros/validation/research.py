"""Step 06 -- RESEARCH VALIDATION.

Answers one question: is this result real, or is it a number we manufactured?

Contents:
  replication_gap    -- our run vs the numbers printed in the paper
  subperiod_table    -- does it work in every regime, or one lucky decade?
  walk_forward       -- out-of-sample by construction
  stationary_bootstrap -- Politis-Romano CIs and PAIRED Sharpe differences
  deflated_sharpe    -- Bailey & Lopez de Prado, penalised by trials tried
  cost_sensitivity   -- at what cost does the edge die?
  lag_sensitivity    -- does the edge survive realistic implementation delay?
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from ros.validation.metrics import (
    ANN, cagr, ann_vol, max_drawdown, sharpe_geometric, sharpe_conventional)


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------
@dataclass
class GapRow:
    portfolio: str
    metric: str
    paper_value: float
    our_value: float
    abs_diff: float
    rel_diff: float
    tolerance: float
    passed: bool


def replication_gap(card, metrics_df: pd.DataFrame,
                    name_map: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """Compare our metrics against the card's replication targets.

    A replication is REPLICATED only if every mandatory target passes. Partial
    passes are reported, never averaged away into a 'mostly replicated' verdict.
    """
    name_map = name_map or {}
    rows: List[GapRow] = []
    for t in card.replication_targets:
        ours_name = name_map.get(t.portfolio, t.portfolio)
        if ours_name not in metrics_df.index or t.metric not in metrics_df.columns:
            rows.append(GapRow(t.portfolio, t.metric, t.value, float("nan"),
                               float("nan"), float("nan"), t.tolerance, False))
            continue
        ours = float(metrics_df.loc[ours_name, t.metric])
        ad = abs(ours - t.value)
        rd = ad / abs(t.value) if t.value else float("inf")
        tol = t.absolute_tolerance
        passed = (ad <= tol) if tol is not None else (rd <= t.tolerance)
        rows.append(GapRow(t.portfolio, t.metric, t.value, ours, ad, rd,
                           tol if tol is not None else t.tolerance, passed))
    return pd.DataFrame([asdict(r) for r in rows])


# ---------------------------------------------------------------------------
# Sub-periods and walk-forward
# ---------------------------------------------------------------------------
def subperiod_table(results, rf_daily: Optional[pd.Series] = None,
                    n_periods: int = 4, metric: str = "sharpe") -> pd.DataFrame:
    """Split the sample into equal calendar blocks and report `metric` in each.

    A strategy whose edge lives in one block is a regime bet, not an alpha.
    """
    idx = results[0].value.index
    edges = pd.date_range(idx[0], idx[-1], periods=n_periods + 1)
    out: Dict[str, Dict[str, float]] = {}
    for res in results:
        row: Dict[str, float] = {}
        for i in range(n_periods):
            lo, hi = edges[i], edges[i + 1]
            v = res.value.loc[lo:hi]
            r = res.returns.loc[lo:hi]
            if len(v) < 60:
                row[f"{lo.year}-{hi.year}"] = float("nan")
                continue
            rf = rf_daily.loc[lo:hi] if rf_daily is not None else None
            row[f"{lo.year}-{hi.year}"] = {
                "sharpe": lambda: sharpe_geometric(v, r, rf),
                "cagr": lambda: cagr(v),
                "vol": lambda: ann_vol(r),
                "max_dd": lambda: max_drawdown(v),
            }[metric]()
        v_all, r_all = res.value, res.returns
        row["full"] = {
            "sharpe": lambda: sharpe_geometric(v_all, r_all, rf_daily),
            "cagr": lambda: cagr(v_all),
            "vol": lambda: ann_vol(r_all),
            "max_dd": lambda: max_drawdown(v_all),
        }[metric]()
        out[res.name] = row
    return pd.DataFrame(out).T


def walk_forward_split(index: pd.DatetimeIndex, n_folds: int = 4,
                       min_train_years: float = 5.0) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Anchored (expanding-window) walk-forward test windows.

    Anchored rather than rolling because a strategy whose parameters are refit on
    a short rolling window is a different strategy from the one the paper
    describes; we want OOS evidence for THIS strategy.
    """
    start = index[0]
    first_test = start + pd.DateOffset(years=min_train_years)
    if first_test >= index[-1]:
        return []
    edges = pd.date_range(first_test, index[-1], periods=n_folds + 1)
    return [(edges[i], edges[i + 1]) for i in range(n_folds)]


def oos_summary(result, splits, rf_daily=None) -> pd.DataFrame:
    rows = []
    for lo, hi in splits:
        v, r = result.value.loc[lo:hi], result.returns.loc[lo:hi]
        if len(v) < 60:
            continue
        rf = rf_daily.loc[lo:hi] if rf_daily is not None else None
        rows.append({"window": f"{lo.date()}..{hi.date()}", "n": len(v),
                     "cagr": cagr(v), "vol": ann_vol(r),
                     "sharpe": sharpe_geometric(v, r, rf), "max_dd": max_drawdown(v)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Stationary block bootstrap (Politis & Romano 1994)
# ---------------------------------------------------------------------------
def _stationary_bootstrap_index(n: int, mean_block: int, rng) -> np.ndarray:
    """Index series for one replication. Block lengths are Geometric(1/mean_block),
    so the resample is stationary and short-memory dependence is preserved."""
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


def stationary_bootstrap(
    returns_map: Dict[str, pd.Series],
    rf_daily: Optional[pd.Series] = None,
    n_boot: int = 2000,
    mean_block: int = 21,
    seed: int = 7,
    baseline: Optional[str] = None,
) -> Dict[str, Any]:
    """Bootstrap CIs for CAGR / Sharpe / maxDD, plus PAIRED Sharpe differences.

    All series are resampled with the SAME index draw in each replication, so the
    contemporaneous correlation between strategies is preserved and the Sharpe
    differences are genuinely paired. Comparing two independently-bootstrapped
    CIs instead would badly understate significance for correlated strategies --
    which factor sleeves in one market always are.
    """
    names = list(returns_map)
    aligned = pd.DataFrame(returns_map).dropna()
    n = len(aligned)
    if n < 250:
        return {"error": f"too few observations to bootstrap ({n})"}
    rf = (rf_daily.reindex(aligned.index).fillna(0.0).to_numpy(dtype=float)
          if rf_daily is not None else np.zeros(n))
    arr = aligned.to_numpy(dtype=float)
    years = (aligned.index[-1] - aligned.index[0]).days / 365.25
    per_year = n / years

    rng = np.random.default_rng(seed)
    stats_out = {nm: {"cagr": [], "sharpe": [], "max_dd": []} for nm in names}
    sharpe_draws = {nm: [] for nm in names}

    for _ in range(n_boot):
        bi = _stationary_bootstrap_index(n, mean_block, rng)
        rf_b = rf[bi]
        rf_total = float(np.prod(1.0 + rf_b))
        rf_cagr = rf_total ** (per_year / n) - 1.0
        for k, nm in enumerate(names):
            r = arr[bi, k]
            nav = np.cumprod(1.0 + r)
            g = float(nav[-1]) ** (per_year / n) - 1.0
            vol = float(np.std(r, ddof=1) * np.sqrt(per_year))
            sh = (g - rf_cagr) / vol if vol > 0 else np.nan
            dd = float(-(nav / np.maximum.accumulate(nav) - 1.0).min())
            stats_out[nm]["cagr"].append(g)
            stats_out[nm]["sharpe"].append(sh)
            stats_out[nm]["max_dd"].append(dd)
            sharpe_draws[nm].append(sh)

    def ci(v):
        a = np.asarray(v, dtype=float)
        a = a[np.isfinite(a)]
        return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]

    out: Dict[str, Any] = {
        "n_boot": n_boot, "mean_block": mean_block, "n_obs": n,
        "intervals": {nm: {m: ci(v) for m, v in d.items()} for nm, d in stats_out.items()},
    }

    if baseline and baseline in names:
        base = np.asarray(sharpe_draws[baseline], dtype=float)
        diffs = {}
        for nm in names:
            if nm == baseline:
                continue
            d = base - np.asarray(sharpe_draws[nm], dtype=float)
            d = d[np.isfinite(d)]
            diffs[nm] = {
                "mean_diff": float(d.mean()),
                "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
                "p_not_positive": float((d <= 0).mean()),
            }
        out["paired_sharpe_diff_vs_" + baseline] = diffs
    return out


# ---------------------------------------------------------------------------
# Deflated Sharpe ratio (Bailey & Lopez de Prado 2014)
# ---------------------------------------------------------------------------
def expected_max_sharpe(n_trials: int, var_sharpe: float = 1.0) -> float:
    """Expected maximum Sharpe from `n_trials` independent null strategies.

    This is the bar a strategy must clear just to be distinguishable from the
    best of a pile of coin flips. It grows like sqrt(2 ln N), which is why
    'we tried a few hundred variants' destroys a Sharpe of 0.8.
    """
    if n_trials < 2:
        return 0.0
    gamma = 0.5772156649015329
    e = np.e
    z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * e))
    return float(np.sqrt(var_sharpe) * ((1 - gamma) * z1 + gamma * z2))


def deflated_sharpe(returns: pd.Series, n_trials: int,
                    rf_daily: Optional[pd.Series] = None,
                    ann: int = ANN, benchmark_sharpe: Optional[float] = None) -> Dict[str, Any]:
    """Probability the observed Sharpe exceeds the selection-adjusted threshold,
    correcting for non-normality (skew and kurtosis) as well as trial count."""
    r = returns.dropna()
    if rf_daily is not None:
        r = r - rf_daily.reindex(r.index).fillna(0.0)
    n = len(r)
    if n < 100:
        return {"error": f"too few observations ({n})"}

    sr_per = float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else float("nan")
    sr_ann = sr_per * np.sqrt(ann)
    skew = float(stats.skew(r, bias=False))
    kurt = float(stats.kurtosis(r, fisher=False, bias=False))

    sr0 = benchmark_sharpe if benchmark_sharpe is not None else expected_max_sharpe(n_trials)
    sr0_per = sr0 / np.sqrt(ann)

    denom = np.sqrt(max(1e-12, 1 - skew * sr_per + (kurt - 1) / 4.0 * sr_per ** 2))
    z = (sr_per - sr0_per) * np.sqrt(n - 1) / denom
    psr = float(stats.norm.cdf(z))

    return {
        "sharpe_ann": sr_ann,
        "n_trials": n_trials,
        "skew": skew, "kurtosis": kurt, "n_obs": n,
        "selection_threshold_sharpe": float(sr0),
        "deflated_sharpe_prob": psr,
        "passes_at_95": bool(psr >= 0.95),
        "interpretation": (
            f"After penalising {n_trials} configuration(s) tried, the threshold Sharpe is "
            f"{sr0:.2f}; observed {sr_ann:.2f}; P(skill) = {psr:.1%}."),
    }


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------
def cost_sensitivity(run_fn: Callable[[float], Any], spreads_bps: Sequence[float],
                     rf_daily: Optional[pd.Series] = None) -> pd.DataFrame:
    """Re-run the strategy at several cost assumptions.

    `run_fn(spread_bps) -> BacktestResult`. The breakeven cost -- where the edge
    over the benchmark disappears -- is a far more useful number than performance
    at one assumed spread, because it maps directly onto capacity.
    """
    rows = []
    for s in spreads_bps:
        res = run_fn(float(s))
        rows.append({"spread_bps": s, "cagr": cagr(res.value), "vol": ann_vol(res.returns),
                     "sharpe": sharpe_geometric(res.value, res.returns, rf_daily),
                     "max_dd": max_drawdown(res.value),
                     "turnover": float(res.turnover.mean() * ANN)})
    return pd.DataFrame(rows)


def lag_sensitivity(run_fn: Callable[[int], Any], lags: Sequence[int],
                    rf_daily: Optional[pd.Series] = None) -> pd.DataFrame:
    """Re-run under increasing implementation lag.

    A real signal decays gently. A signal whose Sharpe collapses when you trade
    one day later is reading the bar it trades, whatever the shift code says.
    """
    rows = []
    for L in lags:
        res = run_fn(int(L))
        rows.append({"lag_days": L, "cagr": cagr(res.value), "vol": ann_vol(res.returns),
                     "sharpe": sharpe_geometric(res.value, res.returns, rf_daily),
                     "max_dd": max_drawdown(res.value)})
    return pd.DataFrame(rows)
