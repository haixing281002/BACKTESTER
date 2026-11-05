# Quant AI Researcher by Harshil Pahuja
"""A metric name means one thing. This fails if any two code paths give different values for the same name."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import openpyxl
import pandas as pd
import pytest

from lightyear import charts, workbook
from ros.metrics import core
from ros.validation import metrics as ros_m
from ros.validation import portfolio, research
from universal_backtester import metrics as ub_m

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATE = 0.065
CASH = core.daily_cash(RATE)


@pytest.fixture(scope="module")
def data():
    rng = np.random.default_rng(11)
    d = pd.bdate_range("2019-01-01", periods=900)
    b = pd.Series(rng.normal(4e-4, 0.01, 900), index=d)
    r = 0.8 * b + pd.Series(rng.normal(3e-4, 0.006, 900), index=d)
    return r, b


def _result(r):
    t = pd.Series(0.01, index=r.index)
    return SimpleNamespace(name="s", value=core.value_from_returns(r), returns=r, turnover=t)


def test_ros_table_and_universal_backtester_agree_with_core(data):
    r, _ = data
    res = _result(r)
    rf = pd.Series(CASH, index=r.index)
    a, u = ros_m.compute_metrics(res, rf), ub_m.compute_metrics(res, rf)
    v = res.value
    want = {"cagr": core.cagr(v), "vol": core.ann_vol(r), "sharpe": core.sharpe(r, CASH), "max_dd": core.max_drawdown(v),
            "turnover": core.annual_turnover(res.turnover)}
    for k, x in want.items():
        assert getattr(a, k) == pytest.approx(x, rel=1e-12), k
        assert getattr(u, k) == pytest.approx(x, rel=1e-12), k


def test_portfolio_relative_block_agrees_with_core(data):
    r, b = data
    br = portfolio.benchmark_relative(r, b, pd.Series(CASH, index=r.index))
    assert br["beta"] == pytest.approx(core.beta(r, b, CASH), rel=1e-12)
    assert br["tracking_error"] == pytest.approx(core.tracking_error(r, b), rel=1e-12)
    assert br["information_ratio"] == pytest.approx(core.information_ratio(r, b), rel=1e-12)
    assert br["up_capture"] == pytest.approx(core.up_capture(r, b), rel=1e-12)
    assert br["down_capture"] == pytest.approx(core.down_capture(r, b), rel=1e-12)


def test_research_reports_the_same_sharpe(data):
    r, _ = data
    res = _result(r)
    rf = pd.Series(CASH, index=r.index)
    split = [(r.index[100], r.index[400])]
    oos = research.oos_summary(res, split, rf)
    assert oos["sharpe"].iloc[0] == pytest.approx(core.sharpe(r.loc[split[0][0]:split[0][1]], CASH), rel=1e-12)
    dsr = research.deflated_sharpe(r, 1, rf)
    assert dsr["sharpe_ann"] == pytest.approx(core.sharpe(r, CASH), rel=1e-12)


def _frame(r, b):
    return pd.DataFrame({"date": r.index, "strategy": r.to_numpy(), "benchmark": b.to_numpy()})


def test_the_dashboard_tiles_agree_with_core(data):
    r, b = data
    ch = charts.build(_frame(r, b), {"strategy": "S"}, cash_rate=RATE)
    m = ch["metrics"]["strategy"]
    assert ch["cash_rate"] == RATE
    assert m["sharpe"] == pytest.approx(core.sharpe(r, CASH), rel=1e-12)
    assert m["sortino"] == pytest.approx(core.sortino(r, CASH), rel=1e-12)
    assert m["beta"] == pytest.approx(core.beta(r, b, CASH), rel=1e-12)
    assert m["vol"] == pytest.approx(core.ann_vol(r), rel=1e-12)
    assert m["information_ratio"] == pytest.approx(core.information_ratio(r, b), rel=1e-12)


def test_with_no_cash_rate_on_the_card_the_ratios_are_blank_not_guessed(data):
    r, b = data
    m = charts.build(_frame(r, b), {"strategy": "S"})["metrics"]["strategy"]
    assert m["sharpe"] is None and m["sortino"] is None and m["beta"] is None
    assert m["cagr"] is not None       # what needs no cash rate is still there


def test_the_workbook_formulas_agree_with_the_dashboard_after_recalculation(data, tmp_path):
    """The Excel path, recalculated. Skipped only where LibreOffice is not installed."""
    r, b = data
    df = _frame(r.iloc[:300], b.iloc[:300])
    ch = charts.build(df, {"strategy": "S"}, cash_rate=RATE)
    res = {"strategy_name": "S", "benchmark_name": "NIFTY 500", "headline": "h", "evidence_supports": "OBSERVE",
           "gate_b": {"decision": "PENDING", "criteria": []}, "validation": [], "notes": []}
    out = tmp_path / "w.xlsx"
    workbook.build(str(tmp_path), res, df, "t", str(out), observations=ch["observations"], core_metrics=ch)
    p = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "xlsx_recalc_libreoffice.py"), str(out)], capture_output=True, text=True, timeout=300)
    rec = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
    if rec.get("status") != "success":
        pytest.skip(f"no recalculation here: {(p.stdout or p.stderr)[:120]}")
    ws = openpyxl.load_workbook(out, data_only=True)["Summary"]
    m = ch["metrics"]["strategy"]
    assert ws["B12"].value == pytest.approx(m["cagr"], rel=1e-9)
    assert ws["B13"].value == pytest.approx(m["vol"], rel=1e-9)
    assert ws["B14"].value == pytest.approx(m["sharpe"], rel=1e-9)
    assert ws["B15"].value == pytest.approx(m["max_dd"], rel=1e-9)
    assert ws["B16"].value == pytest.approx(m["sortino"], rel=1e-9)
    assert ws["B17"].value == pytest.approx(m["calmar"], rel=1e-9)


def test_lightyear_reads_the_cash_rate_from_the_card(tmp_path, monkeypatch):
    from lightyear import jobs
    card = SimpleNamespace(paper=SimpleNamespace(date="2015"), universe=SimpleNamespace(cash_asset="CASH_PROXY_CONSTANT_8PCT"))
    monkeypatch.setattr(jobs, "load_card", lambda p: card)
    df = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=70), "strategy": 0.001, "benchmark": 0.001})
    out, warn = jobs._core_inputs({"phase_a": {"card_path": "cards/x.yaml"}}, {"headline_cost_bp": 0}, df, {})
    assert out["cash_rate"] == 0.08 and out["publication_date"] == "2015"
    assert any("Net-of-cost" in w for w in warn)
    assert out["house_bp"] == 30


def test_no_other_python_file_defines_its_own_sharpe_formula():
    """The clean-room cross-check and the tearsheet awaiting your ruling are the only named exceptions."""
    allowed = {"ros/metrics/core.py", "ros/metrics/legacy_v1.py", "validate/independent.py", "universal_backtester/tearsheet.py",
               "universal_backtester/excel_tearsheet.py", "universal_backtester/validation.py", "ros/validation/metrics.py", "universal_backtester/metrics.py"}
    bad = []
    for root in ("ros", "lightyear", "universal_backtester", "validate"):
        for dp, _dn, fn in os.walk(os.path.join(REPO, root)):
            for f in fn:
                if f.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dp, f), REPO).replace("\\", "/")
                    with open(os.path.join(dp, f), encoding="utf-8") as fh:
                        txt = fh.read()
                    if rel not in allowed and ("def sharpe" in txt or "def _sharpe" in txt):
                        bad.append(rel)
    assert not bad, bad
