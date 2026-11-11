# Quant AI Researcher
"""The tearsheet metrics behave as their definitions say. They live in ros/metrics/core.py; universal_backtester/tearsheet.py
only arranges them. That Excel reproduces them is tests/test_excel_equals_python.py."""
import numpy as np
import pandas as pd
import pytest

from ros.metrics import core
from universal_backtester import tearsheet as ts

IDX = pd.bdate_range("2020-01-01", periods=756)
START = IDX[0] - pd.offsets.BDay(1)


def _r(mean=5e-4, sd=0.01, seed=0):
    return pd.Series(np.random.default_rng(seed).normal(mean, sd, len(IDX)), index=IDX)


def test_average_annual_max_drawdown_uses_the_prior_year_end_as_the_peak():
    idx = pd.DatetimeIndex(["2020-12-30", "2020-12-31", "2021-01-01", "2021-01-04"])
    r = pd.Series([0.10, 0.0, -0.20, 0.05], index=idx)          # 2021 opens with a 20% fall from the 2020 year-end
    d = core.calendar_year_max_drawdown(r)
    assert d[2020] == 0.0 and d[2021] == pytest.approx(0.20)
    assert core.average_annual_max_drawdown(r) == pytest.approx(0.10)


def test_beta_and_adjusted_beta():
    b = _r(seed=1)
    assert core.beta(b, b) == pytest.approx(1.0)
    assert core.beta(1.5 * b, b) == pytest.approx(1.5)
    assert core.adjusted_beta(1.5) == pytest.approx(4 / 3) and core.adjusted_beta(1.0) == 1.0


def test_jensen_alpha_is_zero_for_a_strategy_that_only_earns_its_beta():
    assert core.jensen_alpha(0.05 + 1.0 * 0.07, 0.05 + 0.07, 0.05, 1.0) == pytest.approx(0.0)
    assert core.treynor(0.15, 0.05, 2.0) == pytest.approx(0.05)


def test_sortino_counts_only_the_downside():
    r = _r(seed=2)
    boosted = r.where(r < 0, r * 2.0)                    # bigger gains, same losses
    assert core.sortino(boosted, 0.0) > core.sortino(r, 0.0)
    assert core.downside_deviation(boosted, 0.0) == pytest.approx(core.downside_deviation(r, 0.0))


def test_omega_and_gain_to_pain_sit_either_side_of_one():
    assert core.omega(_r(1.5e-3), 0.0) > 1 > core.omega(_r(-1.5e-3), 0.0)
    assert core.gain_to_pain(_r(1.5e-3)) > 1 > core.gain_to_pain(_r(-1.5e-3))


def test_losses_are_positive_numbers_and_ordered():
    r = _r(seed=3)
    assert 0 < core.var(r, 0.95) < core.var(r, 0.99)
    assert core.cvar(r, 0.95) >= core.var(r, 0.95) and core.cvar(r, 0.99) >= core.var(r, 0.99)
    assert core.max_drawdown(core.value_from_returns(r, start=START)) > 0


def test_a_levered_clone_captures_150_percent_both_ways():
    b = _r(seed=4)
    assert core.up_capture(1.5 * b, b) == pytest.approx(1.5, rel=0.05)
    assert core.down_capture(1.5 * b, b) == pytest.approx(1.5, rel=0.05)


def test_the_hurdle_lowers_sharpe_by_about_hurdle_over_volatility():
    r = _r(seed=5)
    t0, t5 = core.tearsheet(r, START, 0.0), core.tearsheet(r, START, 0.05)
    assert t0["Sharpe Ratio"] - t5["Sharpe Ratio"] == pytest.approx(0.05 / t0["Annualized Volatility"], rel=1e-9)
    assert t5["Sharpe Ratio"] == pytest.approx((t5["CAGR"] - 0.05) / t5["Annualized Volatility"], rel=1e-12)
    assert t0["CAGR"] == t5["CAGR"]                      # a yardstick: it changes no return


def test_compute_tearsheet_from_a_result_is_core():
    r, b = _r(seed=6), _r(seed=7)

    class Res:
        value = core.value_from_returns(r, start=START)
        returns = r
    close = core.value_from_returns(b, start=START)
    got = ts.compute_tearsheet(Res, close, 0.05)
    want = core.tearsheet(r, START, 0.05, b)
    assert got.keys() == want.keys()
    for k in want:
        assert got[k] == pytest.approx(want[k], rel=1e-9, abs=1e-12), k
    assert "PRICE index" in ts.render_tearsheet(got)
