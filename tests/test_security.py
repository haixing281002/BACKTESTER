# Quant AI Researcher
"""Who can change state on the Lightyear server, and when Gate B can be recorded (lightyear/security.py).

Behavioural, not structural: each test makes the request an attacker or a live model session would make and checks
it is refused, then makes the human's request and checks it goes through."""
import importlib
import json
import os
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


@pytest.fixture()
def ly(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTYEAR_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("LIGHTYEAR_CLAUDE", os.path.join(REPO, "tests", "fake_claude.py"))
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
    from lightyear import jobs, security
    with TestClient(lightyear.server.app, base_url="http://127.0.0.1:8100") as c:
        yield c, jobs, security


def _at_gate_b(jobs):
    rid = jobs.create("docs/papers/synthetic_paper.pdf", "synthetic_paper", "Tester", "", False)
    jobs.update(rid, status="gate_b")
    return rid


def _decide(c, security, rid, **headers):
    h = {security.HEADER: security.TOKEN, **headers}
    return c.post(f"/api/runs/{rid}/decide", headers=h,
                  json={"decision": "REJECT", "by": "Test PM", "rationale": "because"})


class _LiveProc:
    def poll(self):
        return None


def test_another_host_name_is_refused(ly):
    c, _, _ = ly
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/health", headers={"host": "attacker.example:8100"}).status_code == 403


def test_a_post_without_the_token_is_refused(ly):
    c, jobs, security = ly
    rid = _at_gate_b(jobs)
    r = c.post(f"/api/runs/{rid}/decide", json={"decision": "REJECT", "by": "x", "rationale": "y"})
    assert r.status_code == 403
    assert _decide(c, security, rid, **{security.HEADER: "wrong"}).status_code == 403
    assert jobs.load(rid)["status"] == "gate_b"


def test_a_post_from_another_site_is_refused_even_with_the_token(ly):
    c, jobs, security = ly
    rid = _at_gate_b(jobs)
    assert _decide(c, security, rid, origin="https://attacker.example").status_code == 403
    assert jobs.load(rid)["status"] == "gate_b"


def test_the_page_carries_the_token_and_the_token_file_matches(ly):
    c, _, security = ly
    assert security.TOKEN in c.get("/").text
    assert security.read_token_file() == security.TOKEN


def test_a_live_session_cannot_record_a_decision(ly):
    c, jobs, security = ly
    rid = _at_gate_b(jobs)
    jobs._procs["some-run"] = _LiveProc()          # a Claude Code session still running
    try:
        r = _decide(c, security, rid)
        assert r.status_code == 409 and "still running" in r.json()["detail"]
    finally:
        jobs._procs.pop("some-run", None)
    jobs.update(rid, review_status="running")      # the analyst review session
    assert _decide(c, security, rid).status_code == 409
    assert jobs.load(rid)["decision"] is None
    assert not os.path.isfile(jobs.LEDGER)

    jobs.update(rid, review_status="done")         # nothing live: the human's request goes through
    r = _decide(c, security, rid)
    assert r.status_code == 200
    assert jobs.load(rid)["status"] == "decided"
    with open(jobs.LEDGER, encoding="utf-8") as fh:
        assert [json.loads(line)["decided_by"] for line in fh] == ["Test PM"]


def test_a_review_left_running_by_a_dead_server_does_not_block_gate_b_for_ever(ly):
    c, jobs, security = ly
    rid = _at_gate_b(jobs)
    jobs.update(rid, review_status="running")
    jobs.recover_interrupted()
    assert jobs.load(rid)["review_status"] == "failed"
    assert _decide(c, security, rid).status_code == 200
