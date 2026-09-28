"""write_holdings_log(): the file that answers "which stocks did the
rule actually pick" -- read directly off a BacktestResult's own weights
and rebalance dates, not reconstructed or summarized away."""
import os
from dataclasses import dataclass, field
from typing import Any, Dict

import numpy as np
import pandas as pd
import pytest

from universal_backtester.data import write_holdings_log


@dataclass
class _FakeResult:
    weights: pd.DataFrame
    rebalances: pd.DatetimeIndex
    name: str = "fake"
    value: pd.Series = None
    returns: pd.Series = None
    turnover: pd.Series = None
    costs: pd.Series = None
    cash_weight: pd.Series = None
    meta: Dict[str, Any] = field(default_factory=dict)


def _make_result():
    dates = pd.bdate_range("2020-01-01", periods=10)
    rebalances = pd.DatetimeIndex([dates[0], dates[5]])
    assets = ["A", "B", "C", "D"]
    w = pd.DataFrame(0.0, index=dates, columns=assets)
    w.loc[dates[0], ["A", "B"]] = [0.6, 0.4]
    w.loc[dates[5], ["B", "C", "D"]] = [0.5, 0.3, 0.2]
    return _FakeResult(weights=w, rebalances=rebalances)


def test_writes_one_row_per_held_asset_per_rebalance(tmp_path):
    result = _make_result()
    path = str(tmp_path / "holdings.csv")
    out = write_holdings_log(path, result, name_lookup={"A": "Alpha Ltd", "B": "Beta Ltd"})
    assert os.path.exists(path)
    assert len(out) == 5   # 2 names on rebal 1 + 3 names on rebal 2
    first_day = out[out["date"] == result.rebalances[0]]
    assert set(first_day["asset"]) == {"A", "B"}
    assert first_day.set_index("asset")["weight"].to_dict() == {"A": 0.6, "B": 0.4}


def test_zero_weight_assets_are_never_listed(tmp_path):
    result = _make_result()
    out = write_holdings_log(str(tmp_path / "h.csv"), result)
    second_day = out[out["date"] == result.rebalances[1]]
    assert "A" not in set(second_day["asset"])


def test_rank_orders_by_weight_descending(tmp_path):
    result = _make_result()
    out = write_holdings_log(str(tmp_path / "h.csv"), result)
    second_day = out[out["date"] == result.rebalances[1]].sort_values("rank")
    assert list(second_day["asset"]) == ["B", "C", "D"]
    assert list(second_day["rank"]) == [1, 2, 3]


def test_name_lookup_is_never_guessed_for_missing_assets(tmp_path):
    result = _make_result()
    out = write_holdings_log(str(tmp_path / "h.csv"), result, name_lookup={"A": "Alpha Ltd"})
    row_c = out[out["asset"] == "C"].iloc[0]
    assert row_c["name"] == ""   # not in the lookup -- blank, not invented


def test_start_end_filters_restrict_which_rebalances_are_written(tmp_path):
    result = _make_result()
    out = write_holdings_log(str(tmp_path / "h.csv"), result,
                             start=result.rebalances[1], end=result.rebalances[1])
    assert out["date"].nunique() == 1
    assert out["date"].iloc[0] == result.rebalances[1]


def test_a_rebalance_date_not_in_the_weights_index_is_skipped_not_an_error(tmp_path):
    result = _make_result()
    result.rebalances = result.rebalances.append(pd.DatetimeIndex(["2099-01-01"]))
    out = write_holdings_log(str(tmp_path / "h.csv"), result)
    assert pd.Timestamp("2099-01-01") not in set(out["date"])
