"""The clean chart set: one strategy against one benchmark, optional single sleeve."""
import numpy as np
import pandas as pd

from universal_backtester.clean_charts import save_clean_charts


def _series(seed, n=600, drift=0.0004):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.Series(100 * np.cumprod(1 + rng.normal(drift, 0.01, n)), index=idx)


def test_writes_the_standard_set_and_no_more(tmp_path):
    s, b = _series(1), _series(2)
    w = pd.DataFrame({"A": 0.5, "B": -0.5}, index=s.index)
    paths = save_clean_charts(s, b, str(tmp_path), "t", weights=w)
    names = sorted(p.split("__")[-1] for p in paths)
    assert names == ["calendar_year.png", "cumulative_return.png", "drawdown.png", "exposure.png", "rolling_volatility.png"]
    assert all((tmp_path / f"t__{n}").stat().st_size > 5000 for n in names)


def test_the_sleeve_gets_its_own_chart_only(tmp_path):
    s, b, c = _series(1), _series(2), _series(3)
    paths = save_clean_charts(s, b, str(tmp_path), "t", sleeve=c, sleeve_name="Comparator")
    assert any(p.endswith("with_sleeve.png") for p in paths)
    assert not any(p.endswith("exposure.png") for p in paths)       # no weights given, so no exposure chart


def test_too_little_overlap_writes_nothing(tmp_path):
    s = _series(1, n=10)
    assert save_clean_charts(s, s, str(tmp_path), "t") == []
