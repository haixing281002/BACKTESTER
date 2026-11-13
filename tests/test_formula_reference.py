# Quant AI Researcher
"""One test per metric of the formula reference (Lightyear daily column and Lightyear monthly column): the formula is
written out here in plain arithmetic on a small fixed series, and the code must give the same number. A test that fails
means the code no longer computes what the reference says. Nothing here reads a run."""
import math
import statistics as st
from pathlib import Path

import pandas as pd
import pytest

from lightyear import main_workbook
from ros import config
from ros.metrics import core, se

# ---------------------------------------------------------------------------------------------------------------- daily
START = pd.Timestamp("2024-01-01")
D = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"])
r = [0.01, -0.02, 0.03, 0.00, 0.01, -0.01]
b = [0.005, -0.01, 0.02, -0.005, 0.0, -0.002]
R, B = pd.Series(r, index=D), pd.Series(b, index=D)
RF = 0.05
N = config.trading_days_per_year()
H = (1 + RF) ** (1 / N) - 1          # the risk-free rate for one day
C = (1 + 0.06) ** (1 / N) - 1        # a card's cash rate for one day
YEARS = (D[-1] - START).days / 365.25
VALUE = core.value_from_returns(R, start=START)


def _cagr(x):
    return math.prod(1 + v for v in x) ** (1 / YEARS) - 1


def test_daily_periods_a_year_is_252_from_the_config():
    assert N == 252 and core.ANN == N


def test_daily_annual_return_is_cagr_on_calendar_days_over_365_25():
    assert core.cagr(VALUE) == pytest.approx(_cagr(r), rel=1e-12)
    assert core.years_between(START, D[-1]) == pytest.approx(8 / 365.25)


def test_daily_volatility_is_the_sample_stdev_times_root_252():
    assert core.ann_vol(R) == pytest.approx(st.stdev(r) * math.sqrt(N), rel=1e-12)


def test_daily_sharpe_is_cagr_minus_rf_over_volatility():
    assert core.sharpe_geometric(VALUE, RF, R) == pytest.approx((_cagr(r) - RF) / (st.stdev(r) * math.sqrt(N)), rel=1e-12)


def test_gate_b_sharpe_is_the_arithmetic_form():
    x = [v - H for v in r]
    assert core.sharpe(R, H) == pytest.approx(st.mean(x) / st.stdev(x) * math.sqrt(N), rel=1e-12)


def test_daily_sortino_is_cagr_minus_rf_over_the_downside_deviation():
    dd = math.sqrt(st.mean(min(v - H, 0.0) ** 2 for v in r)) * math.sqrt(N)
    assert core.sortino_geometric(VALUE, RF, R) == pytest.approx((_cagr(r) - RF) / dd, rel=1e-12)


def test_daily_maximum_drawdown_is_on_the_compounded_value_and_positive():
    worst, peak, v = 0.0, 100.0, 100.0
    for x in r:
        v *= 1 + x
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    assert core.max_drawdown(VALUE) == pytest.approx(-worst, rel=1e-12) and core.max_drawdown(VALUE) > 0


def test_daily_tracking_error_is_the_sample_stdev_of_the_gap_times_root_252():
    gap = [x - y for x, y in zip(r, b)]
    assert core.tracking_error(R, B) == pytest.approx(st.stdev(gap) * math.sqrt(N), rel=1e-12)


def test_daily_information_ratio_is_the_mean_gap_times_252_over_tracking_error():
    gap = [x - y for x, y in zip(r, b)]
    assert core.information_ratio(R, B) == pytest.approx(st.mean(gap) * N / (st.stdev(gap) * math.sqrt(N)), rel=1e-12)


def test_daily_beta_is_covariance_over_variance_on_returns_minus_cash():
    x, y = [v - C for v in r], [v - C for v in b]
    assert core.beta(R, B, C) == pytest.approx(st.covariance(x, y) / st.variance(y), rel=1e-12)


def test_the_workbook_writes_the_daily_beta_in_the_same_form_as_python():
    src = Path(main_workbook.__file__).read_text(encoding="utf-8")
    assert "COVARIANCE.S(Ret_Strat-Cash_Daily,Ret_Bench-Cash_Daily)/_xlfn.VAR.S(Ret_Bench-Cash_Daily)" in src
    assert "SLOPE(Ret_Strat,Ret_Bench)" not in src


def test_idle_cash_accrues_on_the_configured_day_count():
    from ros.data.loaders import synthetic_cash_series
    assert synthetic_cash_series(D, 0.06).iloc[0] == pytest.approx(C, rel=1e-15) == pytest.approx(core.daily_cash(0.06), rel=1e-15)


# -------------------------------------------------------------------------------------------------------------- monthly
M = pd.date_range("2023-01-31", periods=8, freq="ME")
ms = [0.04, -0.03, 0.02, 0.00, 0.05, -0.06, 0.03, 0.01]
mb = [0.02, -0.02, 0.01, 0.01, 0.03, -0.04, 0.02, -0.01]
SE = se.compute(pd.Series(ms, index=M), pd.Series(mb, index=M), {"risk_free_rate": RF})["values"]
XL = {lab: fx for _, lab, _, _, fx in se.SPEC}


def _mcagr(x):
    return math.prod(1 + v for v in x) ** (12 / len(x)) - 1


def _mvol(x):
    return st.pstdev(x) * math.sqrt(12)


def test_monthly_annual_return_is_cagr_by_the_count_of_months():
    assert SE["CAGR"][0] == pytest.approx(_mcagr(ms), rel=1e-12)
    assert XL["CAGR"] == "=({c}{r[Total Return]}+1)^(12/COUNT({x}))-1"


def test_monthly_volatility_is_the_population_stdev_times_root_12():
    assert SE["Annualized Volatility"][0] == pytest.approx(_mvol(ms), rel=1e-12)
    assert XL["Annualized Volatility"] == "=STDEVPA({x})*SQRT(12)"


def test_monthly_sharpe_is_cagr_minus_rf_over_volatility():
    assert SE["Sharpe Ratio"][0] == pytest.approx((_mcagr(ms) - RF) / _mvol(ms), rel=1e-12)


def test_monthly_sortino_uses_the_population_stdev_of_months_at_or_below_zero():
    neg = [v for v in ms if v <= 0]
    assert len(neg) == 3                                    # the 0.00 month counts
    assert SE["Sortino Ratio"][0] == pytest.approx((_mcagr(ms) - RF) / (st.pstdev(neg) * math.sqrt(12)), rel=1e-12)
    assert XL["Negative Monthly Vol"] == "ARRAY:=STDEVPA(IF({x}<=0,{x}))"


def test_monthly_maximum_drawdown_is_on_month_end_wealth_and_negative():
    worst, w, peak = 0.0, 1.0, None
    for x in ms:
        w *= 1 + x
        peak = w if peak is None else max(peak, w)
        worst = min(worst, w / peak - 1)
    assert SE["Max Drawdown"][0] == pytest.approx(worst, rel=1e-12) and SE["Max Drawdown"][0] < 0


def test_monthly_tracking_error_is_the_population_stdev_of_the_gap_times_root_12():
    gap = [x - y for x, y in zip(ms, mb)]
    assert SE["Tracking Error"][0] == pytest.approx(st.pstdev(gap) * math.sqrt(12), rel=1e-12)
    assert XL["Tracking Error"] == "ARRAY:=STDEVPA({C}-{D})*SQRT(12)"


def test_monthly_information_ratio_is_the_cagr_gap_over_tracking_error():
    gap = [x - y for x, y in zip(ms, mb)]
    assert SE["Information Ratio"][0] == pytest.approx((_mcagr(ms) - _mcagr(mb)) / (st.pstdev(gap) * math.sqrt(12)), rel=1e-12)


def test_monthly_beta_is_the_slope_of_strategy_months_on_benchmark_months():
    assert SE["Beta"][0] == pytest.approx(st.linear_regression(mb, ms).slope, rel=1e-12)
    assert XL["Beta"] == "=SLOPE({x},{D})"


def test_monthly_figures_use_complete_months_only():
    days = pd.bdate_range("2024-01-10", "2024-04-12")       # stand-in sessions; the rule is what is tested
    p0, p1, info = se.complete_months(pd.Series(0.001, index=days[1:]), sessions=pd.bdate_range("2024-01-01", "2024-04-30"))
    assert (str(p0), str(p1)) == ("2024-02", "2024-03") and [x["month"] for x in info["left_out"]] == ["2024-01", "2024-04"]
