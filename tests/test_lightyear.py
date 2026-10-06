"""Lightyear end to end with a stand-in for Claude Code: upload -> Gate A -> approve -> Gate B -> decision.
No model, no network, no market data."""
import importlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTYEAR_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("LIGHTYEAR_CLAUDE", os.path.join(REPO, "tests", "fake_claude.py"))
    monkeypatch.setenv("LY_TEST_CARDS", str(tmp_path / "cards"))
    monkeypatch.setenv("LIGHTYEAR_SKIP_RECALC", "1")
    monkeypatch.setenv("LIGHTYEAR_SKIP_REVIEW", "1")
    import lightyear.paths, lightyear.jobs, lightyear.server
    for m in (lightyear.paths, lightyear.jobs, lightyear.server):
        importlib.reload(m)
    from fastapi.testclient import TestClient
    with TestClient(lightyear.server.app) as c:
        yield c


def wait_for(client, rid, statuses, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/runs/{rid}").json()
        if st["status"] in statuses:
            return st
        time.sleep(0.3)
    raise AssertionError(f"run stuck at {st['status']}: {st.get('error')}")


def test_full_flow(client):
    page = client.get("/")
    assert page.status_code == 200 and "<title>Lightyear</title>" in page.text
    paper = client.get("/api/papers").json()[0]
    assert client.post("/api/runs", data={"operator": " ", "existing": paper}).status_code in (400, 422)
    assert client.post("/api/runs", data={"operator": "Tester"}).status_code == 400      # no default paper
    rid = client.post("/api/runs", data={"operator": "Tester", "existing": paper}).json()["id"]

    st = wait_for(client, rid, ["gate_a", "failed"])
    assert st["status"] == "gate_a", st.get("error")
    assert all(st["stages"][s] == "done" for s in ["00", "01", "02", "03m", "GA"])
    assert st["phase_a"]["paper_title"] == "A Test Paper"
    log = client.get(f"/api/runs/{rid}/log").json()["items"]
    assert any(e["kind"] == "stage" for e in log)

    assert client.post(f"/api/runs/{rid}/decide", json={"decision": "APPROVE", "by": "x", "rationale": "y"}).status_code == 409
    assert client.post(f"/api/runs/{rid}/approve", json={"by": ""}).status_code == 400
    assert client.post(f"/api/runs/{rid}/approve", json={"by": "Tester", "notes": "use 12-1"}).status_code == 200

    st = wait_for(client, rid, ["gate_b", "failed"])
    assert st["status"] == "gate_b", st.get("error")
    assert all(st["stages"][s] == "done" for s in ["03", "04", "05", "06", "07", "GB"])
    ch = client.get(f"/api/runs/{rid}/charts").json()
    assert len(ch["dates"]) == 401 and ch["growth"]["strategy"][0] == 100
    assert client.get(f"/api/runs/{rid}/workbook").status_code == 200

    bad = client.post(f"/api/runs/{rid}/decide", json={"decision": "APPROVE", "by": "Tester", "rationale": ""})
    assert bad.status_code == 400
    ok = client.post(f"/api/runs/{rid}/decide", json={"decision": "OBSERVE", "by": "Tester", "rationale": "thin evidence"})
    assert ok.status_code == 200
    st = client.get(f"/api/runs/{rid}").json()
    assert st["status"] == "decided" and st["decision"]["decided_by"] == "Tester"
    ledger = os.path.join(os.environ["LIGHTYEAR_RUNS"], "decisions.jsonl")
    assert json.loads(open(ledger).read().splitlines()[-1])["decision"] == "OBSERVE"


def test_stage_tracker_moves_forward_only_and_reads_banners(client):
    from lightyear import jobs
    paper = client.get("/api/papers").json()[0]
    rid = jobs.create(f"docs/papers/{paper}", "x", "Tester", "", False)
    jobs.update(rid, status="phase_b", current_stage=None)
    B = jobs.IDS_B
    jobs._detect(rid, "LIGHTYEAR-STAGE: 03\nchecking data", B, "text")
    jobs._detect(rid, "=====\nSTAGE 05 -- BUILD AND EXECUTE\n=====", B, "tool")      # loose: 03 -> 05 is two steps, allowed
    st = jobs.load(rid)
    assert st["current_stage"] == "05" and st["stages"]["04"] == "done" and st["stages"]["03"] == "done"
    jobs._detect(rid, "LIGHTYEAR-STAGE: 03", B, "text")                                # never backwards
    assert jobs.load(rid)["current_stage"] == "05"
    jobs._detect(rid, "I will stop at STAGE 0 or so", B, "tool")                       # not a phase-B id
    jobs._detect(rid, "Stage 7 then Gate B", B, "text")                                # loose lead: 05 -> 07 ok
    assert jobs.load(rid)["current_stage"] == "07"
    e = jobs.eta(jobs.load(rid))
    assert e["until"] == "Gate B" and e["minutes_left"] > 0 and e["phase_total"] >= e["minutes_left"] - 1


def test_observations_are_plain_and_signed():
    from lightyear import charts
    d = pd.bdate_range("2022-01-03", periods=600)
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"date": d, "strategy": rng.normal(8e-4, 0.006, 600), "benchmark": rng.normal(2e-4, 0.012, 600)})
    out = charts.build(df, {"strategy": "S", "benchmark": "NIFTY 500"})["observations"]
    assert any("Smoother ride" in p for p in out["positives"])
    assert all(isinstance(x, str) and "%" in x or "correlation" in x for x in out["positives"] + out["negatives"])


def test_gate_rows_advisory_with_a_value_is_a_fail_not_not_computed():
    from lightyear import gates
    rows = gates.rows([
        {"name": "turnover", "passed": False, "blocking": False, "value": "627%", "threshold": "<=400%"},
        {"name": "differentiated", "passed": False, "blocking": False, "value": "NO COMPARISON", "threshold": "<=0.8"},
        {"name": "alpha", "passed": False, "blocking": True, "value": "-2.5", "threshold": "|t|>=2.0"},
        {"name": "dsr", "passed": True, "blocking": True, "value": 0.97, "threshold": 0.95}])
    assert [r["result"] for r in rows] == ["FAIL (advisory)", "not computed", "PASS", "PASS"]
    assert rows[0]["value"] == pytest.approx(6.27) and rows[0]["threshold"] == pytest.approx(4.0)
    assert rows[3]["op"] == ">="


def test_workbook_has_trades_holdings_comparators_and_gate_formulas(tmp_path):
    import openpyxl
    from lightyear import charts, workbook
    d = pd.bdate_range("2023-01-02", periods=120)
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"date": d, "strategy": rng.normal(5e-4, 0.01, 120), "benchmark": rng.normal(3e-4, 0.01, 120)})
    hold = pd.DataFrame({"date": ["2023-01-02"] * 3 + ["2023-04-03"] * 2, "symbol": ["A", "B", "C", "A", "D"],
                         "leg": ["long", "long", "short", "long", "short"], "weight": [0.65, 0.65, -0.3, 1.3, -0.3]})
    cmp = pd.DataFrame({"date": d, "Long leg only": rng.normal(6e-4, 0.012, 120)})
    res = {"strategy_name": "S", "benchmark_name": "NIFTY 500", "headline": "h", "evidence_supports": "OBSERVE",
           "gate_b": {"decision": "PENDING", "criteria": [
               {"name": "turnover", "passed": False, "blocking": False, "value": "627%", "threshold": "<=400%"}]},
           "validation": [], "notes": [], "strengths": ["s1"], "weaknesses": ["w1"]}
    ch = charts.build(df, {"strategy": "S"}, comparators=cmp)
    out = tmp_path / "w.xlsx"
    workbook.build(str(tmp_path), res, df, "t", str(out), holdings=hold, comparators=cmp,
                   observations=ch["observations"], review={"verdict": "v", "strengths": ["r1"], "red_flags": ["f1"]})
    wb = openpyxl.load_workbook(out)
    for sh in ("Summary", "Returns", "Comparators", "Holdings", "Rebalances", "Trades", "Positives & negatives"):
        assert sh in wb.sheetnames, sh
    assert wb["Returns"]["D2"].value == 100 and wb["Returns"]["D3"].value == "=D2*(1+B3)"
    assert wb["Summary"]["B19"].value.startswith("=IF(C19<=E19")
    tr = workbook.derive_trades(hold)
    assert set(zip(tr.symbol, tr.action)) == {("A", "BUY"), ("B", "BUY"), ("C", "SHORT"), ("A", "ADD"), ("B", "SELL"),
                                              ("C", "COVER"), ("D", "SHORT")}
    assert "comparators" in ch and ch["growth"]["strategy"][0] == 100 and len(ch["dates"]) == 121


def test_contract_rejects_percent_returns(tmp_path):
    from lightyear import contract
    d = pd.bdate_range("2022-01-03", periods=100)
    pd.DataFrame({"date": d, "strategy": np.full(100, 1.2), "benchmark": 0.001}).to_csv(tmp_path / "daily_returns.csv", index=False)
    json.dump({"strategy_name": "s", "benchmark_name": "b", "headline": "h", "evidence_supports": "REJECT",
               "gate_b": {"decision": "PENDING", "criteria": []}, "validation": [], "notes": []},
              open(tmp_path / "results.json", "w"))
    with pytest.raises(contract.ContractError, match="percentages"):
        contract.check_results(str(tmp_path))


def test_contract_rejects_a_model_decision(tmp_path):
    from lightyear import contract
    d = pd.bdate_range("2022-01-03", periods=100)
    pd.DataFrame({"date": d, "strategy": 0.001, "benchmark": 0.001}).to_csv(tmp_path / "daily_returns.csv", index=False)
    json.dump({"strategy_name": "s", "benchmark_name": "b", "headline": "h", "evidence_supports": "PROMOTE",
               "gate_b": {"decision": "APPROVED", "criteria": []}, "validation": [], "notes": []},
              open(tmp_path / "results.json", "w"))
    with pytest.raises(contract.ContractError, match="PENDING"):
        contract.check_results(str(tmp_path))


def test_chart_metrics_count_every_return_including_the_first():
    from lightyear import charts
    d = pd.Series(pd.bdate_range("2022-01-03", periods=300))
    r = pd.Series(np.random.default_rng(1).normal(5e-4, 0.01, 300))
    m = charts.metrics(r, d)
    v = 100 * np.r_[1.0, np.cumprod(1 + r.values)]          # 100 at the close before the first return
    years = (d.iloc[-1] - pd.Timestamp("2021-12-31")).days / 365.25
    assert abs(m["final"] - v[-1]) < 1e-9
    assert abs(m["cagr"] - ((v[-1] / 100) ** (1 / years) - 1)) < 1e-12
    assert abs(m["vol"] - r.std(ddof=1) * np.sqrt(252)) < 1e-12
    assert abs(m["max_dd"] - (-(v / np.maximum.accumulate(v) - 1).min())) < 1e-12
