# Quant AI Researcher by Harshil Pahuja
"""The per-result metrics table the pipeline report prints. Every definition is in ros.metrics.core; this adds no formula.

`sharpe_paper_basis` is the one exception to a single Sharpe: a replication target printed in a paper is on the paper's
geometric definition, so replication_gap compares like with like. It is not reported anywhere else.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from ros.metrics.core import (
    ANN,
    ann_vol,
    cagr,
    calmar,
    cvar_95,
    drawdown_duration,
    drawdown_series,
    max_drawdown,
    sharpe,
    sortino,
)
from ros.metrics.core import annual_turnover as ann_turnover
from ros.metrics.legacy_v1 import sharpe_geometric

__all__ = ["ANN", "Metrics", "ann_turnover", "ann_vol", "cagr", "compute_metrics", "drawdown_series", "max_drawdown",
           "metrics_table", "render_table", "sharpe"]


@dataclass
class Metrics:
    name: str
    cagr: float
    vol: float
    sharpe: float
    sortino: float
    calmar: float
    max_dd: float
    dd_duration_days: int
    turnover: float
    cvar_95: float
    sharpe_paper_basis: float
    n_obs: int
    start: str = ""
    end: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_metrics(result, rf_daily: pd.Series | None = None) -> Metrics:
    v, r = result.value, result.returns
    return Metrics(
        name=result.name,
        cagr=cagr(v),
        vol=ann_vol(r),
        sharpe=sharpe(r, rf_daily),
        sortino=sortino(r, rf_daily),
        calmar=calmar(v),
        max_dd=max_drawdown(v),
        dd_duration_days=drawdown_duration(v),
        turnover=ann_turnover(result.turnover),
        cvar_95=cvar_95(r),
        sharpe_paper_basis=sharpe_geometric(v, r, rf_daily),
        n_obs=len(v),
        start=str(v.index[0].date()), end=str(v.index[-1].date()),
    )


def metrics_table(results, rf_daily: pd.Series | None = None) -> pd.DataFrame:
    rows = [compute_metrics(r, rf_daily).to_dict() for r in results]
    return pd.DataFrame(rows).set_index("name")


def render_table(df: pd.DataFrame) -> str:
    """Format a metrics table the way a PM reads it."""
    out = df.copy()
    for c in ["cagr", "vol", "max_dd", "turnover", "cvar_95"]:
        if c in out.columns:
            out[c] = out[c].map(lambda x: f"{x:.1%}" if pd.notna(x) else "--")
    for c in ["sharpe", "sortino", "calmar"]:
        if c in out.columns:
            out[c] = out[c].map(lambda x: f"{x:.2f}" if pd.notna(x) else "--")
    return out.to_string()
