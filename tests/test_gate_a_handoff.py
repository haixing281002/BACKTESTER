# Quant AI Researcher
"""Gate A -> Gate B hand-off: every human decision made at Gate A must reach Phase B, the page and the workbook.

Regression tests for the 2026-10-30 audit (run 20261030-124039-5511), where the operator's five Gate A revisions
reached the backtest only because the model happened to re-read the card: the Phase B prompt carried the (empty)
approval box alone, a crashed revision would have come back as 'Gate A assembled', and the backtest script retyped
every parameter as a literal. Lightyear runs in-process with tests/fake_claude.py standing in for Claude Code.
"""
import importlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTYEAR_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("LIGHTYEAR_CLAUDE", os.path.join(REPO, "tests", "fake_claude.py"))
    monkeypatch.setenv("LY_TEST_CARDS", str(tmp_path / "cards"))
    monkeypatch.setenv("LIGHTYEAR_SKIP_RECALC", "1")
    monkeypatch.setenv("LIGHTYEAR_SKIP_REVIEW", "1")
    papers = tmp_path / "papers"
    papers.mkdir()
    shutil.copy(os.path.join(REPO, "tests", "fixtures", "synthetic_paper.pdf"), papers / "synthetic_paper.pdf")
    monkeypatch.setenv("LIGHTYEAR_PAPERS", str(papers))
    monkeypatch.setenv("LIGHTYEAR_TOKEN_FILE", str(tmp_path / "session_token"))
    monkeypatch.setenv("LIGHTYEAR_PORT", "8100")
    import lightyear.jobs
    import lightyear.paths
    import lightyear.security
    import lightyear.server
    for m in (lightyear.paths, lightyear.security, lightyear.jobs, lightyear.server):
        importlib.reload(m)
    from fastapi.testclient import TestClient

    from lightyear import security
    with TestClient(lightyear.server.app, base_url="http://127.0.0.1:8100",
                    headers={security.HEADER: security.TOKEN}) as c:
        yield c


def wait_for(client, rid, statuses, timeout=90):
    t0 = time.time()
    st = None
    while time.time() - t0 < timeout:
        st = client.get(f"/api/runs/{rid}").json()
        if st["status"] in statuses:
            return st
        time.sleep(0.3)
    raise AssertionError(f"run stuck at {st['status']}: {st.get('error')}")


def start_run(client):
    paper = client.get("/api/papers").json()[0]
    rid = client.post("/api/runs", data={"operator": "Auditor", "existing": paper}).json()["id"]
    st = wait_for(client, rid, ["gate_a", "failed"])
    assert st["status"] == "gate_a", st.get("error")
    return rid


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def test_revision_at_gate_a_reaches_phase_b_page_and_workbook(client):
    """Operator types a change, presses 'Revise the card', then approves with an EMPTY notes box."""
    from openpyxl import load_workbook

    from lightyear.paths import run_dir
    rid = start_run(client)
    sentinel = "SENTINEL-REV-4471 hold exactly 17 names"
    assert client.post(f"/api/runs/{rid}/revise", json={"notes": sentinel}).status_code == 200
    st = wait_for(client, rid, ["gate_a", "failed"])
    assert st["status"] == "gate_a", st.get("error")
    assert [r["notes"] for r in st["revisions"]] == [sentinel]            # persisted in state.json, not only the log
    assert client.post(f"/api/runs/{rid}/approve", json={"by": "Auditor", "notes": ""}).status_code == 200
    st = wait_for(client, rid, ["gate_b", "failed"])
    assert st["status"] == "gate_b", st.get("error")

    rd = run_dir(rid)
    assert sentinel in _read(st["phase_a"]["card_path"])                  # the revision session rewrote the card
    assert sentinel in _read(os.path.join(rd, "prompt_phase_b.txt"))      # and Phase B was TOLD about it
    results = json.loads(_read(os.path.join(rd, "results.json")))
    assert any(n.startswith("PROMPT-NOTES:") and sentinel in n for n in results["notes"])
    assert st["approval"]["card_sha256"] and len(st["approval"]["card_sha256"]) == 64   # the card is pinned at approval
    assert st["card_checks"] and all(c["ok"] for c in st["card_checks"])                 # and the run matched it
    notes_sheet = load_workbook(os.path.join(rd, st["workbook"]))["Notes"]
    cells = " ".join(str(c.value) for row in notes_sheet.iter_rows() for c in row if c.value)
    assert sentinel in cells and "approved by auditor" in cells.lower()  # the workbook records both


def test_approval_notes_still_reach_phase_b(client):
    from lightyear.paths import run_dir
    rid = start_run(client)
    sentinel = "SENTINEL-APP-9920 use 12-1 momentum"
    assert client.post(f"/api/runs/{rid}/approve", json={"by": "Auditor", "notes": sentinel}).status_code == 200
    st = wait_for(client, rid, ["gate_b", "failed"])
    assert st["status"] == "gate_b", st.get("error")
    assert sentinel in _read(os.path.join(run_dir(rid), "prompt_phase_b.txt"))


def test_a_revision_session_that_dies_fails_loudly(client):
    """The session errors before writing anything: the run must NOT come back as a fresh Gate A."""
    from lightyear.paths import run_dir
    rid = start_run(client)
    pa_before = _read(os.path.join(run_dir(rid), "phase_a.json"))
    assert client.post(f"/api/runs/{rid}/revise", json={"notes": "SENTINEL-STALE change costs to 0"}).status_code == 200
    st = wait_for(client, rid, ["gate_a", "failed"])
    assert st["status"] == "failed" and "error" in st["error"].lower() and st["resume_from"] == "revising"
    assert _read(os.path.join(run_dir(rid), "phase_a.json")) == pa_before
    # the operator can go back to Gate A and ask again
    assert client.post(f"/api/runs/{rid}/resume").status_code == 200
    assert wait_for(client, rid, ["gate_a", "failed"])["status"] == "gate_a"


def test_a_revision_that_changes_nothing_fails_loudly(client):
    """The session ends 'successfully' but neither the card nor phase_a.json changed: the notes were not applied."""
    rid = start_run(client)
    assert client.post(f"/api/runs/{rid}/revise", json={"notes": "SENTINEL-NOOP please change nothing"}).status_code == 200
    st = wait_for(client, rid, ["gate_a", "failed"])
    assert st["status"] == "failed" and "neither" in st["error"]


def test_rerun_from_approved_card_inherits_revisions(client):
    from lightyear.paths import run_dir
    rid = start_run(client)
    sentinel = "SENTINEL-REV-0007 use 10 names"
    client.post(f"/api/runs/{rid}/revise", json={"notes": sentinel})
    wait_for(client, rid, ["gate_a", "failed"])
    client.post(f"/api/runs/{rid}/approve", json={"by": "Auditor", "notes": "approval words"})
    wait_for(client, rid, ["gate_b", "failed"])
    assert client.post(f"/api/runs/{rid}/rerun", json={"by": ""}).status_code == 400
    new = client.post(f"/api/runs/{rid}/rerun", json={"by": "Auditor", "note": "SENTINEL-EDIT mandate_allow_cash true"}).json()["id"]
    st = wait_for(client, new, ["gate_b", "failed"])
    assert st["status"] == "gate_b", st.get("error")
    assert st["rerun_of"] == rid and [r["notes"] for r in st["revisions"]] == [sentinel, "SENTINEL-EDIT mandate_allow_cash true"]
    prompt_b = _read(os.path.join(run_dir(new), "prompt_phase_b.txt"))
    assert sentinel in prompt_b and "SENTINEL-EDIT" in prompt_b and "approval words" in prompt_b
    assert all(s == "done" for s in st["stages"].values())


def test_card_consistency_check_catches_a_run_that_ignored_the_card(tmp_path):
    from lightyear import contract
    card = tmp_path / "card.yaml"
    card.write_text("signal:\n  params: {gap_limit: 0.15, signal_weekday: Tuesday}\ncosts: {spread_bps: 0}\n"
                    "backtest_plan: {sample_start: '2014-01-01', sample_end: '2026-09-18'}\nn_configs_tried: 9\n", encoding="utf-8")
    good = {"inputs": {"card": {"sha256": contract.sha256_file(str(card))}},
            "params": {"gap_limit": 0.15, "signal_weekday": 1, "start": "2014-01-01", "end": "2026-09-18", "cost_bp": 0.0, "n_trials": 13}}
    rd = tmp_path / "run"
    rd.mkdir()
    (rd / "manifest.json").write_text(json.dumps(good), encoding="utf-8")
    res = {"headline_cost_bp": 0, "tables": [{"title": "Appendix: cost sweep"}]}
    checks = contract.check_card_consistency(str(rd), str(card), results=res, comparator_columns=["Appendix: same rules at 30bp"])
    assert all(c["ok"] for c in checks) and len(checks) >= 8

    for bad_params, field in (({"start": "2016-01-01"}, "window start"), ({"gap_limit": 0.20}, "gap_limit"),
                              ({"signal_weekday": 3}, "signal_weekday"), ({"cost_bp": 30.0}, "cost"),
                              ({"n_trials": 4}, "trials")):
        m = json.loads(json.dumps(good))
        m["params"].update(bad_params)
        (rd / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        with pytest.raises(contract.ContractError, match=re.escape(field.split()[0])):
            contract.check_card_consistency(str(rd), str(card), results=res)
    (rd / "manifest.json").write_text(json.dumps(good), encoding="utf-8")
    with pytest.raises(contract.ContractError, match="APPENDIX"):      # Fix 4: another costing must say it is an appendix
        contract.check_card_consistency(str(rd), str(card), results=res, comparator_columns=["Same rules at 30bp round trip"])
    with pytest.raises(contract.ContractError, match="sha256"):         # a card edited after approval
        contract.check_card_consistency(str(rd), str(card), approval={"card_sha256": "f" * 64}, results=res)
    with pytest.raises(contract.ContractError, match="headline_cost_bp"):
        contract.check_card_consistency(str(rd), str(card), results={"headline_cost_bp": 30})


def test_clenow_script_reads_its_parameters_from_the_card():
    """The Phase B script for the Clenow card: every parameter comes from the card, none is a literal."""
    from ros.cards.schema import load_card
    script = os.path.join(REPO, "scripts", "oceanofpdf_com_stocks_on_the_move_andreas_clenow_india_backtest.py")
    card_path = os.path.join(REPO, "cards", "oceanofpdf_com_stocks_on_the_move_andreas_clenow.yaml")
    if not (os.path.exists(script) and os.path.exists(card_path)):
        pytest.skip("the Clenow card or script is not on this machine")
    src = _read(script)
    refs = set(re.findall(r"card\.[a-z_]+(?:\.[a-z_]+)*", src)) | set(re.findall(r"CARD_OBJ\.[a-z_]+(?:\.[a-z_]+)*", src))
    assert any("backtest_plan" in r for r in refs) and any("signal.params" in r for r in refs) and any("costs.spread_bps" in r for r in refs)
    assert not re.search(r'pd\.Timestamp\("20\d\d-\d\d-\d\d"\)', src), "window dates must not be literals"
    spec = importlib.util.spec_from_file_location("clenow_script", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                      # imports and card load only; main() is guarded
    card = load_card(card_path)
    wd = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}
    assert str(mod.START.date()) == card.backtest_plan.sample_start and str(mod.END.date()) == card.backtest_plan.sample_end
    assert mod.P["gap_limit"] == float(card.signal.params["gap_limit"])
    assert mod.P["signal_weekday"] == wd[card.signal.params["signal_weekday"].lower()]
    assert mod.P["cost_bp"] == float(card.costs.spread_bps)
    # Wave 3: trials = every version tried (book + Lightyear runs + ledger, ros/validation/trials.py) plus this run's
    # sensitivities, counted in main() once the run folder is known; the book's count is still where it starts.
    assert mod.N_SENSITIVITIES == len(mod.SENSITIVITIES)
    assert "trials.count(SLUG, int(CARD_OBJ.n_configs_tried), exclude_run=run_dir)" in src
    assert mod.MANDATE_ALLOWS_CASH == (card.portfolio.mandate_allow_cash is True)
    blob = yaml.safe_load(_read(card_path))
    assert blob["portfolio"]["mandate_allow_cash"] is True       # the operator's ruling of 2026-10-30
