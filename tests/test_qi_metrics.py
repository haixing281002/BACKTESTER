# Quant AI Researcher
"""Quant insights (monthly), ros/metrics/qi.py, and the complete-months rule of ros/metrics/se.py. Synthetic data only."""
import numpy as np
import pandas as pd
import pytest

from ros import config
from ros.metrics import qi, se


def _cal(start="2019-12-25", end="2023-02-10"):
    return pd.bdate_range(start, end)   # a stand-in trading calendar for the tests: the code only ever reads the dates it is given


def _daily(cal, first, last, seed=7):
    idx = cal[(cal >= first) & (cal <= last)]
    rng = np.random.default_rng(seed)
    b = pd.Series(rng.normal(0.0005, 0.01, len(idx)), index=idx)
    return b * 0.8 + pd.Series(rng.normal(0.0003, 0.006, len(idx)), index=idx), b


def test_a_run_that_starts_and_ends_inside_a_month_loses_both_months_and_says_how_many_days():
    cal = _cal()
    s, b = _daily(cal, "2020-01-15", "2022-09-16")
    blk = se.block(s, b, sessions=cal)
    cm = blk["complete_months"]
    assert (cm["first_month"], cm["last_month"]) == ("2020-02", "2022-08") and blk["months"][0] == "2020-02-29" and blk["months"][-1] == "2022-08-31"
    assert [x["month"] for x in cm["left_out"]] == ["2020-01", "2022-09"]
    assert cm["left_out_days"] == int(((s.index < "2020-02-01") | (s.index > "2022-08-31")).sum())


def test_the_first_month_is_kept_when_only_its_first_session_is_the_starting_point():
    cal = _cal()
    s, b = _daily(cal, "2020-01-02", "2022-08-31")      # 1 Jan 2020 is a session in this calendar and is the starting point
    cm = se.block(s, b, sessions=cal)["complete_months"]
    assert cm["first_month"] == "2020-01" and cm["left_out"] == [] and "starting point" in cm["notes"][0]


def test_a_calendar_that_stops_at_the_last_return_cannot_show_the_month_is_complete():
    cal = _cal(end="2022-08-31")
    s, b = _daily(cal, "2020-01-01", "2022-08-31")
    cm = se.block(s, b, sessions=cal)["complete_months"]
    assert cm["last_month"] == "2022-07" and "cannot be shown" in cm["left_out"][0]["why"]
    assert se.block(s, b)["complete_months"]["calendar"].startswith("not available") and se.block(s, b)["n_months"] == 32


def _block(n=60, seed=3):
    rng = np.random.default_rng(seed)
    months = pd.date_range("2014-01-31", periods=n, freq="ME")
    b = rng.normal(0.01, 0.045, n)
    s = 0.9 * b + rng.normal(0.004, 0.02, n)
    out = se.compute(pd.Series(s, index=months), pd.Series(b, index=months))
    out["rows"] = [{"label": lab, "format": fmt} for _, lab, _, fmt, _ in se.SPEC]
    return out, months, s, b


def test_trailing_returns_annualise_only_beyond_twelve_months():
    blk, _, s, b = _block()
    t = {r["label"]: r for r in qi.block(blk, [])["trailing"]}
    assert t["1Y"]["strategy"] == pytest.approx(np.prod(1 + s[-12:]) - 1) and not t["1Y"]["annualised"]
    assert t["3Y"]["benchmark"] == pytest.approx(np.prod(1 + b[-36:]) ** (12 / 36) - 1) and t["3Y"]["annualised"]
    assert t["10Y"]["strategy"] is None
    assert t["Since inception"]["alpha"] == pytest.approx(blk["values"]["CAGR"][0] - blk["values"]["CAGR"][1])


def test_phases_are_clipped_to_the_run_annualised_by_month_count_and_the_rest_is_unclassified():
    blk, months, s, b = _block()
    cfg = [{"label": "A", "first_month": "2013-04", "last_month": "2015-02", "wyckoff_phase": "Mark-Up", "market_term": "bull"},
           {"label": "B", "first_month": "2015-03", "last_month": "2016-02", "wyckoff_phase": "Mark-Down", "market_term": "fall"}]
    a, bb, u = qi.block(blk, cfg)["phases"]
    assert (a["months"], a["clipped"], bb["months"], bb["clipped"]) == (14, True, 12, False)
    assert a["benchmark_ann"] == pytest.approx((np.prod(1 + b[:14])) ** (12 / 14) - 1)
    assert bb["alpha"] == pytest.approx((np.prod(1 + s[14:26]) - 1) - (np.prod(1 + b[14:26]) - 1))
    assert u["label"] == "Unclassified" and u["first_month"] == "2016-03" and u["months"] == 60 - 26
    assert sum(r["months"] for r in (a, bb, u)) == 60


def test_the_nine_configured_phases_are_contiguous_whole_months():
    cfg = config.market_phases()
    assert len(cfg) == 9 and cfg[0]["first_month"] == "2013-04" and cfg[-1]["last_month"] == "2025-06"
    for x, y in zip(cfg, cfg[1:]):
        assert pd.Period(y["first_month"], "M") == pd.Period(x["last_month"], "M") + 1
    assert [(pd.Period(c["last_month"], "M") - pd.Period(c["first_month"], "M")).n + 1 for c in cfg] == [23, 12, 23, 24, 2, 19, 8, 27, 9]


def test_rolling_alpha_and_excess_sharpe_follow_the_stated_definition():
    blk, _, s, b = _block()
    r = qi.block(blk, [])["rolling"]
    w = slice(60 - 36, 60)
    rs, rb = np.prod(1 + s[w]) ** (1 / 3) - 1, np.prod(1 + b[w]) ** (1 / 3) - 1
    assert r["36"]["alpha"][-1] == pytest.approx(rs - rb)
    assert r["36"]["excess_sharpe"][-1] == pytest.approx((rs - 0.05) / (np.std(s[w]) * 12 ** 0.5) - (rb - 0.05) / (np.std(b[w]) * 12 ** 0.5))
    assert r["12"]["observations"] == 49 and r["12"]["strategy"][0] == pytest.approx(np.prod(1 + s[:12]) - 1)
    assert r["12"]["positive_alpha_share"] == pytest.approx(np.mean(np.asarray(r["12"]["alpha"]) > 0))


def test_factor_attribution_is_least_squares_through_the_origin():
    blk, _, s, _b = _block(n=72)
    rng = np.random.default_rng(11)
    X = rng.normal(0.01, 0.05, (72, 4))
    fa = qi.block(blk, [], {f"F{i}": X[:, i] for i in range(4)})["factor_attribution"]
    coef = np.linalg.solve(X.T @ X, X.T @ s)
    assert [c["coefficient"] for c in fa["coefficients"]] == pytest.approx(coef)
    res = s - X @ coef
    assert fa["anova"]["total"]["ss"] == pytest.approx(float(s @ s)) and fa["anova"]["total"]["df"] == 72
    assert fa["anova"]["regression"]["ss"] + fa["anova"]["residual"]["ss"] == pytest.approx(float(s @ s))
    assert fa["statistics"]["R Square"] == pytest.approx(1 - float(res @ res) / float(s @ s))
    assert fa["statistics"]["Standard Error"] == pytest.approx((float(res @ res) / 68) ** 0.5)
    c0 = fa["coefficients"][0]
    assert c0["t_stat"] == pytest.approx(c0["coefficient"] / c0["standard_error"]) and c0["lower_95"] < c0["coefficient"] < c0["upper_95"]
    w = slice(72 - 12, 72)
    assert [fa["rolling"]["coefficients"][f"F{i}"][-1] for i in range(4)] == pytest.approx(np.linalg.lstsq(X[w], s[w], rcond=None)[0])
    exact = qi.factor_attribution(X @ np.array([0.5, 0.2, -0.1, 0.3]), {f"F{i}": X[:, i] for i in range(4)})
    assert [c["coefficient"] for c in exact["coefficients"]] == pytest.approx([0.5, 0.2, -0.1, 0.3]) and exact["statistics"]["R Square"] == pytest.approx(1.0)


def test_risk_table_tail_risk_and_quarterly_capture():
    blk, _, s, b = _block()
    q = qi.block(blk, [])
    risk = {r["label"]: r for r in q["risk"]}
    assert risk["Downside Deviation"]["strategy"] == pytest.approx(blk["values"]["Negative Monthly Vol"][0] * 12 ** 0.5)
    assert risk["Largest Monthly Loss"]["benchmark"] == pytest.approx(b.min())
    a = s - b
    assert q["tail"]["alpha"]["Mean"] == pytest.approx(a.mean()) and q["tail"]["alpha"]["95% VaR"] == pytest.approx(np.percentile(a, 5))
    assert q["tail"]["strategy"]["99% CVaR"] == pytest.approx(blk["values"]["99% CVaR"][0])
    assert q["tail"]["benchmark"]["Volatility (monthly)"] == pytest.approx(blk["values"]["Annualized Volatility"][1] / 12 ** 0.5)
    qs, qb = (np.prod(1 + s.reshape(20, 3), axis=1) - 1), (np.prod(1 + b.reshape(20, 3), axis=1) - 1)
    c = q["quarterly_capture"]
    assert c["quarters"] == 20 and c["rising_quarters"] == int((qb >= 0).sum())
    assert c["upside_capture"] == pytest.approx(qs[qb >= 0].mean() / qb[qb >= 0].mean())
    assert c["capture_ratio"] == pytest.approx(c["upside_capture"] / c["downside_capture"])
    assert q["drawdown"]["strategy"][0] == 0.0 and min(q["drawdown"]["strategy"]) == pytest.approx(blk["values"]["Max Drawdown"][0])
