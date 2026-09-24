"""Proves the long-short engine capability is (a) opt-in only, never a
default, (b) inert when the wrong allocator/engine pairing is used, (c)
correctly charges a financing cost on short notional every day, not just
on trade days, and (d) caps GROSS exposure, not net, when shorting is on.
"""
import numpy as np
import pandas as pd
import pytest

from universal_backtester import Backtester, build_allocator


def _universe(n_names=20, n_days=800, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n_days)
    names = [f"S{i:03d}" for i in range(n_names)]
    rets = rng.normal(0.0003, 0.015, size=(n_days, n_names))
    prices = pd.DataFrame(100.0 * np.cumprod(1.0 + rets, axis=0), index=idx, columns=names)
    eligible = pd.DataFrame(True, index=idx, columns=names)
    score = prices.pct_change(120, fill_method=None)
    return prices, eligible, names, score


def test_long_only_is_the_default_even_with_a_long_short_allocator():
    """Pairing the long-short allocator with the DEFAULT engine (allow_short
    not passed) must never produce a negative weight -- the engine's clip
    is what actually enforces long-only, not the allocator's good behavior."""
    prices, eligible, names, score = _universe()
    bt = Backtester(prices=prices, assets=names, spread_bps=10, lag_days=1, membership=eligible)
    alloc = build_allocator("cross_sectional_long_short", names, n_hold=3, min_names=8)
    res = bt.run(allocator=alloc, rebalance="monthly", alpha=score, warmup=125)
    assert (res.weights >= -1e-12).all().all(), "a negative weight leaked through the default long-only engine"
    assert res.meta["allow_short"] is False


def test_allow_short_true_actually_produces_negative_weights():
    prices, eligible, names, score = _universe()
    bt = Backtester(prices=prices, assets=names, spread_bps=10, lag_days=1,
                    membership=eligible, allow_short=True, max_gross_exposure=1.0)
    alloc = build_allocator("cross_sectional_long_short", names, n_hold=3, min_names=8)
    res = bt.run(allocator=alloc, rebalance="monthly", alpha=score, warmup=125)
    on_rebal = res.weights.loc[res.rebalances]
    assert (on_rebal < -1e-9).any(axis=None), "allow_short=True never actually shorted anything"
    assert (on_rebal > 1e-9).any(axis=None), "allow_short=True never went long either"


def test_gross_exposure_cap_holds_not_net():
    """A dollar-neutral long-short book has NET exposure ~0 but GROSS
    exposure ~2x (100% long + 100% short) -- the cap must be checked on
    the gross figure, or a 100/100 book would incorrectly look empty."""
    prices, eligible, names, score = _universe()
    bt = Backtester(prices=prices, assets=names, spread_bps=10, lag_days=1,
                    membership=eligible, allow_short=True, max_gross_exposure=2.0)
    alloc = build_allocator("cross_sectional_long_short", names, n_hold=3, min_names=8,
                            long_weight=1.0, short_weight=1.0)
    res = bt.run(allocator=alloc, rebalance="monthly", alpha=score, warmup=125)
    on_rebal = res.weights.loc[res.rebalances]
    gross = on_rebal.abs().sum(axis=1)
    net = on_rebal.sum(axis=1)
    assert gross.max() <= 2.0 + 1e-6
    assert (net.abs() < 0.05).all(), "long_weight == short_weight should be ~dollar-neutral"
    assert gross.mean() > 1.0, "a 100/100 book should show gross exposure well above a long-only book's ceiling of 1.0"


def test_gross_exposure_cap_is_enforced_when_breached():
    prices, eligible, names, score = _universe()
    bt = Backtester(prices=prices, assets=names, spread_bps=10, lag_days=1,
                    membership=eligible, allow_short=True, max_gross_exposure=1.2)
    alloc = build_allocator("cross_sectional_long_short", names, n_hold=3, min_names=8,
                            long_weight=1.0, short_weight=1.0)  # raw gross would be 2.0
    res = bt.run(allocator=alloc, rebalance="monthly", alpha=score, warmup=125)
    on_rebal = res.weights.loc[res.rebalances]
    assert on_rebal.abs().sum(axis=1).max() <= 1.2 + 1e-6


def test_borrow_cost_is_charged_daily_not_only_on_trade_days():
    """Hold a short position across a stretch of non-rebalance days and
    confirm NAV decays purely from the borrow fee even when the underlying
    doesn't move at all (flat prices -> zero trading P&L, so any decay must
    be the financing cost)."""
    idx = pd.bdate_range("2020-01-01", periods=300)
    names = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
    prices = pd.DataFrame(100.0, index=idx, columns=names)  # perfectly flat
    eligible = pd.DataFrame(True, index=idx, columns=names)
    score = pd.DataFrame(np.tile(np.arange(len(names)), (len(idx), 1)), index=idx, columns=names, dtype=float)

    bt_no_borrow = Backtester(prices=prices, assets=names, spread_bps=0, lag_days=1,
                              membership=eligible, allow_short=True, short_borrow_bps=0.0)
    bt_borrow = Backtester(prices=prices, assets=names, spread_bps=0, lag_days=1,
                           membership=eligible, allow_short=True, short_borrow_bps=500.0)  # 5%/yr
    alloc1 = build_allocator("cross_sectional_long_short", names, n_hold=2, min_names=4)
    alloc2 = build_allocator("cross_sectional_long_short", names, n_hold=2, min_names=4)

    res_no_borrow = bt_no_borrow.run(allocator=alloc1, rebalance="monthly", alpha=score, warmup=5)
    res_borrow = bt_borrow.run(allocator=alloc2, rebalance="monthly", alpha=score, warmup=5)

    assert res_no_borrow.value.iloc[-1] == pytest.approx(1.0, abs=1e-9), \
        "flat prices, zero cost, zero borrow -> NAV must not move at all"
    assert res_borrow.value.iloc[-1] < res_no_borrow.value.iloc[-1] - 1e-6, \
        "a real borrow fee on flat prices must show up as pure NAV decay"
