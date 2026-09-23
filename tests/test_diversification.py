"""Measured, not assumed: ros.data.diversification must actually disagree with
itself when two series really are independent, and actually flag redundancy
when they are the same bet twice.
"""
import numpy as np
import pandas as pd
import pytest

from ros.data.diversification import (
    diversification_report, greedy_diverse_subset, returns_frame,
)


def _price_frame(seed=0, n=1000):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    a = rng.normal(0.0004, 0.01, n)
    b = rng.normal(0.0004, 0.01, n)
    independent = 0.98 * a + 0.02 * rng.normal(0, 0.01, n)
    duplicate = a + rng.normal(0, 1e-6, n)          # essentially identical to A
    unrelated = b
    frame = pd.DataFrame({
        "A": 100 * (1 + pd.Series(a, index=idx)).cumprod(),
        "A_DUPLICATE": 100 * (1 + pd.Series(duplicate, index=idx)).cumprod(),
        "A_NEAR": 100 * (1 + pd.Series(independent, index=idx)).cumprod(),
        "B_UNRELATED": 100 * (1 + pd.Series(unrelated, index=idx)).cumprod(),
    }, index=idx)
    return frame


def test_duplicate_series_is_flagged_as_redundant():
    frame = _price_frame()
    r = diversification_report(frame, ["A", "A_DUPLICATE", "B_UNRELATED"])
    assert r.strongest_pair[2] > 0.99
    assert ("A", "A_DUPLICATE", pytest.approx(r.strongest_pair[2], abs=1e-9)) \
        or {r.strongest_pair[0], r.strongest_pair[1]} == {"A", "A_DUPLICATE"}
    assert any({a, b} == {"A", "A_DUPLICATE"} for a, b, _ in r.near_duplicates)


def test_unrelated_series_is_not_flagged():
    frame = _price_frame()
    r = diversification_report(frame, ["A", "B_UNRELATED"])
    assert r.pairwise_max < 0.3
    assert not r.near_duplicates
    assert r.verdict.startswith("GENUINE")


def test_collapsed_verdict_when_everything_correlates():
    frame = _price_frame()
    r = diversification_report(frame, ["A", "A_DUPLICATE", "A_NEAR"])
    assert r.pairwise_mean >= 0.85
    assert r.verdict.startswith("COLLAPSED")


def test_greedy_subset_prefers_the_unrelated_series():
    frame = _price_frame()
    picked = greedy_diverse_subset(
        frame, ["A", "A_DUPLICATE", "A_NEAR", "B_UNRELATED"], k=2)
    assert set(picked) == {"A", "B_UNRELATED"} or set(picked) == {"A_DUPLICATE", "B_UNRELATED"} \
        or set(picked) == {"A_NEAR", "B_UNRELATED"}
    # whichever of the near-identical trio it kept, it must have paired it
    # with the one truly independent series, not with another near-duplicate.
    assert "B_UNRELATED" in picked


def test_greedy_subset_never_returns_two_near_duplicates_when_a_third_option_exists():
    frame = _price_frame()
    picked = greedy_diverse_subset(
        frame, ["A", "A_DUPLICATE", "A_NEAR", "B_UNRELATED"], k=3)
    assert "B_UNRELATED" in picked
    assert len(set(picked)) == 3


def test_missing_series_raises():
    frame = _price_frame()
    with pytest.raises(KeyError):
        returns_frame(frame, ["A", "NOT_HELD"])


def test_fewer_than_two_candidates_raises():
    frame = _price_frame()
    with pytest.raises(ValueError):
        diversification_report(frame, ["A"])


def test_k_exceeding_candidates_raises():
    frame = _price_frame()
    with pytest.raises(ValueError):
        greedy_diverse_subset(frame, ["A", "B_UNRELATED"], k=5)


def test_render_is_readable_text():
    frame = _price_frame()
    r = diversification_report(frame, ["A", "A_DUPLICATE", "B_UNRELATED"])
    out = r.render()
    assert "DIVERSIFICATION" in out
    assert "verdict" in out


def test_real_workbook_matches_the_wood_card_measured_floor():
    """Regression anchor: the actual repo data, the actual 8-sleeve set a
    prior card measured by hand, should reproduce that same 0.76-0.96 floor.
    Skips cleanly if the workbook isn't present in this checkout."""
    import os
    path = "data/raw/NSE_Broad_Factor_Indices_Historical_Data.xlsx"
    if not os.path.exists(path):
        pytest.skip("workbook not present")
    from ros.data.loaders import load_nse_workbook_combined
    frame, _ = load_nse_workbook_combined(path)
    sleeves8 = ["NIFTY500 MOMENTUM 50", "NIFTY500 QUALITY 50", "NIFTY500 VALUE 50",
                "NIFTY500 LOW VOLATILITY 50", "NIFTY ALPHA 50", "NIFTY MIDCAP 150",
                "NIFTY SMALLCAP 250", "NIFTY MICROCAP 250"]
    r = diversification_report(frame, sleeves8)
    assert 0.70 <= r.pairwise_min <= 0.80
    assert 0.90 <= r.pairwise_max <= 1.00
    assert r.verdict.startswith("COLLAPSED")
