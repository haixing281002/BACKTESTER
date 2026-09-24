"""Extended risk/return tearsheet -- the standard ratio set a factsheet
shows beyond metrics.py's core CAGR/vol/Sharpe/drawdown.

Every benchmark-relative number here (alpha, tracking error, capture
ratios, conditional returns) needs a benchmark return series. This repo's
NIFTY 500 series is PRICE-RETURN (dividends excluded), not the Total
Return Index. TRI is the correct, industry-standard comparison for a
long-only equity strategy -- a price-return index structurally understates
the benchmark by its dividend yield, roughly 1.3-1.5%/year for Indian
large/mid caps. Every number below computed against "the benchmark" is
computed against this price-return proxy because that is the only NIFTY
500 series this repo holds, and is systematically flattering to the
strategy relative to a true TRI comparison by about that much. It is fine
for comparing two strategies against the same (biased) benchmark; it is
not fine for a standalone claim like "beat the index by X%" without that
caveat attached.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from universal_backtester.metrics import cagr, ann_vol, drawdown_series, max_drawdown, sharpe as _sharpe

ANN = 252
MONTHLY = 12


def _rf_cagr(rf_daily: Optional[pd.Series], index: pd.DatetimeIndex, ann: int = ANN) -> float:
    if rf_daily is None:
        return 0.0
    rf = rf_daily.reindex(index).fillna(0.0)
    if len(rf) < 2:
        return 0.0
    years = (index[-1] - index[0]).days / 365.25
    if years <= 0:
        return 0.0
    total = float(np.prod(1.0 + rf.to_numpy(dtype=float)))
    return total ** (1.0 / years) - 1.0


TRI_CAVEAT = (
    "Benchmark is NIFTY 500 PRICE-RETURN (dividends excluded), used as a "
    "proxy for NIFTY 500 TRI because that is the only series this repo "
    "holds. Understates the true benchmark by ~1.3-1.5%/year -- every "
    "benchmark-relative number below inherits that bias in the strategy's favor."
)


def _monthly_returns(returns: pd.Series) -> pd.Series:
    r = returns.dropna()
    return (1.0 + r).resample("ME").prod() - 1.0


def positive_volatility(returns: pd.Series) -> float:
    """Population stdev (ddof=0) of positive MONTHLY returns -- verified
    against the reference workbook's real numbers to be UNANNOTATED (no
    *sqrt(12)), unlike every other volatility figure on the same sheet.
    Not our choice of convention -- reproducing the source exactly."""
    m = _monthly_returns(returns)
    pos = m[m > 0]
    return float(pos.std(ddof=0)) if len(pos) > 1 else float("nan")


def negative_volatility(returns: pd.Series) -> float:
    m = _monthly_returns(returns)
    neg = m[m < 0]
    return float(neg.std(ddof=0)) if len(neg) > 1 else float("nan")


def average_annual_max_drawdown(returns: pd.Series) -> float:
    """Mean of each calendar year's max drawdown, with the running peak
    RESET at the start of every calendar year (verified against the
    reference workbook's real numbers -- a whole-history running peak,
    carried across the year boundary, gives a different, wrong number)."""
    dd = calendar_year_max_drawdown(returns)
    return float(np.mean(list(dd.values()))) if dd else float("nan")


def beta(returns: pd.Series, bench_returns: pd.Series) -> float:
    r, b = returns.align(bench_returns, join="inner")
    m = r.notna() & b.notna()
    r, b = r[m], b[m]
    if len(r) < 3 or b.var(ddof=1) == 0:
        return float("nan")
    return float(np.cov(r, b, ddof=1)[0, 1] / b.var(ddof=1))


def adjusted_beta(returns: pd.Series, bench_returns: pd.Series) -> float:
    """Bloomberg-style shrinkage toward 1: (2/3)*raw_beta + (1/3)*1."""
    raw = beta(returns, bench_returns)
    return float((2.0 / 3.0) * raw + (1.0 / 3.0)) if np.isfinite(raw) else float("nan")


def treynor_ratio(value: pd.Series, returns: pd.Series, bench_returns: pd.Series,
                  rf_daily: Optional[pd.Series] = None, ann: int = ANN) -> float:
    b = beta(returns, bench_returns)
    if not np.isfinite(b) or b == 0:
        return float("nan")
    rf_cagr = _rf_cagr(rf_daily, value.index, ann) if rf_daily is not None else 0.0
    return float((cagr(value, ann) - rf_cagr) / b)


def alpha_adj_beta(value: pd.Series, returns: pd.Series, bench_value: pd.Series,
                   bench_returns: pd.Series, rf_daily: Optional[pd.Series] = None,
                   ann: int = ANN) -> float:
    """Jensen's alpha using the Bloomberg-adjusted beta:
    alpha = portfolio_CAGR - [rf + adj_beta * (benchmark_CAGR - rf)]."""
    b = adjusted_beta(returns, bench_returns)
    if not np.isfinite(b):
        return float("nan")
    rf_cagr = _rf_cagr(rf_daily, value.index, ann) if rf_daily is not None else 0.0
    bench_cagr = cagr(bench_value, ann)
    return float(cagr(value, ann) - (rf_cagr + b * (bench_cagr - rf_cagr)))


def tracking_error(returns: pd.Series, bench_returns: pd.Series, ann: int = ANN) -> float:
    """Population stdev (ddof=0) of the return difference, annualized --
    verified against the reference workbook's real number; ddof=1 (sample
    stdev) misses it by a small but real margin."""
    r, b = returns.align(bench_returns, join="inner")
    diff = (r - b).dropna()
    return float(diff.std(ddof=0) * np.sqrt(ann)) if len(diff) > 2 else float("nan")


def downside_deviation(returns: pd.Series, mar: float = 0.0, ann: int = ANN) -> float:
    r = returns.dropna()
    diff = np.minimum(r.to_numpy() - mar / ann, 0.0)
    return float(np.sqrt((diff ** 2).mean()) * np.sqrt(ann))


def sortino_ratio(returns: pd.Series, mar: float = 0.0, ann: int = ANN,
                  rf_daily: Optional[pd.Series] = None) -> float:
    r = returns.dropna()
    excess = r - (rf_daily.reindex(r.index).fillna(0.0) if rf_daily is not None else 0.0)
    dd = downside_deviation(excess, mar=mar, ann=ann)
    if dd <= 0:
        return float("nan")
    return float((excess.mean() * ann - mar) / dd)


def calmar_ratio(value: pd.Series, ann: int = ANN) -> float:
    mdd = max_drawdown(value)
    return float(cagr(value, ann) / mdd) if mdd > 0 else float("nan")


def sterling_ratio(value: pd.Series, ann: int = ANN) -> float:
    """CAGR / average annual max drawdown (the simple, no-10%-adjustment
    convention -- some vendors subtract a further 10 points from the
    denominator; this does not, documented here rather than silently picked)."""
    aamdd = average_annual_max_drawdown(value.pct_change().dropna())
    return float(cagr(value, ann) / abs(aamdd)) if aamdd < 0 else float("nan")


def omega_ratio(returns: pd.Series, threshold: float = 0.0) -> float:
    r = returns.dropna()
    excess = r - threshold
    gains = float(excess[excess > 0].sum())
    losses = float(-excess[excess < 0].sum())
    return float(gains / losses) if losses > 0 else float("nan")


def gain_to_pain_ratio(returns: pd.Series) -> float:
    """Sum of WINNING months' returns / abs(sum of losing months'
    returns) -- verified against the reference workbook's real number;
    summing ALL months (winners and losers together) in the numerator,
    as an earlier version of this function did, misses it by almost
    exactly 1.0 every time."""
    m = _monthly_returns(returns)
    gains = float(m[m > 0].sum())
    losses = float(-m[m < 0].sum())
    return float(gains / losses) if losses > 0 else float("nan")


def tail_ratio(returns: pd.Series, pct: float = 0.05) -> float:
    r = returns.dropna()
    right = np.percentile(r, 100 * (1 - pct))
    left = np.percentile(r, 100 * pct)
    return float(abs(right) / abs(left)) if left != 0 else float("nan")


def conditional_return(returns: pd.Series, bench_returns: pd.Series,
                       positive: bool, ann: int = ANN) -> float:
    """Mean daily portfolio return on days the benchmark was up (or down),
    reported as an annualized run-rate (mean * ann) for comparability --
    not a compounded total, since these days aren't contiguous."""
    r, b = returns.align(bench_returns, join="inner")
    mask = (b > 0) if positive else (b < 0)
    sub = r[mask]
    return float(sub.mean() * ann) if len(sub) else float("nan")


def _monthly_pair(returns: pd.Series, bench_returns: pd.Series):
    """Every ratio below is computed on MONTHLY returns, matching the
    reference "SE Return Analytics" workbook's own convention -- verified
    cell-for-cell against its real (non-synthetic) numbers, not assumed."""
    r, b = returns.align(bench_returns, join="inner")
    mr = (1.0 + r).resample("ME").prod() - 1.0
    mb = (1.0 + b).resample("ME").prod() - 1.0
    return mr, mb


def _mean_ratio(monthly_r: pd.Series, monthly_b: pd.Series, mask: pd.Series):
    """Simple AVERAGEIF-style mean of monthly returns under `mask`, for
    both portfolio and benchmark, plus their ratio -- the reference
    workbook's actual "Ret +Ve/-Ve" and "Capture" definition (confirmed by
    reproducing its real numbers to 10+ significant figures; NOT a
    compounded/annualized figure, and not scaled by 100)."""
    port_mean = float(monthly_r[mask].mean()) if mask.any() else float("nan")
    bench_mean = float(monthly_b[mask].mean()) if mask.any() else float("nan")
    ratio = float(port_mean / bench_mean) if bench_mean not in (0.0,) and np.isfinite(bench_mean) else float("nan")
    return port_mean, bench_mean, ratio


def upside_capture(returns: pd.Series, bench_returns: pd.Series) -> float:
    mr, mb = _monthly_pair(returns, bench_returns)
    _, _, ratio = _mean_ratio(mr, mb, mb > 0)
    return ratio


def downside_capture(returns: pd.Series, bench_returns: pd.Series) -> float:
    mr, mb = _monthly_pair(returns, bench_returns)
    _, _, ratio = _mean_ratio(mr, mb, mb < 0)
    return ratio


def capture_ratio(returns: pd.Series, bench_returns: pd.Series) -> float:
    up, down = upside_capture(returns, bench_returns), downside_capture(returns, bench_returns)
    return float(up / down) if np.isfinite(down) and down != 0 else float("nan")


# Extreme-capture thresholds: PERCENTILE(benchmark monthly returns, 0.83)
# for the upside cut and PERCENTILE(..., 0.07) for the downside cut. Not a
# round, "principled" number (a symmetric 90/10 or 95/5 would be the
# obvious guess) -- these exact two constants are what reproduces the
# reference workbook's real Extreme Capture Ratio figures bit-for-bit, so
# they're treated as the workbook's own fixed definition, not re-derived.
EXTREME_UPPER_PCT = 0.83
EXTREME_LOWER_PCT = 0.07


def extreme_capture_ratio(returns: pd.Series, bench_returns: pd.Series,
                          upper_pct: float = EXTREME_UPPER_PCT,
                          lower_pct: float = EXTREME_LOWER_PCT) -> float:
    mr, mb = _monthly_pair(returns, bench_returns)
    hi, lo = mb.quantile(upper_pct), mb.quantile(lower_pct)
    _, _, up = _mean_ratio(mr, mb, mb >= hi)
    _, _, down = _mean_ratio(mr, mb, mb <= lo)
    return float(up / down) if np.isfinite(down) and down != 0 else float("nan")


def extreme_capture_breakdown(returns: pd.Series, bench_returns: pd.Series,
                              upper_pct: float = EXTREME_UPPER_PCT,
                              lower_pct: float = EXTREME_LOWER_PCT) -> Dict[str, float]:
    """The five rows the reference workbook's "Extreme Capture Ratio"
    section actually shows, for both the strategy and the benchmark."""
    mr, mb = _monthly_pair(returns, bench_returns)
    hi, lo = mb.quantile(upper_pct), mb.quantile(lower_pct)
    strat_pos, bench_pos, up = _mean_ratio(mr, mb, mb >= hi)
    strat_neg, bench_neg, down = _mean_ratio(mr, mb, mb <= lo)
    ratio = float(up / down) if np.isfinite(down) and down != 0 else float("nan")
    return {
        "ex_ret_positive_strategy": strat_pos, "ex_ret_positive_benchmark": bench_pos,
        "ex_ret_negative_strategy": strat_neg, "ex_ret_negative_benchmark": bench_neg,
        "ex_upside_capture": up, "ex_downside_capture": down,
        "extreme_capture_ratio": ratio,
    }


def capture_breakdown(returns: pd.Series, bench_returns: pd.Series) -> Dict[str, float]:
    """The five rows of the reference workbook's regular "Capture Ratio"
    section (not the extreme one)."""
    mr, mb = _monthly_pair(returns, bench_returns)
    strat_pos, bench_pos, up = _mean_ratio(mr, mb, mb > 0)
    strat_neg, bench_neg, down = _mean_ratio(mr, mb, mb < 0)
    ratio = float(up / down) if np.isfinite(down) and down != 0 else float("nan")
    return {
        "ret_positive_strategy": strat_pos, "ret_positive_benchmark": bench_pos,
        "ret_negative_strategy": strat_neg, "ret_negative_benchmark": bench_neg,
        "upside_capture": up, "downside_capture": down, "capture_ratio": ratio,
    }


def financial_year_label(dt: pd.Timestamp) -> str:
    """Indian FY: April Y to March Y+1 is "FY{Y+1 mod 100}"."""
    y = dt.year + 1 if dt.month >= 4 else dt.year
    return f"FY{y % 100:02d}"


def financial_year_returns(returns: pd.Series) -> "OrderedDict[str, float]":
    """Compounded return per Indian financial year (Apr-Mar), from MONTHLY
    returns -- matches the reference workbook's "Financial Year
    Performance" table exactly (verified against its real numbers)."""
    mr, _ = _monthly_pair(returns, returns)
    labels = mr.index.map(financial_year_label)
    out = OrderedDict()
    for label in sorted(set(labels), key=lambda s: int(s[2:])):
        mask = labels == label
        out[label] = float((1.0 + mr[mask]).prod() - 1.0)
    return out


def calendar_year_returns(returns: pd.Series) -> "OrderedDict[str, float]":
    """Compounded return per calendar year, from MONTHLY returns."""
    mr, _ = _monthly_pair(returns, returns)
    out = OrderedDict()
    for year, g in mr.groupby(mr.index.year):
        out[f"CY{year % 100:02d}"] = float((1.0 + g).prod() - 1.0)
    return out


def calendar_year_max_drawdown(returns: pd.Series) -> "OrderedDict[str, float]":
    """Worst peak-to-trough drawdown WITHIN each calendar year, with the
    running peak reset to the year's first NAV point (not the whole-
    history running peak) -- verified against the reference workbook's
    real "Max Calendar Year Drawdown" table, including a year that shows
    exactly 0.0 because the strategy never dipped below its own Jan-1
    level that year."""
    mr, _ = _monthly_pair(returns, returns)
    out = OrderedDict()
    for year, g in mr.groupby(mr.index.year):
        nav = (1.0 + g).cumprod()
        peak = nav.cummax()
        out[f"CY{year % 100:02d}"] = float((nav / peak - 1.0).min())
    return out


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Returned WITHOUT negation -- a negative number, the raw tail
    percentile itself. Verified against the reference workbook's real
    number, which reports VaR this way (not as a positive loss
    magnitude, despite the glossary's "expected loss" phrasing)."""
    r = returns.dropna()
    return float(np.percentile(r, 100 * (1 - confidence)))


def historical_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Also unnegated, for the same reason as historical_var above."""
    r = returns.dropna()
    cutoff = np.percentile(r, 100 * (1 - confidence))
    tail = r[r <= cutoff]
    return float(tail.mean()) if len(tail) else float("nan")


@dataclass
class Tearsheet:
    annualized_volatility: float
    positive_volatility: float
    negative_volatility: float
    max_drawdown: float
    average_annual_max_drawdown: float
    sharpe_ratio: float
    treynor_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    sterling_ratio: float
    omega_ratio: float
    gain_to_pain_ratio: float
    tail_ratio: float
    alpha_adj_beta: float
    tracking_error: float
    ret_positive_benchmark_days: float
    ret_negative_benchmark_days: float
    upside_capture: float
    downside_capture: float
    capture_ratio: float
    ex_ret_positive_strategy: float
    ex_ret_positive_benchmark: float
    ex_ret_negative_strategy: float
    ex_ret_negative_benchmark: float
    ex_upside_capture: float
    ex_downside_capture: float
    extreme_capture_ratio: float
    skewness: float
    kurtosis: float
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_LABELS = {
    "annualized_volatility": "Annualized Volatility",
    "positive_volatility": "Positive Volatility",
    "negative_volatility": "Negative Volatility",
    "max_drawdown": "Max Drawdown",
    "average_annual_max_drawdown": "Average Annual Max Drawdown",
    "sharpe_ratio": "Sharpe Ratio",
    "treynor_ratio": "Treynor Ratio",
    "sortino_ratio": "Sortino Ratio",
    "calmar_ratio": "Calmar Ratio",
    "sterling_ratio": "Sterling Ratio",
    "omega_ratio": "Omega Ratio",
    "gain_to_pain_ratio": "Gain to Pain Ratio",
    "tail_ratio": "Tail Ratio",
    "alpha_adj_beta": "Alpha (Adj Beta)",
    "tracking_error": "Tracking Error",
    "ret_positive_benchmark_days": "Ret +Ve Nifty 500 (PR proxy for TRI)",
    "ret_negative_benchmark_days": "Ret -Ve Nifty 500 (PR proxy for TRI)",
    "upside_capture": "Upside Capture",
    "downside_capture": "Downside Capture",
    "capture_ratio": "Capture Ratio",
    "ex_ret_positive_strategy": "Ex. Ret +Ve (strategy)",
    "ex_ret_positive_benchmark": "Ex. Ret +Ve Nifty 500 TRI",
    "ex_ret_negative_strategy": "Ex. Ret -Ve (strategy)",
    "ex_ret_negative_benchmark": "Ex. Ret -Ve Nifty 500 TRI",
    "ex_upside_capture": "Ex. Upside Capture",
    "ex_downside_capture": "Ex. Downside Capture",
    "extreme_capture_ratio": "Extreme Capture Ratio",
    "skewness": "Skewness",
    "kurtosis": "Kurtosis",
    "var_95": "95% VaR",
    "var_99": "99% VaR",
    "cvar_95": "95% CVaR",
    "cvar_99": "99% CVaR",
}

_PCT_FIELDS = {"annualized_volatility", "positive_volatility", "negative_volatility",
              "max_drawdown", "average_annual_max_drawdown", "tracking_error",
              "ret_positive_benchmark_days", "ret_negative_benchmark_days",
              "ex_ret_positive_strategy", "ex_ret_positive_benchmark",
              "ex_ret_negative_strategy", "ex_ret_negative_benchmark",
              "var_95", "var_99", "cvar_95", "cvar_99"}
_RATIO_FIELDS = {"upside_capture", "downside_capture", "capture_ratio",
                 "ex_upside_capture", "ex_downside_capture", "extreme_capture_ratio"}


def compute_tearsheet(result, bench_close: pd.Series, rf_daily: Optional[pd.Series] = None,
                      ann: int = ANN) -> Tearsheet:
    """`result` is a BacktestResult (or anything with .value and .returns).
    `bench_close` is the benchmark's raw price series -- returns and an
    aligned value path are derived from it here."""
    r = result.returns
    bench_close = bench_close.reindex(result.value.index)
    bench_returns = bench_close.pct_change()
    bench_value = bench_close / bench_close.dropna().iloc[0]

    cap = capture_breakdown(r, bench_returns)
    excap = extreme_capture_breakdown(r, bench_returns)

    return Tearsheet(
        annualized_volatility=ann_vol(r, ann),
        positive_volatility=positive_volatility(r),
        negative_volatility=negative_volatility(r),
        max_drawdown=max_drawdown(result.value),
        average_annual_max_drawdown=average_annual_max_drawdown(r),
        sharpe_ratio=_sharpe(result.value, r, rf_daily, ann),
        treynor_ratio=treynor_ratio(result.value, r, bench_returns, rf_daily, ann),
        sortino_ratio=sortino_ratio(r, ann=ann, rf_daily=rf_daily),
        calmar_ratio=calmar_ratio(result.value, ann),
        sterling_ratio=sterling_ratio(result.value, ann),
        omega_ratio=omega_ratio(r),
        gain_to_pain_ratio=gain_to_pain_ratio(r),
        tail_ratio=tail_ratio(r),
        alpha_adj_beta=alpha_adj_beta(result.value, r, bench_value, bench_returns, rf_daily, ann),
        tracking_error=tracking_error(r, bench_returns, ann),
        ret_positive_benchmark_days=cap["ret_positive_strategy"],
        ret_negative_benchmark_days=cap["ret_negative_strategy"],
        upside_capture=cap["upside_capture"],
        downside_capture=cap["downside_capture"],
        capture_ratio=cap["capture_ratio"],
        ex_ret_positive_strategy=excap["ex_ret_positive_strategy"],
        ex_ret_positive_benchmark=excap["ex_ret_positive_benchmark"],
        ex_ret_negative_strategy=excap["ex_ret_negative_strategy"],
        ex_ret_negative_benchmark=excap["ex_ret_negative_benchmark"],
        ex_upside_capture=excap["ex_upside_capture"],
        ex_downside_capture=excap["ex_downside_capture"],
        extreme_capture_ratio=excap["extreme_capture_ratio"],
        skewness=float(r.dropna().skew()),
        kurtosis=float(r.dropna().kurtosis()),
        var_95=historical_var(r, 0.95),
        var_99=historical_var(r, 0.99),
        cvar_95=historical_cvar(r, 0.95),
        cvar_99=historical_cvar(r, 0.99),
    )


def render_tearsheet(ts: Tearsheet) -> str:
    lines = []
    for field, label in _LABELS.items():
        v = getattr(ts, field)
        if not np.isfinite(v):
            s = "--"
        elif field in _PCT_FIELDS:
            s = f"{v:.2%}"
        elif field in _RATIO_FIELDS:
            s = f"{v:.1f}"
        else:
            s = f"{v:.2f}"
        lines.append(f"  {label:<38s} {s:>10s}")
    lines.append(f"\n  {TRI_CAVEAT}")
    return "\n".join(lines)
