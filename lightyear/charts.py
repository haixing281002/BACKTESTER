# Quant AI Researcher
"""Series for the interactive charts, computed once on the server from daily_returns.csv.

The page only draws; every number comes from here. Definitions match the workbook's formulas:
  - value starts at 100 at the close BEFORE the first return (start = the NSE session before the first date, from the
    NSE index workbook's own dates; never weekday logic), so every daily return counts, including the first;
  - every metric comes from ros.metrics.core. Sharpe and Sortino are over the Sharpe hurdle in config/fund.yaml (a
    yardstick); beta is over the cash rate on the run's card, which is also what idle cash earns.
"""
import functools
import math
import os

import numpy as np
import pandas as pd

from ros import config
from ros.metrics import core, qi, se

ROLL = 63   # three months of trading days for rolling volatility


@functools.lru_cache(maxsize=4)
def _sessions(path: str, mtime: float) -> pd.DatetimeIndex:
    from ros.data.loaders import load_nse_factor_workbook
    frame, _ = load_nse_factor_workbook(path)
    return pd.DatetimeIndex(sorted(pd.to_datetime(frame.index).unique()))


def nse_sessions() -> tuple[pd.DatetimeIndex | None, str]:
    """The NSE trading calendar as the index workbook saw it, and where it came from."""
    from ros.data import sources
    p = sources.NSE_INDEX_WORKBOOK
    if p and os.path.isfile(p):
        return _sessions(p, os.path.getmtime(p)), "NSE index workbook"
    return None, "none: no NSE index workbook on this machine"


def start_date(dates: pd.Series) -> pd.Timestamp:
    """The NSE session before the first return. Without the workbook (a data-less test machine) the previous calendar
    day is used and calendar_source says so; a real run always has the workbook."""
    first = pd.Timestamp(dates.iloc[0])
    sessions, _ = nse_sessions()
    if sessions is not None:
        before = sessions[sessions < first]
        if len(before):
            return before[-1]
    return first - pd.Timedelta(days=1)


def value_path(r: pd.Series) -> np.ndarray:
    """100 at the start, then compounded by every return."""
    return 100 * np.r_[1.0, np.cumprod(1 + r.fillna(0.0).to_numpy())]


def metrics(r: pd.Series, dates: pd.Series, cash_rate=None, bench: pd.Series = None, sharpe_hurdle=None):
    """The core block for one series. Sharpe and Sortino are over `sharpe_hurdle` (a yearly rate; config's when None).
    With no cash rate from the card, beta stays blank."""
    t0 = start_date(dates)
    x = pd.Series(r.to_numpy(dtype=float), index=pd.DatetimeIndex(dates)).fillna(0.0)
    b = None if bench is None else pd.Series(bench.to_numpy(dtype=float), index=pd.DatetimeIndex(dates)).fillna(0.0)
    cash = core.daily_cash(cash_rate) if cash_rate is not None else None
    out = core.summary(x, cash, b, start=t0, hurdle_annual=_hurdle(sharpe_hurdle))
    out["years"] = core.years_between(t0, x.index[-1])
    if cash_rate is None and b is not None:
        out["beta"] = float("nan")
    return out


def _filter_betas(strat, bench, cash, index_filter):
    """Beta on the days the card's index filter was open and on the days it was shut. The filter's state on day t is read
    at the PREVIOUS session's close (index close above its N-day average), so nothing from day t is used. None when the
    card has no index filter; a reason when the index series is not on this machine."""
    if not index_filter or not index_filter.get("days") or not index_filter.get("series"):
        return None
    try:
        from ros.data.loaders import load_nse_workbook_combined
        from ros.data.sources import NSE_INDEX_WORKBOOK
        levels, _ = load_nse_workbook_combined(NSE_INDEX_WORKBOOK)
        px = levels[index_filter["series"]].dropna()
    except Exception as e:  # noqa: BLE001 -- information only; the reason is shown on the page
        return {"status": "not computed", "why": f"{type(e).__name__}: {e}"[:200]}
    n = int(index_filter["days"])
    is_open = (px > px.rolling(n).mean()).shift(1).reindex(strat.index)
    known = is_open.notna()
    o = core.beta_on(strat, bench, (is_open == True) & known, cash)      # noqa: E712
    s = core.beta_on(strat, bench, (is_open == False) & known, cash)     # noqa: E712
    return {"status": "computed", "series": index_filter["series"], "days": n, "open": o, "shut": s,
            "rule": f"open on a day when {index_filter['series']} closed above its {n}-day average at the previous session"}


def factor_monthly(dates: pd.DatetimeIndex, months: list[str]):
    """Monthly returns of the four attribution indices on the SE block's months, each compounded from the index's daily
    returns on the run's own dates, so a month covers exactly the days the strategy's month covers. Returns
    (returns by index name, "") or (None, the reason)."""
    try:
        from ros.data.loaders import load_nse_workbook_combined
        from ros.data.sources import NSE_INDEX_WORKBOOK
        levels, _ = load_nse_workbook_combined(NSE_INDEX_WORKBOOK)
    except Exception as e:  # noqa: BLE001 -- the reason is shown on the page; the attribution is then left out
        return None, f"index workbook not read: {type(e).__name__}: {e}"[:200]
    want = pd.DatetimeIndex(months).to_period("M")
    out = {}
    for nm in qi.FACTOR_INDICES:
        if nm not in levels.columns:
            return None, f"{nm} is not in the index workbook"
        r = levels[nm].dropna().pct_change().reindex(dates)
        r = r[(r.index.to_period("M") >= want[0]) & (r.index.to_period("M") <= want[-1])]
        if r.isna().any():
            return None, f"{nm} has no level on {int(r.isna().sum())} of the run's days, first {r[r.isna()].index[0].date()}"
        m = (1.0 + r).resample("ME").prod() - 1.0
        out[nm] = [float(x) for x in m.to_numpy()]
        if len(out[nm]) != len(months):
            return None, f"{nm}: {len(out[nm])} months against the run's {len(months)}"
    return out, ""


def _hurdle(sharpe_hurdle) -> float:
    return config.hurdle_annual() if sharpe_hurdle is None else float(sharpe_hurdle)


def _p(x):
    return f"{x * 100:.1f}%"


def observations(df, met, names, sharpe_hurdle=None):
    """Positives and negatives measured straight from the daily returns. Each is a plain sentence with its number."""
    s, b = met["strategy"], met["benchmark"]
    bn = names.get("benchmark", "the benchmark")
    pos, neg = [], []
    gap = s["cagr"] - b["cagr"]
    (pos if gap > 0 else neg).append(
        f"Grew {_p(s['cagr'])} a year against {_p(b['cagr'])} for {bn}, {'ahead' if gap > 0 else 'behind'} by {_p(abs(gap))} a year.")
    if not (math.isnan(s["sharpe"]) or math.isnan(b["sharpe"])):
        (pos if s["sharpe"] > b["sharpe"] else neg).append(
            f"Return per unit of risk (Sharpe, risk-free rate {_hurdle(sharpe_hurdle):.0%}) of {s['sharpe']:.2f} against {b['sharpe']:.2f} for {bn}"
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
    if longest > core.ANN:
        neg.append(f"Longest stretch below its previous high lasted {longest} trading days (about {longest / core.ANN:.1f} years).")
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
          card_bp=None, publication_date=None, cash_source=None, sharpe_hurdle=None, benchmark_basis="price", index_filter=None):
    df = df.sort_values("date").reset_index(drop=True)
    cols = [c for c in ("strategy", "benchmark", "sleeve") if c in df.columns]
    d = df["date"]
    t0 = start_date(d)
    dates = [t0.strftime("%Y-%m-%d")] + d.dt.strftime("%Y-%m-%d").tolist()
    out = {"dates": dates, "start": dates[0], "calendar_source": nse_sessions()[1],
           "names": {c: names.get(c, c) for c in cols},
           "growth": {}, "drawdown": {}, "rolling_vol": {}, "metrics": {}, "cash_rate": cash_rate, "cash_source": cash_source,
           "sharpe_hurdle": (sharpe_hurdle := _hurdle(sharpe_hurdle)),
           "trading_days_per_year": core.ANN,    # config/fund.yaml; the page and the workbooks print and use this one
           # the headline Sharpe and Sortino are geometric, (CAGR - hurdle) / risk; yearly and Gate B figures are arithmetic
           "sharpe_basis": "geometric"}
    for c in cols:
        r = df[c].fillna(0.0)
        v = value_path(r)
        out["growth"][c] = [round(float(x), 4) for x in v]
        out["drawdown"][c] = [round(float(x), 6) for x in (v / np.maximum.accumulate(v) - 1)]
        rv = core.rolling_vol(r, ROLL)
        out["rolling_vol"][c] = [None] + [None if np.isnan(x) else round(float(x), 6) for x in rv]
        out["metrics"][c] = metrics(r, d, cash_rate, df["benchmark"] if c == "strategy" else None, sharpe_hurdle)

    yr = df.assign(year=d.dt.year).groupby("year")
    out["calendar"] = {"years": [str(y) for y in yr.groups.keys()],
                       **{c: [float((1 + g[c].fillna(0)).prod() - 1) for _, g in yr] for c in cols}}
    hd = core.daily_cash(sharpe_hurdle)
    out["calendar"]["sharpe_arithmetic"] = {c: [float(v) for v in core.calendar_year_sharpe(
        pd.Series(df[c].fillna(0.0).to_numpy(dtype=float), index=pd.DatetimeIndex(d)), hd)] for c in cols}
    out["calendar"]["sortino_arithmetic"] = {c: [float(v) for v in core.calendar_year_sortino(
        pd.Series(df[c].fillna(0.0).to_numpy(dtype=float), index=pd.DatetimeIndex(d)), hd)] for c in cols}
    out["observations"] = observations(df, out["metrics"], out["names"], sharpe_hurdle)

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
            out["comparators"]["metrics"][c] = metrics(r.fillna(0.0), d, cash_rate, sharpe_hurdle=sharpe_hurdle)

    idx = pd.DatetimeIndex(d)
    strat = pd.Series(df["strategy"].fillna(0.0).to_numpy(dtype=float), index=idx)
    bench = pd.Series(df["benchmark"].fillna(0.0).to_numpy(dtype=float), index=idx)
    cash = core.daily_cash(cash_rate) if cash_rate is not None else None
    # daily_returns.csv is at the card's cost. Gross is those trades with that cost put back. At 0bp the two are one number.
    out["card_bp"] = card_bp
    out["annual_turnover"] = core.annual_turnover(turnover) if turnover is not None else None
    out["gross"] = None
    # Barra reconciliation mode (core.site_block): this book's daily returns on the site's conventions, kept for the tie-out. Not displayed.
    out["daily_site"] = {"days_per_year": core.SITE_ANN, "strategy": core.site_block(strat), "benchmark": core.site_block(bench), "gross": None}
    if turnover is not None and card_bp:
        gross = core.returns_at_cost(strat, turnover, 0.0, card_bp)
        out["gross"] = metrics(pd.Series(gross.to_numpy()), d, cash_rate, df["benchmark"], sharpe_hurdle)
        out["daily_site"]["gross"] = core.site_block(pd.Series(gross.to_numpy(), index=idx))
    out["post_publication"] = core.post_publication(strat, bench, cash, publication_date, hurdle=core.daily_cash(sharpe_hurdle))
    # SE Return Analytics (monthly): the reference sheet's own formulas on calendar-month returns. Separate from every
    # daily figure above and from Gate B. Its risk-free rate is the same one config setting.
    out["se"] = se.block(strat, bench, out["names"].get("benchmark", "Benchmark"), benchmark_basis,
                         {"risk_free_rate": sharpe_hurdle}, sessions=nse_sessions()[0])
    # Quant insights (monthly): the main display, built from the SE block's complete months. Not read by Gate B.
    fac, why = factor_monthly(idx, out["se"]["months"])
    out["qi"] = qi.block(out["se"], config.market_phases(), fac, why)
    up, dn = core.beta_on(strat, bench, bench > 0, cash), core.beta_on(strat, bench, bench < 0, cash)
    out["beta_split"] = {"up_market": up, "down_market": dn, "index_filter": _filter_betas(strat, bench, cash, index_filter)}
    wd = core.worst_days(strat)
    out["worst_days"] = [{"date": str(k.date()), "return": float(v)} for k, v in wd.items()]
    return _blank_nans(out)
