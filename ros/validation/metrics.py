"""Performance metrics.

Two Sharpe definitions are reported side by side, deliberately. The test paper
defines Sharpe as (CAGR - compounded cash return) / annualised vol -- a geometric
measure -- while almost every other paper and every risk system uses the
arithmetic mean of periodic excess returns. They differ by roughly half the
variance, which is ~0.5% a year at 10% vol: enough to move a Sharpe by 0.05 and
enough to make a replication look broken when it is not. A card must state which
one it is replicating; the engine always computes both.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

ANN = 252


def cagr(value: pd.Series, ann: int = ANN) -> float:
    v = value.dropna()
    if len(v) < 2 or v.iloc[0] <= 0:
        return float("nan")
    years = (v.index[-1] - v.index[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float((v.iloc[-1] / v.iloc[0]) ** (1.0 / years) - 1.0)


def ann_vol(returns: pd.Series, ann: int = ANN) -> float:
    r = returns.dropna()
    return float(r.std(ddof=1) * np.sqrt(ann)) if len(r) > 2 else float("nan")


def compounded_cash_cagr(rf_daily: pd.Series, index: pd.DatetimeIndex,
                         ann: int = ANN) -> float:
    rf = rf_daily.reindex(index).fillna(0.0)
    if len(rf) < 2:
        return 0.0
    years = (index[-1] - index[0]).days / 365.25
    total = float(np.prod(1.0 + rf.to_numpy(dtype=float)))
    return total ** (1.0 / years) - 1.0 if years > 0 else float("nan")


def sharpe_geometric(value: pd.Series, returns: pd.Series,
                     rf_daily: Optional[pd.Series] = None, ann: int = ANN) -> float:
    """Paper definition: (CAGR - compounded cash CAGR) / annualised vol."""
    v = ann_vol(returns, ann)
    if not np.isfinite(v) or v == 0:
        return float("nan")
    rf_cagr = compounded_cash_cagr(rf_daily, value.index, ann) if rf_daily is not None else 0.0
    return float((cagr(value, ann) - rf_cagr) / v)


def sharpe_conventional(returns: pd.Series, rf_daily: Optional[pd.Series] = None,
                        ann: int = ANN) -> float:
    """Conventional definition: arithmetic mean excess return / std, annualised."""
    r = returns.dropna()
    if len(r) < 3:
        return float("nan")
    ex = r - (rf_daily.reindex(r.index).fillna(0.0) if rf_daily is not None else 0.0)
    sd = ex.std(ddof=1)
    return float(ex.mean() / sd * np.sqrt(ann)) if sd > 0 else float("nan")


def drawdown_series(value: pd.Series) -> pd.Series:
    return value / value.cummax() - 1.0


def max_drawdown(value: pd.Series) -> float:
    return float(-drawdown_series(value).min())


def mean_drawdown(value: pd.Series) -> float:
    return float(-drawdown_series(value).mean())


def drawdown_duration_days(value: pd.Series) -> int:
    """Longest stretch, in calendar days, spent below a prior peak."""
    dd = drawdown_series(value)
    under = dd < -1e-12
    longest = cur_start = None
    best = 0
    for d, u in under.items():
        if u and cur_start is None:
            cur_start = d
        elif not u and cur_start is not None:
            best = max(best, (d - cur_start).days)
            cur_start = None
    if cur_start is not None:
        best = max(best, (under.index[-1] - cur_start).days)
    return int(best)


def ann_turnover(turnover: pd.Series, ann: int = ANN) -> float:
    t = turnover.dropna()
    return float(t.mean() * ann) if len(t) else float("nan")


def cvar(returns: pd.Series, alpha: float = 0.05, ann: int = ANN,
         horizon: int = 21) -> float:
    """Conditional VaR of horizon-aggregated returns, at the alpha tail.

    Reported on a monthly (21-day) horizon because that is the horizon a risk
    committee actually sizes against; a daily CVaR understates the tail that
    matters for a monthly-rebalanced book.
    """
    r = returns.dropna()
    if len(r) < horizon * 6:
        return float("nan")
    agg = (1.0 + r).rolling(horizon).apply(np.prod, raw=True) - 1.0
    agg = agg.dropna()
    q = agg.quantile(alpha)
    tail = agg[agg <= q]
    return float(-tail.mean()) if len(tail) else float("nan")


def calendar_year_vol(returns: pd.Series, ann: int = ANN) -> pd.Series:
    return returns.groupby(returns.index.year).apply(
        lambda s: s.std(ddof=1) * np.sqrt(ann))


def vol_consistency(returns: pd.Series, ann: int = ANN) -> float:
    """Spread of realised calendar-year vol (max - min). The paper's 'consistency'."""
    cy = calendar_year_vol(returns, ann).dropna()
    return float(cy.max() - cy.min()) if len(cy) > 1 else float("nan")


def hit_rate_monthly(returns: pd.Series) -> float:
    m = (1.0 + returns).resample("ME").prod() - 1.0
    return float((m > 0).mean()) if len(m) else float("nan")


@dataclass
class Metrics:
    name: str
    cagr: float
    vol: float
    sharpe: float             # paper (geometric) definition
    sharpe_conventional: float
    max_dd: float
    mean_dd: float
    dd_duration_days: int
    turnover: float
    cvar_95_monthly: float
    vol_consistency: float
    hit_rate_monthly: float
    n_obs: int
    start: str = ""
    end: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_metrics(result, rf_daily: Optional[pd.Series] = None,
                    ann: int = ANN) -> Metrics:
    v, r = result.value, result.returns
    return Metrics(
        name=result.name,
        cagr=cagr(v, ann),
        vol=ann_vol(r, ann),
        sharpe=sharpe_geometric(v, r, rf_daily, ann),
        sharpe_conventional=sharpe_conventional(r, rf_daily, ann),
        max_dd=max_drawdown(v),
        mean_dd=mean_drawdown(v),
        dd_duration_days=drawdown_duration_days(v),
        turnover=ann_turnover(result.turnover, ann),
        cvar_95_monthly=cvar(r, 0.05, ann),
        vol_consistency=vol_consistency(r, ann),
        hit_rate_monthly=hit_rate_monthly(r),
        n_obs=int(len(v)),
        start=str(v.index[0].date()), end=str(v.index[-1].date()),
    )


def metrics_table(results, rf_daily: Optional[pd.Series] = None) -> pd.DataFrame:
    rows = [compute_metrics(r, rf_daily).to_dict() for r in results]
    df = pd.DataFrame(rows).set_index("name")
    return df


def render_table(df: pd.DataFrame) -> str:
    """Format a metrics table the way a PM reads it."""
    pct = ["cagr", "vol", "max_dd", "mean_dd", "turnover", "cvar_95_monthly",
           "vol_consistency", "hit_rate_monthly"]
    out = df.copy()
    for c in pct:
        if c in out.columns:
            out[c] = out[c].map(lambda x: f"{x:.1%}" if pd.notna(x) else "--")
    for c in ["sharpe", "sharpe_conventional"]:
        if c in out.columns:
            out[c] = out[c].map(lambda x: f"{x:.2f}" if pd.notna(x) else "--")
    return out.to_string()
