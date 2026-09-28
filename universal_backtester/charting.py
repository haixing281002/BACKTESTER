"""Backtest picture set -- one PNG per view, not one crowded panel.

WHY SEPARATE FILES: a single 4-in-1 panel is hard to read at a glance and
hard to print. Each view here is its own file, named so a directory listing
groups them by run (`<tag>_<view>.png`), and each is skipped (never a blank
or crashed chart) when the data it needs isn't available for this backtest --
e.g. a single-leg momentum run has no SMALL/BIG spread to plot, and a run
with no `weights` history skips the holdings-composition chart. Which
pictures get produced is decided by what data this run actually has, not by
a fixed list every script must supply.

No AI/API step anywhere in this module -- matplotlib only, deterministic,
same inputs produce the same PNG bytes.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from universal_backtester.metrics import drawdown_series


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def save_backtest_charts(
    results: Dict[str, "pd.Series"],
    outdir: str,
    tag: str,
    benchmark: Optional[pd.Series] = None,
    benchmark_name: str = "Benchmark",
    weights: Optional[pd.DataFrame] = None,
    weights_name: str = "",
    cash_weight: Optional[pd.Series] = None,
) -> List[str]:
    """`results`: {display name -> cumulative value series (base 1.0 or 100)}.
    Every chart is a separate PNG under `outdir`, named `<tag>__<view>.png`.
    Returns the list of file paths actually written -- a chart whose inputs
    aren't available (e.g. no `weights` passed) is skipped, not faked.

    This never raises on a missing matplotlib install -- it prints a note
    and returns an empty list, the same "no silent fake output" discipline
    as the rest of this repo's data loaders.
    """
    try:
        plt = _mpl()
    except ImportError:
        print("  [charts skipped: matplotlib not installed]")
        return []

    os.makedirs(outdir, exist_ok=True)
    written: List[str] = []
    series = {name: s.dropna() for name, s in results.items() if s is not None and len(s.dropna()) > 1}
    if benchmark is not None and len(benchmark.dropna()) > 1:
        series = {**series, benchmark_name: benchmark.dropna()}

    def _save(fig, view: str) -> None:
        path = os.path.join(outdir, f"{tag}__{view}.png")
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        written.append(path)

    # 1. Cumulative return, linear scale -- the plain "what would I have made" view.
    if series:
        fig, ax = plt.subplots(figsize=(11, 6))
        for name, s in series.items():
            ax.plot(s.index, s.values / s.iloc[0], lw=1.4, label=name[:44])
        ax.set_title(f"{tag}: cumulative return (base 1.0)")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(alpha=.3)
        _save(fig, "cumulative_return")

        # 2. Same series, log scale -- makes the EARLY-period gap/crossover
        # visible when the later-period compounding would otherwise dwarf it.
        fig, ax = plt.subplots(figsize=(11, 6))
        for name, s in series.items():
            ax.plot(s.index, s.values / s.iloc[0], lw=1.4, label=name[:44])
        ax.set_yscale("log")
        ax.set_title(f"{tag}: cumulative return (log scale)")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(alpha=.3, which="both")
        _save(fig, "cumulative_return_log")

        # 3. Drawdown -- the "how bad did it get" view, same series.
        fig, ax = plt.subplots(figsize=(11, 5))
        for name, s in series.items():
            dd = drawdown_series(s) * 100
            ax.plot(dd.index, dd.values, lw=1.2, label=name[:44])
        ax.set_title(f"{tag}: drawdown (%)")
        ax.legend(fontsize=8, loc="lower left")
        ax.grid(alpha=.3)
        _save(fig, "drawdown")

        # 4. Rolling 1-year annualised volatility -- realised risk over time,
        # not just the single full-period number in the tearsheet.
        fig, ax = plt.subplots(figsize=(11, 5))
        any_plotted = False
        for name, s in series.items():
            r = s.pct_change(fill_method=None).dropna()
            if len(r) < 260:
                continue
            roll_vol = r.rolling(252).std() * np.sqrt(252) * 100
            ax.plot(roll_vol.index, roll_vol.values, lw=1.2, label=name[:44])
            any_plotted = True
        if any_plotted:
            ax.set_title(f"{tag}: rolling 1-year annualised volatility (%)")
            ax.legend(fontsize=8, loc="upper left")
            ax.grid(alpha=.3)
            _save(fig, "rolling_volatility")
        else:
            plt.close(fig)

        # 5. Calendar-year returns, bar chart -- the year-by-year cumulative
        # run the user asked to be able to see, one bar per series per year.
        cy = {}
        for name, s in series.items():
            r = s.pct_change(fill_method=None).dropna()
            if r.empty:
                continue
            yearly = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1) * 100
            cy[name] = yearly
        if cy:
            all_years = sorted(set().union(*[set(v.index) for v in cy.values()]))
            fig, ax = plt.subplots(figsize=(max(11, 0.5 * len(all_years)), 5.5))
            n = len(cy)
            width = 0.8 / max(n, 1)
            x = np.arange(len(all_years))
            for i, (name, yearly) in enumerate(cy.items()):
                vals = [yearly.get(y, np.nan) for y in all_years]
                ax.bar(x + i * width, vals, width=width, label=name[:44])
            ax.set_xticks(x + width * (n - 1) / 2)
            ax.set_xticklabels(all_years, rotation=45)
            ax.axhline(0, color="black", lw=0.8)
            ax.set_title(f"{tag}: calendar-year return (%)")
            ax.legend(fontsize=8)
            ax.grid(alpha=.3, axis="y")
            _save(fig, "calendar_year_returns")

    # 6. Holdings composition over time -- only if weights were actually
    # supplied; a strategy this script didn't track weights for skips this.
    if weights is not None and not weights.empty:
        w = weights.copy()
        if cash_weight is not None:
            w = w.copy()
            w["CASH"] = cash_weight.reindex(w.index).fillna(0.0)
        # Collapse to the names that were ever material, to keep the legend readable.
        material = w.columns[(w.abs().max(axis=0) > 0.01)]
        w = w[material] if len(material) else w
        if not w.empty:
            fig, ax = plt.subplots(figsize=(11, 6))
            ax.stackplot(w.index, *[w[c].values for c in w.columns],
                        labels=[str(c)[:24] for c in w.columns])
            ax.set_title(f"{tag}: holdings composition{' -- ' + weights_name if weights_name else ''}")
            ax.set_ylim(0, max(1.0, float(w.sum(axis=1).max())))
            ax.legend(fontsize=6, loc="lower left", ncol=2)
            _save(fig, "holdings_composition")

    if written:
        print(f"  charts written ({len(written)}):")
        for p in written:
            print(f"    {p}")
    return written


def save_decile_charts(
    decile_values: Dict[int, pd.Series],
    decile_summary: pd.DataFrame,
    outdir: str,
    tag: str,
    benchmark: Optional[pd.Series] = None,
    benchmark_name: str = "Benchmark",
    benchmark_cagr: Optional[float] = None,
    benchmark_sharpe: Optional[float] = None,
) -> List[str]:
    """The NIFTY 500 decile deep-dive picture set -- not just SMALL vs BIG,
    all ten deciles at once, so a monotonic size effect (or the lack of one)
    is visible directly rather than inferred from two numbers.

    `decile_values`: {1..10 -> cumulative value series}. `decile_summary`:
    the DataFrame from decile_analysis.summarize_deciles() (columns decile,
    cagr, vol, sharpe, max_dd). Same "skip, never fake" discipline as
    save_backtest_charts -- an empty input skips the picture, not a blank one.
    """
    try:
        plt = _mpl()
    except ImportError:
        print("  [decile charts skipped: matplotlib not installed]")
        return []
    if not decile_values:
        return []

    os.makedirs(outdir, exist_ok=True)
    written: List[str] = []
    cmap = plt.get_cmap("RdYlBu")
    n = len(decile_values)
    colors = {k: cmap(i / max(n - 1, 1)) for i, k in enumerate(sorted(decile_values))}

    def _save(fig, view: str) -> None:
        path = os.path.join(outdir, f"{tag}__{view}.png")
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        written.append(path)

    # 1. Cumulative return, all 10 deciles at once (decile 1 = smallest =
    # blue-to-red gradient toward decile 10 = largest), plus the benchmark
    # in black so it reads as the reference line, not just another series.
    fig, ax = plt.subplots(figsize=(11, 6.5))
    for k, s in sorted(decile_values.items()):
        s = s.dropna()
        if len(s) < 2:
            continue
        ax.plot(s.index, s.values / s.iloc[0], lw=1.1, color=colors[k],
                label=f"Decile {k}" + (" (smallest)" if k == min(decile_values) else
                                       " (largest)" if k == max(decile_values) else ""))
    if benchmark is not None and len(benchmark.dropna()) > 1:
        b = benchmark.dropna()
        ax.plot(b.index, b.values / b.iloc[0], lw=2.0, color="black", label=benchmark_name)
    ax.set_title(f"{tag}: cumulative return by NIFTY 500 decile (base 1.0)")
    ax.legend(fontsize=7, loc="upper left", ncol=2)
    ax.grid(alpha=.3)
    _save(fig, "decile_cumulative_return")

    # 2. CAGR by decile -- the bar chart that shows whether the size effect
    # is monotonic across the whole market-cap range or concentrated at one end.
    if not decile_summary.empty:
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ks = decile_summary["decile"].tolist()
        cagrs = (decile_summary["cagr"] * 100).tolist()
        bar_colors = [colors.get(k, "gray") for k in ks]
        ax.bar([str(k) for k in ks], cagrs, color=bar_colors)
        if benchmark_cagr is not None and not pd.isna(benchmark_cagr):
            ax.axhline(benchmark_cagr * 100, color="black", lw=1.5, ls="--",
                      label=f"{benchmark_name} ({benchmark_cagr:.1%})")
            ax.legend(fontsize=8)
        ax.set_xlabel("Decile (1 = smallest, 10 = largest)")
        ax.set_ylabel("CAGR (%)")
        ax.set_title(f"{tag}: CAGR by decile")
        ax.grid(alpha=.3, axis="y")
        _save(fig, "decile_cagr_bar")

        # 3. Sharpe by decile -- the same question, risk-adjusted.
        fig, ax = plt.subplots(figsize=(10, 5.5))
        sharpes = decile_summary["sharpe"].tolist()
        ax.bar([str(k) for k in ks], sharpes, color=bar_colors)
        if benchmark_sharpe is not None and not pd.isna(benchmark_sharpe):
            ax.axhline(benchmark_sharpe, color="black", lw=1.5, ls="--",
                      label=f"{benchmark_name} ({benchmark_sharpe:.2f})")
            ax.legend(fontsize=8)
        ax.set_xlabel("Decile (1 = smallest, 10 = largest)")
        ax.set_ylabel("Sharpe ratio")
        ax.set_title(f"{tag}: Sharpe ratio by decile")
        ax.grid(alpha=.3, axis="y")
        _save(fig, "decile_sharpe_bar")

    # 4. The size-premium spread: long the smallest decile, short the
    # largest (financed, not a real position -- a research diagnostic,
    # never itself a tradable leg per this fund's long-only mandate).
    small, big = min(decile_values), max(decile_values)
    s_small, s_big = decile_values[small].dropna(), decile_values[big].dropna()
    common = s_small.index.intersection(s_big.index)
    if len(common) > 2:
        r_small = s_small.loc[common].pct_change(fill_method=None).fillna(0.0)
        r_big = s_big.loc[common].pct_change(fill_method=None).fillna(0.0)
        spread = (1 + (r_small - r_big)).cumprod()
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(spread.index, spread.values, lw=1.3, color="purple")
        ax.axhline(1.0, color="black", lw=0.8, ls=":")
        ax.set_title(f"{tag}: size-premium spread (Decile {small} minus Decile {big}, "
                    "research diagnostic only -- not a tradable position)")
        ax.grid(alpha=.3)
        _save(fig, "decile_size_premium_spread")

    if written:
        print(f"  decile charts written ({len(written)}):")
        for p in written:
            print(f"    {p}")
    return written
