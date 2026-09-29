"""walk_forward_windows / oos_stability_summary / parameter_sensitivity_sweep /
sensitivity_verdict -- the overfitting checks deflated Sharpe does not cover:
in-sample parameter fitting, as opposed to selection across many trials.
"""
import numpy as np
import pandas as pd
import pytest

from universal_backtester.validation import (
    oos_stability_summary, parameter_sensitivity_sweep,
    sensitivity_verdict, walk_forward_windows,
)


def _trending_series(n_days=1200, drift=0.0004, vol=0.01, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n_days)
    r = pd.Series(rng.normal(drift, vol, n_days), index=idx)
    v = 100.0 * (1.0 + r).cumprod()
    return v, r


def test_walk_forward_windows_are_sequential_oos_slices_after_the_training_period():
    v, _ = _trending_series(n_days=1200)
    windows = walk_forward_windows(v.index, n_folds=4, min_train_years=1.0)
    assert len(windows) == 4
    # Each window is out-of-sample relative to an ANCHORED (fixed-start,
    # expanding) training period -- so the windows themselves are
    # sequential, non-overlapping test slices: window i+1 starts exactly
    # where window i ends, never resetting or overlapping.
    for (lo1, hi1), (lo2, hi2) in zip(windows, windows[1:]):
        assert hi1 == lo2
    assert windows[0][0] > v.index[0]
    assert windows[-1][1] == v.index[-1]


def test_walk_forward_windows_empty_when_history_too_short():
    v, _ = _trending_series(n_days=100)
    assert walk_forward_windows(v.index, n_folds=4, min_train_years=3.0) == []


def test_oos_stability_summary_one_row_per_window_with_enough_observations():
    v, r = _trending_series(n_days=1200)
    windows = walk_forward_windows(v.index, n_folds=4, min_train_years=1.0)
    summary = oos_stability_summary(v, r, windows, min_obs=60)
    assert len(summary) == 4
    assert {"window", "n_obs", "cagr", "vol", "sharpe", "max_dd"}.issubset(summary.columns)
    assert (summary["n_obs"] >= 60).all()


def test_oos_stability_summary_drops_a_too_short_window():
    v, r = _trending_series(n_days=1200)
    windows = walk_forward_windows(v.index, n_folds=4, min_train_years=1.0)
    tiny = [(windows[0][0], windows[0][0] + pd.Timedelta(days=5))] + list(windows[1:])
    summary = oos_stability_summary(v, r, tiny, min_obs=60)
    assert len(summary) == 3   # the too-short window is dropped, not reported as zero/NaN


def test_oos_stability_summary_catches_a_decayed_edge():
    """A strategy that's flat in the first half and losing in the second
    half must show a positive early window and a negative late one -- the
    exact pattern a single full-sample Sharpe would hide."""
    idx = pd.bdate_range("2018-01-01", periods=1200)
    rng = np.random.default_rng(1)
    r = pd.Series(0.0, index=idx)
    r.iloc[:600] = rng.normal(0.001, 0.01, 600)     # strong early edge
    r.iloc[600:] = rng.normal(-0.0015, 0.01, 600)    # decays into a real loss
    v = 100.0 * (1.0 + r).cumprod()
    windows = walk_forward_windows(idx, n_folds=4, min_train_years=1.0)
    summary = oos_stability_summary(v, r, windows, min_obs=60)
    assert summary["sharpe"].iloc[0] > 0
    assert summary["sharpe"].iloc[-1] < 0


# ---------------------------------------------------------------------------
def test_parameter_sensitivity_sweep_runs_the_grid_and_shapes_a_table():
    def run_one(lookback):
        v, r = _trending_series(n_days=800, seed=lookback)
        return v, r

    sweep = parameter_sensitivity_sweep(run_one, "lookback", [126, 189, 252, 315])
    assert list(sweep["lookback"]) == [126, 189, 252, 315]
    assert {"cagr", "vol", "sharpe", "max_dd"}.issubset(sweep.columns)


def test_sensitivity_verdict_calls_a_stable_grid_a_ridge():
    sweep = pd.DataFrame({"lookback": [126, 189, 252, 315],
                          "sharpe": [0.62, 0.68, 0.70, 0.65],
                          "cagr": [0.1] * 4, "vol": [0.15] * 4, "max_dd": [-0.2] * 4})
    verdict = sensitivity_verdict(sweep, chosen_value=252, param_name="lookback")
    assert verdict.startswith("RIDGE")


def test_sensitivity_verdict_calls_a_fragile_grid_a_spike():
    sweep = pd.DataFrame({"lookback": [126, 189, 252, 315],
                          "sharpe": [-0.10, 0.05, 1.40, -0.20],
                          "cagr": [0.1] * 4, "vol": [0.15] * 4, "max_dd": [-0.2] * 4})
    verdict = sensitivity_verdict(sweep, chosen_value=252, param_name="lookback")
    assert verdict.startswith("SPIKE")


def test_sensitivity_verdict_handles_a_missing_chosen_value():
    sweep = pd.DataFrame({"lookback": [126, 189], "sharpe": [0.5, 0.6],
                          "cagr": [0.1, 0.1], "vol": [0.15, 0.15], "max_dd": [-0.2, -0.2]})
    verdict = sensitivity_verdict(sweep, chosen_value=252, param_name="lookback")
    assert "not in the swept grid" in verdict


def test_sensitivity_verdict_handles_an_empty_sweep():
    assert "no rows" in sensitivity_verdict(pd.DataFrame(), 252, "lookback")
