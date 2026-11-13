# Quant AI Researcher
"""Quant insights (monthly): the tables and chart series of the main Results display, on complete calendar months.

Everything here starts from the two monthly return series of the SE block (ros/metrics/se.py) and uses its conventions:
calendar-month returns, population standard deviation, annualising by month count, the one risk-free rate. Nothing here
is read by a backtest or by Gate B, and no pass mark depends on it.

Conventions that are choices, stated wherever the figure is shown:
  - a return over more than 12 months is annualised as (1 + return)^(12 / months) - 1; 12 months or fewer is not;
  - a market phase is annualised the same way whatever its length, which is what the reference deck's table does;
  - rolling Sharpe = (annualised return of the window - risk-free rate) / (population stdev of the window x sqrt(12)),
    and excess Sharpe = strategy rolling Sharpe - benchmark rolling Sharpe (the operator's assumption);
  - the factor attribution is an ordinary least squares regression WITHOUT an intercept, so it has no alpha term and its
    R-squared is the uncentred one (total sum of squares = sum of y squared). Adjusted R-squared = 1 - (1 - R2) x n / (n - k);
  - quarterly capture uses complete calendar quarters only; a rising quarter is one where the benchmark's return is >= 0.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

NAN = float("nan")
TRAILING = [("1M", 1), ("3M", 3), ("6M", 6), ("1Y", 12), ("3Y", 36), ("5Y", 60), ("10Y", 120)]
ROLL_WINDOWS = (12, 36)
FACTOR_WINDOW = 12
# the indices of the attribution regression, by their names in the NSE index workbook. Three, by the operator's
# instruction of 2026-11-13 to keep only the ones that matter: quality, momentum and size. NIFTY500 Value 50 was dropped
# because its coefficient is not statistically different from zero once the other three are in the regression.
FACTOR_INDICES = ["NIFTY500 QUALITY 50", "NIFTY500 MOMENTUM 50", "NIFTY SMALLCAP 250"]
HIST_WIDTH = 0.02      # the tail-risk distribution chart counts months in bands this wide


def _f(x) -> float | None:
    x = float(x)
    return None if x != x or x in (float("inf"), float("-inf")) else x


def _div(a, b):
    return NAN if b == 0 or b != b or a != a else a / b


def period_return(x: np.ndarray) -> float:
    """Compounded return; annualised by month count when the period is longer than 12 months."""
    tr = float(np.prod(1.0 + x) - 1.0)
    return tr if len(x) <= 12 else float((1.0 + tr) ** (12.0 / len(x)) - 1.0)


def trailing(s: np.ndarray, b: np.ndarray) -> list[dict[str, Any]]:
    out = []
    for label, k in TRAILING + [("Since inception", len(s))]:
        if k > len(s):
            out.append({"label": label, "months": k, "strategy": None, "benchmark": None, "alpha": None, "annualised": k > 12})
            continue
        rs, rb = period_return(s[-k:]), period_return(b[-k:])
        out.append({"label": label, "months": k, "strategy": rs, "benchmark": rb, "alpha": rs - rb, "annualised": k > 12})
    return out


def phases(months: pd.DatetimeIndex, s: np.ndarray, b: np.ndarray, cfg: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per configured phase that overlaps the run, then one "Unclassified" row for the months no phase covers
    after the last phase. first/last are positions in the monthly series (inclusive)."""
    per = months.to_period("M")
    pos = np.arange(len(per))
    rows, covered = [], np.zeros(len(per), dtype=bool)
    # a phase with no last_month is still running: it covers every month from its first on, and is not "clipped"
    spans = [(c, pd.Period(c["first_month"], "M"), pd.Period(c["last_month"], "M") if c.get("last_month") else max(per[-1], pd.Period(c["first_month"], "M"))) for c in cfg]
    spans.append(({"label": "Unclassified", "wyckoff_phase": "Unclassified", "market_term": "not yet named"},
                  (spans[-1][2] + 1) if spans else per[0], per[-1]))
    for c, p0, p1 in spans:
        if p1 < p0:
            continue
        m = np.asarray((per >= p0) & (per <= p1)) & ~covered
        if not m.any():
            continue
        covered |= m
        i, j = int(pos[m][0]), int(pos[m][-1])
        n = j - i + 1
        abs_s, abs_b = float(np.prod(1 + s[i:j + 1]) - 1), float(np.prod(1 + b[i:j + 1]) - 1)
        ann_s, ann_b = float((1 + abs_s) ** (12.0 / n) - 1), float((1 + abs_b) ** (12.0 / n) - 1)
        rows.append({"label": c["label"], "wyckoff_phase": c["wyckoff_phase"], "market_term": c["market_term"], "first": i, "last": j,
                     "first_month": str(per[i]), "last_month": str(per[j]), "months": n,
                     # the phase runs from the month-end before its first month to its last month-end
                     "from_date": str((per[i] - 1).to_timestamp("M").date()), "to_date": str(per[j].to_timestamp("M").date()),
                     "clipped": bool(per[i] > p0 or per[j] < p1) and c["label"] != "Unclassified", "open": not c.get("last_month") and c["label"] != "Unclassified",
                     "strategy_abs": abs_s, "benchmark_abs": abs_b, "strategy_ann": ann_s, "benchmark_ann": ann_b, "alpha": ann_s - ann_b})
    return rows


def rolling(s: np.ndarray, b: np.ndarray, k: int, rf: float) -> dict[str, Any] | None:
    """Rolling k-month windows ending at each month from the k-th. Returns the series and the summary numbers."""
    n = len(s)
    if n < k:
        return None
    out = {"window": k, "annualised": k > 12, "end": list(range(k - 1, n)), "strategy": [], "benchmark": [], "alpha": [],
           "strategy_sharpe": [], "benchmark_sharpe": [], "excess_sharpe": []}
    for e in range(k - 1, n):
        ws, wb = s[e - k + 1:e + 1], b[e - k + 1:e + 1]
        rs, rb = period_return(ws), period_return(wb)
        ss = _div(rs - rf, float(np.std(ws)) * np.sqrt(12.0))
        sb = _div(rb - rf, float(np.std(wb)) * np.sqrt(12.0))
        for key, v in (("strategy", rs), ("benchmark", rb), ("alpha", rs - rb), ("strategy_sharpe", ss), ("benchmark_sharpe", sb), ("excess_sharpe", ss - sb)):
            out[key].append(_f(v))
    a = np.asarray(out["alpha"], dtype=float)
    out["observations"] = len(a)
    out["positive_alpha_share"] = float((a > 0).mean())
    for who in ("strategy", "benchmark"):
        x = np.asarray(out[who], dtype=float)
        out[f"{who}_avg"], out[f"{who}_min"], out[f"{who}_max"] = float(x.mean()), float(x.min()), float(x.max())
    return out


def _ols0(y: np.ndarray, X: np.ndarray) -> dict[str, Any]:
    """Least squares through the origin: coefficients, standard errors and the sums of squares."""
    n, k = X.shape
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    fit = X @ coef
    ss_res, ss_reg, ss_tot = float(((y - fit) ** 2).sum()), float((fit ** 2).sum()), float((y ** 2).sum())
    df = n - k
    mse = ss_res / df if df > 0 else NAN
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * mse) if df > 0 else np.full(k, NAN)
    return {"n": n, "k": k, "df": df, "coef": coef, "se": se, "ss_res": ss_res, "ss_reg": ss_reg, "ss_tot": ss_tot, "mse": mse}


def factor_attribution(s: np.ndarray, factors: dict[str, np.ndarray]) -> dict[str, Any]:
    """Strategy monthly returns regressed on the factor indices' monthly returns, no intercept: the regression
    statistics, the ANOVA table, the coefficient table, and the same coefficients on rolling 12-month windows."""
    names = list(factors)
    X = np.column_stack([np.asarray(factors[k], dtype=float) for k in names])
    r = _ols0(s, X)
    n, k, df = r["n"], r["k"], r["df"]
    r2 = _div(r["ss_reg"], r["ss_tot"])
    f = _div(r["ss_reg"] / k, r["mse"])
    t = r["coef"] / r["se"]
    tcrit = float(stats.t.ppf(0.975, df))
    roll = {nm: [] for nm in names}
    for e in range(FACTOR_WINDOW - 1, n):
        c = _ols0(s[e - FACTOR_WINDOW + 1:e + 1], X[e - FACTOR_WINDOW + 1:e + 1])["coef"]
        for nm, v in zip(names, c):
            roll[nm].append(_f(v))
    return {"factors": names, "window": FACTOR_WINDOW,
            "statistics": {"Multiple R": _f(np.sqrt(r2)), "R Square": _f(r2), "Adjusted R Square": _f(1 - (1 - r2) * n / df),
                           "Standard Error": _f(np.sqrt(r["mse"])), "Observations": n},
            "anova": {"regression": {"df": k, "ss": r["ss_reg"], "ms": r["ss_reg"] / k, "f": _f(f), "significance_f": _f(stats.f.sf(f, k, df))},
                      "residual": {"df": df, "ss": r["ss_res"], "ms": _f(r["mse"])}, "total": {"df": n, "ss": r["ss_tot"]}},
            "coefficients": [{"factor": nm, "coefficient": float(r["coef"][i]), "standard_error": _f(r["se"][i]), "t_stat": _f(t[i]),
                              "p_value": _f(2 * stats.t.sf(abs(t[i]), df)), "lower_95": _f(r["coef"][i] - tcrit * r["se"][i]),
                              "upper_95": _f(r["coef"][i] + tcrit * r["se"][i])} for i, nm in enumerate(names)],
            "rolling": {"end": list(range(FACTOR_WINDOW - 1, n)), "coefficients": roll}}


def drawdown_series(x: np.ndarray) -> list[float]:
    """Month-end wealth over its running peak, minus 1; the peak starts at the first month's own wealth (as in se._dd)."""
    w = np.cumprod(1.0 + x)
    return [float(v) for v in w / np.maximum.accumulate(w) - 1.0]


def tail(x: np.ndarray) -> dict[str, float | None]:
    v95, v99 = float(np.percentile(x, 5)), float(np.percentile(x, 1))
    return {"Mean": float(x.mean()), "Volatility (monthly)": float(np.std(x)), "Skewness": _f(stats.skew(x, bias=False)),
            "Kurtosis": _f(stats.kurtosis(x, fisher=True, bias=False)), "95% VaR": v95, "99% VaR": v99,
            "95% CVaR": float(x[x <= v95].mean()), "99% CVaR": float(x[x <= v99].mean())}


def histogram(s: np.ndarray, b: np.ndarray, width: float = HIST_WIDTH) -> dict[str, list]:
    """Months counted in bands of monthly return [from, to), strategy and benchmark, over one set of bands."""
    k0 = int(np.floor(min(s.min(), b.min()) / width))
    k1 = int(np.floor(max(s.max(), b.max()) / width)) + 1
    lo, hi = [k * width for k in range(k0, k1)], [(k + 1) * width for k in range(k0, k1)]
    count = lambda x: [int(((x >= a) & (x < c)).sum()) for a, c in zip(lo, hi)]   # noqa: E731
    return {"from": lo, "to": hi, "strategy": count(s), "benchmark": count(b)}


def quarterly_capture(quarters: list[dict[str, Any]]) -> dict[str, Any]:
    """Average quarterly return in rising and falling quarters, from the SE block's quarterly table; part quarters out."""
    q = [t for t in quarters if not t["part"]]
    s, b = np.asarray([t["strategy"] for t in q]), np.asarray([t["benchmark"] for t in q])
    up, dn = b >= 0, b < 0
    m = lambda x, k: float(x[k].mean()) if k.any() else NAN
    su, sd, bu, bd = m(s, up), m(s, dn), m(b, up), m(b, dn)
    uc, dc = _div(su, bu), _div(sd, bd)
    return {"quarters": len(q), "rising_quarters": int(up.sum()), "falling_quarters": int(dn.sum()),
            "strategy_rising": _f(su), "strategy_falling": _f(sd), "benchmark_rising": _f(bu), "benchmark_falling": _f(bd),
            "upside_capture": _f(uc), "downside_capture": _f(dc), "capture_ratio": _f(_div(uc, dc)),
            "part_quarters_left_out": [t["label"] for t in quarters if t["part"]]}


KEY_RETURN = [("Total Return", "Total Return", True), ("CAGR", "CAGR", True), ("Avg Month Ret", "Avg Month Ret", True),
              ("Positive Months", "Positive Months", False), ("Negative Months", "Negative Months", False),
              ("Positive Alpha Months", "Positive Monthly Alpha", False), ("Hit Rate", "Hit Rate", False),
              ("Best Month Ret", "Max Month Ret", True), ("Worst Month Ret", "Min Month Ret", True),
              ("Best Month Contribution", "Best Month Contri", False), ("Worst Month Contribution", "Worst Month Contri", False)]
# shown label, SE label (None = derived here), format
RISK = [("Annualized Vol", "Annualized Volatility", "pct"), ("Negative Monthly Vol", "Negative Monthly Vol", "pct"),
        ("Downside Deviation", None, "pct"), ("Largest Monthly Loss", "Min Month Ret", "pct"), ("Max Drawdown", "Max Drawdown", "pct"),
        ("Average Annual Max Drawdown", "Average Annual Max Drawdown", "pct"), ("Sharpe Ratio", "Sharpe Ratio", "num"),
        ("Treynor Ratio", "Treynor Ratio", "num"), ("Sortino Ratio", "Sortino Ratio", "num"), ("Calmar Ratio", "Calmar Ratio", "num"),
        ("Sterling Ratio", "Sterling Ratio", "num"), ("Omega Ratio", "Omega Ratio", "num"), ("Gain to Pain ratio", "Gain to Pain ratio", "num"),
        ("Tail Ratio", "Tail Ratio", "num")]


def block(se_block: dict[str, Any], phase_cfg: list[dict[str, Any]], factors: dict[str, list[float]] | None = None,
          factors_missing: str = "") -> dict[str, Any]:
    """Every table and series of the main display, from the SE block of a run (se.block). `factors` maps a factor index's
    name to its monthly returns on the SE block's months; None (with the reason in `factors_missing`) leaves the
    attribution out."""
    months = pd.DatetimeIndex(se_block["months"])
    s, b = np.asarray(se_block["monthly"]["strategy"], dtype=float), np.asarray(se_block["monthly"]["benchmark"], dtype=float)
    v, rf, fmt = se_block["values"], se_block["inputs"]["risk_free_rate"], {r["label"]: r["format"] for r in se_block["rows"]}
    fy = [{**t, "alpha": t["strategy"] - t["benchmark"]} for t in se_block["tables"]["financial_year"]]
    key = [{"label": lab, "strategy": v[src][0], "benchmark": v[src][1], "alpha": (v[src][0] - v[src][1]) if diff else None, "format": fmt[src]}
           for lab, src, diff in KEY_RETURN]
    risk = []
    for lab, src, f in RISK:
        if src is None:   # Downside Deviation = Negative Monthly Vol x sqrt(12)
            sv, bv = v["Negative Monthly Vol"][0] * np.sqrt(12.0), v["Negative Monthly Vol"][1] * np.sqrt(12.0)
        else:
            sv, bv = v[src]
        risk.append({"label": lab, "strategy": _f(sv), "benchmark": _f(bv), "format": f})
    out = {"title": "Quant insights (monthly)", "months": se_block["months"], "risk_free_rate": rf,
           "financial_year": fy, "annualised_alpha": v["CAGR"][0] - v["CAGR"][1],
           "nav": {"strategy": [100.0] + [float(x) for x in 100 * np.cumprod(1 + s)], "benchmark": [100.0] + [float(x) for x in 100 * np.cumprod(1 + b)]},
           "trailing": trailing(s, b), "key_return": key, "phases": phases(months, s, b, phase_cfg),
           "rolling": {str(k): rolling(s, b, k, rf) for k in ROLL_WINDOWS},
           "drawdown": {"strategy": drawdown_series(s), "benchmark": drawdown_series(b)}, "risk": risk,
           "tail": {"strategy": tail(s), "benchmark": tail(b), "alpha": tail(s - b)},
           "monthly_alpha": [float(x) for x in s - b], "histogram": histogram(s, b),
           "quarterly_capture": quarterly_capture(se_block["tables"]["quarterly"]),
           "factor_attribution": None, "factors_missing": factors_missing, "factor_returns": None}
    if factors:
        out["factor_attribution"] = factor_attribution(s, {k: np.asarray(x, dtype=float) for k, x in factors.items()})
        out["factor_returns"] = {k: [float(x) for x in xs] for k, xs in factors.items()}
    return out
