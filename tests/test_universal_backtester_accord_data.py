"""Tests for accord_data.py, built against SYNTHETIC files that reproduce
the specific quirks found in the real Accord Fintech files (mixed sheet
schemas, empty trailing sheets, a footer row with no Accord Code, an
irregular mid-series coverage swing) -- not the real files themselves,
which are local-only and never committed (see data/raw/stocks/README.md).
If the real files are present locally, one integration test also runs
against them directly and is skipped otherwise.
"""
import os

import numpy as np
import openpyxl
import pandas as pd
import pytest

from universal_backtester.accord_data import (
    load_accord_price_panel, load_accord_fundamentals, load_accord_monthly_universe,
    diagnose_accord_dataset, DEFAULT_REPORTING_LAG_DAYS,
)

REAL_PRICE = "data/raw/stocks/price_data_till_03aug2026.xlsx"
REAL_UNIVERSE = "data/raw/stocks/Monthly_uni_new.xlsx"
REAL_VALUATION = "data/raw/stocks/valuation_ratios_all_till_2025.xlsx"


def _make_price_file(path, codes=(100001, 100002, 100003), n_days=40):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["NDP_Date", *codes])
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    rng = np.random.default_rng(0)
    for d in dates:
        ws.append([d.strftime("%Y-%m-%d"), *rng.uniform(50, 200, size=len(codes))])
    wb.save(path)


def _make_fundamentals_file(path, with_footer=True):
    rows = [
        {"Sr.No.": 1, "Accord Code": 100001, "Company Name": "Alpha Ltd.",
         "FR_Year End": 202403, "FR_Adjusted PE (x)": 25.4, "FR_EV/EBIT(x)": 18.2, "CONS_FR_1": "C"},
        {"Sr.No.": 2, "Accord Code": 100001, "Company Name": "Alpha Ltd.",
         "FR_Year End": 202303, "FR_Adjusted PE (x)": 22.1, "FR_EV/EBIT(x)": 17.0, "CONS_FR_1": "C"},
        {"Sr.No.": 3, "Accord Code": 100002, "Company Name": "Beta Ltd.",
         "FR_Year End": 202403, "FR_Adjusted PE (x)": 14.0, "FR_EV/EBIT(x)": 9.5, "CONS_FR_1": "S"},
    ]
    df = pd.DataFrame(rows)
    if with_footer:
        footer = pd.DataFrame([
            {"Sr.No.": np.nan, "Accord Code": np.nan, "Company Name": np.nan,
             "FR_Year End": np.nan, "FR_Adjusted PE (x)": np.nan, "FR_EV/EBIT(x)": np.nan, "CONS_FR_1": np.nan},
            {"Sr.No.": "Source: Ace Equity Nxt... Disclaimer: Accord...", "Accord Code": np.nan,
             "Company Name": np.nan, "FR_Year End": np.nan, "FR_Adjusted PE (x)": np.nan,
             "FR_EV/EBIT(x)": np.nan, "CONS_FR_1": np.nan},
        ])
        df = pd.concat([df, footer], ignore_index=True)
    df.to_excel(path, index=False)


def _make_universe_file(path):
    """Two schema variants, one empty trailing sheet, one big coverage swing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "31-Jan-2023"
    ws.append(["Accord Code", "Company Name", "NDP_Date", "NDP_Close", "NDP_Mcap", "NSE_symbol", "Market Rank"])
    for i, code in enumerate([100001, 100002, 100003], start=1):
        ws.append([code, f"Company{i}", "2023-01-31", 100.0 + i, 5000.0 - i * 10, f"SYM{i}", i])

    ws2 = wb.create_sheet("28-Feb-2023")   # shorter schema, no Close/Symbol
    ws2.append(["Accord Code", "Company Name", "NDP_Date", "NDP_Mcap", "Market Rank"])
    ws2.append([100001, "Company1", "2023-02-28", 4990.0, 1])

    ws3 = wb.create_sheet("31-Mar-2023")   # the coverage swing: many more names suddenly
    ws3.append(["Accord Code", "Company Name", "NDP_Date", "NDP_Mcap", "Market Rank"])
    for i in range(1, 21):
        ws3.append([100000 + i, f"Company{i}", "2023-03-31", 1000.0 - i, i])

    ws4 = wb.create_sheet("30-Apr-2023")   # completely empty trailing sheet
    wb.save(path)


@pytest.fixture(scope="module")
def synthetic_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("accord")
    price_path = d / "price.xlsx"
    fund_path = d / "fundamentals.xlsx"
    uni_path = d / "universe.xlsx"
    _make_price_file(str(price_path))
    _make_fundamentals_file(str(fund_path))
    _make_universe_file(str(uni_path))
    return str(price_path), str(fund_path), str(uni_path)


def test_price_panel_loads_with_int_codes(synthetic_files):
    price_path, _, _ = synthetic_files
    df, prov = load_accord_price_panel(price_path)
    assert list(df.columns) == [100001, 100002, 100003]
    assert df.shape[0] == 40
    assert prov["n_securities"] == 3


def test_fundamentals_drops_footer_rows_not_silently(synthetic_files):
    _, fund_path, _ = synthetic_files
    df, prov = load_accord_fundamentals(fund_path)
    assert len(df) == 3   # footer rows gone
    assert prov["n_footer_rows_dropped"] == 2
    assert set(df["accord_code"]) == {100001, 100002}


def test_fundamentals_basis_is_decoded(synthetic_files):
    _, fund_path, _ = synthetic_files
    df, _ = load_accord_fundamentals(fund_path)
    assert set(df["basis"]) == {"consolidated", "standalone"}


def test_fundamentals_known_date_is_after_fiscal_year_end_by_the_stated_lag(synthetic_files):
    _, fund_path, _ = synthetic_files
    df, _ = load_accord_fundamentals(fund_path)
    row = df[df["accord_code"] == 100001].iloc[0]
    assert row["known_date"] > row["fiscal_year_end_date"]
    assert (row["known_date"] - row["fiscal_year_end_date"]).days == DEFAULT_REPORTING_LAG_DAYS


def test_universe_loader_handles_mixed_schemas(synthetic_files):
    _, _, uni_path = synthetic_files
    df, prov = load_accord_monthly_universe(uni_path)
    # 3 rows from Jan (7-col schema) + 1 row from Feb (5-col schema, no close/symbol)
    jan = df[df["month_end"] == pd.Timestamp("2023-01-31")]
    feb = df[df["month_end"] == pd.Timestamp("2023-02-28")]
    assert len(jan) == 3
    assert len(feb) == 1
    assert jan["nse_symbol"].notna().all()
    assert feb["nse_symbol"].isna().all()   # not fabricated for the shorter schema
    assert prov["schema_variants"]
    assert len(prov["schema_variants"]) >= 2


def test_universe_loader_records_empty_sheets_not_silently(synthetic_files):
    _, _, uni_path = synthetic_files
    _, prov = load_accord_monthly_universe(uni_path)
    assert "30-Apr-2023" in prov["empty_sheets"]
    assert prov["n_empty_sheets"] == 1


def test_universe_loader_flags_the_coverage_swing(synthetic_files):
    _, _, uni_path = synthetic_files
    _, prov = load_accord_monthly_universe(uni_path)
    # Both the Jan(3)->Feb(1) drop and the Feb(1)->Mar(20) jump are real
    # >50% swings and should both be caught.
    assert prov["n_irregular_swings"] >= 2
    jump = next(s for s in prov["irregular_month_to_month_swings"] if s["rows"] > s["prev_rows"])
    assert jump["rows"] > jump["prev_rows"] * 1.5


def test_diagnose_reports_blocking_severity_for_real_problems(synthetic_files):
    price_path, _, uni_path = synthetic_files
    diag = diagnose_accord_dataset(price_path, uni_path)
    blocking = diag[diag["severity"] == "block"]
    assert len(blocking) >= 2   # empty sheet + coverage swing, at minimum
    checks = set(diag["check"])
    assert "empty universe-file sheets" in checks
    assert "month-to-month coverage swings >50%" in checks


@pytest.mark.skipif(not os.path.exists(REAL_PRICE), reason="real Accord files not present locally")
def test_against_the_real_price_file_if_present():
    df, prov = load_accord_price_panel(REAL_PRICE)
    assert df.shape[1] > 1000
    assert prov["date_min"] < "2013-01-01"


@pytest.mark.skipif(not os.path.exists(REAL_UNIVERSE), reason="real Accord files not present locally")
def test_against_the_real_universe_file_if_present():
    _, prov = load_accord_monthly_universe(REAL_UNIVERSE)
    assert prov["n_empty_sheets"] >= 1
    assert prov["n_irregular_swings"] >= 1
