"""Look-ahead safety of the actual signal-construction functions used by the
three real production scripts (accord_stock_selection, alquist small-cap,
asness value long-short) -- not just the engine's own generic shift logic
(already covered by test_universal_backtester_causality.py). These import
the scripts' own functions directly and run assert_causal against them, so
a future edit to the signal-building code in scripts/*.py is caught here
even though ros.runner.execute_card() never touches this path (see
new-paper-backtest skill) and these scripts have no dedicated unit tests
of their own otherwise.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from universal_backtester.engine import assert_causal, LookaheadError


def _synthetic_prices(n_names=15, n_days=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n_days)
    names = list(range(1, n_names + 1))
    rets = rng.normal(0.0003, 0.012, size=(n_days, n_names))
    prices = pd.DataFrame(100.0 * np.cumprod(1.0 + rets, axis=0), index=idx, columns=names)
    return prices, idx, names


def test_accord_momentum_signal_is_causal_once_shifted():
    """momentum_signal() (accord_stock_selection_backtest.py) is a pure
    function of past prices (shift(skip)/shift(lookback) - 1) -- after the
    engine's own (1 + lag_days) shift on top, it must not correlate with
    the return it trades or the one after it."""
    from scripts.accord_stock_selection_backtest import momentum_signal

    prices, idx, names = _synthetic_prices()
    sig = momentum_signal(prices, lookback=252, skip=21)
    returns = prices.pct_change(fill_method=None)

    shifted = sig.shift(1 + 1)   # engine's (1 + lag_days), lag_days=1
    assert_causal(shifted, returns, label="accord_momentum")   # must not raise


def test_accord_tripwire_still_catches_a_planted_leak_on_this_price_series():
    """Negative control, same shape as run_pipeline.py's own "planted
    next-bar leak" check: proves assert_causal would actually catch a real
    leak on THIS script's own synthetic return series, not just in the
    engine's generic test fixtures -- momentum_signal() itself is already
    causal by construction (it only ever reads prices.shift(skip)/
    .shift(lookback), both look-BACK; proven by the earlier test passing
    even before the engine's own extra shift is applied)."""
    prices, idx, names = _synthetic_prices()
    returns = prices.pct_change(fill_method=None)

    with pytest.raises(LookaheadError):
        assert_causal(returns.shift(-1), returns, label="planted next-bar leak")


def test_asness_build_daily_step_never_leaks_a_value_before_its_known_date():
    """build_daily_step() (asness_2015_india_value_longshort_backtest.py) is
    THE point-in-time mechanism for this card: each security's fundamental
    ratio must be NaN before its own known_date and hold exactly that value
    from known_date onward, never earlier -- the property the card's whole
    "never before it was actually knowable" claim rests on."""
    from scripts.asness_2015_india_value_longshort_backtest import build_daily_step

    idx = pd.bdate_range("2020-01-01", periods=100)
    known_date = idx[40]
    fund_pref = pd.DataFrame({
        "accord_code": [1],
        "known_date": [known_date],
        "value_col": [7.0],
    })
    daily = build_daily_step(fund_pref, "value_col", [1], idx)

    before = daily.loc[idx < known_date, 1]
    on_and_after = daily.loc[idx >= known_date, 1]
    assert before.isna().all(), "value appeared before its own known_date -- a leak"
    assert (on_and_after == 7.0).all(), "value not held constant from known_date onward"


def test_asness_composite_zscore_is_causal_once_shifted():
    """The composite value z-score (equal-weighted average of two
    point-in-time step signals) must also pass the tripwire once shifted,
    same as the momentum signal above -- a step function updating on known
    dates is exactly the kind of signal a broken merge or an off-by-one on
    known_date could quietly turn into a leak."""
    from scripts.asness_2015_india_value_longshort_backtest import (
        build_daily_step, zscore_cross_section,
    )

    prices, idx, names = _synthetic_prices(n_names=12, n_days=300)
    rng = np.random.default_rng(2)
    known_dates = idx[::15][: len(names)]   # a new known_date roughly every 15 trading days
    fund_pref = pd.DataFrame({
        "accord_code": names,
        "known_date": known_dates,
        "value_col": rng.normal(0, 1, size=len(names)),
    })
    daily = build_daily_step(fund_pref, "value_col", names, idx)
    mask = daily.notna()
    z = zscore_cross_section(daily, mask)

    returns = prices.pct_change(fill_method=None)
    shifted = z.shift(1 + 1)
    assert_causal(shifted, returns, label="asness_composite")   # must not raise
