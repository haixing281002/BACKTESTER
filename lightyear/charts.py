# Quant AI Researcher by Harshil Pahuja
"""Series for the interactive charts, computed once on the server from daily_returns.csv.

The page only draws; every number comes from here. Definitions match the workbook's formulas:
  - value starts at 100 at the close BEFORE the first return (start = first date minus one business day),
    so every daily return counts, including the first;
  - every metric comes from ros.metrics.core, and Sharpe is over the cash rate on the run's card.
"""
import math

import numpy as np
import pandas as pd

from ros.metrics import core

ROLL = 63   # three months of trading days for rolling volatility


def start_date(dates: pd.Series) -> pd.Timestamp:
    return pd.Timestamp(dates.iloc[0]) - pd.offsets.BDay(1)


def value_path(r: pd.Series) -> np.ndarray:
    """100 at the start, then compounded by every return."""
    return 100 * np.r_[1.0, np.cumprod(1 + r.fillna(0.0).to_numpy())]


def metrics(r: pd.Series, dates: pd.Series, cash_rate=None, bench: pd.Series = None):
    """The core block for one series. With no cash rate on the card, the two ratios that need one stay blank."""
    t0 = start_date(dates)
    x = pd.Series(r.to_numpy(dtype=float), index=pd.DatetimeIndex(dates)).fillna(0.0)
    b = None if bench is None else pd.Series(bench.to_numpy(dtype=float), index=pd.DatetimeIndex(dates)).fillna(0.0)
    cash = core.daily_cash(cash_rate) if cash_rate is not None else None
    out = core.summary(x, cash, b, start=t0)
    out["years"] = core.years_between(t0, x.index[-1])
    if cash_rate is None:
        out["sharpe"] = out["sortino"] = float("nan")
        if b is not None:
            out["beta"] = float("nan")
    return out


def _p(x):
    return f"{x * 100:.1f}%"


def observations(df, met, names):
    """Positives and negatives measured straight from the daily returns. Each is a plain sentence with its number."""
    s, b = met["strategy"], met["benchmark"]
    bn = names.get("benchmark", "the benchmark")
    pos, neg = [], []
    gap = s["cagr"] - b["cagr"]
    (pos if gap > 0 else neg).append(
        f"Grew {_p(s['cagr'])} a year against {_p(b['cagr'])} for {bn}, {'ahead' if gap > 0 else 'behind'} by {_p(abs(gap))} a year.")
    if not (math.isnan(s["sharpe"]) or math.isnan(b["sharpe"])):
        (pos if s["sharpe"] > b["sharpe"] else neg).append(
            f"Return per unit of risk (Sharpe) of {s['sharpe']:.2f} against {b['sharpe']:.2f} for {bn}"
            + (": better risk-adjusted." if s["sharpe"] > b["sharpe"] else ": the extra return came with even more extra risk."))
    if s["vol"] < b["vol"]:
        pos.append(f"Smoother ride: yearly volatility {_p(s['vol'])} against {_p(b['vol'])} for {bn}.")
    else:
        neg.append(f"Bumpier ride: yearly volatility {_p(s['vol'])} against {_p(b['vol'])} for {bn}"
                   f" ({s['vol'] / b['vol']:.1f} times as volatile).")
    if s["max_dd"] < b["max_dd"]:
        pos.append(f"Shallower worst fall: {_p(s['max_dd'])} from peak against {_p(b['max_dd'])} for {bn}.")
    else:
        neg.append(f"Deeper worst fall: {_p(s['max_dd'])} from peak against {_p(b['max_dd'])} for {bn}.")

    x = df.set_index("date")
    mo = x[["strategy", "benchmark"]].fillna(0).add(1).resample("ME").prod().sub(1)
    beat = float((mo["strategy"] > mo["benchmark"]).mean())
    (pos if beat >= 0.5 else neg).append(f"Beat {bn} in {beat * 100:.0f}% of the {len(mo)} months.")
    corr = float(df["strategy"].corr(df["benchmark"]))
    if corr < 0.5:
        pos.append(f"Moves fairly independently of {bn} (daily correlation {corr:.2f}), which helps diversify.")
    elif corr > 0.85:
        neg.append(f"Moves almost in step with {bn} (daily correlation {corr:.2f}), so it adds little diversification.")

    worst = x["strategy"].nsmallest(1)
    if len(worst) and worst.iloc[0] < -0.08:
        neg.append(f"Single-day shock: lost {_p(-worst.iloc[0])} on {worst.index[0].date()}, a sign of concentrated positions.")
    lr = np.log1p(x["strategy"].fillna(0))
    if lr.sum() > 0:
        top = float(lr.nlargest(10).sum() / lr.sum())
        if top > 0.6:
            neg.append(f"Fragile: the best 10 days out of {len(lr)} account for {top * 100:.0f}% of the whole gain.")

    v = value_path(x["strategy"])
    under = v < np.maximum.accumulate(v)
    longest, run = 0, 0
    for u in under:
        run = run + 1 if u else 0
        longest = max(longest, run)
    if longest > 252:
        neg.append(f"Longest stretch below its previous high lasted {longest} trading days (about {longest / 252:.1f} years).")
    yr = df.assign(y=df["date"].dt.year).groupby("y")["strategy"].apply(lambda s_: (1 + s_.fillna(0)).prod() - 1)
    neg_years = int((yr < 0).sum())
    if len(yr) >= 3:
        (neg if neg_years else pos).append(
            f"{neg_years} losing calendar year{'s' if neg_years != 1 else ''} out of {len(yr)} (first and last are part-years); "
            f"best {int(yr.idxmax())} ({_p(yr.max())}), worst {int(yr.idxmin())} ({_p(yr.min())}).")
    return {"positives": pos, "negatives": neg}


def _blank_nans(x):
    """A metric that cannot be computed is null on the page, never a NaN the JSON response cannot carry."""
    if isinstance(x, dict):
        return {k: _blank_nans(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_blank_nans(v) for v in x]
    return None if isinstance(x, float) and math.isnan(x) else x


def build(df: pd.DataFrame, names: dict, cash_rate=None, comparators: pd.DataFrame = None, turnover: pd.Series = None,
          house_bp=None, charged_bp=0.0, publication_date=None, cash_source=None):
    df = df.sort_values("date").reset_index(drop=True)
    cols = [c for c in ("strategy", "benchmark", "sleeve") if c in df.columns]
    d = df["date"]
    t0 = start_date(d)
    dates = [t0.strftime("%Y-%m-%d")] + d.dt.strftime("%Y-%m-%d").tolist()
    out = {"dates": dates, "start": dates[0], "names": {c: names.get(c, c) for c in cols},
           "growth": {}, "drawdown": {}, "rolling_vol": {}, "metrics": {}, "cash_rate": cash_rate, "cash_source": cash_source}
    for c in cols:
        r = df[c].fillna(0.0)
        v = value_path(r)
        out["growth"][c] = [round(float(x), 4) for x in v]
        out["drawdown"][c] = [round(float(x), 6) for x in (v / np.maximum.accumulate(v) - 1)]
        rv = core.rolling_vol(r, ROLL)
        out["rolling_vol"][c] = [None] + [None if np.isnan(x) else round(float(x), 6) for x in rv]
        out["metrics"][c] = metrics(r, d, cash_rate, df["benchmark"] if c == "strategy" else None)

    yr = df.assign(year=d.dt.year).groupby("year")
    out["calendar"] = {"years": [str(y) for y in yr.groups.keys()],
                       **{c: [float((1 + g[c].fillna(0)).prod() - 1) for _, g in yr] for c in cols}}
    out["observations"] = observations(df, out["metrics"], out["names"])

    m = df.assign(ym=d.dt.to_period("M")).groupby("ym")["strategy"].apply(lambda x: (1 + x.fillna(0)).prod() - 1)
    years = sorted({p.year for p in m.index})
    out["monthly"] = {"years": [str(y) for y in years], "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                      "z": [[(float(m[p]) if (p := pd.Period(year=y, month=k, freq="M")) in m.index else None)
                             for k in range(1, 13)] for y in years]}

    if comparators is not None and len(comparators.columns) > 1:
        cmp = comparators.set_index("date").reindex(d.values)
        out["comparators"] = {"names": [], "growth": {}, "metrics": {}}
        for c in cmp.columns:
            r = cmp[c].astype(float)
            out["comparators"]["names"].append(c)
            out["comparators"]["growth"][c] = [round(float(x), 4) for x in value_path(r)]
            out["comparators"]["metrics"][c] = metrics(r.fillna(0.0), d, cash_rate)

    idx = pd.DatetimeIndex(d)
    strat = pd.Series(df["strategy"].fillna(0.0).to_numpy(dtype=float), index=idx)
    bench = pd.Series(df["benchmark"].fillna(0.0).to_numpy(dtype=float), index=idx)
    cash = core.daily_cash(cash_rate) if cash_rate is not None else None
    if turnover is not None and house_bp is not None:
        net = core.net_returns(strat, turnover, house_bp, charged_bp)
        out["net"] = {"house_bp": house_bp, "charged_bp": charged_bp, "annual_turnover": core.annual_turnover(turnover),
                      "metrics": metrics(pd.Series(net.to_numpy()), d, cash_rate, df["benchmark"])}
    else:
        out["net"] = None
    out["post_publication"] = core.post_publication(strat, bench, cash, publication_date) if cash is not None else None
    wd = core.worst_days(strat)
    out["worst_days"] = [{"date": str(k.date()), "return": float(v)} for k, v in wd.items()]
    return _blank_nans(out)
