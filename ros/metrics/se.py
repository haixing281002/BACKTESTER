# Quant AI Researcher
"""SE Return Analytics (monthly): the reference analytics sheet, reproduced exactly, on calendar-month returns.

This block is SEPARATE from the daily headline metrics in ros/metrics/core.py and from every Gate B calculation. It uses
the reference sheet's own conventions, which differ from core's on purpose: monthly returns, population standard
deviation, CAGR = (1 + total return)^(12 / months) - 1, drawdowns on month-end wealth shown as negative numbers, and
three inputs (risk-free rate, Omega threshold a month, drawdown limit). Every figure it produces is labelled "(monthly)".

One spec, SPEC, drives both sides: `py` is the Python definition and `xl` the Excel formula the workbook writes, so the
rule "every Excel formula equals its Python definition" is checked row by row (tests/test_se_metrics.py and the
workbook's "Python vs Excel" sheet).

Where a formula differs from its label or from the textbook definition, it is reproduced as the reference has it:
  - Jensens Alpha (Adj Beta) = CAGR - benchmark CAGR x beta: no risk-free rate and no adjusted beta.
  - Sortino = (CAGR - Rf) / (population stdev of the months <= 0 x sqrt(12)): not a downside deviation.
  - Sterling = CAGR / (|average annual max drawdown| - drawdown limit): no 10-point adjustment unless the limit is set.
  - Information Ratio = (CAGR - benchmark CAGR) / tracking error.
  - Negative Months counts months <= 0; Positive / Negative Monthly Vol are not annualised.
  - A drawdown's peak starts at the FIRST month-end wealth of its range, so a loss in the first month of the series, or
    of a calendar year, is not counted; the average annual drawdown includes part-years.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

DEFAULT_INPUTS = {"drawdown_limit": 0.0, "omega_threshold": 0.01, "risk_free_rate": 0.05}
NAN = float("nan")
PCT, NUM, INT = "pct", "num", "int"


def monthly_returns(daily: pd.Series) -> pd.Series:
    """Calendar-month returns compounded from daily returns, indexed by calendar month-end."""
    r = daily.dropna()
    return (1.0 + r).resample("ME").prod().loc[lambda s: s.index >= r.index[0].to_period("M").to_timestamp("M")] - 1.0


def complete_months(daily: pd.Series, sessions: pd.DatetimeIndex | None = None) -> tuple[pd.Period, pd.Period, dict[str, Any]]:
    """The first and last COMPLETE calendar months of a daily return series, and what is left out (operator, Wave 6).

    `sessions` is the NSE trading calendar. A month is complete when the series has a return for every session in it;
    the first month also counts as complete when the only session without a return is the month's first, because that
    session is the run's starting point (value 100 at its close). The last month is complete only when the calendar shows
    no later session in it; a calendar that stops at the last return cannot show that, so the month is left out.
    Without a calendar nothing can be judged: every month is kept and `calendar` says so."""
    r = daily.dropna()
    d0, d1 = r.index[0], r.index[-1]
    p0, p1 = d0.to_period("M"), d1.to_period("M")
    info: dict[str, Any] = {"first_return": str(d0.date()), "last_return": str(d1.date()), "calendar": "NSE sessions", "left_out": [], "notes": []}
    if sessions is None:
        info["calendar"] = "not available: months not checked"
    else:
        per = sessions.to_period("M")
        before = sessions[(per == p0) & (sessions < d0)]
        if len(before) > 1:
            info["left_out"].append({"month": str(p0), "days": int((r.index.to_period("M") == p0).sum()), "from": str(d0.date()),
                                     "to": str(r.index[r.index.to_period("M") == p0][-1].date()),
                                     "why": f"the run starts inside the month: {len(before)} sessions of it come before the first return"})
            p0 = p0 + 1
        elif len(before) == 1:
            info["notes"].append(f"{d0:%B %Y} is kept: its first session ({before[0]:%d %b %Y}) is the starting point, so it has no return of its own.")
        after = sessions[(per == p1) & (sessions > d1)]
        if len(after) or sessions[-1] <= d1:
            first_day = r.index[r.index.to_period("M") == p1][0]
            why = (f"the run ends inside the month: {len(after)} sessions of it come after the last return" if len(after)
                   else "the trading calendar on file stops at the last return, so the month cannot be shown to be complete")
            info["left_out"].append({"month": str(p1), "days": int((r.index.to_period("M") == p1).sum()), "from": str(first_day.date()),
                                     "to": str(d1.date()), "why": why})
            p1 = p1 - 1
    info.update(first_month=str(p0), last_month=str(p1), left_out_days=sum(x["days"] for x in info["left_out"]))
    return p0, p1, info


def _dd(m: np.ndarray) -> float:
    """MIN(wealth / running peak - 1) on month-end wealth; the peak starts at the first month's own wealth."""
    if not len(m):
        return NAN
    w = np.cumprod(1.0 + m)
    return float((w / np.maximum.accumulate(w) - 1.0).min())


def _std_p(x: np.ndarray) -> float:
    return float(np.std(x, ddof=0)) if len(x) else NAN


def _mean(x: np.ndarray) -> float:
    return float(np.mean(x)) if len(x) else NAN


def _div(a: float, b: float) -> float:
    return float(a / b) if b not in (0, 0.0) and b == b and a == a else NAN


def periods(index: pd.DatetimeIndex) -> dict[str, list[dict[str, Any]]]:
    """Quarter, financial-year (April to March) and calendar-year blocks of a month-end index: label, first and last
    position (inclusive), and whether the block is a part-period. Built from the run's own dates."""
    n = len(index)
    pos = np.arange(n)

    def blocks(key, fmt, full):
        out = []
        for k in pd.unique(key):
            p = pos[key == k]
            out.append({"key": int(k), "label": fmt(int(k)), "first": int(p[0]), "last": int(p[-1]), "part": len(p) < full})
        return out

    q = blocks(np.asarray(index.year * 10 + index.quarter), lambda k: f"{k // 10} Q{k % 10}", 3)
    fy = blocks(np.asarray(index.year + (index.month >= 4)), lambda k: f"FY{k % 100:02d}", 12)
    cy = blocks(np.asarray(index.year), lambda k: f"CY{k % 100:02d}", 12)
    for b in (fy, cy):      # the reference's marks: * the first year ("returns from the start month", whether or not it is a
        if b:               # full year there), ** a last year that is a part-year ("returns till the last month")
            b[0]["label"] += "*"
        if len(b) > 1 and b[-1]["part"]:
            b[-1]["label"] += "**"
    return {"quarterly": q, "financial_year": fy, "calendar_year": cy}


def compute(strategy_monthly: pd.Series, benchmark_monthly: pd.Series, inputs: dict[str, float] | None = None) -> dict[str, Any]:
    """Every SE metric for the strategy and the benchmark, from two monthly return series on one month-end index.
    Returns {"values": {label: (strategy, benchmark-or-None)}, "tables": {...}, "periods": {...}, "inputs": {...}}."""
    inp = {**DEFAULT_INPUTS, **(inputs or {})}
    rf, om, dl = inp["risk_free_rate"], inp["omega_threshold"], inp["drawdown_limit"]
    df = pd.concat([strategy_monthly.rename("s"), benchmark_monthly.rename("b")], axis=1).dropna()
    s, b = df["s"].to_numpy(dtype=float), df["b"].to_numpy(dtype=float)
    per = periods(df.index)
    cy_dd = {w: [_dd(x[p["first"]:p["last"] + 1]) for p in per["calendar_year"]] for w, x in (("s", s), ("b", b))}

    def one(x: np.ndarray, who: str) -> dict[str, float]:
        tr = float(np.prod(1.0 + x) - 1.0)
        cagr = float((1.0 + tr) ** (12.0 / len(x)) - 1.0)
        vol = _std_p(x) * np.sqrt(12.0)
        neg_vol = _std_p(x[x <= 0])
        mdd = _dd(x)
        avg_dd = _mean(np.asarray(cy_dd[who]))
        beta = float(np.cov(x, b, ddof=0)[0, 1] / np.var(b)) if np.var(b) > 0 else NAN
        var95, var99 = float(np.percentile(x, 5)), float(np.percentile(x, 1))
        up, dn = _mean(x[b >= 0]), _mean(x[b < 0])
        eup, edn = _mean(x[b >= 0.05]), _mean(x[b < -0.05])
        return {"Total Return": tr, "CAGR": cagr, "Avg Month Ret": _mean(x), "Positive Months": float((x > 0).sum()),
                "Negative Months": float((x <= 0).sum()), "Max Month Ret": float(x.max()), "Min Month Ret": float(x.min()),
                "Best Month Contri": _div(float(x.max()), tr), "Worst Month Contri": _div(float(x.min()), tr),
                "Annualized Volatility": vol, "Positive Monthly Vol": _std_p(x[x >= 0]), "Negative Monthly Vol": neg_vol,
                "Max Drawdown": mdd, "Average Annual Max Drawdown": avg_dd,
                "Sharpe Ratio": _div(cagr - rf, vol), "Treynor Ratio": _div(cagr - rf, beta),
                "Sortino Ratio": _div(cagr - rf, neg_vol * np.sqrt(12.0)), "Calmar Ratio": _div(cagr, abs(mdd)),
                "Sterling Ratio": _div(cagr, abs(avg_dd) - dl),
                "Omega Ratio": _div(float(np.where(x > om, x - om, 0.0).sum()), abs(float(np.where(x < om, x - om, 0.0).sum()))),
                "Gain to Pain ratio": _div(float(x[x >= 0].sum()), abs(float(x[x < 0].sum()))),
                "Tail Ratio": _div(abs(float(np.percentile(x, 95))), abs(float(np.percentile(x, 5)))),
                "Beta": beta,
                "Ret +Ve": up, "Ret -Ve": dn, "Ex. Ret +Ve": eup, "Ex. Ret -Ve": edn,
                "Skewness": float(stats.skew(x, bias=False)), "Kurtosis": float(stats.kurtosis(x, fisher=True, bias=False)),
                "95% VaR": var95, "99% VaR": var99, "95% CVaR": _mean(x[x <= var95]), "99% CVaR": _mean(x[x <= var99])}

    S, B = one(s, "s"), one(b, "b")
    for d in (S, B):
        d["Upside Capture"] = _div(d["Ret +Ve"], B["Ret +Ve"])
        d["Downside Capture"] = _div(d["Ret -Ve"], B["Ret -Ve"])
        d["Capture Ratio"] = _div(d["Upside Capture"], d["Downside Capture"])
        d["Ex. Upside Capture"] = _div(d["Ex. Ret +Ve"], B["Ex. Ret +Ve"])
        d["Ex. Downside Capture"] = _div(d["Ex. Ret -Ve"], B["Ex. Ret -Ve"])
        d["Extreme Capture Ratio"] = _div(d["Ex. Upside Capture"], d["Ex. Downside Capture"])
    gap = s - b
    pos, neg = float((s > b).sum()), float((s < b).sum())
    te = _std_p(gap) * np.sqrt(12.0)
    alpha = S["CAGR"] - B["CAGR"]
    only_s = {"Alpha": alpha, "Jensens Alpha (Adj Beta)": S["CAGR"] - B["CAGR"] * S["Beta"],
              "Positive Monthly Alpha": pos, "Negative Monthly Alpha": neg, "Tracking Error": te,
              "Information Ratio": _div(alpha, te), "Hit Rate": _div(pos, pos + neg),
              "Max Monthly Alpha": float(gap.max()), "Min Monthly Alpha": float(gap.min())}
    values = {k: (S[k], B[k]) for k in S}
    values.update({k: (v, None) for k, v in only_s.items()})

    def table(blocks):
        return [{"label": p["label"], "part": p["part"], "first": p["first"], "last": p["last"],
                 "strategy": float(np.prod(1.0 + s[p["first"]:p["last"] + 1]) - 1.0),
                 "benchmark": float(np.prod(1.0 + b[p["first"]:p["last"] + 1]) - 1.0)} for p in blocks]

    tables = {"quarterly": table(per["quarterly"]), "financial_year": table(per["financial_year"]),
              "calendar_year": table(per["calendar_year"]),
              "calendar_year_drawdown": [{"label": p["label"], "part": p["part"], "first": p["first"], "last": p["last"],
                                          "strategy": cy_dd["s"][i], "benchmark": cy_dd["b"][i]}
                                         for i, p in enumerate(per["calendar_year"])]}
    return {"values": values, "tables": tables, "inputs": inp, "months": [d.strftime("%Y-%m-%d") for d in df.index],
            "monthly": {"strategy": s.tolist(), "benchmark": b.tolist()}}


# ---------------------------------------------------------------------------------------------------------------- the spec
# (section, label, columns, format, Excel formula). In a formula: {x} is the column's own monthly range, {C} the strategy's
# and {D} the benchmark's (absolute); {c} is the column letter (K strategy, L benchmark); {r[Label]} is the row of another
# metric; {RF}, {OM}, {DL} are the three input cells; {cyd} is the range of this column's calendar-year drawdowns.
# "ARRAY:" marks a formula entered as an array formula, as in the reference. Columns: "SB" both, "S" strategy only.
_LET_DD = ("_xlfn.LET(_xlpm.r,1 + _xlfn._xlws.FILTER({rng}, ISNUMBER({rng})), _xlpm.wealth, _xlfn.SCAN(1, _xlpm.r,_xlfn.LAMBDA(_xlpm.acc,_xlpm.x, "
           "_xlpm.acc * _xlpm.x)),_xlpm.peak,_xlfn.SCAN(0, _xlpm.wealth, _xlfn.LAMBDA(_xlpm.acc,_xlpm.x, MAX(_xlpm.acc, _xlpm.x))),"
           "MIN( _xlpm.wealth / _xlpm.peak - 1))")


def drawdown_formula(rng: str) -> str:
    """The reference's LET / SCAN / LAMBDA drawdown, on one range of monthly returns."""
    return "=" + _LET_DD.format(rng=rng)


SPEC: list[tuple[str, str, str, str, str]] = [
    ("Performance", "Total Return", "SB", PCT, "ARRAY:=PRODUCT({x}+1)-1"),
    ("Performance", "CAGR", "SB", PCT, "=({c}{r[Total Return]}+1)^(12/COUNT({x}))-1"),
    ("Performance", "Avg Month Ret", "SB", PCT, "=AVERAGE({x})"),
    ("Performance", "Positive Months", "SB", INT, '=COUNTIFS({x},">0")'),
    ("Performance", "Negative Months", "SB", INT, '=COUNTIFS({x},"<=0")'),
    ("Performance", "Max Month Ret", "SB", PCT, "=MAX({x})"),
    ("Performance", "Min Month Ret", "SB", PCT, "=MIN({x})"),
    ("Performance", "Best Month Contri", "SB", PCT, "=+{c}{r[Max Month Ret]}/{c}${r[Total Return]}"),
    ("Performance", "Worst Month Contri", "SB", PCT, "=+{c}{r[Min Month Ret]}/{c}${r[Total Return]}"),
    ("Risk Parameters", "Annualized Volatility", "SB", PCT, "=STDEVPA({x})*SQRT(12)"),
    ("Risk Parameters", "Positive Monthly Vol", "SB", PCT, "ARRAY:=STDEVPA(IF({x}>=0,{x}))"),
    ("Risk Parameters", "Negative Monthly Vol", "SB", PCT, "ARRAY:=STDEVPA(IF({x}<=0,{x}))"),
    ("Risk Parameters", "Max Drawdown", "SB", PCT, "ARRAY:" + drawdown_formula("{x}")),
    ("Risk Parameters", "Average Annual Max Drawdown", "SB", PCT, "=AVERAGE({cyd})"),
    ("Risk Parameters", "Sharpe Ratio", "SB", NUM, "=({c}{r[CAGR]}-{RF})/{c}{r[Annualized Volatility]}"),
    ("Risk Parameters", "Treynor Ratio", "SB", NUM, "=({c}{r[CAGR]}-{RF})/{c}{r[Beta]}"),
    ("Risk Parameters", "Sortino Ratio", "SB", NUM, "=({c}{r[CAGR]}-{RF})/({c}{r[Negative Monthly Vol]}*SQRT(12))"),
    ("Risk Parameters", "Calmar Ratio", "SB", NUM, "={c}{r[CAGR]}/ABS({c}{r[Max Drawdown]})"),
    ("Risk Parameters", "Sterling Ratio", "SB", NUM, "={c}{r[CAGR]}/(ABS({c}{r[Average Annual Max Drawdown]})-{DL})"),
    ("Risk Parameters", "Omega Ratio", "SB", NUM, "ARRAY:=SUM(IF({x}>{OM},{x}-{OM},0))/ABS(SUM(IF({x}<{OM},{x}-{OM},0)))"),
    ("Risk Parameters", "Gain to Pain ratio", "SB", NUM, '=SUMIF({x},">="& 0%,{x}) / ABS(SUMIF({x},"<"& 0%,{x}))'),
    ("Risk Parameters", "Tail Ratio", "SB", NUM, "=ABS(_xlfn.PERCENTILE.INC({x}, 0.95)) / ABS(_xlfn.PERCENTILE.INC({x}, 0.05))"),
    ("Performance Vs Index", "Beta", "SB", NUM, "=SLOPE({x},{D})"),
    ("Performance Vs Index", "Alpha", "S", PCT, "=K{r[CAGR]}-$L${r[CAGR]}"),
    ("Performance Vs Index", "Jensens Alpha (Adj Beta)", "S", PCT, "=(K{r[CAGR]}-($L${r[CAGR]}*K{r[Beta]}))"),
    ("Performance Vs Index", "Positive Monthly Alpha", "S", INT, "ARRAY:=COUNT(IF({C}>{D},{C}))"),
    ("Performance Vs Index", "Negative Monthly Alpha", "S", INT, "ARRAY:=COUNT(IF({C}<{D},{C}))"),
    ("Performance Vs Index", "Tracking Error", "S", PCT, "ARRAY:=STDEVPA({C}-{D})*SQRT(12)"),
    ("Performance Vs Index", "Information Ratio", "S", NUM, "=K{r[Alpha]}/K{r[Tracking Error]}"),
    ("Performance Vs Index", "Hit Rate", "S", PCT, "=K{r[Positive Monthly Alpha]}/(SUM(K{r[Positive Monthly Alpha]}:K{r[Negative Monthly Alpha]}))"),
    ("Performance Vs Index", "Max Monthly Alpha", "S", PCT, "ARRAY:=MAX({C}-{D})"),
    ("Performance Vs Index", "Min Monthly Alpha", "S", PCT, "ARRAY:=MIN({C}-{D})"),
    ("Capture Ratio", "Ret +Ve", "SB", PCT, '=AVERAGEIFS({x},{D},">=0")'),
    ("Capture Ratio", "Ret -Ve", "SB", PCT, '=AVERAGEIFS({x},{D},"<0")'),
    ("Capture Ratio", "Upside Capture", "SB", NUM, "={c}{r[Ret +Ve]}/$L${r[Ret +Ve]}"),
    ("Capture Ratio", "Downside Capture", "SB", NUM, "={c}{r[Ret -Ve]}/$L${r[Ret -Ve]}"),
    ("Capture Ratio", "Capture Ratio", "SB", NUM, "={c}{r[Upside Capture]}/{c}{r[Downside Capture]}"),
    ("Extreme Capture Ratio", "Ex. Ret +Ve", "SB", PCT, '=AVERAGEIFS({x},{D},">=5%")'),
    ("Extreme Capture Ratio", "Ex. Ret -Ve", "SB", PCT, '=AVERAGEIFS({x},{D},"<-5%")'),
    ("Extreme Capture Ratio", "Ex. Upside Capture", "SB", NUM, "={c}{r[Ex. Ret +Ve]}/$L${r[Ex. Ret +Ve]}"),
    ("Extreme Capture Ratio", "Ex. Downside Capture", "SB", NUM, "={c}{r[Ex. Ret -Ve]}/$L${r[Ex. Ret -Ve]}"),
    ("Extreme Capture Ratio", "Extreme Capture Ratio", "SB", NUM, "={c}{r[Ex. Upside Capture]}/{c}{r[Ex. Downside Capture]}"),
    ("Tail Risk", "Skewness", "SB", NUM, "=SKEW({x})"),
    ("Tail Risk", "Kurtosis", "SB", NUM, "=KURT({x})"),
    ("Tail Risk", "95% VaR", "SB", PCT, "=_xlfn.PERCENTILE.INC({x},0.05)"),
    ("Tail Risk", "99% VaR", "SB", PCT, "=_xlfn.PERCENTILE.INC({x},0.01)"),
    ("Tail Risk", "95% CVaR", "SB", PCT, '=AVERAGEIFS({x},{x},"<="&{c}{r[95% VaR]})'),
    ("Tail Risk", "99% CVaR", "SB", PCT, '=AVERAGEIFS({x},{x},"<="&{c}{r[99% VaR]})'),
]
SECTIONS = ["Performance", "Risk Parameters", "Performance Vs Index", "Capture Ratio", "Extreme Capture Ratio", "Tail Risk"]
# labels that name the benchmark: the page and workbook show them with the benchmark's name and basis
BENCHMARK_LABELS = {"Ret +Ve", "Ret -Ve", "Ex. Ret +Ve", "Ex. Ret -Ve"}
# rows whose value depends on the benchmark series: labelled with its basis (price index or total return) wherever shown
BENCHMARK_DEPENDENT = {lab for sec, lab, *_ in SPEC if sec in ("Performance Vs Index", "Capture Ratio", "Extreme Capture Ratio")} | {"Treynor Ratio"}

GLOSSARY = [
    ("Annualized Volatility", "Measures how much an investment's returns fluctuate on an annualized basis calculated using standard deviation."),
    ("Positive Volatility", "Measures fluctuations in returns when the investment's returns are positive"),
    ("Negative Volatility", "Measures fluctuations in returns when the investment's returns are negative"),
    ("Sharpe Ratio", "Shows how much returns an investment delivers per unit of risk - higher is better."),
    ("Treynor Ratio", "Measures return per unit of market risk."),
    ("Sortino Ratio", "Evaluates an investment's returns relative to only downside risk - higher means better returns with fewer losses."),
    ("Calmar Ratio", "Measures the risk-adjusted return of a portfolio by comparing its return to the worst peak-to-trough decline (drawdown)"),
    ("Sterling Ratio", "Measures return over average drawdown"),
    ("Omega Ratio", "Measures the likelihood and magnitude of gains vs. losses, based on a chosen threshold."),
    ("Gain to Pain Ratio", "Evaluates reward per unit of risk, focusing purely on the magnitude of profits vs. losses"),
    ("Tail Ratio", "Ratio of 95th to 5th percentile returns. Measures skewness and extremes in the return distribution."),
    ("Alpha (Adj Beta)", "Jensens Alpha, indicates whether an investment performed better after adjusting for market risk."),
    ("Tracking Error", "Measures how closely a portfolio follows its benchmark. (Standard deviation of the Alpha)"),
    ("Ret +Ve benchmark", "Average Monthly Returns when Benchmark Returns is positive"),
    ("Ret -Ve benchmark", "Average Monthly Returns when Benchmark Returns is negative"),
    ("Upside Capture", "Measures how much times an investment returns rises during market upswings - higher the better"),
    ("Downside Capture", "Measures how much times an investment returns declines during market downturns - lower the better"),
    ("Capture Ratio", "Ratio of upside to downside capture - a ratio above 1 means the investment gains more in up markets than it loses in down markets."),
    ("Extreme Capture Ratio", "Assesses portfolio performance specifically during periods of extreme market moves, typically the top and bottom percentile of benchmark returns."),
    ("Skewness", "Indicates asymmetry in returns. Positive skew = rare large gains; negative = rare large losses."),
    ("Kurtosis", "Measures \"tailedness\" of returns. High kurtosis = frequent extreme outcomes."),
    ("95% VaR (Value at Risk)", "Expected loss in the worst 5% of scenarios. Indicates threshold beyond which losses rarely occur."),
    ("99% VaR", "Stricter version of VaR capturing the worst 1% outcomes. Used in high-risk contexts."),
    ("95% CVaR (Conditional VaR)", "Average loss in the worst 5% of cases beyond VaR. Captures tail risk magnitude."),
    ("99% CVaR", "Average loss in the worst 1% of cases beyond VaR. Reflects extreme downside exposure."),
]


def block(strategy_daily: pd.Series, benchmark_daily: pd.Series, benchmark_name: str = "Benchmark", benchmark_basis: str = "price",
          inputs: dict[str, float] | None = None, sessions: pd.DatetimeIndex | None = None) -> dict[str, Any]:
    """The SE block for a run: returns of its COMPLETE calendar months (complete_months) compounded from its daily
    returns, then compute(). The result is what the Results tab shows and what the workbook's "Python vs Excel" sheet
    holds as the Python side."""
    p0, p1, cm = complete_months(strategy_daily, sessions)
    keep = lambda m: m[(m.index.to_period("M") >= p0) & (m.index.to_period("M") <= p1)]   # noqa: E731
    ms, mb = keep(monthly_returns(strategy_daily)), keep(monthly_returns(benchmark_daily))
    out = compute(ms, mb, inputs)
    basis = "price index, no dividends" if benchmark_basis != "total_return" else "total-return index"
    rows = []
    for sec, lab, cols, fmt, _ in SPEC:
        v = out["values"][lab]
        shown = f"{lab} {benchmark_name}" if lab in BENCHMARK_LABELS else lab
        rows.append({"section": sec, "label": lab, "shown": shown, "strategy": v[0], "benchmark": v[1] if cols == "SB" else None,
                     "format": fmt, "depends_on_benchmark": lab in BENCHMARK_DEPENDENT})
    r = strategy_daily.dropna()
    out.update(title="SE Return Analytics (monthly)", rows=rows, sections=SECTIONS, glossary=[list(g) for g in GLOSSARY],
               benchmark_name=benchmark_name, benchmark_basis=benchmark_basis, benchmark_label=f"{benchmark_name} ({basis})",
               first_return=str(r.index[0].date()), last_return=str(r.index[-1].date()), n_months=len(out["months"]),
               complete_months=cm)
    return out
