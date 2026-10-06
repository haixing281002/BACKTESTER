"""Series for the interactive charts, computed once on the server from daily_returns.csv.

The page only draws; every number comes from here. Metric definitions match the workbook's formulas
(CAGR on calendar days / 365.25, volatility = stdev(daily) * sqrt(252), Sharpe = (CAGR - hurdle) / vol).
"""
import math

import numpy as np
import pandas as pd

HURDLE = 0.06
ROLL = 63   # three months of trading days for rolling volatility


def metrics(r: pd.Series, dates: pd.Series, hurdle=HURDLE):
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    # value starts at 100 on the first day; the first return applies from day 2 (matches the workbook)
    v = 100 * (1 + r.where(r.index > 0, 0.0)).cumprod()
    final = float(v.iloc[-1])
    cagr = (final / 100) ** (1 / years) - 1 if years > 0 else float("nan")
    vol = float(r.std(ddof=1) * math.sqrt(252))
    dd = v / v.cummax() - 1
    return {"final": final, "cagr": cagr, "vol": vol,
            "sharpe": (cagr - hurdle) / vol if vol else float("nan"),
            "max_dd": float(-dd.min()), "years": years, "days": int(len(r))}


def _p(x):
    return f"{x * 100:.1f}%"


def observations(df, met, names, hurdle=HURDLE):
    """Positives and negatives measured straight from the daily returns. Each is a plain sentence with its number."""
    s, b = met["strategy"], met["benchmark"]
    bn = names.get("benchmark", "the benchmark")
    pos, neg = [], []
    gap = s["cagr"] - b["cagr"]
    (pos if gap > 0 else neg).append(
        f"Grew {_p(s['cagr'])} a year against {_p(b['cagr'])} for {bn}, {'ahead' if gap > 0 else 'behind'} by {_p(abs(gap))} a year.")
    (pos if s["sharpe"] > 0 else neg).append(
        f"Risk-adjusted return (Sharpe) of {s['sharpe']:.2f} against a {_p(hurdle)} cash hurdle"
        + (", so it beat cash after allowing for its swings." if s["sharpe"] > 0 else ", so it did not beat cash once its swings are counted."))
    if s["vol"] < b["vol"]:
        pos.append(f"Smoother ride: yearly volatility {_p(s['vol'])} against {_p(b['vol'])} for {bn}.")
    else:
        neg.append(f"Bumpier ride: yearly volatility {_p(s['vol'])} against {_p(b['vol'])} for {bn}.")
    if s["max_dd"] < b["max_dd"]:
        pos.append(f"Shallower worst fall: {_p(s['max_dd'])} from peak against {_p(b['max_dd'])} for {bn}.")
    else:
        neg.append(f"Deeper worst fall: {_p(s['max_dd'])} from peak against {_p(b['max_dd'])} for {bn}.")

    mo = df.set_index("date")[["strategy", "benchmark"]].fillna(0).add(1).resample("ME").prod().sub(1)
    beat = float((mo["strategy"] > mo["benchmark"]).mean())
    (pos if beat >= 0.5 else neg).append(f"Beat {bn} in {beat * 100:.0f}% of the {len(mo)} months.")
    corr = float(df["strategy"].corr(df["benchmark"]))
    if corr < 0.5:
        pos.append(f"Moves fairly independently of {bn} (daily correlation {corr:.2f}), which helps diversify.")
    elif corr > 0.85:
        neg.append(f"Moves almost in step with {bn} (daily correlation {corr:.2f}), so it adds little diversification.")

    v = (1 + df["strategy"].fillna(0)).cumprod()
    under = v < v.cummax()
    longest, run = 0, 0
    for u in under:
        run = run + 1 if u else 0
        longest = max(longest, run)
    if longest > 252:
        neg.append(f"Longest stretch below its previous high lasted {longest} trading days (about {longest / 252:.1f} years).")
    yr = df.assign(y=df["date"].dt.year).groupby("y")["strategy"].apply(lambda x: (1 + x.fillna(0)).prod() - 1)
    neg_years = int((yr < 0).sum())
    if len(yr) >= 3:
        (neg if neg_years else pos).append(
            f"{neg_years} losing calendar year{'s' if neg_years != 1 else ''} out of {len(yr)}; best {int(yr.idxmax())} "
            f"({_p(yr.max())}), worst {int(yr.idxmin())} ({_p(yr.min())}).")
    return {"positives": pos, "negatives": neg}


def build(df: pd.DataFrame, names: dict, hurdle=HURDLE):
    df = df.sort_values("date").reset_index(drop=True)
    cols = [c for c in ("strategy", "benchmark", "sleeve") if c in df.columns]
    d = df["date"]
    out = {"dates": d.dt.strftime("%Y-%m-%d").tolist(), "names": {c: names.get(c, c) for c in cols},
           "growth": {}, "drawdown": {}, "rolling_vol": {}, "metrics": {}, "hurdle": hurdle}
    for c in cols:
        r = df[c].fillna(0.0)
        v = 100 * (1 + r.where(r.index > 0, 0.0)).cumprod()
        out["growth"][c] = [round(x, 4) for x in v]
        out["drawdown"][c] = [round(x, 6) for x in (v / v.cummax() - 1)]
        rv = r.rolling(ROLL).std() * math.sqrt(252)
        out["rolling_vol"][c] = [None if np.isnan(x) else round(x, 6) for x in rv]
        out["metrics"][c] = metrics(r, d, hurdle)

    yr = df.assign(year=d.dt.year).groupby("year")
    out["calendar"] = {"years": [str(y) for y in yr.groups.keys()],
                       **{c: [float((1 + g[c].fillna(0)).prod() - 1) for _, g in yr] for c in cols}}

    out["observations"] = observations(df, out["metrics"], out["names"], hurdle)

    m = df.assign(ym=d.dt.to_period("M")).groupby("ym")["strategy"].apply(lambda x: (1 + x.fillna(0)).prod() - 1)
    years = sorted({p.year for p in m.index})
    out["monthly"] = {"years": [str(y) for y in years], "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                      "z": [[(float(m[p]) if (p := pd.Period(year=y, month=k, freq="M")) in m.index else None)
                             for k in range(1, 13)] for y in years]}
    return out
