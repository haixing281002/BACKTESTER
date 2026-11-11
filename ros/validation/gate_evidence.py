# Quant AI Researcher by Harshil Pahuja
"""The numbers gate v2 reads. All of it is arithmetic on return series; the calibration runs this same code."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ros.data.loaders import load_nse_workbook_combined
from ros.data.sources import NSE_INDEX_WORKBOOK
from ros.metrics import core
from ros.validation.portfolio import factor_fingerprint, incremental_ir

# Investable factors with size included. Where the workbook has the series. Backfilled before launch, and price-only.
INVESTABLE_FACTORS = {"market": "NIFTY 500", "midcap150": "NIFTY MIDCAP 150", "smallcap250": "NIFTY SMALLCAP 250", "momentum": "NIFTY500 MOMENTUM 50",
                      "value": "NIFTY500 VALUE 50", "quality": "NIFTY500 QUALITY 50", "low_vol": "NIFTY500 LOW VOLATILITY 50"}


def factor_returns(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Factor index returns on these dates, from the index workbook."""
    levels, _ = load_nse_workbook_combined(NSE_INDEX_WORKBOOK)
    have = {k: v for k, v in INVESTABLE_FACTORS.items() if v in levels.columns}
    return levels[list(have.values())].rename(columns={v: k for k, v in have.items()}).reindex(levels.index.union(index)).ffill().pct_change(fill_method=None).reindex(index)


def version_inputs(versions: pd.DataFrame | None, bench: pd.Series, cash: float, n_selected_from: int, v_floor: float) -> dict[str, float]:
    """Effective N and V for the deflated Sharpe, from the return series of the versions actually chosen between.

    Correlation is taken on returns minus the benchmark. Long-only versions all share the market, and on raw returns that
    shared market would make unrelated ideas look like one idea and shrink the penalty.
    """
    if n_selected_from <= 1 or versions is None or versions.shape[1] < 2:
        return {"n": max(1, n_selected_from), "mean_corr": float("nan"), "n_eff": float(max(1, n_selected_from)), "v_observed": float("nan"), "v": v_floor}
    active = versions.sub(bench.reindex(versions.index), axis=0)
    c = active.corr().to_numpy()
    rho = float(c[np.triu_indices_from(c, k=1)].mean())
    v_obs = float(np.var([core.sharpe(versions[k], cash) for k in versions.columns], ddof=1))
    return {"n": n_selected_from, "mean_corr": rho, "n_eff": core.effective_trials(n_selected_from, rho), "v_observed": v_obs, "v": max(v_obs, v_floor)}


def deflated_sharpe(r: pd.Series, bench: pd.Series, cash: float, n_eff: float, v: float, null: str = "benchmark") -> dict[str, float]:
    """P(true Sharpe > luck bar). `null` is what a no-skill version earns before any luck: "zero", as the original paper
    assumes, or "benchmark", because a no-skill long-only strategy still earns the market's Sharpe."""
    x = core.excess(r, cash)
    base = core.sharpe(bench, cash) if null == "benchmark" else 0.0
    bar = base + core.expected_max_sharpe(n_eff, v)
    sr = float(x.mean() / x.std(ddof=1))
    return {"sharpe": sr * np.sqrt(core.ANN), "bar": float(bar), "n_obs": len(x), "dsr": core.probabilistic_sharpe(sr, bar / np.sqrt(core.ANN), len(x), core.skew(x), core.kurtosis(x))}


def windows(index: pd.DatetimeIndex, n_windows: int = 4, skip_years: float = 0.0) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    first = index[0] + pd.DateOffset(years=skip_years) if skip_years else index[0]
    if first >= index[-1]:
        return []
    edges = pd.date_range(first, index[-1], periods=n_windows + 1)
    return [(edges[i], edges[i + 1]) for i in range(n_windows)]


def sub_period(r: pd.Series, bench: pd.Series, cash: float, fits_parameters: bool = False, n_windows: int = 4, min_train_years: float = 5.0) -> dict[str, Any]:
    """Sharpe gap to the benchmark per window. With no fitted parameters this is sub-period stability over the whole run;
    a window of a fixed rule tests nothing out of sample, so it is not called that. With fitted parameters, the first
    `min_train_years` are skipped and it is a walk-forward."""
    rows = []
    for lo, hi in windows(r.index, n_windows, min_train_years if fits_parameters else 0.0):
        x, y = r.loc[lo:hi], bench.loc[lo:hi]
        if len(x) < 60:
            continue
        sx, sy = core.sharpe(x, cash), core.sharpe(y, cash)
        rows.append({"window": f"{lo.date()}..{hi.date()}", "sharpe": sx, "benchmark_sharpe": sy, "gap": sx - sy})
    gaps = [w["gap"] for w in rows]
    return {"name": "Walk-forward" if fits_parameters else "Sub-period stability", "windows": rows, "n": len(rows),
            "positive": int(sum(g > 0 for g in gaps)), "worst": float(min(gaps)) if gaps else float("nan")}


def paired_bootstrap(r: pd.Series, bench: pd.Series, cash: float, n_boot: int = 2000, mean_block: int = 21, seed: int = 7) -> dict[str, float]:
    """Share of draws where strategy Sharpe minus benchmark Sharpe is at or below zero, plus the paired max-drawdown gap
    as evidence only."""
    df = pd.concat([r, bench], axis=1).dropna()
    x, y = df.iloc[:, 0].to_numpy(dtype=float), df.iloc[:, 1].to_numpy(dtype=float)
    idx = core.stationary_bootstrap_indices(len(x), n_boot, mean_block, np.random.default_rng(seed))
    d = core.sharpe_draws(x, idx, cash) - core.sharpe_draws(y, idx, cash)
    d = d[np.isfinite(d)]
    g = core.max_drawdown_draws(y, idx) - core.max_drawdown_draws(x, idx)
    return {"p": float((d <= 0).mean()), "mean_gap": float(d.mean()), "max_dd_gap_mean": float(g.mean())}


def factor_alpha(r: pd.Series, factors: pd.DataFrame, cash: float, product_cost_bp: dict[str, float] | None = None, leave_one_out: bool = True) -> dict[str, Any]:
    """Alpha against investable factors, with each factor left out in turn. With product costs, also alpha against what
    the fund would really earn from the matching products: their index return less their yearly cost."""
    rf = pd.Series(cash, index=r.index)
    # A strategy that IS one of the factors fits it exactly, and alpha's t on that fit is rounding noise. Leave it out and say so.
    same = [k for k in factors.columns if float(r.corr(factors[k])) > 0.9999]
    factors = factors.drop(columns=same)
    fit = factor_fingerprint(r, factors, rf)
    if "error" in fit:
        return fit
    out = {k: fit[k] for k in ("alpha_ann", "alpha_t_hac", "loadings", "t_stats_hac", "r_squared", "hac_lags", "n_obs")}
    out["left_out_as_identical"] = same
    if leave_one_out and factors.shape[1] > 1:
        loo = {}
        for k in factors.columns:
            f = factor_fingerprint(r, factors.drop(columns=[k]), rf)
            loo[k] = {"alpha_ann": f.get("alpha_ann"), "alpha_t_hac": f.get("alpha_t_hac")}
        out["leave_one_out"] = loo
    if product_cost_bp:
        drag = sum(fit["loadings"][k] * product_cost_bp[k] / 1e4 for k in fit["loadings"] if k in product_cost_bp)
        out["alpha_net_of_products"] = float(fit["alpha_ann"] + drag)
    return out


def book_tests(r: pd.Series, book: pd.Series | None, bench: pd.Series) -> dict[str, float | None]:
    """Correlation to the book and the best gain in its information ratio at a realistic sleeve size. No book, no numbers."""
    if book is None:
        return {"book_corr": None, "active_corr": None, "book_ir_gain": None}
    a, b, m = r.align(book, join="inner")[0], r.align(book, join="inner")[1], bench.reindex(r.index)
    t = incremental_ir(a, b, m)
    gains = t.loc[t["sleeve_weight"] > 0, "delta_ir"]
    active = pd.concat([a - m, b - m], axis=1).dropna()
    return {"book_corr": float(a.corr(b)), "active_corr": float(active.iloc[:, 0].corr(active.iloc[:, 1])), "book_ir_gain": float(gains.max()) if len(gains) else None}
