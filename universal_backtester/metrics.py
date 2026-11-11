# Quant AI Researcher by Harshil Pahuja
"""Performance metrics computed from a BacktestResult. Every definition is in ros.metrics.core."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from ros import config
from ros.metrics import core

ANN = core.ANN
drawdown_series = core.drawdown_series
max_drawdown = core.max_drawdown


def cagr(value: pd.Series, ann: int = ANN) -> float:
    return core.cagr(value)


def ann_vol(returns: pd.Series, ann: int = ANN) -> float:
    return core.ann_vol(returns)


def sharpe(value: pd.Series, returns: pd.Series, rf_daily: pd.Series | None = None, ann: int = ANN) -> float:
    return core.sharpe(returns, rf_daily)


def ann_turnover(turnover: pd.Series, ann: int = ANN) -> float:
    return core.annual_turnover(turnover)


@dataclass
class Metrics:
    name: str
    cagr: float
    vol: float
    sharpe: float
    max_dd: float
    turnover: float
    n_obs: int
    start: str = ""
    end: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_metrics(result, rf_daily: pd.Series | None = None, ann: int = ANN) -> Metrics:
    """Sharpe is the arithmetic form over the Sharpe hurdle in config/fund.yaml. `rf_daily` is kept for callers that pass
    it; no Sharpe subtracts a cash rate."""
    v, r = result.value, result.returns
    return Metrics(
        name=result.name,
        cagr=cagr(v, ann),
        vol=ann_vol(r, ann),
        sharpe=core.sharpe(r, config.hurdle_daily()),
        max_dd=max_drawdown(v),
        turnover=ann_turnover(result.turnover, ann),
        n_obs=len(v),
        start=str(v.index[0].date()), end=str(v.index[-1].date()),
    )


def metrics_table(results, rf_daily: pd.Series | None = None) -> pd.DataFrame:
    rows = [compute_metrics(r, rf_daily).to_dict() for r in results]
    return pd.DataFrame(rows).set_index("name")


def render_table(df: pd.DataFrame) -> str:
    out = df.copy()
    for c in ["cagr", "vol", "max_dd", "turnover"]:
        if c in out.columns:
            out[c] = out[c].map(lambda x: f"{x:.1%}" if pd.notna(x) else "--")
    if "sharpe" in out.columns:
        out["sharpe"] = out["sharpe"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "--")
    return out.to_string()
