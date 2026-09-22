"""The engine and the clean-room reimplementation must agree, and the check
must be capable of disagreeing.

A cross-check that always passes proves nothing. Half of this file is negative
controls: deliberate perturbations that MUST make the comparison fail. If a
planted bug slips through, the agreement in the other half is worthless.
"""
import ast
import pathlib

import numpy as np
import pandas as pd
import pytest

from ros.data.loaders import load_nse_factor_workbook, synthetic_cash_series
from ros.engine.backtest import Backtester, rebalance_dates
from ros.engine.templates import build_allocator
from ros.validation import metrics as M
from validate import independent as ind

ROOT = pathlib.Path(__file__).resolve().parent.parent
XLSX = str(ROOT / "data/raw/NSE_Broad_Factor_Indices_Historical_Data.xlsx")
SPREAD, LAG, WARMUP, NDAYS = 30.0, 1, 16, 400


@pytest.fixture(scope="module")
def setup():
    frame, _ = load_nse_factor_workbook(XLSX)
    assets = [c for c in frame.columns if "50" in c][:5]
    prices = frame[assets].dropna().iloc[:NDAYS]
    rf = synthetic_cash_series(prices.index, 0.06)
    return prices, assets, rf


def _engine(prices, assets, rf, spread=SPREAD, lag=LAG, warmup=WARMUP,
            allow_cash=False):
    bt = Backtester(prices=prices, assets=assets, rf_daily=rf, spread_bps=spread,
                    lag_days=lag, allow_cash=allow_cash)
    w = {a: 1.0 / len(assets) for a in assets}
    return bt.run(allocator=build_allocator("fixed_weight", assets, weights=w),
                  rebalance="monthly", name="t", warmup=warmup)


def _independent(prices, assets, rf, spread=SPREAD, lag=LAG, warmup=WARMUP,
                 allow_cash=False):
    bt = ind.UnitsBacktest(prices=prices, assets=assets, rf_daily=rf,
                           spread_bps=spread, lag_days=lag, allow_cash=allow_cash)
    w = np.ones(len(assets)) / len(assets)
    return bt.run(ind.fixed_weight_fn(w), ind.month_end_dates(prices.index),
                  warmup=warmup)


# ---------------------------------------------------------------------------
# Independence is structural, not a promise
# ---------------------------------------------------------------------------
def test_the_independent_implementation_imports_nothing_from_ros():
    """If it imported the engine it would be validating itself."""
    src = (ROOT / "validate/independent.py").read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name.split(".")[0] == "ros"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "ros":
                offenders.append(node.module)
    assert not offenders, f"validate/independent.py imports from ros: {offenders}"


def test_the_two_parsers_read_the_same_prices():
    eng, _ = load_nse_factor_workbook(XLSX)
    alt = ind.read_workbook(XLSX)
    shared = [c for c in eng.columns if c in alt.columns]
    assert len(shared) >= 5, f"only {len(shared)} series in common"
    idx = eng.index.intersection(alt.index)
    assert len(idx) == len(eng.index)
    for c in shared:
        a, b = eng.loc[idx, c].astype(float), alt.loc[idx, c].astype(float)
        both = a.notna() & b.notna()
        assert float((a[both] - b[both]).abs().max()) == 0.0, c


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------
def test_nav_paths_agree_to_floating_point(setup):
    prices, assets, rf = setup
    e, i = _engine(*setup), _independent(*setup)
    assert float((e.value - i["value"]).abs().max()) < 1e-10


@pytest.mark.parametrize("metric", ["cagr", "vol", "maxdd", "sharpe_geo",
                                    "sharpe_conv", "cost", "turnover"])
def test_headline_metrics_agree(setup, metric):
    prices, assets, rf = setup
    e, i = _engine(*setup), _independent(*setup)
    pairs = {
        "cagr": (M.cagr(e.value), ind.cagr(i["value"])),
        "vol": (M.ann_vol(e.returns), ind.ann_vol(i["returns"].to_numpy())),
        "maxdd": (M.max_drawdown(e.value), ind.max_drawdown(i["value"])),
        "sharpe_geo": (M.sharpe_geometric(e.value, e.returns, rf),
                       ind.sharpe_geometric(i["value"], i["returns"].to_numpy(),
                                            rf.to_numpy())),
        "sharpe_conv": (M.sharpe_conventional(e.returns, rf),
                        ind.sharpe_conventional(i["returns"].to_numpy(),
                                                rf.to_numpy())),
        "cost": (float(e.costs.sum()), float(i["costs"].sum())),
        "turnover": (float(e.turnover.sum()), float(i["turnover"].sum())),
    }
    a, b = pairs[metric]
    assert abs(a - b) < 1e-10, f"{metric}: {a} vs {b}"


def test_rebalance_calendars_agree(setup):
    prices, _, _ = setup
    assert list(pd.DatetimeIndex(rebalance_dates(prices.index, "monthly"))) == \
           list(pd.DatetimeIndex(ind.month_end_dates(prices.index)))


# ---------------------------------------------------------------------------
# Negative controls -- the check must be able to FAIL
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("perturb,why", [
    ({"spread": SPREAD * 2}, "double the spread"),
    ({"spread": 0.0}, "charge no cost at all"),
    ({"warmup": WARMUP + 40}, "start trading 40 days later"),
    ({"allow_cash": True}, "let the book hold cash"),
])
def test_a_perturbed_independent_run_disagrees(setup, perturb, why):
    """If these still matched, the comparison would be measuring nothing."""
    e = _engine(*setup)
    i = _independent(*setup, **perturb)
    gap = float((e.value - i["value"]).abs().max())
    if perturb.get("allow_cash") and gap < 1e-10:
        pytest.skip("fully-invested target holds no cash, so this knob is inert here")
    assert gap > 1e-10, f"cross-check failed to notice: {why}"


def test_a_lag_error_changes_a_vol_targeted_run(setup):
    """The causal lag is the one control a backtest most often gets wrong.

    Fixed weights ignore the signal entirely, so the lag can only be tested on a
    strategy that reads one. Shifting by the wrong number of days must move the
    NAV -- if it did not, `lag_days` would be decorative.
    """
    prices, assets, rf = setup
    rets = prices.pct_change()
    w = np.ones(len(assets)) / len(assets)
    sigma = ind.trailing_portfolio_vol(rets, w, 11)

    def run(lag):
        bt = ind.UnitsBacktest(prices=prices, assets=assets, rf_daily=rf,
                               spread_bps=SPREAD, lag_days=lag, allow_cash=True)
        fn = ind.vol_target_fn(w, 0.18, ind.shift_causal(sigma, lag))
        return bt.run(fn, ind.month_end_dates(prices.index), warmup=WARMUP)["value"]

    assert float((run(1) - run(0)).abs().max()) > 1e-8, \
        "changing the implementation lag did not change the result"


def test_a_long_only_book_stays_inside_its_holdings(setup):
    """A fully-invested long-only portfolio is a weighted average of its assets.

    So on any day it neither beats the best sleeve nor trails the worst one --
    except by the spread it paid to trade. Two carve-outs, both real rather than
    convenient: before the first rebalance the book holds nothing and correctly
    earns zero whatever the sleeves did, and on a rebalance day the cost comes
    out of NAV on top of the market move.
    """
    prices, assets, rf = setup
    i = _independent(*setup)
    v, cost = i["value"], i["costs"]

    assert np.isfinite(v).all()
    assert (v > 0).all(), "NAV went non-positive"

    invested = i["turnover"].cumsum().shift(1).fillna(0.0) > 0
    rets = prices.pct_change()
    lo, hi = rets.min(axis=1), rets.max(axis=1)
    daily = v.pct_change()
    live = invested & daily.notna() & lo.notna()

    below = live & (daily < lo - cost - 1e-9)
    above = live & (daily > hi + 1e-9)
    assert not below.any(), f"NAV trailed every holding on {int(below.sum())} days"
    assert not above.any(), f"NAV beat every holding on {int(above.sum())} days"


def test_nothing_is_earned_before_the_first_trade(setup):
    """The engine holds NAV flat at 1.0 until it first rebalances.

    An implementation that quietly accrued the cash rate over that window would
    inflate every result by the warmup period. This pins the behaviour.
    """
    i = _independent(*setup)
    first = i["turnover"].to_numpy().nonzero()[0]
    assert len(first), "the run never traded"
    assert np.allclose(i["value"].to_numpy()[:first[0]], 1.0)
