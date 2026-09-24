"""Ground-truth regression test: reproduces the REAL "SE Return Analytics"
reference workbook's own reported numbers (read directly from the .xlsb
the fund supplied, not synthetic data) from this repo's tearsheet.py
functions. If any of these break, the CSV/Excel output has drifted from
the reference file the fund asked us to match -- this is the test that
would have caught the earlier capture-ratio definition bug (compounded
product vs. simple mean) before it shipped.

tests/fixtures/se_return_analytics_reference.json holds 161 months
(Apr-2013 .. Aug-2026) of the reference workbook's own monthly returns
for its "Systematic Equity Gross" strategy column and its "Nifty 500 TRI"
benchmark column, extracted with pyxlsb. All expected values below are
copied verbatim from that same workbook's own Analytics panel.
"""
import json
import os

import pandas as pd
import pytest

from universal_backtester import tearsheet as ts

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "se_return_analytics_reference.json")


@pytest.fixture(scope="module")
def real_series():
    with open(_FIXTURE) as f:
        d = json.load(f)
    idx = pd.to_datetime(d["dates"])
    strat = pd.Series(d["strat"], index=idx)
    bench = pd.Series(d["bench"], index=idx)
    return strat, bench


def test_capture_ratio_matches_the_reference_workbook_exactly(real_series):
    strat, bench = real_series
    cap = ts.capture_breakdown(strat, bench)
    assert cap["ret_positive_benchmark"] == pytest.approx(0.03912363320944919, abs=1e-9)
    assert cap["ret_positive_strategy"] == pytest.approx(0.03916965364458047, abs=1e-9)
    assert cap["ret_negative_benchmark"] == pytest.approx(-0.03376421285369745, abs=1e-9)
    assert cap["ret_negative_strategy"] == pytest.approx(-0.02360429858220242, abs=1e-9)
    assert cap["upside_capture"] == pytest.approx(1.0011762822456929, abs=1e-9)
    assert cap["downside_capture"] == pytest.approx(0.6990922218291123, abs=1e-9)
    assert cap["capture_ratio"] == pytest.approx(1.4321090279422715, abs=1e-8)


def test_extreme_capture_ratio_matches_the_reference_workbook_exactly(real_series):
    strat, bench = real_series
    excap = ts.extreme_capture_breakdown(strat, bench)
    assert excap["ex_ret_positive_benchmark"] == pytest.approx(0.08020522725287162, abs=1e-9)
    assert excap["ex_ret_positive_strategy"] == pytest.approx(0.06692023959399765, abs=1e-9)
    assert excap["ex_ret_negative_benchmark"] == pytest.approx(-0.08639847230442903, abs=1e-9)
    assert excap["ex_ret_negative_strategy"] == pytest.approx(-0.0760055320577027, abs=1e-9)
    assert excap["ex_upside_capture"] == pytest.approx(0.834362570696434, abs=1e-8)
    assert excap["ex_downside_capture"] == pytest.approx(0.8797092127959587, abs=1e-8)
    assert excap["extreme_capture_ratio"] == pytest.approx(0.9484526915940774, abs=1e-8)


def test_financial_year_returns_match_the_reference_workbook(real_series):
    strat, _ = real_series
    fy = ts.financial_year_returns(strat)
    assert fy["FY14"] == pytest.approx(0.3400000000366854, abs=1e-9)
    assert fy["FY15"] == pytest.approx(0.6456902983919779, abs=1e-9)
    assert fy["FY20"] == pytest.approx(-0.2318, abs=1e-9)
    assert fy["FY26"] == pytest.approx(-0.09970415087409401, abs=1e-9)
    assert list(fy.keys())[0] == "FY14"
    assert list(fy.keys())[-1] == "FY27"


def test_calendar_year_returns_match_the_reference_workbook(real_series):
    strat, _ = real_series
    cy = ts.calendar_year_returns(strat)
    assert cy["CY13"] == pytest.approx(0.301505545788342, abs=1e-9)
    assert cy["CY20"] == pytest.approx(0.21454737138493485, abs=1e-9)
    assert cy["CY26"] == pytest.approx(0.021878666965042814, abs=1e-9)


def test_calendar_year_max_drawdown_matches_the_reference_workbook(real_series):
    """CY14 is the interesting case: the reference workbook shows EXACTLY
    0.0 for the strategy that year (it never dipped below its own Jan-1
    NAV), which only reproduces correctly if the running peak resets at
    the start of each calendar year rather than carrying the whole-
    history peak."""
    strat, bench = real_series
    dd = ts.calendar_year_max_drawdown(strat)
    assert dd["CY13"] == pytest.approx(-0.046058130040875, abs=1e-9)
    assert dd["CY14"] == pytest.approx(0.0, abs=1e-9)
    assert dd["CY20"] == pytest.approx(-0.2536137367768616, abs=1e-9)

    dd_b = ts.calendar_year_max_drawdown(bench)
    assert dd_b["CY14"] == pytest.approx(-0.020702399556822293, abs=1e-9)


def test_average_annual_max_drawdown_matches_the_reference_workbook(real_series):
    strat, bench = real_series
    assert ts.average_annual_max_drawdown(strat) == pytest.approx(-0.07929586510595528, abs=1e-8)
    assert ts.average_annual_max_drawdown(bench) == pytest.approx(-0.08780822143675493, abs=1e-8)


def test_positive_negative_volatility_match_the_reference_workbook(real_series):
    """Verified quirk: these two rows are the ONLY volatility figures on
    the reference sheet that are NOT annualized (no *sqrt(12))."""
    strat, bench = real_series
    assert ts.positive_volatility(strat) == pytest.approx(0.029545885215888704, abs=1e-9)
    assert ts.negative_volatility(strat) == pytest.approx(0.03397338870848164, abs=1e-9)
    assert ts.positive_volatility(bench) == pytest.approx(0.031548023593170486, abs=1e-9)
    assert ts.negative_volatility(bench) == pytest.approx(0.03892126426988953, abs=1e-9)


def test_gain_to_pain_ratio_matches_the_reference_workbook(real_series):
    strat, bench = real_series
    assert ts.gain_to_pain_ratio(strat) == pytest.approx(2.3807487127854228, abs=1e-7)
    assert ts.gain_to_pain_ratio(bench) == pytest.approx(2.003229510355096, abs=1e-7)


def test_var_and_cvar_match_the_reference_workbook_unnegated(real_series):
    strat, _ = real_series
    assert ts.historical_var(strat, 0.95) == pytest.approx(-0.053399999999999996, abs=1e-9)
    assert ts.historical_var(strat, 0.99) == pytest.approx(-0.0995, abs=1e-9)
    assert ts.historical_cvar(strat, 0.95) == pytest.approx(-0.09352556183529755, abs=1e-7)
    assert ts.historical_cvar(strat, 0.99) == pytest.approx(-0.15379227306450227, abs=1e-7)


def test_tracking_error_matches_the_reference_workbook(real_series):
    strat, bench = real_series
    assert ts.tracking_error(strat, bench, ann=12) == pytest.approx(0.0953132978736625, abs=1e-9)
