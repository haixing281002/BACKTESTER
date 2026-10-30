"""ros/data/ace.py: the Ace Equity price loader, on a small synthetic file in the real layout, plus a live
check against the real files when they are on this machine."""
import os
import sys

import numpy as np
import openpyxl
import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.data import ace, sources

ACE_HEADER = ["Sr.No.", "Accord Code", "Company Name", "NDP_Date", "NDP_Open", "NDP_High", "NDP_Low", "NDP_Close",
              "NDP_Mcap", "NDP_Volume ('000)", "NDP_Value", "NDP_No of trades", "NDP_Un Adj Open", "NDP_Un Adj High",
              "NDP_Un Adj Low", "NDP_Un Adj Close", "NDP_PE", "NDP_Price_BV", "NDP_EV_EBIDTA", "NDP_MCAP_NS",
              "NDP_Consolidated PE", "NDP_Consolidated Price BV", "NDP_Consolidated MCAP NS",
              "NDP_Consolidated EV EBIDTA", "FH_Year End", "FH_Gross Sales"]


def write_ace_csv(path, dates, codes, bad_rows=0):
    rows = []
    k = 1
    rng = np.random.default_rng(0)
    for d in dates:
        for code, name in codes:
            px = 100 + code % 7 + rng.normal(0, 1)
            rows.append([k, code, name, d.strftime("%Y-%m-%d"), px, px + 1, px - 1, px, px * 1.5, 10.0, 0.1, 50,
                         px * 2, px * 2 + 2, px * 2 - 2, px * 2, 20.0, 3.0, 12.0, 2.0, "", "", "", "", 202603, 1.0])
            k += 1
    for _ in range(bad_rows):
        rows.append([k, codes[0][0], codes[0][1], "2020-01-01", 1, 1, 1, "", 1, 1, 1, 1, 1, 1, 1, 1, "", "", "", "",
                     "", "", "", "", "", ""])
        k += 1
    pd.DataFrame(rows, columns=ACE_HEADER).to_csv(path, index=False)


def write_holdings_xlsx(path, master_rows, snapshots):
    """master_rows: (accord_code, name, nse_symbol, bbg, isin, sector). snapshots: {date: [(bbg_id, isin, ticker,
    name, flags dict)]}. Same cell layout as the real workbook: headers on row 3, data from row 4, column B first."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bifurcation"
    ws.append([])
    ws.append([None, "Nifty 500 with Bifurcation"])
    ws.append([None, "id().value", None, "Company Name", "ISIN", "Ticker", "Date", "Concat", "Nifty 50",
               "Nifty Next 50", "Nifty 100", "Nifty Midcap 150", "Nifty Smallcap 250"])
    for d, rows in snapshots.items():
        for bbg, isin, ticker, name, flags in rows:
            ws.append([None, bbg, None, name, isin or "#N/A", ticker or "#N/A", pd.Timestamp(d).to_pydatetime(),
                       f"{bbg}{d}", *[(f"{bbg}{d}" if flags.get(f) else "#N/A")
                                      for f in ("n50", "nn50", "n100", "mc150", "sc250")]])
    ws2 = wb.create_sheet("Sheet2")
    ws2.append([])
    ws2.append([None, None, "Sr.No.", "Accord Code", "Company Name", "CD_NSE Symbol", "CD_Bloomberg Code",
                "CD_ISIN No", "CD_Sector"])
    for i, r in enumerate(master_rows, start=1):
        ws2.append([None, None, i, *r])
    wb.save(path)


@pytest.fixture
def small_world(tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=30)
    codes = [(100001, "Alpha Ltd."), (100002, "Beta Ltd."), (100003, "Gamma Ltd."), (999999, "Delisted Co.")]
    csv = tmp_path / "prices.csv"
    write_ace_csv(csv, dates, codes, bad_rows=2)
    xlsx = tmp_path / "holdings.xlsx"
    master = [(100001, "Alpha Ltd.", "ALPHA", "ALPHA IN", "INE000A01011", "Finance"),
              (100002, "Beta Ltd.", "BETA", "BETA IN", "INE000B01012", "Power"),
              (100003, "Gamma Ltd.", "GAMMA", "GAMMA IN", "INE000C01013", "IT"),
              (100004, "Not in Ace Ltd.", "NOTACE", "NOTACE IN", "INE000D01014", "IT")]
    write_holdings_xlsx(xlsx, master, {})
    return {"csv": str(csv), "xlsx": str(xlsx), "out": str(tmp_path / "cache"), "dates": dates}


def test_cache_is_built_once_and_cleaning_is_counted(small_world):
    w = small_world
    prov = ace.build_cache(w["csv"], w["out"])
    assert prov["rows"] == 30 * 4 and prov["securities"] == 4
    assert prov["dropped_rows"]["missing_or_nonpositive_close"] == 2
    assert prov["first_date"] == "2024-01-01" and prov["trading_days"] == 30
    assert prov["built_at"].endswith("+05:30"), "provenance timestamps are tz-aware Asia/Kolkata"
    before = os.path.getmtime(prov["cache"])
    again = ace.build_cache(w["csv"], w["out"])
    assert again["built_at"] == prov["built_at"] and os.path.getmtime(prov["cache"]) == before


def test_security_master_bridges_accord_code_to_isin_and_keeps_unmapped_codes(small_world):
    w = small_world
    sm = ace.security_master(w["xlsx"], w["csv"], w["out"])
    by = sm.set_index("accord_code")
    assert by.loc[100001, "isin"] == "INE000A01011" and by.loc[100001, "nse_symbol"] == "ALPHA"
    assert pd.isna(by.loc[999999, "isin"]) and by.loc[999999, "in_ace"]
    assert by.loc[999999, "company_name"] == "Delisted Co."       # name comes from the Ace file
    assert not by.loc[100004, "in_ace"]                             # in the master, never priced
    assert os.path.exists(os.path.join(w["out"], "security_master.csv"))


def test_wide_panel_is_keyed_by_isin_and_drops_unmapped_codes(small_world, monkeypatch):
    w = small_world
    monkeypatch.setattr(sources, "ACE_PRICES_CSV", w["csv"])
    monkeypatch.setattr(sources, "NIFTY500_HOLDINGS_XLSX", w["xlsx"])
    close = ace.wide("close", out_dir=w["out"])
    assert list(close.columns) == ["INE000A01011", "INE000B01012", "INE000C01013"]
    assert close.shape == (30, 3) and close.index.name == "date"
    by_code = ace.wide("close", key="accord_code", out_dir=w["out"])
    assert 999999 in by_code.columns and by_code.shape == (30, 4)
    p = ace.panel(["close", "mcap_cr"], out_dir=w["out"])
    assert p["close"].shape == p["mcap_cr"].shape
    assert np.allclose(p["mcap_cr"].to_numpy(), p["close"].to_numpy() * 1.5)


def test_load_long_filters_by_date_and_rejects_unknown_fields(small_world, monkeypatch):
    w = small_world
    monkeypatch.setattr(sources, "ACE_PRICES_CSV", w["csv"])
    monkeypatch.setattr(sources, "NIFTY500_HOLDINGS_XLSX", w["xlsx"])
    df = ace.load_long(["close", "unadj_close"], out_dir=w["out"], start="2024-01-15", end="2024-01-19")
    assert df["date"].min() == pd.Timestamp("2024-01-15") and df["date"].max() == pd.Timestamp("2024-01-19")
    assert set(df.columns) == {"date", "accord_code", "isin", "close", "unadj_close"}
    assert np.allclose(df["unadj_close"], df["close"] * 2)
    with pytest.raises(ace.AceDataError, match="unknown field"):
        ace.load_long(["dividend"], out_dir=w["out"])


def test_trading_calendar_is_the_dates_in_the_file(small_world, monkeypatch):
    w = small_world
    monkeypatch.setattr(sources, "ACE_PRICES_CSV", w["csv"])
    cal = ace.trading_calendar(out_dir=w["out"], min_securities=2)
    assert len(cal) == 30 and cal.equals(pd.DatetimeIndex(w["dates"], name="date"))


def test_a_file_without_the_ace_columns_is_refused(tmp_path):
    bad = tmp_path / "x.csv"
    pd.DataFrame({"Date": ["2020-01-01"], "Close": [1.0]}).to_csv(bad, index=False)
    with pytest.raises(ace.AceDataError, match="expected Ace columns are missing"):
        ace.build_cache(str(bad), str(tmp_path / "c"))


def test_a_missing_file_names_the_path_and_the_override(tmp_path):
    with pytest.raises(FileNotFoundError, match="LIGHTYEAR_|environment variable"):
        ace.build_cache(str(tmp_path / "nope.csv"), str(tmp_path / "c"))


@pytest.mark.skipif(not (os.path.isfile(sources.ACE_PRICES_CSV) and os.path.isfile(sources.NIFTY500_HOLDINGS_XLSX)),
                    reason="the real Ace file and holdings workbook are not on this machine")
def test_live_ace_file_matches_what_the_module_documents():
    prov = ace.provenance()
    assert prov["first_date"] == "2000-01-03" and prov["securities"] >= 4000 and prov["rows"] > 9_000_000
    assert prov["dropped_rows"]["bad_date"] == 0
    sm = ace.security_master()
    assert sm["isin"].notna().sum() > 3500 and not sm["isin"].dropna().duplicated().any()
    cal = ace.trading_calendar()
    assert cal.is_monotonic_increasing and cal.is_unique and len(cal) > 6000
