"""cross_sectional's new weighting="mcap" mode: weights chosen names
proportional to ctx.vols (reinterpreted as a size/market-cap array, not
a volatility) -- added so a strategy can be true cap-weighted, not just
equal- or signal-weighted, when a real market-cap series exists."""
import numpy as np
import pytest

from universal_backtester.allocators import AllocatorContext, CrossSectional


def _ctx(alpha, mcap, eligible=None):
    n = len(alpha)
    return AllocatorContext(
        date=None, current_weights=np.zeros(n),
        alpha=np.array(alpha, dtype=float),
        eligible=np.array(eligible if eligible is not None else [True] * n),
        vols=np.array(mcap, dtype=float) if mcap is not None else None,
    )


def test_mcap_weighting_is_proportional_to_size_among_chosen_names():
    names = ["a", "b", "c", "d"]
    alloc = CrossSectional(names, n_hold=3, weighting="mcap", min_names=1)
    # alpha ranks a > b > c > d; top 3 chosen = a, b, c
    ctx = _ctx(alpha=[4, 3, 2, 1], mcap=[100, 300, 600, 999999])
    w = alloc.target_weights(ctx)
    assert w[3] == 0.0   # d never chosen despite huge mcap -- ranking still governs selection
    total = w[:3].sum()
    assert total == pytest.approx(1.0)
    # weights among a,b,c proportional to 100:300:600
    assert w[0] == pytest.approx(100 / 1000)
    assert w[1] == pytest.approx(300 / 1000)
    assert w[2] == pytest.approx(600 / 1000)


def test_mcap_weighting_falls_back_to_equal_when_no_size_array_given():
    names = ["a", "b", "c"]
    alloc = CrossSectional(names, n_hold=2, weighting="mcap", min_names=1)
    ctx = _ctx(alpha=[2, 1, 0], mcap=None)
    w = alloc.target_weights(ctx)
    assert w[0] == pytest.approx(0.5)
    assert w[1] == pytest.approx(0.5)
    assert w[2] == 0.0


def test_mcap_weighting_respects_max_weight_cap():
    names = ["a", "b", "c"]
    alloc = CrossSectional(names, n_hold=3, weighting="mcap", max_weight=0.5, min_names=1)
    ctx = _ctx(alpha=[3, 2, 1], mcap=[1, 1, 100])
    w = alloc.target_weights(ctx)
    assert w.max() <= 0.5 + 1e-9
    assert w.sum() == pytest.approx(1.0)


def test_unknown_weighting_still_rejected():
    with pytest.raises(ValueError, match="unknown weighting"):
        CrossSectional(["a", "b"], n_hold=1, weighting="bogus", min_names=1)
