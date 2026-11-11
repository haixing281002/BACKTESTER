# Quant AI Researcher
"""HARD RULE: Excel and Python use the same formulas. ros/metrics/core.py is the single definition of every metric; every
Excel formula in the return-analytics workbook and in the Lightyear workbook must reproduce it.

These tests write each workbook, recalculate it with LibreOffice, and FAIL if any Excel metric differs from Python by more
than 1e-6. They are never skipped: a machine without LibreOffice fails them, with the reason, because a suite that cannot
recalculate cannot vouch for the workbook. Install LibreOffice or set SOFFICE to soffice's full path.
"""
import json
import math
import os
import subprocess
import sys

import numpy as np
import openpyxl
import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from lightyear import charts, workbook
from ros import config
from ros.metrics import core
from universal_backtester import excel_tearsheet as xt

TOL = 1e-6


def recalculate(path) -> None:
    """Recalculate in place. Any failure is a test failure, never a skip."""
    p = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "xlsx_recalc_libreoffice.py"), str(path)],
                       capture_output=True, text=True, timeout=600, check=False)
    out = (p.stdout or "").strip()
    rec = json.loads(out) if out.startswith("{") else {}
    assert rec.get("status") == "success", ("the workbook could not be recalculated, so Excel cannot be checked against Python. "
                                            f"LibreOffice is required for this test (set SOFFICE). Got: {(out or p.stderr)[:300]}")
    assert rec.get("total_errors") == 0, f"formula errors after recalculation: {rec.get('error_summary')}"


def _series():
    rng = np.random.default_rng(20261111)
    idx = pd.bdate_range("2019-06-03", periods=1100)          # spans calendar and financial year ends
    b = pd.Series(rng.standard_t(5, 1100) * 0.008 + 4e-4, index=idx)
    s = 0.8 * b + pd.Series(rng.standard_t(5, 1100) * 0.006 + 3e-4, index=idx)
    return s, b, idx[0] - pd.offsets.BDay(1)


def _diffs(pairs):
    """[(what, excel, python)] -> the rows that differ by more than TOL."""
    bad = []
    for what, e, p in pairs:
        if e is None or not isinstance(e, (int, float)) or math.isnan(float(p)) or abs(float(e) - float(p)) > TOL:
            bad.append((what, e, p))
    return bad


@pytest.fixture(scope="module")
def analytics(tmp_path_factory):
    s, b, start = _series()
    path = tmp_path_factory.mktemp("xl") / "return_analytics.xlsx"
    where = xt.write_return_analytics_workbook(str(path), s, b, start, "Strategy", "Benchmark")
    recalculate(path)
    return openpyxl.load_workbook(path, data_only=True), where, xt.python_values(s, b, start)


def test_every_return_analytics_metric_equals_python(analytics):
    wb, where, py = analytics
    ws = wb[where["sheet"]]
    pairs = []
    for lab, row in where["rows"].items():
        pairs.append((f"{lab} (strategy)", ws[f"B{row}"].value, py["strategy"][lab]))
        if lab in py["benchmark"]:
            pairs.append((f"{lab} (benchmark)", ws[f"C{row}"].value, py["benchmark"][lab]))
    assert len(pairs) == len(xt.METRIC_LABELS) + 26, "every metric row must be compared"
    assert not _diffs(pairs), _diffs(pairs)


def test_every_month_and_year_table_cell_equals_python(analytics):
    wb, where, py = analytics
    wm, wy = wb["Monthly"], wb["Years"]
    pairs = []
    for k, ym in enumerate(where["months"]["keys"], start=2):
        for col, who in (("B", "strategy"), ("C", "benchmark")):
            m = py["monthly"][who]
            pairs.append((f"month {ym} {who}", wm[f"{col}{k}"].value, m[(m.index.year * 100 + m.index.month) == ym].iloc[0]))
    for k, y in enumerate(where["years"]["calendar"], start=2):
        for col, who, key in (("B", "strategy", "calendar_year"), ("C", "benchmark", "calendar_year"),
                              ("D", "strategy", "year_max_drawdown"), ("E", "benchmark", "year_max_drawdown")):
            pairs.append((f"{key} {y} {who}", wy[f"{col}{k}"].value, py[key][who][y]))
    for k, y in enumerate(where["years"]["financial"], start=2):
        for col, who in (("H", "strategy"), ("I", "benchmark")):
            pairs.append((f"financial year {y} {who}", wy[f"{col}{k}"].value, py["financial_year"][who][y]))
    assert len(pairs) > 100
    assert not _diffs(pairs), _diffs(pairs)[:10]


def test_no_return_analytics_metric_is_a_pasted_number(tmp_path):
    """Every metric cell is a formula: Excel recomputes it, nothing is typed in."""
    s, b, start = _series()
    path = tmp_path / "f.xlsx"
    where = xt.write_return_analytics_workbook(str(path), s, b, start)
    ws = openpyxl.load_workbook(path)[where["sheet"]]
    for lab, row in where["rows"].items():
        v = ws[f"B{row}"].value
        text = v.text if hasattr(v, "text") else v
        assert isinstance(text, str) and text.startswith("="), (lab, v)


def test_the_lightyear_workbook_summary_and_comparators_equal_the_dashboard(tmp_path):
    """The Lightyear workbook's formulas, recalculated, against the numbers the dashboard shows (lightyear/charts.py, which
    reads ros/metrics/core.py)."""
    s, b, _ = _series()
    df = pd.DataFrame({"date": s.index, "strategy": s.to_numpy(), "benchmark": b.to_numpy()}).iloc[:500]
    rng = np.random.default_rng(3)
    cmp = pd.DataFrame({"date": df["date"], "Equal weight": rng.normal(5e-4, 0.011, len(df)), "Momentum 50": rng.normal(6e-4, 0.013, len(df))})
    ch = charts.build(df, {"strategy": "S", "benchmark": "NIFTY 500"}, cash_rate=0.0, comparators=cmp)
    res = {"strategy_name": "S", "benchmark_name": "NIFTY 500", "headline": "h", "evidence_supports": "OBSERVE",
           "gate_b": {"decision": "PENDING", "criteria": []}, "validation": [], "notes": []}
    out = tmp_path / "w.xlsx"
    workbook.build(str(tmp_path), res, df, "t", str(out), comparators=cmp, observations=ch["observations"], core_metrics=ch)
    recalculate(out)
    wb = openpyxl.load_workbook(out, data_only=True)
    ws = wb["Summary"]
    labels = {str(ws[f"A{r}"].value): r for r in range(7, 30) if ws[f"A{r}"].value}
    hl = f"({config.hurdle_annual():.0%} hurdle)"
    want = {"CAGR": "cagr", "Annualised volatility": "vol", f"Sharpe {hl}": "sharpe", "Maximum drawdown": "max_dd",
            f"Sortino {hl}": "sortino", "Calmar": "calmar", "Final value (100 = start)": "final"}
    pairs = []
    for lab, key in want.items():
        assert lab in labels, (lab, sorted(labels))
        for col, who in (("B", "strategy"), ("C", "benchmark")):
            pairs.append((f"Summary {lab} {who}", ws[f"{col}{labels[lab]}"].value, ch["metrics"][who][key]))
    wc = wb["Comparators"]
    head = {str(wc.cell(4, c).value): c for c in range(1, 12) if wc.cell(4, c).value}
    for r in range(5, 5 + len(cmp.columns) - 1 + 2):
        nm = wc.cell(r, 1).value
        m = ch["comparators"]["metrics"].get(nm) or (ch["metrics"]["strategy"] if nm == "S" else ch["metrics"]["benchmark"] if nm == "NIFTY 500" else None)
        if m is None:
            continue
        for lab, key in (("CAGR", "cagr"), ("Annualised volatility", "vol"), (f"Sharpe {hl}", "sharpe"), ("Maximum drawdown", "max_dd")):
            pairs.append((f"Comparators {nm} {lab}", wc.cell(r, head[lab]).value, m[key]))
    # the monthly sheet: month statistics and calendar-year returns, against core's one monthly definition
    wm = wb["Monthly returns"]
    idx = pd.DatetimeIndex(df["date"])
    rs, rb = pd.Series(df["strategy"].to_numpy(), index=idx), pd.Series(df["benchmark"].to_numpy(), index=idx)
    ms, mb = core.monthly_returns(rs), core.monthly_returns(rb)
    stat = {str(wm[f"A{r}"].value): wm[f"B{r}"].value for r in range(1, wm.max_row + 1) if wm[f"A{r}"].value and wm[f"B{r}"].value is not None}
    pairs += [("Months", stat["Months"], len(ms)), ("Best month", stat["Best month (S)"], ms.max()), ("Worst month", stat["Worst month (S)"], ms.min()),
              ("Average month S", stat["Average month (S)"], ms.mean()), ("Average month benchmark", stat["Average month (NIFTY 500)"], mb.mean()),
              ("Months ahead", stat["Months S beat NIFTY 500"], int((ms - mb > 0).sum()))]
    cy = {"S: calendar view": core.calendar_year_returns(rs), "NIFTY 500: calendar view": core.calendar_year_returns(rb)}
    n_grid = 0
    for r in range(1, wm.max_row + 1):
        title = wm.cell(r, 15).value
        if title in cy:
            for k, y in enumerate(cy[title].index):
                row = r + 2 + k
                assert wm.cell(row, 15).value == y
                pairs.append((f"{title} {y} year return", wm.cell(row, 28).value, cy[title][y]))
                for m in range(1, 13):
                    cell = wm.cell(row, 15 + m).value
                    mser = ms if title.startswith("S:") else mb
                    hit = mser[(mser.index.year == y) & (mser.index.month == m)]
                    if len(hit):
                        pairs.append((f"{title} {y}-{m:02d}", cell, hit.iloc[0]))
                        n_grid += 1
    assert n_grid == len(ms) + len(mb), "every month of both calendar grids must be compared"
    assert len(pairs) >= 14 + 8 + 6 + n_grid, len(pairs)
    assert not _diffs(pairs), _diffs(pairs)[:12]


def test_python_tearsheet_module_only_delegates_to_core():
    """universal_backtester/tearsheet.py may format and arrange; it may not define a metric of its own."""
    from universal_backtester import tearsheet as ts
    s, b, start = _series()
    got = ts.compute_tearsheet_from_returns(s, b, start)
    want = core.tearsheet(s, start, config.hurdle_annual(), b)
    assert got == want
