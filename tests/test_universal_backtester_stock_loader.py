"""load_stock_universe is unverified against a real file (none has arrived
yet -- see data/raw/stocks/README.md), so these tests are what stand in for
that: prove it actually parses both shapes it claims to support, and prove
it fails loudly and specifically rather than guessing on a shape it doesn't
recognize.
"""
import numpy as np
import pandas as pd
import pytest

from universal_backtester.data import load_stock_universe


def test_long_tidy_shape_with_isin(tmp_path):
    rows = []
    dates = pd.bdate_range("2022-01-01", periods=5)
    isins = ["INE001A01036", "INE002A01018", "INE003A01024"]
    for d in dates:
        for isin in isins:
            rows.append({"Date": d, "ISIN": isin, "Open": 100.0, "High": 105.0,
                         "Low": 99.0, "Close": 102.0, "Volume": 10000})
    df = pd.DataFrame(rows)
    path = tmp_path / "long.csv"
    df.to_csv(path, index=False)

    out, prov = load_stock_universe(str(path))
    assert prov["shape"] == "long_tidy"
    assert prov["id_column"] == "ISIN"
    assert set(out["close"].columns) == set(isins)
    assert out["close"].shape == (5, 3)
    assert out["high"] is not None
    assert (out["close"] == 102.0).all().all()


def test_long_tidy_shape_with_symbol_when_isin_absent(tmp_path):
    rows = []
    dates = pd.bdate_range("2022-01-01", periods=3)
    for d in dates:
        for sym in ["RELIANCE", "TCS"]:
            rows.append({"Date": d, "Symbol": sym, "Close": 100.0})
    df = pd.DataFrame(rows)
    path = tmp_path / "long_symbol.csv"
    df.to_csv(path, index=False)

    out, prov = load_stock_universe(str(path))
    assert prov["id_column"] == "Symbol"
    assert set(out["close"].columns) == {"RELIANCE", "TCS"}
    assert out["high"] is None   # not present in this file -- must not fabricate it


def test_wide_close_only_shape(tmp_path):
    dates = pd.bdate_range("2022-01-01", periods=5)
    df = pd.DataFrame({
        "Date": dates,
        "STOCK_A": np.linspace(100, 110, 5),
        "STOCK_B": np.linspace(200, 190, 5),
    })
    path = tmp_path / "wide.csv"
    df.to_csv(path, index=False)

    out, prov = load_stock_universe(str(path))
    assert prov["shape"] == "wide_close_only"
    assert set(out["close"].columns) == {"STOCK_A", "STOCK_B"}
    assert out["close"].shape == (5, 2)
    assert out["high"] is None


def test_no_date_column_raises_clearly(tmp_path):
    df = pd.DataFrame({"Foo": [1, 2, 3], "Bar": [4, 5, 6]})
    path = tmp_path / "bad.csv"
    df.to_csv(path, index=False)
    with pytest.raises(ValueError, match="no recognizable date column"):
        load_stock_universe(str(path))


def test_unrecognized_extension_raises_clearly(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("not a real data file")
    with pytest.raises(ValueError, match="unrecognized extension"):
        load_stock_universe(str(path))


def test_isin_preferred_over_symbol_when_both_present(tmp_path):
    """CLAUDE.md's own README warning: key on ISIN, never on symbol, since
    symbols get reused and a rename splices two companies into one series."""
    rows = []
    dates = pd.bdate_range("2022-01-01", periods=3)
    for d in dates:
        rows.append({"Date": d, "ISIN": "INE001A01036", "Symbol": "OLDNAME", "Close": 100.0})
    df = pd.DataFrame(rows)
    path = tmp_path / "both_ids.csv"
    df.to_csv(path, index=False)
    out, prov = load_stock_universe(str(path))
    assert prov["id_column"] == "ISIN"
