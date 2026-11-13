# Quant AI Researcher
"""The Barra site step and the analyst read at Gate B: both are reports. Neither holds a site address, votes, or
changes a gate status. The tester here is a stand-in script in a temp folder; no network is touched."""
import json
from pathlib import Path

import pytest

from lightyear import barra_site, gate_b_read, prompts

GOOD = {"what_the_exposures_say": "Momentum +0.74 and Size -0.83.", "where_the_return_came_from": "Market 10.3%, style 7.6%, stock-specific -1.7% a year.",
        "risks_carried": "A momentum reversal would hurt.", "what_this_read_cannot_tell": "Every suggestion is fitted to this history.",
        "suggestions": [{"change": "Cap the size tilt.", "why": "Size -0.83.", "how_to_test": "A new run with a size cap; compare stock-specific return."}],
        "used_barra_site": True}


def _write(d, obj):
    Path(d, gate_b_read.FILE).write_text(json.dumps(obj), encoding="utf-8")


def test_a_complete_read_loads_and_shows_its_headings_and_suggestions(tmp_path):
    _write(tmp_path, GOOD)
    page = gate_b_read.for_page(str(tmp_path))
    assert page["status"] == "ok" and [s["key"] for s in page["sections"]] == [k for k, _ in gate_b_read.HEADINGS]
    assert page["suggestions"][0]["how_to_test"].startswith("A new run") and page["used_barra_site"] and not page["pinned"]


def test_no_read_is_said_plainly(tmp_path):
    assert gate_b_read.for_page(str(tmp_path))["status"] == "none" and gate_b_read.sha256(str(tmp_path)) is None


@pytest.mark.parametrize("broken", [{**GOOD, "risks_carried": " "}, {**GOOD, "suggestions": []},
                                    {**GOOD, "suggestions": [{"change": "x", "why": "y"}]}])
def test_a_read_with_a_missing_part_is_not_shown(tmp_path, broken):
    _write(tmp_path, broken)
    with pytest.raises(ValueError):
        gate_b_read.load(str(tmp_path))
    assert gate_b_read.for_page(str(tmp_path))["status"] == "invalid"


@pytest.mark.parametrize("text", ["On this evidence the committee should approve it.", "I would reject this strategy.", "It should pass."])
def test_a_read_that_votes_is_refused(tmp_path, text):
    _write(tmp_path, {**GOOD, "risks_carried": text})
    with pytest.raises(ValueError, match="votes"):
        gate_b_read.load(str(tmp_path))


def test_a_read_changed_after_the_decision_is_withheld(tmp_path):
    _write(tmp_path, GOOD)
    decision = {"gate_b_read_sha256": gate_b_read.sha256(str(tmp_path))}
    assert gate_b_read.for_page(str(tmp_path), decision)["pinned"]
    _write(tmp_path, {**GOOD, "risks_carried": "Edited afterwards."})
    page = gate_b_read.for_page(str(tmp_path), decision)
    assert page["status"] == "changed" and "sections" not in page


def test_the_prompt_forbids_a_vote_and_calls_every_suggestion_a_new_run():
    p = prompts.GATE_B_READ
    assert "You do NOT vote" in p and "never a change to this run" in p and "one more version tried" in p


def test_lightyear_holds_no_site_address_or_login():
    for mod in (barra_site, gate_b_read):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "192.168" not in src and "http://" not in src and "password" not in src.lower()


def test_without_a_tester_the_step_is_not_offered(monkeypatch, tmp_path):
    monkeypatch.setattr(barra_site, "tester_dir", lambda: "")
    assert not barra_site.configured()
    with pytest.raises(RuntimeError, match="not set up"):
        barra_site.run(str(tmp_path), lambda m: None)


def _tester(tmp_path, body):
    t = tmp_path / "tester"
    (t / "scripts").mkdir(parents=True)
    (t / "scripts" / "run_for_lightyear.py").write_text(body, encoding="utf-8")
    return str(t)


def test_the_step_passes_progress_on_and_copies_the_result_into_the_run_folder(monkeypatch, tmp_path):
    res = tmp_path / "res.json"
    res.write_text(json.dumps({"site_last_date": "2026-06-10", "signed": "Quant AI Researcher"}), encoding="utf-8")
    t = _tester(tmp_path, f"import sys\nprint('STEP map: 10 of 10 rows mapped')\nprint('RESULT ' + {str(res)!r})\n")
    monkeypatch.setattr(barra_site, "tester_dir", lambda: t)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    seen = []
    out = barra_site.run(str(run_dir), seen.append)
    assert seen == ["Barra site, map: 10 of 10 rows mapped"] and out["site_last_date"] == "2026-06-10"
    assert barra_site.load(str(run_dir)) == out


def test_a_failed_step_says_why_and_writes_nothing(monkeypatch, tmp_path):
    t = _tester(tmp_path, "import sys\nprint('STEP FAILED map: a date maps less than 95%')\nsys.exit(1)\n")
    monkeypatch.setattr(barra_site, "tester_dir", lambda: t)
    with pytest.raises(RuntimeError, match="less than 95%"):
        barra_site.run(str(tmp_path), lambda m: None)
    assert barra_site.load(str(tmp_path)) is None


def test_a_finished_backtest_is_sent_by_itself_only_when_a_tester_is_set_up_and_not_switched_off(monkeypatch, tmp_path):
    monkeypatch.setattr(barra_site, "tester_dir", lambda: "")
    assert not barra_site.auto_send()                                   # no tester: nothing is ever sent
    t = _tester(tmp_path, "print('x')\n")
    monkeypatch.setattr(barra_site, "tester_dir", lambda: t)
    monkeypatch.delenv("LIGHTYEAR_BARRA_AUTO", raising=False)
    assert barra_site.auto_send() or barra_site.sources._LOCAL.get("barra_auto_send") == "0"
    monkeypatch.setenv("LIGHTYEAR_BARRA_AUTO", "0")
    assert not barra_site.auto_send()


def test_a_rebuild_never_sends_anything():
    src = Path(barra_site.__file__).with_name("jobs.py").read_text(encoding="utf-8")
    assert "if review and not os.environ.get(\"LIGHTYEAR_SKIP_REVIEW\") and barra_site.auto_send():" in src
