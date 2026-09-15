"""Engine correctness tests.

These target the properties that, if broken, make every downstream number wrong
while the code still runs happily: accounting identity, cost arithmetic,
causality, and comparison fairness.
"""
import numpy as np
import pandas as pd
import pytest

from ros.engine.backtest import Backtester, LookaheadError, assert_causal, rebalance_dates
from ros.engine.templates import build_allocator
from ros.validation.metrics import cagr, max_drawdown, sharpe_conventional
from ros.validation.research import expected_max_sharpe, _stationary_bootstrap_index


def _prices(n=800, seed=0, drift=0.0003, vol=0.01, k=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    r = rng.normal(drift, vol, size=(n, k))
    px = 100 * np.cumprod(1 + r, axis=0)
    return pd.DataFrame(px, index=idx, columns=[f"A{i}" for i in range(k)])


def test_buy_and_hold_identity():
    """A 100% single-asset fixed-weight portfolio, rebalanced daily with zero cost,
    must reproduce that asset's return exactly."""
    px = _prices(k=1)
    bt = Backtester(px, ["A0"], spread_bps=0.0, lag_days=0)
    alloc = build_allocator("fixed_weight", ["A0"], weights={"A0": 1.0})
    res = bt.run(alloc, rebalance="daily", name="bh", warmup=0)
    v = res.value.loc[res.rebalances[0]:]
    p = px["A0"].loc[res.rebalances[0]:]
    assert np.allclose(v / v.iloc[0], p / p.iloc[0], atol=1e-10)


def test_all_cash_earns_the_risk_free_rate():
    px = _prices(k=1)
    rf = pd.Series((1.05) ** (1 / 252) - 1, index=px.index)
    bt = Backtester(px, ["A0"], rf_daily=rf, spread_bps=0.0)
    alloc = build_allocator("fixed_weight", ["A0"], weights={"A0": 0.0})
    res = bt.run(alloc, rebalance="daily", name="cash", warmup=0)
    v = res.value.loc[res.rebalances[0]:]
    got = (v.iloc[-1] / v.iloc[0]) ** (252 / (len(v) - 1)) - 1
    assert abs(got - 0.05) < 1e-3


def test_weights_sum_and_nonnegativity():
    px = _prices()
    bt = Backtester(px, list(px.columns), spread_bps=5.0)
    alloc = build_allocator("fixed_weight", list(px.columns),
                            weights={"A0": 0.5, "A1": 0.3, "A2": 0.2})
    res = bt.run(alloc, rebalance="monthly", name="fw", warmup=5)
    gross = res.weights.sum(axis=1)
    assert (gross <= 1.0 + 1e-9).all()
    assert (res.weights >= -1e-12).all().all()
    assert np.allclose(res.cash_weight, 1 - gross, atol=1e-12)


def test_trading_cost_is_charged_exactly_once_at_the_half_spread():
    """One rebalance from all-cash into a 60/40 mix trades 100% of the book;
    at a 100bp spread that must cost exactly 50bp of NAV."""
    px = _prices(k=2)
    px.iloc[:, :] = 100.0                      # flat prices isolate the cost
    bt = Backtester(px, ["A0", "A1"], spread_bps=100.0, lag_days=0)
    alloc = build_allocator("fixed_weight", ["A0", "A1"], weights={"A0": 0.6, "A1": 0.4})
    res = bt.run(alloc, rebalance="annual", name="c", warmup=0)
    first = res.rebalances[0]
    assert abs(res.costs.loc[first] - 0.005) < 1e-12
    assert abs(res.turnover.loc[first] - 0.5) < 1e-12
    assert abs(res.value.loc[first] - 0.995) < 1e-12


def test_signal_is_shifted_and_lag_compounds():
    """The engine must consume signals shifted by 1 + lag_days."""
    px = _prices()
    for lag in (0, 1, 5):
        bt = Backtester(px, list(px.columns), lag_days=lag)
        sig = pd.Series(np.arange(len(px), dtype=float), index=px.index)
        assert bt._shift_causal(sig).iloc[10] == 10 - (1 + lag)


def test_lookahead_tripwire_catches_both_leak_classes():
    px = _prices()
    rets = px.pct_change()
    with pytest.raises(LookaheadError):
        assert_causal(rets, rets, label="same-bar")
    with pytest.raises(LookaheadError):
        assert_causal(rets.shift(-1), rets, label="next-bar")
    assert_causal(rets.shift(5), rets, label="causal")   # must not raise


def test_rebalance_dates_use_last_trading_day():
    idx = pd.bdate_range("2020-01-01", "2020-12-31")
    m = rebalance_dates(idx, "monthly")
    assert len(m) == 12
    assert all(d in idx for d in m)
    jan = idx[idx.month == 1]
    assert m[0] == jan[-1]


def test_vol_target_never_levers_and_scales_correctly():
    from ros.engine.templates import AllocatorContext
    a = build_allocator("vol_target", ["A0", "A1"],
                        weights={"A0": 0.6, "A1": 0.4}, target_vol=0.10)
    ctx = lambda s: AllocatorContext(pd.Timestamp("2020-01-01"), np.zeros(2), s, None, None)
    assert np.allclose(a.target_weights(ctx(0.20)), np.array([0.3, 0.2]))   # halve
    assert np.allclose(a.target_weights(ctx(0.05)), np.array([0.6, 0.4]))   # no lever


def test_markowitz_respects_its_constraints():
    from ros.engine.templates import AllocatorContext
    rng = np.random.default_rng(1)
    X = rng.normal(0, 0.01, size=(400, 3))
    cov = np.cov(X, rowvar=False) * 252
    a = build_allocator("markowitz_l1", ["A0", "A1", "A2"],
                        strategic_weights={"A0": .5, "A1": .3, "A2": .2},
                        target_vol=0.05, l1_budget=1.0)
    w = a.target_weights(AllocatorContext(
        pd.Timestamp("2020-01-01"), np.zeros(3), None, cov,
        np.array([0.02, 0.01, 0.03]), rf_period=0.004))
    assert (w >= -1e-8).all()
    assert w.sum() <= 1 + 1e-6
    assert np.sqrt(w @ cov @ w) <= 0.05 + 1e-5
    g = w.sum()
    if g > 1e-8:
        assert np.abs(w - g * np.array([.5, .3, .2])).sum() <= g + 1e-5


def test_fully_invested_mode_holds_no_cash():
    px = _prices()
    bt = Backtester(px, list(px.columns), spread_bps=5.0, allow_cash=False)
    alloc = build_allocator("vol_target", list(px.columns),
                            weights={c: 1 / 3 for c in px.columns}, target_vol=0.001)
    rets = px.pct_change()
    sig = (rets @ np.repeat(1 / 3, 3)).rolling(20).std() * np.sqrt(252)
    res = bt.run(alloc, rebalance="monthly", sigma_bench=sig, name="fi", warmup=25)
    live = res.cash_weight.loc[res.rebalances[0]:]
    assert live.abs().max() < 1e-9


def test_align_runs_gives_every_strategy_the_same_start():
    from ros.runner import RunSet, align_runs, buy_and_hold
    px = _prices()
    bt = Backtester(px, list(px.columns), spread_bps=0.0)
    early = bt.run(build_allocator("equal_weight", list(px.columns)),
                   rebalance="monthly", name="early", warmup=5)
    late = bt.run(build_allocator("equal_weight", list(px.columns)),
                  rebalance="monthly", name="late", warmup=300)
    rs = align_runs(RunSet(primary=late, mandate=None, benchmarks=[early],
                           references=[buy_and_hold(px["A0"], "ref")]))
    starts = {r.value.index[0] for r in rs.all_results()}
    assert len(starts) == 1
    assert all(abs(r.value.iloc[0] - 1.0) < 1e-12 for r in rs.all_results())


def test_snapshot_hash_detects_mutation():
    from ros.data.snapshot import SnapshotBuilder
    px = _prices()
    snap = SnapshotBuilder("t", pit_status="true_pit").add_source(px, {"path": "x"}).freeze()
    assert snap.verify()
    snap.frame.iloc[0, 0] += 1e-9
    assert not snap.verify()


def test_expected_max_sharpe_grows_with_trials():
    vals = [expected_max_sharpe(n) for n in (2, 10, 100, 1000)]
    assert all(b > a for a, b in zip(vals, vals[1:]))
    assert vals[-1] > 3.0      # 1000 coin flips produce a "Sharpe 3" strategy


def test_bootstrap_index_is_in_range_and_right_length():
    rng = np.random.default_rng(0)
    for n in (250, 1000):
        idx = _stationary_bootstrap_index(n, 21, rng)
        assert len(idx) == n
        assert idx.min() >= 0 and idx.max() < n


def test_metrics_against_hand_computed_values():
    idx = pd.bdate_range("2020-01-01", periods=504)
    v = pd.Series(np.linspace(1.0, 1.21, 504), index=idx)   # ~ +21% over 2y
    assert abs(cagr(v) - 0.10) < 0.01
    dd = pd.Series([1, 2, 1, 2], index=pd.bdate_range("2020-01-01", periods=4))
    assert abs(max_drawdown(dd) - 0.5) < 1e-12


def test_engine_rejects_nan_prices():
    px = _prices()
    px.iloc[5, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        Backtester(px, list(px.columns))


def test_card_rejects_unknown_keys_and_unresolved_ambiguity(tmp_path):
    from ros.cards.schema import CardValidationError, load_card
    p = tmp_path / "c.yaml"
    p.write_text("paper: {id: x}\nnot_a_section: 1\n")
    with pytest.raises(CardValidationError, match="unknown top-level"):
        load_card(str(p))
    p.write_text(
        "paper: {id: x}\nintent: {mode: adaptation, transferred_mechanism: m}\n"
        "universe: {assets: [A]}\nsignal: {template: fixed_weight}\n"
        "ambiguities:\n  - {field: f, issue: i}\n")
    with pytest.raises(CardValidationError, match="no resolution"):
        load_card(str(p))
