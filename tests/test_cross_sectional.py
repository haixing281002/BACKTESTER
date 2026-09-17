"""The cross-sectional template, and the ways a cross-sectional backtest lies.

Ranking securities is where most equity research lives and where most backtest
errors hide. Three of them are structural rather than arithmetic, so no amount
of checking the NAV arithmetic finds them:

  1. SURVIVORSHIP -- names that delisted are missing from the price file, so the
     book never owns anything that went to zero.
  2. LOOK-AHEAD MEMBERSHIP -- selecting from today's index constituents, which
     were announced later.
  3. FREE EXITS -- zeroing a dead position and renormalising the rest, so the
     book leaves every failure at no cost.

Each has a test below that plants the bias and confirms it is caught.
"""
import numpy as np
import pandas as pd
import pytest

from ros.engine.backtest import Backtester
from ros.engine.templates import build_allocator

SPREAD, LAG, WARMUP = 30.0, 1, 5


def synthetic_universe(n_names=30, n_days=760, n_doomed=6, seed=7):
    """A cross-section where some names die, badly, and leave the index.

    The doomed names lose 80% over their final 60 sessions before delisting.
    That is the point: a survivorship-biased run never sees the fall, so any
    test that cannot tell the two apart is not testing anything.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n_days)
    names = [f"STK{i:03d}" for i in range(n_names)]

    rets = rng.normal(0.0004, 0.014, size=(n_days, n_names))
    prices = pd.DataFrame(100.0 * np.cumprod(1.0 + rets, axis=0),
                          index=idx, columns=names)
    member = pd.DataFrame(True, index=idx, columns=names)

    doomed = names[:n_doomed]
    for j, nm in enumerate(doomed):
        death = n_days - 200 + j * 20            # staggered, all mid-sample
        start = death - 60
        decay = np.linspace(0.0, 1.0, death - start)
        base = prices[nm].iloc[start]
        prices.iloc[start:death, prices.columns.get_loc(nm)] = (
            base * (1.0 - 0.8 * decay))
        prices.iloc[death:, prices.columns.get_loc(nm)] = np.nan
        member.iloc[death:, member.columns.get_loc(nm)] = False
    return prices, member, names, doomed


@pytest.fixture(scope="module")
def uni():
    return synthetic_universe()


def _run(prices, member, names, score, **kw):
    bt = Backtester(prices=prices, assets=names, spread_bps=SPREAD, lag_days=LAG,
                    allow_cash=True, membership=member)
    alloc = build_allocator("cross_sectional", names,
                            **{"n_hold": 10, "min_names": 5, **kw})
    return bt.run(allocator=alloc, rebalance="monthly", alpha=score,
                  name="xs", warmup=WARMUP)


# ---------------------------------------------------------------------------
# It runs at all
# ---------------------------------------------------------------------------
def test_a_changing_universe_must_be_declared(uni):
    """NaNs without a membership frame are a data fault, not a cross-section."""
    prices, member, names, _ = uni
    with pytest.raises(ValueError, match="membership"):
        Backtester(prices=prices, assets=names, spread_bps=SPREAD, lag_days=LAG)


def test_it_produces_a_usable_nav_path(uni):
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)
    res = _run(prices, member, names, score)
    assert np.isfinite(res.value).all(), "NaN prices leaked into the NAV"
    assert (res.value > 0).all()
    assert res.meta["changing_universe"] is True
    assert res.meta["n_rebalances"] > 20


def test_it_holds_the_number_of_names_it_was_told_to(uni):
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)
    res = _run(prices, member, names, score, n_hold=10)
    held = (res.weights > 1e-9).sum(axis=1)
    on_rebal = held.loc[res.rebalances]
    assert on_rebal.max() <= 10, f"held {on_rebal.max()} names, cap was 10"
    assert on_rebal.median() == 10


def test_a_quantile_rule_scales_with_the_eligible_count(uni):
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)
    bt = Backtester(prices=prices, assets=names, spread_bps=SPREAD, lag_days=LAG,
                    allow_cash=True, membership=member)
    alloc = build_allocator("cross_sectional", names, quantile=0.2, min_names=5)
    res = bt.run(allocator=alloc, rebalance="monthly", alpha=score, warmup=WARMUP)
    held = (res.weights > 1e-9).sum(axis=1).loc[res.rebalances]
    assert 4 <= held.median() <= 7, held.median()      # ~20% of ~24-30 names


# ---------------------------------------------------------------------------
# THE BIAS TESTS -- each plants the error and confirms it is caught
# ---------------------------------------------------------------------------
def test_a_survivor_only_universe_flatters_the_result(uni):
    """Build the price file from survivors only -- the classic bias -- and the
    same strategy looks better.

    Note what this does and does not show. A momentum score never BUYS the
    doomed names: they are collapsing, so they rank last. The gain comes from
    the SELECTION POOL being cleaner -- ranking 24 names that all survived is an
    easier problem than ranking 30 of which 6 die. That is survivorship bias in
    universe construction, and it is the form that reaches a backtest even when
    the strategy would never have touched the casualties.

    Holding a dying name, and paying to exit it, is a separate mechanism with
    its own test below.
    """
    prices, member, names, doomed = uni
    score = prices.pct_change(252, fill_method=None)

    honest = _run(prices, member, names, score)
    survivors = [n for n in names if n not in doomed]
    biased = _run(prices[survivors], member[survivors], survivors,
                  score[survivors])

    h, b = float(honest.value.iloc[-1]), float(biased.value.iloc[-1])
    assert b > h, (
        f"a survivor-only universe produced the same answer ({b:.4f} vs {h:.4f}), "
        f"so this test is not detecting survivorship bias at all")


def test_a_dead_position_is_sold_at_cost_not_quietly_zeroed(uni):
    """A free exit from every failure is survivorship bias wearing a cost model."""
    prices, member, names, _ = uni
    # A score that actively likes the doomed names, so they ARE held when they die.
    score = pd.DataFrame(0.0, index=prices.index, columns=names)
    score.iloc[:, :6] = 1.0
    res = _run(prices, member, names, score, n_hold=6, min_names=3)
    assert res.meta["forced_exits"] >= 6, res.meta
    assert float(res.costs.sum()) > 0.0


def test_forced_exits_cost_more_than_a_frictionless_one(uni):
    """Turn the spread off and the same run keeps more: the exits are charged."""
    prices, member, names, _ = uni
    score = pd.DataFrame(0.0, index=prices.index, columns=names)
    score.iloc[:, :6] = 1.0

    def run(spread):
        bt = Backtester(prices=prices, assets=names, spread_bps=spread,
                        lag_days=LAG, allow_cash=True, membership=member)
        a = build_allocator("cross_sectional", names, n_hold=6, min_names=3)
        return bt.run(allocator=a, rebalance="monthly", alpha=score, warmup=WARMUP)

    assert float(run(0.0).value.iloc[-1]) > float(run(SPREAD).value.iloc[-1])


def test_membership_is_lagged_like_any_other_signal(uni):
    """Selecting from tomorrow's constituents is reading the future."""
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)

    def run(lag):
        bt = Backtester(prices=prices, assets=names, spread_bps=SPREAD,
                        lag_days=lag, allow_cash=True, membership=member)
        a = build_allocator("cross_sectional", names, n_hold=10, min_names=5)
        return bt.run(allocator=a, rebalance="monthly", alpha=score,
                      warmup=WARMUP).value

    assert float((run(1) - run(0)).abs().max()) > 1e-9, \
        "changing the lag changed nothing, so the mask is not being shifted"


def test_a_name_is_never_held_before_it_is_eligible(uni):
    """The mask is a hard constraint, not a preference."""
    prices, member, names, _ = uni
    score = pd.DataFrame(1.0, index=prices.index, columns=names)   # wants everything
    res = _run(prices, member, names, score, n_hold=30, min_names=3)
    w = res.weights
    # Once a name has left for good, it must never reappear with weight.
    for nm in names:
        gone = ~member[nm]
        if gone.any():
            first_gone = member.index[gone.argmax()]
            after = w.loc[w.index > first_gone, nm]
            # one bar of tolerance: the lagged mask exits a bar late, by design
            assert (after.iloc[2:] <= 1e-12).all(), f"{nm} held after delisting"


def test_a_thin_cross_section_is_refused_not_ranked(uni):
    """Ranking four names into deciles produces weights that mean nothing."""
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)
    bt = Backtester(prices=prices, assets=names[:4], spread_bps=SPREAD,
                    lag_days=LAG, allow_cash=True, membership=member[names[:4]])
    a = build_allocator("cross_sectional", names[:4], n_hold=2, min_names=10)
    res = bt.run(allocator=a, rebalance="monthly", alpha=score[names[:4]],
                 warmup=WARMUP)
    assert a.diagnostics()["rebalances_skipped_thin_universe"] > 0
    assert float(res.value.iloc[-1]) == 1.0, "it traded a universe it called too thin"


# ---------------------------------------------------------------------------
# The ranking itself
# ---------------------------------------------------------------------------
def test_ascending_picks_the_other_end(uni):
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)
    hi = _run(prices, member, names, score, n_hold=5, ascending=False)
    lo = _run(prices, member, names, score, n_hold=5, ascending=True)
    d = hi.rebalances[-1]
    assert not set(hi.weights.loc[d][hi.weights.loc[d] > 0].index) & \
               set(lo.weights.loc[d][lo.weights.loc[d] > 0].index)


def test_a_per_name_cap_binds(uni):
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)
    res = _run(prices, member, names, score, n_hold=4, max_weight=0.30)
    on_rebal = res.weights.loc[res.rebalances]
    assert on_rebal.max(axis=1).max() <= 0.30 + 1e-9


@pytest.mark.parametrize("weighting", ["equal", "signal", "inverse_vol"])
def test_every_weighting_rule_produces_a_long_only_unlevered_book(uni, weighting):
    prices, member, names, _ = uni
    score = prices.pct_change(252, fill_method=None)
    vols = prices.pct_change(fill_method=None).rolling(60).std() * np.sqrt(252)
    bt = Backtester(prices=prices, assets=names, spread_bps=SPREAD, lag_days=LAG,
                    allow_cash=True, membership=member)
    a = build_allocator("cross_sectional", names, n_hold=10, min_names=5,
                        weighting=weighting)
    res = bt.run(allocator=a, rebalance="monthly", alpha=score, vols=vols,
                 warmup=WARMUP)
    w = res.weights
    assert (w >= -1e-12).all().all(), "a weight went negative in a long-only book"
    assert w.sum(axis=1).max() <= 1.0 + 1e-9, "the book levered up"


def test_it_refuses_an_ambiguous_selection_rule():
    with pytest.raises(ValueError, match="exactly one"):
        build_allocator("cross_sectional", ["a", "b"], n_hold=1, quantile=0.5)
    with pytest.raises(ValueError, match="exactly one"):
        build_allocator("cross_sectional", ["a", "b"])
