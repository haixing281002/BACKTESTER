# Quant AI Researcher
"""Failure handling in the run driver (lightyear/jobs.py): check-then-act under a lock, atomic JSON writes, and a
turn cap on every headless session."""
import importlib
import json
import os
import sys
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


@pytest.fixture()
def jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTYEAR_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("LIGHTYEAR_CLAUDE", os.path.join(REPO, "tests", "fake_claude.py"))
    monkeypatch.setenv("LY_TEST_CARDS", str(tmp_path / "cards"))
    import lightyear.jobs
    import lightyear.paths
    importlib.reload(lightyear.paths)
    j = importlib.reload(lightyear.jobs)
    started = []
    monkeypatch.setattr(j, "start", lambda fn, *a: started.append(fn.__name__))
    j._started = started
    return j


def test_two_decisions_at_once_record_exactly_one(jobs):
    rid = jobs.create("docs/papers/x.pdf", "x", "Tester", "", False)
    jobs.update(rid, status="gate_b")
    results, barrier = [], threading.Barrier(2)

    def click(name):
        barrier.wait()
        try:
            results.append(("ok", jobs.decide(rid, "REJECT", name, "because")["decided_by"]))
        except jobs.GateConflict as e:
            results.append(("refused", str(e)))
    threads = [threading.Thread(target=click, args=(n,)) for n in ("First PM", "Second PM")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r[0] for r in results) == ["ok", "refused"]
    with open(jobs.LEDGER, encoding="utf-8") as fh:
        assert len(fh.readlines()) == 1
    assert not any(f.endswith(".tmp") for f in os.listdir(jobs.run_dir(rid)))


def test_a_second_approval_is_refused_and_starts_nothing(jobs):
    rid = jobs.create("docs/papers/x.pdf", "x", "Tester", "", False)
    jobs.update(rid, status="gate_a")
    jobs.approve(rid, "Tester")
    with pytest.raises(jobs.GateConflict, match="not Gate A"):
        jobs.approve(rid, "Tester")
    assert jobs._started == ["phase_b"]


def test_a_session_past_the_turn_cap_is_stopped(jobs, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_TURNS", 0)
    rid = jobs.create("docs/papers/x.pdf", "x", "Tester", "", False)
    ok, _ = jobs.run_claude(rid, "stages 00 through Gate A for the paper (slug: x)", "Test session", [])
    assert ok is False
    with open(os.path.join(jobs.run_dir(rid), "log.jsonl"), encoding="utf-8") as fh:
        msgs = [json.loads(line)["msg"] for line in fh if line.strip()]
    assert any("passed 0 turns" in m for m in msgs)


def test_json_is_written_atomically(jobs, tmp_path):
    p = str(tmp_path / "x.json")
    jobs.write_json_atomic(p, {"a": 1})
    with open(p, encoding="utf-8") as fh:
        assert json.load(fh) == {"a": 1}
    assert not os.path.exists(p + ".tmp")
