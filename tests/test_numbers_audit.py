# Quant AI Researcher
"""The numbers audit (lightyear/numbers_audit.py) passes a consistent run and fails a tampered one."""
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from lightyear import numbers_audit as na

DAYS = pd.bdate_range("2024-01-01", periods=8)
CLOSE = pd.DataFrame({"A": [10, 10, 11, 12, 12, 13, 12, 14.0], "B": [20, 21, 22, 21, 23, 24, 25, 26.0]}, index=DAYS)
PX = {"close": CLOSE, "unadj_close": CLOSE * 2, "unadj_open": CLOSE * 2 - 0.5}
PARAMS = {"cash_rate": 0.0, "cost_bp": 0.0, "start_capital": 1000.0}


def _run():
    """A tiny book: buy 400 of A on day 1, sell it on day 5. NAV and daily returns written the way a run writes them."""
    tr = pd.DataFrame([
        {"execution_date": DAYS[1], "signal_date": DAYS[0], "isin": "A", "action": "BUY", "value_rs": 400.0,
         "adjusted_close": 10.0, "price": 20.0},
        {"execution_date": DAYS[5], "signal_date": DAYS[4], "isin": "A", "action": "SELL", "value_rs": 520.0,
         "adjusted_close": 13.0, "price": 26.0}])
    nav = pd.Series([1000, 1000, 1040, 1080, 1080, 1120, 1120, 1120.0], index=DAYS)
    dr = pd.DataFrame({"date": DAYS[1:], "strategy": nav.pct_change().dropna().to_numpy()})
    return dr, tr


def test_a_consistent_run_rebuilds_to_zero():
    dr, tr = _run()
    assert na.nav_rebuild(dr, tr, PX, PARAMS)["passed"] is True


def test_a_tampered_trade_or_return_fails_the_rebuild():
    dr, tr = _run()
    t2 = tr.copy()
    t2.loc[0, "value_rs"] = 410.0
    assert na.nav_rebuild(dr, t2, PX, PARAMS)["passed"] is False
    d2 = dr.copy()
    d2.loc[3, "strategy"] += 1e-4                                  # 1bp off on one day
    assert na.nav_rebuild(d2, tr, PX, PARAMS)["passed"] is False


def test_the_fill_price_must_be_the_field_the_card_names():
    _, tr = _run()
    assert na.fill_price_check(tr, PX, {"fill_price": "close"})["passed"] is True
    assert na.fill_price_check(tr, PX, {"fill_price": "open"})["passed"] is False
    assert na.fill_price_check(tr, PX, {})["passed"] is False


def test_filters_are_recomputed_from_prices():
    _, tr = _run()
    sp = {"gap_limit": 0.05, "gap_days": 3, "stock_trend_days": 2}
    rows = na.filters_from_source(tr, None, PX, sp, None)
    assert all(r["passed"] for r in rows)                          # no >5% move before day 0, above its 2-day mean
    bad = tr.copy()
    bad.loc[0, "signal_date"] = DAYS[3]                            # A rose 10% on day 2: inside 3 days of day 3
    assert not na.filters_from_source(bad, None, PX, sp, None)[0]["passed"]
    assert np.isfinite(CLOSE.to_numpy()).all()
