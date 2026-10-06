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

    m = df.assign(ym=d.dt.to_period("M")).groupby("ym")["strategy"].apply(lambda x: (1 + x.fillna(0)).prod() - 1)
    years = sorted({p.year for p in m.index})
    out["monthly"] = {"years": [str(y) for y in years], "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                      "z": [[(float(m[p]) if (p := pd.Period(year=y, month=k, freq="M")) in m.index else None)
                             for k in range(1, 13)] for y in years]}
    return out
