# Quant AI Researcher
"""A metric name means one thing. This fails if any two code paths give different values for the same name."""
import json
import os
import re
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
HURDLE = core.daily_cash(0.05)      # config/fund.yaml sharpe_hurdle


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
    want = {"cagr": core.cagr(v), "vol": core.ann_vol(r), "sharpe": core.sharpe(r, HURDLE), "max_dd": core.max_drawdown(v),   # the hurdle, never the cash series passed in
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
    assert ch["cash_rate"] == RATE and ch["sharpe_hurdle"] == 0.05
    v = core.value_from_returns(r, start=charts.start_date(pd.Series(r.index)))
    assert m["sharpe"] == pytest.approx(core.sharpe_geometric(v, 0.05, r), rel=1e-12)       # the headline: (CAGR - 5%) / volatility
    assert m["sharpe"] == pytest.approx((m["cagr"] - 0.05) / m["vol"], rel=1e-12)
    assert m["sortino"] == pytest.approx(core.sortino_geometric(v, 0.05, r), rel=1e-12)
    assert m["sharpe_arithmetic"] == pytest.approx(core.sharpe(r, HURDLE), rel=1e-12)      # yearly and Gate B figures use this form
    assert m["sortino_arithmetic"] == pytest.approx(core.sortino(r, HURDLE), rel=1e-12)
    assert m["beta"] == pytest.approx(core.beta(r, b, CASH), rel=1e-12)
    assert m["vol"] == pytest.approx(core.ann_vol(r), rel=1e-12)
    assert m["information_ratio"] == pytest.approx(core.information_ratio(r, b), rel=1e-12)


def test_yearly_sharpe_is_arithmetic_and_the_headline_is_geometric(data):
    r, b = data
    ch = charts.build(_frame(r, b), {"strategy": "S"}, cash_rate=RATE)
    assert ch["sharpe_basis"] == "geometric"
    by_year = core.calendar_year_sharpe(r, HURDLE)
    assert ch["calendar"]["sharpe_arithmetic"]["strategy"] == pytest.approx(list(by_year), rel=1e-12)
    assert by_year.iloc[1] == pytest.approx(core.sharpe(r[r.index.year == by_year.index[1]], HURDLE), rel=1e-12)
    # the cash rate on the card moves neither Sharpe: only the hurdle does
    other = charts.build(_frame(r, b), {"strategy": "S"}, cash_rate=0.0)
    for k in ("sharpe", "sortino", "sharpe_arithmetic", "sortino_arithmetic"):
        assert other["metrics"]["strategy"][k] == ch["metrics"]["strategy"][k], k


def test_with_no_cash_rate_on_the_card_beta_is_blank_not_guessed(data):
    r, b = data
    m = charts.build(_frame(r, b), {"strategy": "S"})["metrics"]["strategy"]
    assert m["beta"] is None                                              # beta needs the card's cash rate
    assert m["sharpe_arithmetic"] == pytest.approx(core.sharpe(r, HURDLE), rel=1e-12)   # Sharpe needs only the hurdle
    assert m["sharpe"] == pytest.approx((m["cagr"] - 0.05) / m["vol"], rel=1e-12)
    assert m["cagr"] is not None       # what needs no cash rate is still there


def test_the_workbook_formulas_agree_with_the_dashboard_after_recalculation(data, tmp_path):
    """The Excel path, recalculated. Fails, never skips, where LibreOffice is not installed."""
    r, b = data
    df = _frame(r.iloc[:300], b.iloc[:300])
    ch = charts.build(df, {"strategy": "S"}, cash_rate=RATE)
    res = {"strategy_name": "S", "benchmark_name": "NIFTY 500", "headline": "h", "evidence_supports": "OBSERVE",
           "gate_b": {"decision": "PENDING", "criteria": []}, "validation": [], "notes": []}
    out = tmp_path / "w.xlsx"
    workbook.build(str(tmp_path), res, df, "t", str(out), observations=ch["observations"], core_metrics=ch)
    p = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "xlsx_recalc_libreoffice.py"), str(out)], capture_output=True, text=True, timeout=300, check=False)
    rec = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
    # never skipped (hard rule, 2026-11-11): a machine that cannot recalculate cannot vouch for the workbook
    assert rec.get("status") == "success", f"LibreOffice is required to check Excel against Python (set SOFFICE): {(p.stdout or p.stderr)[:200]}"
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
    card = SimpleNamespace(paper=SimpleNamespace(date="2015"), universe=SimpleNamespace(cash_asset="CASH_PROXY_CONSTANT_8PCT"), costs=SimpleNamespace(spread_bps=0.0))
    monkeypatch.setattr(jobs, "load_card", lambda p: card)
    df = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=70), "strategy": 0.001, "benchmark": 0.001})
    out, warn = jobs._core_inputs({"phase_a": {"card_path": "cards/x.yaml"}}, {"headline_cost_bp": 0}, df, {})
    assert out["cash_rate"] == 0.08 and out["cash_source"] == "the card" and out["publication_date"] == "2015"
    assert out["card_bp"] == 0.0
    assert any("Turnover not computed" in w for w in warn)


def test_a_card_with_no_rate_gets_no_invented_rate_and_says_so():
    from ros import config
    rate, src = config.cash_rate_for(SimpleNamespace(universe=SimpleNamespace(cash_asset=None)))
    assert rate == 0.0 and "names no rate" in src
    assert config.cash_rate_for(SimpleNamespace(universe=SimpleNamespace(cash_asset="CASH_PROXY_CONSTANT_8PCT"))) == (0.08, "the card")


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


def test_at_zero_on_the_card_gross_is_the_only_number_and_no_other_cost_appears(data):
    r, b = data
    t = pd.Series(0.05, index=r.index)
    zero = charts.build(_frame(r, b), {"strategy": "S"}, cash_rate=RATE, turnover=t, card_bp=0.0)
    assert zero["card_bp"] == 0.0 and zero["gross"] is None
    assert zero["metrics"]["strategy"]["sharpe_arithmetic"] == pytest.approx(core.sharpe(r, HURDLE), rel=1e-12)
    costed = charts.build(_frame(r, b), {"strategy": "S"}, cash_rate=RATE, turnover=t, card_bp=30.0)
    assert costed["gross"]["cagr"] > costed["metrics"]["strategy"]["cagr"]
    assert costed["metrics"]["strategy"]["sharpe_arithmetic"] == pytest.approx(core.sharpe(r, HURDLE), rel=1e-12)    # as run is the card's cost


def test_no_cost_or_cash_number_is_written_into_live_code():
    """The card sets a run's cost and cash; config holds only appendix grids. Anything else is what this repo once charged by mistake."""
    bad = re.compile(r"house_(bp|cost|round)|default_cash_rate|DEFAULT_RISK_FREE|\b\d+bp (round trip|house)|\bhouse floor\b|SPREAD_BPS\s*=|spread_bps\s*[:=]\s*(float\s*=\s*)?\d|cash_rate\s*:\s*float\s*=\s*\d|--cash-rate\", type=float, default=\d")
    hits = []
    for root in ("ros", "lightyear", "universal_backtester", "validate", "scripts", "config"):
        for dp, dn, fn in os.walk(os.path.join(REPO, root)):
            dn[:] = [d for d in dn if d not in ("vendor", "__pycache__", "universe_v2", "gate_v2")]
            for f in fn:
                if f.endswith((".py", ".yaml", ".html")):
                    with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                        hits += [f"{f}: {m.group(0)}" for m in bad.finditer(fh.read())]
    assert not hits, hits
