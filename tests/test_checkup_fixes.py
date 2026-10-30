"""Checks added with the 2026-10-28 checkup fixes: one Sharpe formula, run lineage, process hygiene."""
import importlib
import json
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def test_workbook_sharpe_is_the_arithmetic_formula_everywhere(tmp_path):
    """Summary!B14 and the Comparators sheet use (mean daily x 252 - hurdle) / vol, the results.json formula,
    not (CAGR - hurdle) / vol. Before 2026-10-28 the same label gave 0.47 in the workbook and 0.53 in the report."""
    import openpyxl

    from lightyear import charts, workbook
    d = pd.bdate_range("2023-01-02", periods=120)
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"date": d, "strategy": rng.normal(5e-4, 0.01, 120), "benchmark": rng.normal(3e-4, 0.01, 120)})
    cmp = pd.DataFrame({"date": d, "Long leg only": rng.normal(6e-4, 0.012, 120)})
    res = {"strategy_name": "S", "benchmark_name": "NIFTY 500", "headline": "h", "evidence_supports": "OBSERVE",
           "gate_b": {"decision": "PENDING", "criteria": []}, "validation": [], "notes": []}
    ch = charts.build(df, {"strategy": "S"}, comparators=cmp)
    out = tmp_path / "w.xlsx"
    workbook.build(str(tmp_path), res, df, "t", str(out), comparators=cmp, observations=ch["observations"])
    wb = openpyxl.load_workbook(out)
    assert wb["Summary"]["B14"].value == "=(AVERAGE(Ret_Strat)*252-Hurdle)/B13"
    assert wb["Summary"]["C14"].value == "=(AVERAGE(Ret_Bench)*252-Hurdle)/C13"
    assert wb["Summary"]["A14"].value.startswith("Sharpe vs hurdle")
    assert "AVERAGE(" in wb["Comparators"]["D5"].value and "Hurdle" in wb["Comparators"]["D5"].value


def test_run_manifest_round_trip_and_detects_a_changed_input(tmp_path):
    from ros.data.lineage import verify_run_manifest, write_run_manifest
    run = tmp_path / "run"
    run.mkdir()
    (run / "daily_returns.csv").write_text("date,strategy\n2024-01-01,0.0\n", encoding="utf-8")
    card = tmp_path / "card.yaml"
    card.write_text("a: 1\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "2024-01-01.pkl").write_bytes(b"x")
    (cache / "2024-01-02.pkl").write_bytes(b"y")
    p = write_run_manifest(str(run), __file__, inputs={"card": str(card), "cache": str(cache)},
                           params={"sample_end": "2024-01-02"}, outputs=("daily_returns.csv", "missing.csv"))
    m = json.load(open(p, encoding="utf-8"))
    assert m["inputs"]["cache"]["files"] == 2 and m["inputs"]["cache"]["last"] == "2024-01-02.pkl"
    assert len(m["inputs"]["card"]["sha256"]) == 64 and m["script"]["sha256"]
    assert m["outputs"]["daily_returns.csv"] and m["outputs"]["missing.csv"] is None
    assert m["written_at"].endswith("+05:30"), "manifest timestamps are Asia/Kolkata"
    assert m["params"] == {"sample_end": "2024-01-02"} and m["packages"]["pandas"]
    assert verify_run_manifest(p)["ok"]
    card.write_text("a: 2\n", encoding="utf-8")
    v = verify_run_manifest(p)
    assert not v["ok"] and v["changed"] == ["card"] and v["missing"] == []
    (cache / "2024-01-02.pkl").unlink()
    assert "cache" in verify_run_manifest(p)["changed"]


def test_git_bash_helper_never_returns_a_path_that_does_not_exist(monkeypatch):
    from lightyear import paths
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", os.path.join("C:" if os.name == "nt" else "", "no", "such", "bash.exe"))
    b = paths.git_bash()
    assert b is None or os.path.exists(b)


def test_pid_alive_checks_the_image_name_against_reuse():
    from lightyear import jobs
    me = os.getpid()
    assert jobs._pid_alive(me)
    assert jobs._pid_alive(me, names=("python",))
    assert not jobs._pid_alive(me, names=("claude",))
    assert not jobs._pid_alive(2 ** 22 + 12345)
    assert not jobs._pid_alive("not a pid") and not jobs._pid_alive(None)


def test_unreadable_state_json_is_logged_not_swallowed(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("LIGHTYEAR_RUNS", str(tmp_path))
    import lightyear.jobs
    import lightyear.paths
    importlib.reload(lightyear.paths)
    importlib.reload(lightyear.jobs)
    bad = tmp_path / "badrun"
    bad.mkdir()
    (bad / "state.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level("WARNING", logger="lightyear"):
        runs = lightyear.jobs.list_runs()
    assert runs == []
    assert "badrun" in caplog.text


def test_recover_interrupted_kills_an_orphaned_child_and_clears_its_pid(tmp_path, monkeypatch):
    """A run left 'phase_b' by a dead server keeps its last child's pid in state.json. On restart the server
    kills that child when it is still alive and is a Claude/Python image, then marks the run interrupted."""
    import subprocess
    monkeypatch.setenv("LIGHTYEAR_RUNS", str(tmp_path))
    import lightyear.jobs
    import lightyear.paths
    importlib.reload(lightyear.paths)
    importlib.reload(lightyear.jobs)
    jobs = lightyear.jobs
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        rid = "orphan"
        (tmp_path / rid).mkdir()
        json.dump({"id": rid, "status": "phase_b", "created": "2026-10-28T00:00:00", "sessions": [], "pid": child.pid},
                  open(tmp_path / rid / "state.json", "w", encoding="utf-8"))
        jobs.recover_interrupted()
        child.wait(timeout=20)
        st = jobs.load(rid)
        assert st["status"] == "interrupted" and st.get("pid") is None
        assert any("orphan" in (l.get("msg") or "").lower() or "killed" in (l.get("msg") or "").lower()
                   for l in jobs.read_log(rid)[0]) if hasattr(jobs, "read_log") else True
    finally:
        if child.poll() is None:
            child.kill()
