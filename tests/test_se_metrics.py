# Quant AI Researcher
"""SE Return Analytics (monthly): ros/metrics/se.py against the reference sheet, and Python against Excel.

  - The reference check feeds the reference workbook's own monthly returns to Python and compares every stored result to
    1e-9. The reference holds real fund returns and is never in git: this test runs only where reference/SE_Metrics.xlsx
    exists.
  - The synthetic check runs on every machine: it builds the SE sheet from a committed synthetic fixture, recalculates it,
    and reads the workbook's own "Python vs Excel" sheet. Desktop Excel is used where installed. Under LibreOffice the
    cells built on LET / SCAN / LAMBDA cannot be calculated: they are reported, never rewritten to suit the engine, and
    every other figure must still agree.
"""
import json
import os
import subprocess
import sys

import numpy as np
import openpyxl
import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from lightyear import se_sheet
from ros.metrics import se

REFERENCE = os.path.join(REPO, "reference", "SE_Metrics.xlsx")
FIXTURE = os.path.join(REPO, "tests", "fixtures", "se_synthetic_daily.csv")
# figures that rest on a LET / SCAN / LAMBDA cell: the only ones LibreOffice may fail
NEEDS_EXCEL = ("Max Drawdown", "Average Annual Max Drawdown", "Calmar Ratio", "Sterling Ratio", "CY")


def _recalc(path) -> dict:
    """scripts/xlsx_recalc.py in its own process (Excel is driven over COM, which stays out of the test process)."""
    p = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "xlsx_recalc.py"), path], capture_output=True, text=True, timeout=900, check=False)
    out = (p.stdout or "").strip()
    return json.loads(out) if out.startswith("{") else {"status": "failed", "error": (p.stderr or out)[-400:]}


def _daily():
    d = pd.read_csv(FIXTURE, parse_dates=["date"]).set_index("date")
    return d["strategy"], d["benchmark"]


def test_python_reproduces_every_stored_result_of_the_reference():
    if not os.path.isfile(REFERENCE):
        pytest.skip("reference/SE_Metrics.xlsx is not on this machine (it holds real fund returns and is never in git)")
    ws = openpyxl.load_workbook(REFERENCE, data_only=True)["SE Return Analytics"]
    rows = [r for r in range(5, 400) if isinstance(ws.cell(r, 3).value, (int, float))]
    idx = pd.DatetimeIndex([ws.cell(r, 2).value for r in rows])
    s, b = (pd.Series([ws.cell(r, c).value for r in rows], index=idx) for c in (3, 4))
    inp_row = next(r for r in range(60, 200) if ws.cell(r, 9).value == "Drawdown limit")
    out = se.compute(s, b, {"drawdown_limit": ws.cell(inp_row, 10).value or 0.0, "omega_threshold": ws.cell(inp_row + 1, 10).value,
                            "risk_free_rate": ws.cell(inp_row + 2, 10).value})
    lab = {" ".join(str(ws.cell(r, 10).value).split()): r for r in range(5, 58) if ws.cell(r, 10).value}
    suffix = {"Ret +Ve", "Ret -Ve", "Ex. Ret +Ve", "Ex. Ret -Ve"}
    bad, n = [], 0
    for _sec, name, cols, _fmt, _xl in se.SPEC:
        r = next(v for k, v in lab.items() if k == name or (name in suffix and k.startswith(name + " ")))
        for col, i in ((11, 0), (12, 1)):
            if i == 1 and cols != "SB":
                continue
            n += 1
            if abs(ws.cell(r, col).value - out["values"][name][i]) > 1e-9:
                bad.append((name, i))
    for key, first_label, after in (("financial_year", "FY", 58), ("calendar_year", "CY", 58), ("calendar_year_drawdown", "CY", 90)):
        r0 = next(r for r in range(after, 200) if str(ws.cell(r, 10).value).startswith(first_label) and ws.cell(r, 11).value is not None)
        for k, t in enumerate(out["tables"][key]):
            assert str(ws.cell(r0 + k, 10).value) == t["label"]
            for col, w in ((11, "strategy"), (12, "benchmark")):
                n += 1
                if abs(ws.cell(r0 + k, col).value - t[w]) > 1e-9:
                    bad.append((key, t["label"], w))
    for t in out["tables"]["quarterly"]:
        for col, w in ((6, "strategy"), (7, "benchmark")):
            n += 1
            if abs(ws.cell(5 + t["last"], col).value - t[w]) > 1e-9:
                bad.append(("quarterly", t["label"], w))
    assert n >= 270 and not bad, bad


def test_the_quirks_of_the_reference_are_reproduced_not_corrected():
    idx = pd.date_range("2020-01-31", periods=6, freq="ME")
    s = pd.Series([-0.10, 0.05, 0.0, 0.04, -0.02, 0.03], index=idx)
    b = pd.Series([-0.06, 0.06, 0.01, 0.02, -0.01, 0.02], index=idx)
    v = se.compute(s, b)["values"]
    assert v["Negative Months"][0] == 3 and v["Positive Months"][0] == 3          # a flat month counts as negative
    assert v["Max Drawdown"][0] == pytest.approx(-0.02)                          # the 10% loss in month one is not a drawdown
    assert v["Jensens Alpha (Adj Beta)"][0] == pytest.approx(v["CAGR"][0] - v["CAGR"][1] * v["Beta"][0])    # no risk-free rate
    assert v["Sortino Ratio"][0] == pytest.approx((v["CAGR"][0] - 0.05) / (np.std([-0.10, 0.0, -0.02]) * np.sqrt(12)))
    assert v["Information Ratio"][0] == pytest.approx(v["Alpha"][0] / v["Tracking Error"][0])
    assert v["Annualized Volatility"][0] == pytest.approx(np.std(s.to_numpy()) * np.sqrt(12))   # population, not sample
    assert v["95% VaR"][0] < 0 and v["Max Drawdown"][0] < 0                      # losses are negative in this block
    assert v["Beta"][1] == pytest.approx(1.0) and v["Alpha"][1] is None


def test_periods_come_from_the_dates_of_the_run_and_part_years_are_marked():
    s, b = _daily()
    blk = se.block(s, b, "NIFTY 500", "price")
    fy, cy = blk["tables"]["financial_year"], blk["tables"]["calendar_year"]
    assert fy[0]["label"].endswith("*") and fy[0]["part"] and cy[0]["part"] and cy[-1]["label"].endswith("**")
    assert sum(t["last"] - t["first"] + 1 for t in cy) == blk["n_months"]
    assert blk["benchmark_label"] == "NIFTY 500 (price index, no dividends)"
    assert all(r["depends_on_benchmark"] for r in blk["rows"] if r["section"] == "Capture Ratio")
    assert blk["title"].endswith("(monthly)")


@pytest.fixture(scope="module")
def synthetic_workbook(tmp_path_factory):
    s, b = _daily()
    blk = se.block(s, b, "Benchmark", "price")
    wb = openpyxl.Workbook()
    wr = wb.active
    wr.title = "Returns"
    wr.append(["Date", "Strategy", "Benchmark"])
    wr.append([(s.index[0] - pd.offsets.BDay(1)).to_pydatetime(), None, None])
    for d, x, y in zip(s.index, s, b):
        wr.append([d.to_pydatetime(), float(x), float(y)])
    where = se_sheet.write_se_sheet(wb, blk, "Strategy", 3, 2 + len(s))
    chk = se_sheet.write_check_sheet(wb, se_sheet.check_items(blk, where))
    path = str(tmp_path_factory.mktemp("se") / "se.xlsx")
    wb.save(path)
    rec = _recalc(path)
    assert rec.get("status") in ("success", "errors_found"), f"the workbook could not be recalculated (Excel or LibreOffice is required): {rec}"
    return path, where, chk, rec


def test_every_se_cell_is_a_formula_and_no_fund_name_is_written(synthetic_workbook):
    path, where, _chk, _rec = synthetic_workbook
    ws = openpyxl.load_workbook(path)[se_sheet.SHEET]
    for name, row in where["rows"].items():
        v = ws[f"K{row}"].value
        text = v.text if hasattr(v, "text") else v
        assert isinstance(text, str) and text.startswith("="), (name, v)
    for col in ("C", "D"):
        v = ws[f"{col}{where['first']}"].value
        assert (v.text if hasattr(v, "text") else v).startswith("="), "monthly returns are formulas over the Returns sheet"
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert "Systematic Equity" not in text and "[1]" not in text          # no fund name, no external link
    assert ws[where["inputs"]["RF"].replace("$", "")].value == 0.05


def test_python_and_excel_agree_on_the_synthetic_fixture(synthetic_workbook):
    path, _where, chk, rec = synthetic_workbook
    ws = openpyxl.load_workbook(path, data_only=True)[se_sheet.CHECK]
    rows = [[c.value for c in r] for r in ws.iter_rows(min_row=chk["first"], max_row=chk["last"])]
    assert len(rows) == chk["n"] > 300
    fails = [r for r in rows if r[5] != "OK"]
    if rec["engine"] == "excel":
        assert not fails, fails[:10]
        assert rec["total_errors"] == 0 and str(ws[chk["result_cell"]].value).startswith("ALL ")
    else:
        # LibreOffice: only the figures resting on LET / SCAN / LAMBDA may be missing, and they are reported, not hidden
        other = [r for r in fails if not any(k in str(r[1]) for k in NEEDS_EXCEL)]
        assert not other, other[:10]
        assert rec["n_not_calculated"] > 0 and rec["total_errors"] == 0
        print(f"LibreOffice could not calculate {rec['n_not_calculated']} cell(s): {rec['not_calculated'][:8]}")
