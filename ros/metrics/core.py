# Quant AI Researcher
"""The one definition of every performance metric. Dashboards, workbooks, reports and gates import from here.

Daily simple returns as fractions, dates as the index. `cash` is one period's cash return: a number or a Series, and it
comes from the card (see cash_rate_from_card). A name defined here means the same thing everywhere; a test fails if two
code paths disagree (tests/test_metrics_cross_path.py).
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

ANN = 252
_CASH_CONSTANT = re.compile(r"^CASH_PROXY_CONSTANT_(\d+(?:\.\d+)?)PCT$")


class MissingCashRate(ValueError):
    """The card names no cash rate this module can read. Never fall back to a typed number."""


def cash_rate_from_card(card) -> float:
    """The annual cash rate the card declares in universe.cash_asset (CASH_PROXY_CONSTANT_<n>PCT)."""
    asset = getattr(getattr(card, "universe", None), "cash_asset", None)
    m = _CASH_CONSTANT.match(str(asset or ""))
    if not m:
        raise MissingCashRate(f"card universe.cash_asset is {asset!r}; expected CASH_PROXY_CONSTANT_<n>PCT")
    return float(m.group(1)) / 100.0


def daily_cash(annual_rate: float) -> float:
    """One trading day's accrual at an annual rate (the same accrual as ros.data.loaders.synthetic_cash_series)."""
    return (1.0 + annual_rate) ** (1.0 / ANN) - 1.0


def excess(returns: pd.Series, cash: float | pd.Series | None = None) -> pd.Series:
    r = returns.dropna()
    if cash is None:
        return r
    if isinstance(cash, pd.Series):
        return r - cash.reindex(r.index).fillna(0.0)
    return r - float(cash)


# ---------------------------------------------------------------------------------------------- return
def value_from_returns(returns: pd.Series, base: float = 100.0, start=None) -> pd.Series:
    """`base` at `start`, the close before the first return, then compounded by every return. Give `start` whenever a CAGR
    is taken: without it the series begins AFTER the first return, which a CAGR then leaves out."""
    v = base * (1.0 + returns.fillna(0.0)).cumprod()
    if start is not None:
        v = pd.concat([pd.Series([base], index=[pd.Timestamp(start)]), v])
    return v


def cagr_from_returns(returns: pd.Series, start) -> float:
    """The one CAGR of a return series: base at `start`, the NSE session before the first return, so every return counts
    and the years run from that base date."""
    return cagr(value_from_returns(returns.dropna(), start=start))


def split_windows(index: pd.DatetimeIndex, edges) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.DatetimeIndex, pd.Timestamp | None]]:
    """Consecutive windows of `index` at `edges`: the first is [e0, e1], each later one (e_i, e_i+1], so no day falls in
    two windows. Each comes with its anchor: the last date of `index` before the window's first day (None when the window
    starts the index), which is the base of that window's value and CAGR."""
    out = []
    for i in range(len(edges) - 1):
        lo, hi = pd.Timestamp(edges[i]), pd.Timestamp(edges[i + 1])
        days = index[((index >= lo) if i == 0 else (index > lo)) & (index <= hi)]
        if not len(days):
            continue
        pos = index.get_loc(days[0])
        out.append((lo, hi, days, index[pos - 1] if pos > 0 else None))
    return out


def years_between(start, end) -> float:
    return (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25


def cagr(value: pd.Series) -> float:
    """(last / first) ** (1 / years) - 1, on calendar days / 365.25."""
    v = value.dropna()
    if len(v) < 2 or v.iloc[0] <= 0:
        return float("nan")
    years = years_between(v.index[0], v.index[-1])
    return float((v.iloc[-1] / v.iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else float("nan")


def edge(strategy_cagr: float, benchmark_cagr: float) -> float:
    return float(strategy_cagr - benchmark_cagr)


def monthly_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.dropna()).resample("ME").prod() - 1.0


def calendar_year_returns(returns: pd.Series) -> pd.Series:
    r = returns.dropna()
    return (1.0 + r).groupby(r.index.year).prod() - 1.0


def financial_year_returns(returns: pd.Series) -> pd.Series:
    """Indian financial year, April to March, labelled by the year it ends in."""
    r = returns.dropna()
    return (1.0 + r).groupby(r.index.year + (r.index.month >= 4).astype(int)).prod() - 1.0


def period_return(returns: pd.Series, start=None, end=None) -> float:
    return float((1.0 + returns.loc[start:end].dropna()).prod() - 1.0)


# ---------------------------------------------------------------------------------------------- risk
def ann_vol(returns: pd.Series) -> float:
    r = returns.dropna()
    return float(r.std(ddof=1) * np.sqrt(ANN)) if len(r) > 2 else float("nan")


def rolling_vol(returns: pd.Series, window: int = 63) -> pd.Series:
    return returns.rolling(window).std(ddof=1) * np.sqrt(ANN)


def drawdown_series(value: pd.Series) -> pd.Series:
    return value / value.cummax() - 1.0


def max_drawdown(value: pd.Series) -> float:
    """Worst fall from a previous high on daily values, as a positive number."""
    return float(-drawdown_series(value).min())


def drawdown_duration(value: pd.Series) -> int:
    """Longest stretch below a previous high, in trading days."""
    best = cur = 0
    for under in (drawdown_series(value) < -1e-12).to_numpy():
        cur = cur + 1 if under else 0
        best = max(best, cur)
    return int(best)


def cvar_95(returns: pd.Series) -> float:
    """Mean daily loss on the days at or below the 5th percentile, as a positive number."""
    r = returns.dropna()
    return float(-r[r <= np.percentile(r, 5)].mean()) if len(r) else float("nan")


def skew(returns: pd.Series) -> float:
    return float(stats.skew(returns.dropna(), bias=False))


def kurtosis(returns: pd.Series) -> float:
    """Raw kurtosis (a bell curve is 3). Kept only as a deflated Sharpe input."""
    return float(stats.kurtosis(returns.dropna(), fisher=False, bias=False))


def worst_days(returns: pd.Series, n: int = 5) -> pd.Series:
    return returns.dropna().nsmallest(n)


# ---------------------------------------------------------------------------------------------- risk-adjusted
def sharpe(returns: pd.Series, cash: float | pd.Series | None = None) -> float:
    """mean(r - c) / stdev(r - c) * sqrt(252). The only Sharpe in the repository's reports and gates."""
    x = excess(returns, cash)
    if len(x) < 3:
        return float("nan")
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(ANN)) if sd > 0 else float("nan")


def sortino(returns: pd.Series, cash: float | pd.Series | None = None) -> float:
    """mean(r - c) * 252 / downside deviation, where downside deviation = sqrt(mean(min(r - c, 0)^2)) * sqrt(252)."""
    x = excess(returns, cash)
    if not len(x):
        return float("nan")
    dd = float(np.sqrt((np.minimum(x.to_numpy(), 0.0) ** 2).mean()) * np.sqrt(ANN))
    return float(x.mean() * ANN / dd) if dd > 0 else float("nan")


def calmar(value: pd.Series) -> float:
    mdd = max_drawdown(value)
    return float(cagr(value) / mdd) if mdd > 0 else float("nan")


# ---------------------------------------------------------------------------------------------- against the benchmark
def _aligned(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    df = pd.concat([a, b], axis=1, join="inner").dropna()
    return df.iloc[:, 0], df.iloc[:, 1]


def beta(returns: pd.Series, bench: pd.Series, cash: float | pd.Series | None = None) -> float:
    """Cov(r - c, b - c) / Var(b - c), on excess returns."""
    r, b = _aligned(returns, bench)
    x, y = excess(r, cash), excess(b, cash)
    v = float(y.var(ddof=1))
    return float(x.cov(y) / v) if v > 0 else float("nan")


def tracking_error(returns: pd.Series, bench: pd.Series) -> float:
    """stdev(r - b) * sqrt(252), sample standard deviation of daily gaps."""
    r, b = _aligned(returns, bench)
    return float((r - b).std(ddof=1) * np.sqrt(ANN)) if len(r) > 2 else float("nan")


def information_ratio(returns: pd.Series, bench: pd.Series) -> float:
    r, b = _aligned(returns, bench)
    te = tracking_error(r, b)
    return float((r - b).mean() * ANN / te) if te and te > 0 else float("nan")


def up_capture(returns: pd.Series, bench: pd.Series) -> float:
    """Mean monthly strategy return / mean monthly benchmark return, in months the benchmark rose."""
    m, mb = _aligned(monthly_returns(returns), monthly_returns(bench))
    up = mb > 0
    return float(m[up].mean() / mb[up].mean()) if up.any() else float("nan")


def down_capture(returns: pd.Series, bench: pd.Series) -> float:
    """The same, in months the benchmark fell. Below 1 means it falls less than the benchmark."""
    m, mb = _aligned(monthly_returns(returns), monthly_returns(bench))
    dn = mb < 0
    return float(m[dn].mean() / mb[dn].mean()) if dn.any() else float("nan")


def rolling_periods_behind(returns: pd.Series, bench: pd.Series, window: int = ANN) -> float:
    """Share of rolling one-year periods in which the strategy's compounded return is below the benchmark's."""
    r, b = _aligned(returns, bench)
    gap = (1.0 + r).rolling(window).apply(np.prod, raw=True) - (1.0 + b).rolling(window).apply(np.prod, raw=True)
    gap = gap.dropna()
    return float((gap < 0).mean()) if len(gap) else float("nan")


# ---------------------------------------------------------------------------------------------- robustness re-reads
def cagr_without_best_days(returns: pd.Series, n: int = 10) -> float:
    """Compound every day except the n best, over the same calendar span."""
    r = returns.dropna()
    years = years_between(r.index[0], r.index[-1])
    kept = r.drop(r.nlargest(n).index)
    return float((1.0 + kept).prod() ** (1.0 / years) - 1.0) if years > 0 else float("nan")


def politis_white_block(x) -> float:
    """Automatic mean block length for the stationary bootstrap: Politis and White (2004), with the correction of Patton,
    Politis and White (2009). Flat-top lag window; its bandwidth M = 2 m-hat, where m-hat is the smallest lag after which
    K_n = max(5, sqrt(log10 n)) autocorrelations in a row are inside 2 sqrt(log10 n / n). Capped at min(3 sqrt(n), n / 3).
        b = (2 G^2 / D)^(1/3) n^(1/3),  G = sum lambda(k/M) |k| R(k),  D = 2 (sum lambda(k/M) R(k))^2"""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return 1.0
    e = x - x.mean()
    kn = max(5, int(np.ceil(np.sqrt(np.log10(n)))))
    m_max = int(np.ceil(np.sqrt(n))) + kn
    b_max = float(np.ceil(min(3.0 * np.sqrt(n), n / 3.0)))
    acov = np.array([e[k:] @ e[:n - k] / n for k in range(min(m_max + kn, n - 1) + 1)])
    if acov[0] <= 0:
        return 1.0
    rho = np.abs(acov / acov[0])
    crit = 2.0 * np.sqrt(np.log10(n) / n)
    m_hat = next((m for m in range(m_max + 1) if m + kn < len(rho) and np.all(rho[m + 1:m + kn + 1] < crit)), None)
    big_m = m_max if m_hat is None else min(2 * max(m_hat, 1), m_max)
    big_m = min(big_m, len(acov) - 1)
    k = np.arange(1, big_m + 1)
    lam = np.where(k / big_m <= 0.5, 1.0, 2.0 * (1.0 - k / big_m))
    g = 2.0 * float(np.sum(lam * k * acov[1:big_m + 1]))
    d = 2.0 * float(acov[0] + 2.0 * np.sum(lam * acov[1:big_m + 1])) ** 2
    if d <= 0 or g == 0:
        return 1.0
    return float(min(max((2.0 * g * g / d) ** (1.0 / 3.0) * n ** (1.0 / 3.0), 1.0), b_max))


def auto_mean_block(*series) -> float:
    """One block length for paired draws of several series: the largest Politis-White length among them, so no series'
    dependence is cut shorter than its own estimate asks."""
    return max(politis_white_block(s) for s in series)


def stationary_bootstrap_indices(n: int, n_boot: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis and Romano (1994): each day starts a new block with probability 1 / mean_block, wrapping at the end.
    Returns an n_boot x n matrix of day positions; pass the same matrix to every series to keep them paired."""
    pos = np.arange(n, dtype=np.int32)
    new = rng.random((n_boot, n)) < 1.0 / mean_block
    new[:, 0] = True
    starts = rng.integers(0, n, size=(n_boot, n), dtype=np.int32)
    last = np.maximum.accumulate(np.where(new, pos, 0), axis=1)
    return (np.take_along_axis(starts, last, axis=1) + pos - last) % n


def sharpe_draws(values: np.ndarray, idx: np.ndarray, cash: float | np.ndarray = 0.0) -> np.ndarray:
    """The Sharpe of one return array under every draw of an index matrix. `cash` is a number or a same-length array."""
    x = values[idx] - (cash[idx] if isinstance(cash, np.ndarray) else cash)
    sd = x.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return x.mean(axis=1) / sd * np.sqrt(ANN)


def max_drawdown_draws(values: np.ndarray, idx: np.ndarray) -> np.ndarray:
    nav = np.cumprod(1.0 + values[idx], axis=1)
    return -(nav / np.maximum.accumulate(nav, axis=1) - 1.0).min(axis=1)


# ---------------------------------------------------------------------------------------------- costs and capacity
def returns_at_cost(returns: pd.Series, two_way_turnover: pd.Series, cost_bp: float, charged_bp: float) -> pd.Series:
    """The same trades at another round-trip cost. A round trip is one buy plus one sell, so each unit of two-way turnover
    pays half of it. `charged_bp` is what the series already carries, so nothing is charged twice."""
    t = two_way_turnover.reindex(returns.index).fillna(0.0)
    return returns - t * (cost_bp - charged_bp) / 2.0 / 1e4


def annual_turnover(two_way_turnover: pd.Series) -> float:
    """Sum of daily (bought + sold) / NAV, per calendar year. 1.0 means trading capital once a year."""
    t = two_way_turnover.dropna()
    if len(t) < 2:
        return float("nan")
    years = years_between(t.index[0], t.index[-1])
    return float(t.sum() / years) if years > 0 else float("nan")


def two_way_turnover_from_trades(trades: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Daily two-way turnover from a run's trades.csv: |weight_after - weight_before| summed by execution date."""
    date = "execution_date" if "execution_date" in trades.columns else "date"
    # The first book can be bought on the day before the first return. It still traded: count it on the first day.
    dates = pd.to_datetime(trades[date]).clip(lower=index[0])
    t = (trades["weight_after"].astype(float) - trades["weight_before"].astype(float)).abs().groupby(dates).sum()
    return t.reindex(index).fillna(0.0)


def adv_20(traded_value: pd.DataFrame) -> pd.DataFrame:
    """Average traded value over the 20 sessions BEFORE each day. A trade cannot be sized on its own day's volume."""
    return traded_value.rolling(20, min_periods=10).mean().shift(1)


def capacity(trades: pd.DataFrame, adv: pd.DataFrame, aum: float, limit: float) -> dict[str, Any]:
    """Each trade's size at the fund's AUM as a share of that name's 20-day ADV. `aum` and `adv` share a currency unit.
    A name with no ADV on its trade date is counted, not dropped: an unmeasurable trade is not a small one."""
    date = "execution_date" if "execution_date" in trades.columns else "date"
    t = pd.DataFrame({"date": pd.to_datetime(trades[date]), "isin": trades["isin"],
                      "rupees": (trades["weight_after"].astype(float) - trades["weight_before"].astype(float)).abs() * aum})
    t = t[t["rupees"] > 0]
    long_adv = adv.stack().rename("adv").rename_axis(["date", "isin"]).reset_index()
    t = t.merge(long_adv, how="left", on=["date", "isin"])
    t["participation"] = t["rupees"] / t["adv"].where(t["adv"] > 0)
    ok = t["participation"].dropna()
    return {"n_trades": len(t), "n_no_adv": int(t["participation"].isna().sum()),
            "median": float(ok.median()) if len(ok) else float("nan"),
            "p95": float(ok.quantile(0.95)) if len(ok) else float("nan"),
            "max": float(ok.max()) if len(ok) else float("nan"), "limit": limit,
            "names_above_limit": sorted(t.loc[t["participation"] > limit, "isin"].unique().tolist())}


def capacity_unit(trades: pd.DataFrame, adv: pd.DataFrame, limit: float) -> dict[str, Any]:
    """Capacity with NO AUM assumed. For every trade: its size for each Rs 1 crore of capital as a share of that name's
    20-day ADV (adv in Rs crore). Reports the median and 95th percentile per Rs 1 crore, and the capital at which the
    95th-percentile trade reaches `limit` of ADV20: capital = limit / p95 (Rs crore). A name with no ADV is counted."""
    date = "execution_date" if "execution_date" in trades.columns else "date"
    t = pd.DataFrame({"date": pd.to_datetime(trades[date]), "isin": trades["isin"],
                      "share_of_capital": (trades["weight_after"].astype(float) - trades["weight_before"].astype(float)).abs()})
    t = t[t["share_of_capital"] > 0]
    long_adv = adv.stack().rename("adv").rename_axis(["date", "isin"]).reset_index()
    t = t.merge(long_adv, how="left", on=["date", "isin"])
    t["per_cr"] = t["share_of_capital"] / t["adv"].where(t["adv"] > 0)          # participation per Rs 1 crore of capital
    ok = t["per_cr"].dropna()
    p95 = float(ok.quantile(0.95)) if len(ok) else float("nan")
    return {"n_trades": len(t), "n_no_adv": int(t["per_cr"].isna().sum()),
            "per_cr_median": float(ok.median()) if len(ok) else float("nan"), "per_cr_p95": p95, "limit": limit,
            "capital_at_limit_cr": float(limit / p95) if limit and p95 and p95 > 0 else float("nan")}


# ---------------------------------------------------------------------------------------------- post-publication
def publication_cutoff(date: str | None) -> pd.Timestamp | None:
    """The first day after a paper was public. A bare year means the end of that year, the cautious reading."""
    s = str(date or "").strip()
    if re.fullmatch(r"\d{4}", s):
        return pd.Timestamp(f"{s}-12-31")
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return pd.Timestamp(f"{s}-01") + pd.offsets.MonthEnd(0)
    try:
        return pd.Timestamp(s) if s else None
    except ValueError:
        return None


def post_publication(returns: pd.Series, bench: pd.Series, cash: float | pd.Series | None, date: str | None) -> dict[str, Any] | None:
    """Metrics from the publication date onward, shown apart from the full window. None if under a year is left."""
    cut = publication_cutoff(date)
    if cut is None:
        return None
    r_all, b_all = returns.dropna(), bench.dropna()
    r, b = r_all.loc[cut:], b_all.loc[cut:]
    if len(r) < ANN:
        return None
    # base: the last date before the first post-publication return, so that return counts
    before_r, before_b = r_all.index[r_all.index < r.index[0]], b_all.index[b_all.index < b.index[0]]
    vr = value_from_returns(r, start=before_r[-1] if len(before_r) else None)
    vb = value_from_returns(b, start=before_b[-1] if len(before_b) else None)
    return {"from": str(cut.date()), "days": len(r), "cagr": cagr(vr), "benchmark_cagr": cagr(vb), "edge": edge(cagr(vr), cagr(vb)),
            "sharpe": sharpe(r, cash), "benchmark_sharpe": sharpe(b, cash), "max_dd": max_drawdown(vr), "information_ratio": information_ratio(r, b)}


# ---------------------------------------------------------------------------------------------- one block of metrics
def summary(returns: pd.Series, cash: float | pd.Series | None = None, bench: pd.Series | None = None, start=None) -> dict[str, float]:
    """The core block for one return series. `start` is the value-100 date before the first return, when there is one."""
    r = returns.dropna()
    v = value_from_returns(r, start=start)
    out = {"final": float(v.iloc[-1]), "cagr": cagr(v), "vol": ann_vol(r), "sharpe": sharpe(r, cash), "sortino": sortino(r, cash),
           "calmar": calmar(v), "max_dd": max_drawdown(v), "dd_duration_days": drawdown_duration(v), "cvar_95": cvar_95(r),
           "skew": skew(r), "best_days_removed_cagr": cagr_without_best_days(r), "days": len(r)}
    if bench is not None:
        out.update(beta=beta(r, bench, cash), tracking_error=tracking_error(r, bench), information_ratio=information_ratio(r, bench),
                   up_capture=up_capture(r, bench), down_capture=down_capture(r, bench), rolling_behind=rolling_periods_behind(r, bench))
    return out


# ---------------------------------------------------------------------------------------------- selection-adjusted Sharpe
def probabilistic_sharpe(sr_daily: float, bar_daily: float, n: int, skewness: float, kurt: float) -> float:
    """P(true Sharpe > bar), allowing for sample length, skew and raw kurtosis (Bailey and Lopez de Prado, 2014)."""
    denom = np.sqrt(max(1e-12, 1.0 - skewness * sr_daily + (kurt - 1.0) / 4.0 * sr_daily ** 2))
    return float(stats.norm.cdf((sr_daily - bar_daily) * np.sqrt(n - 1) / denom))


def expected_max_sharpe(n_trials: float, var_sharpe: float) -> float:
    """Expected best yearly Sharpe among n_trials independent no-skill versions, whose Sharpes have variance var_sharpe."""
    if n_trials <= 1:
        return 0.0
    gamma = 0.5772156649015329
    return float(np.sqrt(var_sharpe) * ((1 - gamma) * stats.norm.ppf(1.0 - 1.0 / n_trials) + gamma * stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e))))


def effective_trials(n: int, mean_correlation: float) -> float:
    """Independent versions implied by n versions with this average pairwise correlation: rho + (1 - rho) * n.
    Perfectly correlated versions count as one; uncorrelated versions count in full."""
    rho = min(1.0, max(0.0, mean_correlation))
    return float(rho + (1.0 - rho) * n)
