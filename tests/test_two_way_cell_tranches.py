"""Tests for the two_way_cell_tranches allocator (Lee & Swaminathan style sort cells)."""
import numpy as np
import pandas as pd
import pytest

from universal_backtester import Backtester, build_allocator
from universal_backtester.allocators import AllocatorContext


def _ctx(alpha, elig, current=None, date="2023-03-31"):
    n = len(alpha)
    return AllocatorContext(date=pd.Timestamp(date),
                            current_weights=np.zeros(n) if current is None else current,
                            alpha=np.array(alpha, float), eligible=np.array(elig, bool))


def _alloc(n, **kw):
    return build_allocator("two_way_cell_tranches", [f"S{i}" for i in range(n)], **kw)


def test_one_tranche_is_equal_weight_inside_each_leg():
    a = _alloc(10, k_tranches=1, min_cell=2)
    w = a.target_weights(_ctx([1, 1, 1, 0, 0, 0, -1, -1, 0, 0], [True] * 10))
    assert w[:3] == pytest.approx([0.5 / 3] * 3)
    assert w[6:8] == pytest.approx([-0.25, -0.25])
    assert w.sum() == pytest.approx(0.0)


def test_thin_cell_skips_the_month_and_carries_the_book_forward():
    a = _alloc(10, k_tranches=3, min_cell=3)
    cur = np.linspace(-0.1, 0.1, 10)
    w = a.target_weights(_ctx([1, 1, 0, 0, 0, 0, -1, -1, -1, 0], [True] * 10, current=cur))
    assert w == pytest.approx(cur)
    d = a.diagnostics()
    assert d["months_skipped_thin_cell"] == 1 and d["tranches_formed"] == 0
    assert d["skipped_dates"] == ["2023-03-31"]


def test_tranches_overlap_and_the_oldest_drops_out():
    a = _alloc(6, k_tranches=2, long_weight=1.0, short_weight=0.0, min_cell=1)
    w1 = a.target_weights(_ctx([1, 0, 0, 0, 0, 0], [True] * 6))
    w2 = a.target_weights(_ctx([0, 1, 0, 0, 0, 0], [True] * 6))
    w3 = a.target_weights(_ctx([0, 0, 1, 0, 0, 0], [True] * 6))
    assert w1 == pytest.approx([1, 0, 0, 0, 0, 0])
    assert w2 == pytest.approx([0.5, 0.5, 0, 0, 0, 0])
    assert w3 == pytest.approx([0, 0.5, 0.5, 0, 0, 0])      # tranche 1 aged out


def test_ineligible_name_is_zeroed_not_relevered():
    a = _alloc(4, k_tranches=1, long_weight=1.0, short_weight=0.0, min_cell=1)
    w = a.target_weights(_ctx([1, 1, 0, 0], [True, False, True, True]))
    # only name 0 is both in the cell and eligible, so it carries the whole leg
    assert w[1] == 0.0 and w[0] == pytest.approx(1.0)


def test_single_sided_only_needs_the_long_cell():
    a = _alloc(5, k_tranches=1, long_weight=1.0, short_weight=0.0, min_cell=2)
    w = a.target_weights(_ctx([1, 1, 0, 0, -1], [True] * 5))
    assert w[4] == 0.0 and w[:2] == pytest.approx([0.5, 0.5])


def test_runs_through_the_engine_with_causal_shift_and_shorts():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2022-01-03", periods=400)
    names = [f"S{i:02d}" for i in range(40)]
    prices = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.0003, 0.012, (400, 40)), axis=0),
                          index=idx, columns=names)
    ind = pd.DataFrame(0.0, index=idx, columns=names)
    ind.iloc[:, :10] = 1.0
    ind.iloc[:, 30:] = -1.0
    bt = Backtester(prices=prices, assets=names, spread_bps=10, lag_days=5,
                    membership=pd.DataFrame(True, index=idx, columns=names),
                    allow_short=True, max_gross_exposure=1.0)
    res = bt.run(allocator=build_allocator("two_way_cell_tranches", names, k_tranches=3, min_cell=5),
                 rebalance="monthly", alpha=ind, name="t")
    on = res.weights.loc[res.rebalances]
    assert (on.iloc[-1, :10] > 0).all() and (on.iloc[-1, 30:] < 0).all()
    assert res.meta["allocator_diagnostics"]["tranches_formed"] >= 5
