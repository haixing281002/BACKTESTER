"""A small, readable chart set: ONE strategy against ONE benchmark.

charting.save_backtest_charts plots every series it is given on every chart, which turns
unreadable past two or three lines. This module is the opposite on purpose: each chart shows
the strategy and its benchmark (NIFTY 500) and nothing else. One extra "sleeve" may be passed
for a single separate cumulative-return chart when a comparator is genuinely important; it
never appears on the other charts.

Charts (each its own PNG, `<tag>__<view>.png`):
  cumulative_return   strategy vs benchmark, rebased to 100, end values labelled
  drawdown            strategy filled, benchmark as a line, worst drawdown of each labelled
  rolling_volatility  rolling 1-year annualised volatility, two lines
  calendar_year       grouped bars by calendar year, partial first/last years marked
  exposure            long and short gross as areas, net as a line (strategy only)
  with_sleeve         cumulative return with the one extra sleeve (only if one is given)

Deterministic, matplotlib only, no API step.
"""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np
import pandas as pd

from universal_backtester.metrics import cagr, drawdown_series

STRAT, BENCH, SLEEVE = "#1f4e79", "#d98324", "#6a994e"


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.6,
                         "legend.frameon": False})
    return plt


def _clean(s: pd.Series) -> pd.Series:
    return s.dropna()


def _label_end(ax, s: pd.Series, text: str, color: str, dy: float = 0.0) -> None:
    ax.annotate(text, xy=(s.index[-1], s.iloc[-1]), xytext=(6, dy), textcoords="offset points",
                color=color, fontsize=10, fontweight="bold", va="center", annotation_clip=False)


def save_clean_charts(strategy: pd.Series, benchmark: pd.Series, outdir: str, tag: str,
                      strategy_name: str = "Strategy", benchmark_name: str = "NIFTY 500",
                      weights: Optional[pd.DataFrame] = None, sleeve: Optional[pd.Series] = None,
                      sleeve_name: str = "Comparator", footnote: str = "") -> List[str]:
    """Write the charts and return the paths. `strategy` and `benchmark` are value series on
    comparable dates; they are aligned to their common dates before anything is drawn."""
    plt = _plt()
    os.makedirs(outdir, exist_ok=True)
    s, b = _clean(strategy), _clean(benchmark)
    idx = s.index.intersection(b.index)
    s, b = s.loc[idx], b.loc[idx]
    if len(idx) < 30:
        print("  [clean charts skipped: fewer than 30 common dates]")
        return []
    s100, b100 = 100 * s / s.iloc[0], 100 * b / b.iloc[0]
    span = f"{idx[0].date()} to {idx[-1].date()}"
    written: List[str] = []

    def save(fig, view, note=True):
        path = os.path.join(outdir, f"{tag}__{view}.png")
        fig.tight_layout()
        if footnote and note:
            fig.subplots_adjust(bottom=max(fig.subplotpars.bottom, 0.16))
            fig.text(0.01, 0.01, footnote, fontsize=8.5, color="#666666", ha="left", va="bottom")
        fig.savefig(path, dpi=130)
        plt.close(fig)
        written.append(path)

    # 1. cumulative return
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(b100.index, b100, color=BENCH, lw=2, label=benchmark_name)
    ax.plot(s100.index, s100, color=STRAT, lw=2.2, label=strategy_name)
    ax.axhline(100, color="#999999", lw=0.8, ls=":")
    _label_end(ax, s100, f"{s100.iloc[-1]:.0f}", STRAT, dy=6 if s100.iloc[-1] >= b100.iloc[-1] else -6)
    _label_end(ax, b100, f"{b100.iloc[-1]:.0f}", BENCH, dy=-6 if s100.iloc[-1] >= b100.iloc[-1] else 6)
    ax.set_title(f"Cumulative return, rebased to 100\n{span}   CAGR: {strategy_name} {cagr(s):.1%}, "
                 f"{benchmark_name} {cagr(b):.1%}", loc="left", fontsize=11)
    ax.legend(loc="upper left")
    ax.margins(x=0.02)
    fig.subplots_adjust(right=0.92)
    save(fig, "cumulative_return")

    # 2. drawdown
    ds, db = drawdown_series(s) * 100, drawdown_series(b) * 100
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(ds.index, ds.values, 0, color=STRAT, alpha=0.30, lw=0, label=strategy_name)
    ax.plot(ds.index, ds.values, color=STRAT, lw=1.2)
    ax.plot(db.index, db.values, color=BENCH, lw=1.8, label=benchmark_name)
    for ser, col, nm in ((ds, STRAT, strategy_name), (db, BENCH, benchmark_name)):
        t = ser.idxmin()
        ax.annotate(f"{nm} worst {ser.min():.1f}%", xy=(t, ser.min()), xytext=(0, -14),
                    textcoords="offset points", color=col, fontsize=9.5, ha="center", fontweight="bold")
    ax.set_title(f"Drawdown from the previous peak (%)\n{span}", loc="left", fontsize=11)
    ax.set_ylim(min(ds.min(), db.min()) * 1.25, 1.5)
    ax.legend(loc="lower right")
    ax.margins(x=0.02)
    save(fig, "drawdown")

    # 3. rolling 1-year volatility
    rs, rb = s.pct_change(fill_method=None), b.pct_change(fill_method=None)
    vs, vb = rs.rolling(252).std() * np.sqrt(252) * 100, rb.rolling(252).std() * np.sqrt(252) * 100
    if vs.notna().sum() > 20:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(vb.index, vb, color=BENCH, lw=2, label=benchmark_name)
        ax.plot(vs.index, vs, color=STRAT, lw=2.2, label=strategy_name)
        ax.set_title(f"Rolling 1-year annualised volatility (%)\n{span}", loc="left", fontsize=11)
        ax.legend(loc="best")
        ax.margins(x=0.02)
        save(fig, "rolling_volatility")

    # 4. calendar-year returns
    def cal(v):
        yr = v.groupby(v.index.year)
        first = v.groupby(v.index.year).first()
        last = v.groupby(v.index.year).last()
        prev_last = last.shift(1)
        base = prev_last.fillna(first)
        return (last / base - 1) * 100
    cs, cb = cal(s), cal(b)
    yrs = sorted(set(cs.index) | set(cb.index))
    x = np.arange(len(yrs))
    fig, ax = plt.subplots(figsize=(10, 5))
    w = 0.38
    bs = ax.bar(x - w / 2, [cs.get(y, np.nan) for y in yrs], w, color=STRAT, label=strategy_name)
    bb = ax.bar(x + w / 2, [cb.get(y, np.nan) for y in yrs], w, color=BENCH, label=benchmark_name)
    for bars in (bs, bb):
        for r in bars:
            h = r.get_height()
            if np.isfinite(h):
                ax.annotate(f"{h:.1f}", xy=(r.get_x() + r.get_width() / 2, h), xytext=(0, 3 if h >= 0 else -11),
                            textcoords="offset points", ha="center", fontsize=9)
    labels = []
    for y in yrs:
        part = ""
        if y == idx[0].year and idx[0] > pd.Timestamp(f"{y}-01-15"):
            part = f"\nfrom {idx[0].strftime('%d %b')}"
        if y == idx[-1].year and idx[-1] < pd.Timestamp(f"{y}-12-15"):
            part = f"\nto {idx[-1].strftime('%d %b')}"
        labels.append(f"{y}{part}")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.axhline(0, color="#666666", lw=0.8)
    ax.set_title(f"Calendar-year return (%)\n{span}", loc="left", fontsize=11)
    ax.legend(loc="best")
    save(fig, "calendar_year")

    # 5. exposure: long and short gross as areas, net as a line
    if weights is not None and len(weights):
        w_ = weights.reindex(idx)
        longg = w_.clip(lower=0).sum(axis=1)
        shortg = -w_.clip(upper=0).sum(axis=1)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.fill_between(longg.index, longg.values, 0, color=STRAT, alpha=0.35, lw=0, label="Long (share of NAV)")
        if shortg.max() > 1e-6:
            ax.fill_between(shortg.index, -shortg.values, 0, color=BENCH, alpha=0.35, lw=0, label="Short (share of NAV)")
            ax.plot(longg.index, (longg - shortg).values, color="#222222", lw=1.6, label="Net")
        ax.axhline(0, color="#666666", lw=0.8)
        ax.set_title(f"Exposure of {strategy_name}\n{span}", loc="left", fontsize=11)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3)
        ax.margins(x=0.02)
        save(fig, "exposure", note=False)

    # 6. the one extra sleeve, on its own chart
    if sleeve is not None and len(_clean(sleeve)) > 30:
        sl = _clean(sleeve).reindex(idx).dropna()
        sl100 = 100 * sl / sl.iloc[0]
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.plot(b100.index, b100, color=BENCH, lw=2, label=benchmark_name)
        ax.plot(s100.index, s100, color=STRAT, lw=2.2, label=strategy_name)
        ax.plot(sl100.index, sl100, color=SLEEVE, lw=2.2, label=sleeve_name)
        ax.axhline(100, color="#999999", lw=0.8, ls=":")
        ax.set_title(f"Cumulative return with one comparator, rebased to 100\n{span}", loc="left", fontsize=11)
        ax.legend(loc="upper left")
        ax.margins(x=0.02)
        save(fig, "with_sleeve")
    return written
