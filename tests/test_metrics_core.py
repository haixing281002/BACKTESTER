# Quant AI Researcher by Harshil Pahuja
"""Each metric against numbers worked out by hand in plain Python (no numpy, no pandas), and the rules the metrics live by."""
import numpy as np
import pandas as pd
import pytest

from ros.metrics import core

D = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"])
R = pd.Series([0.01, -0.02, 0.03, 0.00, 0.01, -0.01], index=D)
B = pd.Series([0.005, -0.01, 0.02, -0.005, 0.0, -0.002], index=D)
CASH = 0.0002


def _value():
    v = core.value_from_returns(R, base=1.0)
    return pd.concat([pd.Series([1.0], index=[pd.Timestamp("2024-01-01")]), v])


@pytest.mark.parametrize("got,want", [
    (lambda: core.sharpe(R, CASH), 2.8403612752452894),
    (lambda: core.sortino(R, CASH), 5.383895553276908),
    (lambda: core.ann_vol(R), 0.2779928056623049),
    (lambda: core.max_drawdown(_value()), 0.02),
    (lambda: core.cagr(_value()), 1.4034210228683572),
    (lambda: core.calmar(_value()), 70.1710511434178),
    (lambda: core.beta(R, B, CASH), 1.5521472392638034),
    (lambda: core.tracking_error(R, B), 0.14019985734657509),
    (lambda: core.information_ratio(R, B), 3.5948681370916673),
    (lambda: float(_value().iloc[-1]), 1.0193920506),
    (lambda: core.cvar_95(R), 0.02),             # only -2% sits at or below the 5th percentile of these six
    (lambda: core.daily_cash(0.06), 1.06 ** (1 / 252) - 1),
])
def test_metric_matches_hand_computed_value(got, want):
    assert got() == pytest.approx(want, rel=1e-9)


def test_max_drawdown_is_positive_and_duration_is_in_trading_days():
    v = pd.Series([100.0, 99.0, 98.0, 101.0, 100.0, 102.0], index=pd.bdate_range("2024-01-01", periods=6))
    assert core.max_drawdown(v) == pytest.approx(0.02)
    assert core.drawdown_duration(v) == 2


def test_capture_is_monthly_means():
    d = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-29"])
    r, b = pd.Series([0.02, -0.01, 0.03], index=d), pd.Series([0.01, -0.02, 0.02], index=d)
    assert core.up_capture(r, b) == pytest.approx(0.025 / 0.015)
    assert core.down_capture(r, b) == pytest.approx(0.5)


def test_period_returns_compound_and_financial_year_ends_in_march():
    d = pd.to_datetime(["2024-03-29", "2024-04-01", "2025-01-02"])
    r = pd.Series([0.10, 0.10, 0.10], index=d)
    assert core.calendar_year_returns(r)[2024] == pytest.approx(0.21)
    assert core.financial_year_returns(r)[2024] == pytest.approx(0.10)
    assert core.financial_year_returns(r)[2025] == pytest.approx(0.21)


def test_cagr_without_best_days_drops_the_best_day_over_the_same_span():
    v = core.cagr_without_best_days(R, n=1)
    kept = (1.01) * (0.98) * (1.0) * (1.01) * (0.99)
    years = (D[-1] - D[0]).days / 365.25
    assert v == pytest.approx(kept ** (1 / years) - 1)


def test_net_returns_charge_half_a_round_trip_per_unit_of_two_way_turnover():
    t = pd.Series(0.0, index=D)
    t.iloc[0] = 2.0     # sold everything, bought everything
    net = core.net_returns(R, t, house_bp=30)
    assert net.iloc[0] == pytest.approx(0.01 - 2.0 * 15 / 1e4)
    assert net.iloc[1] == R.iloc[1]


def test_net_returns_never_charge_twice():
    t = pd.Series(1.0, index=D)
    assert core.net_returns(R, t, house_bp=30, charged_bp=30).equals(R)


def test_annual_turnover_is_sum_per_calendar_year():
    t = pd.Series(0.5, index=pd.to_datetime(["2023-01-01", "2024-01-01"]))
    assert core.annual_turnover(t) == pytest.approx(1.0 / (365 / 365.25))


def test_capacity_uses_adv_before_the_trade_and_flags_names():
    idx = pd.bdate_range("2024-01-01", periods=30)
    value = pd.DataFrame({"AAA": 10.0, "BBB": 1.0}, index=idx)
    value.loc[idx[25], "AAA"] = 1e6       # a spike on the trade day must not make the trade look small
    adv = core.adv_20(value)
    trades = pd.DataFrame({"date": [idx[25], idx[25]], "isin": ["AAA", "BBB"], "weight_before": [0.0, 0.0], "weight_after": [0.01, 0.01]})
    out = core.capacity(trades, adv, aum=100.0, limit=0.5)
    assert out["median"] == pytest.approx((1.0 / 10.0 + 1.0 / 1.0) / 2)
    assert out["max"] == pytest.approx(1.0)
    assert out["names_above_limit"] == ["BBB"]


def test_capacity_counts_a_name_it_cannot_measure():
    idx = pd.bdate_range("2024-01-01", periods=30)
    adv = core.adv_20(pd.DataFrame({"AAA": 10.0}, index=idx))
    t = pd.DataFrame({"date": [idx[25]], "isin": ["ZZZ"], "weight_before": [0.0], "weight_after": [0.01]})
    assert core.capacity(t, adv, aum=100.0, limit=0.5)["n_no_adv"] == 1


def test_publication_cutoff_reads_a_bare_year_as_its_end():
    assert core.publication_cutoff("2015") == pd.Timestamp("2015-12-31")
    assert core.publication_cutoff("2015-03") == pd.Timestamp("2015-03-31")
    assert core.publication_cutoff("2015-03-10") == pd.Timestamp("2015-03-10")
    assert core.publication_cutoff("") is None


def test_post_publication_uses_only_days_after_the_date():
    idx = pd.bdate_range("2020-01-01", periods=800)
    rng = np.random.default_rng(1)
    r, b = pd.Series(rng.normal(0, 0.01, 800), index=idx), pd.Series(rng.normal(0, 0.01, 800), index=idx)
    out = core.post_publication(r, b, 0.0, "2020-12-31")
    assert out["days"] == len(r.loc["2020-12-31":])
    assert out["sharpe"] == pytest.approx(core.sharpe(r.loc["2020-12-31":], 0.0))
    assert core.post_publication(r, b, 0.0, "2023-01-01") is None     # under a year left


class _Card:
    def __init__(self, asset):
        self.universe = type("U", (), {"cash_asset": asset})()


def test_cash_rate_comes_from_the_card():
    assert core.cash_rate_from_card(_Card("CASH_PROXY_CONSTANT_7PCT")) == pytest.approx(0.07)
    assert core.cash_rate_from_card(_Card("CASH_PROXY_CONSTANT_6.5PCT")) == pytest.approx(0.065)


@pytest.mark.parametrize("asset", [None, "", "TBILL_91D"])
def test_a_card_without_a_readable_cash_rate_raises_rather_than_guessing(asset):
    with pytest.raises(core.MissingCashRate):
        core.cash_rate_from_card(_Card(asset))


def test_bootstrap_indices_are_blocks_of_mean_length_and_wrap():
    idx = core.stationary_bootstrap_indices(5000, 50, 21, np.random.default_rng(7))
    assert idx.shape == (50, 5000) and idx.min() >= 0 and idx.max() < 5000
    continues = (np.diff(idx, axis=1) % 5000) == 1
    assert (1 / (1 - continues.mean())) == pytest.approx(21, rel=0.05)


def test_bootstrap_draws_match_the_plain_sharpe_on_the_same_days():
    rng = np.random.default_rng(3)
    x = rng.normal(0.0005, 0.01, 500)
    idx = core.stationary_bootstrap_indices(500, 5, 21, rng)
    draws = core.sharpe_draws(x, idx, CASH)
    for k in range(5):
        assert draws[k] == pytest.approx(core.sharpe(pd.Series(x[idx[k]]), CASH))
    assert core.max_drawdown_draws(x, idx)[0] == pytest.approx(core.max_drawdown(pd.Series(np.cumprod(1 + x[idx[0]]))))
