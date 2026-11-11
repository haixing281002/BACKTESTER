# Quant AI Researcher
"""Provenance that survives a checkout: hashes ignore line endings, a run records a dirty tree, verify recomputes the
script and code hashes, and the page shows the commit the backtest ran on (not whatever HEAD is when it is drawn)."""
import importlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.data import lineage
from ros.data.snapshot import code_hash


def _two_copies(tmp_path, name, text):
    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    for d, body in ((lf, text), (crlf, text.replace("\n", "\r\n"))):
        (d / os.path.dirname(name)).mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(body.encode())
    return lf, crlf


def test_a_crlf_checkout_hashes_the_same_as_an_lf_one(tmp_path):
    lf, crlf = _two_copies(tmp_path, "ros/engine/backtest.py", "x = 1\ny = 2\n")
    assert lineage.sha256_file(str(lf / "ros/engine/backtest.py")) == lineage.sha256_file(str(crlf / "ros/engine/backtest.py"))
    assert code_hash(["ros/engine/backtest.py"], root=str(lf)) == code_hash(["ros/engine/backtest.py"], root=str(crlf))
    a, b = lineage.sha256_both(str(crlf / "ros/engine/backtest.py"))
    assert a != b, "the raw hash is kept beside the normalised one"


def test_a_binary_file_is_never_line_ending_normalised(tmp_path):
    p = tmp_path / "w.xlsx"
    p.write_bytes(b"PK\r\n\x00\r\n")
    norm, raw = lineage.sha256_both(str(p))
    assert norm == raw


def test_the_manifest_records_a_dirty_tree_and_verify_catches_a_changed_script(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    script = repo / "scripts" / "x_india_backtest.py"
    script.parent.mkdir()
    script.write_text("print('v1')\n", encoding="utf-8")
    data = repo / "in.csv"
    data.write_text("a,b\n1,2\n", encoding="utf-8")
    run = repo / "run"
    run.mkdir()
    mp = lineage.write_run_manifest(str(run), str(script), {"data": str(data)}, repo=str(repo))
    with open(mp, encoding="utf-8") as fh:
        m = json.load(fh)
    assert m["git_dirty"] is True and any("scripts/" in f or "in.csv" in f for f in m["dirty_files"])
    assert lineage.verify_run_manifest(mp, repo=str(repo))["ok"] is True

    script.write_text("print('v2')\n", encoding="utf-8")
    v = lineage.verify_run_manifest(mp, repo=str(repo))
    assert v["ok"] is False and v["script_changed"] is True and v["code_changed"] is True


def test_an_older_manifest_with_raw_hashes_still_verifies(tmp_path):
    data = tmp_path / "in.csv"
    data.write_bytes(b"a,b\r\n1,2\r\n")
    m = {"inputs": {"data": {"path": str(data), "sha256": lineage.sha256_both(str(data))[1]}}}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(m), encoding="utf-8")
    assert lineage.verify_run_manifest(str(mp), repo=str(tmp_path))["changed"] == []


def test_the_page_shows_the_commit_the_backtest_ran_on(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTYEAR_RUNS", str(tmp_path / "runs"))
    import lightyear.jobs
    import lightyear.paths
    importlib.reload(lightyear.paths)
    jobs = importlib.reload(lightyear.jobs)
    rid = jobs.create("docs/papers/x.pdf", "x", "Tester", "", False)
    with open(os.path.join(jobs.run_dir(rid), "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"git_commit": "50f2b3b0123456789", "git_dirty": True}, fh)
    pv = jobs.provenance(jobs.load(rid))
    assert pv["git_commit"] == "50f2b3b" and pv["git_dirty"] is True
    assert "git_commit_now" in pv
