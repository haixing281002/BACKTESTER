# Quant AI Researcher
"""Wave 3: the Politis-White block length, one CAGR base, and half-open windows anchored on the last value before each."""
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.metrics import core
from ros.validation import gate_evidence as ev
from ros.validation import research


def _ar1(phi, n, rng):
    e = rng.standard_normal(n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def test_block_length_grows_with_dependence_and_is_capped():
    rng = np.random.default_rng(3)
    n = 3000
    iid, mild, strong = (core.politis_white_block(_ar1(p, n, rng)) for p in (0.0, 0.5, 0.9))
    assert iid < 5 < mild < strong <= np.ceil(min(3 * np.sqrt(n), n / 3))


def test_block_length_matches_ar1_theory():
    # AR(1), unit innovations: R(k) = phi^|k| / (1 - phi^2). Long-run variance g0 = 1 / (1 - phi)^2 and
    # G = sum over k != 0 of |k| R(k) = 2 phi / ((1 - phi)^2 (1 - phi^2)), so b = (G / g0)^(2/3) n^(1/3).
    phi, n = 0.5, 20000
    x = _ar1(phi, n, np.random.default_rng(11))
    g0 = 1 / (1 - phi) ** 2
    gk = 2 * phi / ((1 - phi) ** 2 * (1 - phi ** 2))
    b_theory = (2 * gk ** 2 / (2 * g0 ** 2)) ** (1 / 3) * n ** (1 / 3)
    assert abs(core.politis_white_block(x) / b_theory - 1) < 0.35


def test_auto_block_is_the_largest_and_paired_bootstrap_reports_it():
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2015-01-01", periods=2000)
    b = pd.Series(rng.normal(0.0004, 0.01, 2000), index=idx)
    r = b + pd.Series(_ar1(0.6, 2000, rng) * 0.002 + 0.0003, index=idx)
    out = ev.paired_bootstrap(r, b, 0.0, n_boot=300)
    assert out["mean_block"] == core.auto_mean_block(r.to_numpy(), b.to_numpy(), (r - b).to_numpy())
    assert out["block_method"].startswith("Politis-White") and set(out["sensitivity"]) == {"5", "21", "63"}
    assert ev.paired_bootstrap(r, b, 0.0, n_boot=300, mean_block=21)["p"] == out["sensitivity"]["21"]


def test_cagr_counts_the_first_return():
    idx = pd.DatetimeIndex(["2020-01-02", "2020-01-03"])
    r = pd.Series([0.10, 0.0], index=idx)
    assert core.cagr(core.value_from_returns(r)) == 0.0             # the old way: the 10% vanishes
    t0 = pd.Timestamp("2020-01-01")
    assert core.cagr_from_returns(r, t0) > 1.0                       # with the base date, it counts


def test_windows_are_half_open_and_anchored():
    idx = pd.bdate_range("2020-01-01", periods=400)
    edges = [idx[0], idx[100], idx[200], idx[399]]
    w = core.split_windows(idx, edges)
    days = [d for _, _, dd, _ in w for d in dd]
    assert len(days) == len(set(days)) == 400                      # every day once, none twice
    assert w[0][3] is None and w[1][3] == idx[100] and w[1][2][0] == idx[101]


class _Res:
    def __init__(self, value):
        self.value, self.returns = value, value.pct_change().fillna(0.0)


def test_sub_period_cagr_keeps_each_window_s_first_return():
    idx = pd.bdate_range("2014-01-01", periods=1500)   # long enough that every window has its own year label
    r = pd.Series(0.0, index=idx)
    edges = pd.date_range(idx[0], idx[-1], periods=4)
    w = core.split_windows(idx, edges)
    first_of_second = w[1][2][0]
    r[first_of_second] = 0.05                                        # the whole window's gain sits on its first day
    v = core.value_from_returns(r)
    res = _Res(v)
    out = research.oos_summary(res, [(edges[i], edges[i + 1]) for i in range(3)], bench=_Res(pd.Series(100.0, index=idx)))
    assert out.loc[1, "cagr"] > 0.02 and out.loc[1, "excess_cagr"] == out.loc[1, "cagr"]   # before the fix: exactly 0
    tbl = research.subperiod_table([type("R", (), {"value": v, "returns": r, "name": "s"})()], n_periods=3, metric="cagr")
    assert tbl.iloc[0, 1] > 0.02                                    # dropped first return: exactly 0


def test_sharpe_hurdle_is_five_percent_a_year_as_a_daily_rate():
    from ros import config
    assert config.sharpe_hurdle_annual() == 0.05
    assert abs((1 + config.sharpe_hurdle()) ** 252 - 1.05) < 1e-12
