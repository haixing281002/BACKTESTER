# Quant AI Researcher
"""Every output is tied to a run id and a card sha, nothing is picked by 'latest file', and a stale hand-off is refused.

Two runs with different cards get different run ids and different card shas; the run list shows the newer one first;
the workbook's file name and Summary carry the run id and the card sha; a results.json older than the approval fails
the build; the page's run state carries the provenance block.
"""
import importlib
import json
import os
import shutil
import sys
import time

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
    papers = tmp_path / "papers"
    papers.mkdir()
    shutil.copy(os.path.join(REPO, "tests", "fixtures", "synthetic_paper.pdf"), papers / "synthetic_paper.pdf")
    monkeypatch.setenv("LIGHTYEAR_PAPERS", str(papers))
    monkeypatch.setenv("LIGHTYEAR_TOKEN_FILE", str(tmp_path / "session_token"))
    monkeypatch.setenv("LIGHTYEAR_PORT", "8100")
    import lightyear.jobs
    import lightyear.paths
    import lightyear.server
    import lightyear.security
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


def _run_to_gate_b(client, revision=None):
    paper = client.get("/api/papers").json()[0]
    rid = client.post("/api/runs", data={"operator": "Auditor", "existing": paper}).json()["id"]
    wait_for(client, rid, ["gate_a", "failed"])
    if revision:
        assert client.post(f"/api/runs/{rid}/revise", json={"notes": revision}).status_code == 200
        wait_for(client, rid, ["gate_a", "failed"])
    assert client.post(f"/api/runs/{rid}/approve", json={"by": "Auditor", "notes": ""}).status_code == 200
    st = wait_for(client, rid, ["gate_b", "failed"])
    assert st["status"] == "gate_b", st.get("error")
    return rid, st


def test_two_runs_two_ids_two_card_shas_newest_first(client):
    from openpyxl import load_workbook

    from lightyear.paths import run_dir
    rid1, st1 = _run_to_gate_b(client)
    time.sleep(1.1)                                            # run ids carry the second
    rid2, st2 = _run_to_gate_b(client, revision="use 17 names")  # a different card
    assert rid1 != rid2
    p1, p2 = st1["provenance"], st2["provenance"]
    assert p1["card_sha256_approved"] != p2["card_sha256_approved"]
    assert p1["card_sha256_approved"] == p1["card_sha256_run"] and p2["card_sha256_approved"] == p2["card_sha256_run"]
    assert p2["code_hash_disk"] and p2["git_commit"]
    runs = client.get("/api/runs").json()
    assert [r["id"] for r in runs[:2]] == [rid2, rid1]        # newest first on the page
    for rid, st in ((rid1, st1), (rid2, st2)):
        assert rid in st["workbook"]                          # file name carries the run id
        wb = load_workbook(os.path.join(run_dir(rid), st["workbook"]), read_only=True)
        a3 = str(wb["Summary"]["A3"].value)
        assert rid in a3 and st["provenance"]["card_sha256_approved"][:12] in a3
        r = client.get(f"/api/runs/{rid}/workbook")
        assert r.status_code == 200 and rid in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"


def test_a_hand_off_older_than_the_approval_is_refused(client):
    from lightyear.paths import run_dir
    rid, st = _run_to_gate_b(client)
    rd = run_dir(rid)
    old = time.time() - 3600
    for f in ("results.json", "daily_returns.csv", "manifest.json"):
        os.utime(os.path.join(rd, f), (old, old))
    assert client.post(f"/api/runs/{rid}/rebuild").status_code == 200
    st = wait_for(client, rid, ["gate_b", "failed"])
    assert st["status"] == "failed" and "predate the Gate A approval" in st["error"]


def test_health_reports_code_version():
    from lightyear.paths import code_hash, git_commit
    assert len(code_hash()) == 12 and git_commit()
