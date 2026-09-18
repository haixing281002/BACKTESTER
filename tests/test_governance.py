"""Gate A and Gate B are human decisions. These tests exist to keep them that way.

A machine that both scores the evidence and rules on it is not a governed
pipeline, whatever its criteria say. The gates may compute a CHECKLIST -- that is
mechanical and fine -- but the DECISION must come from a named person, and the
research library must be able to show which decisions nobody has made yet.

This file exists because the opposite was true for a while: run_pipeline.py
derived gb.decision from the promotion ladder and wrote it to the library as
though a human had ruled.
"""
import json
import subprocess
import sys

import pytest

from ros.cards.schema import load_card
from ros.governance.gates import GateResult, Criterion, gate_a, gate_b

CARD = "examples/cards/devanathan_2026_india_factor_adaptation.yaml"


def _run(*extra):
    return subprocess.run(
        [sys.executable, "run_pipeline.py", "--card", CARD,
         "--n-boot", "120", "--no-charts", *extra],
        capture_output=True, text=True)


def _latest(outdir):
    entries = [json.load(open(p, encoding="utf-8")) for p in (outdir / "library").glob("*.json")]
    assert entries, f"no library entry written to {outdir}"
    return max(entries, key=lambda x: x["created_utc"])


# A full pipeline run is ~100s, so each scenario runs ONCE and the assertions
# share it. Two runs, not four.
@pytest.fixture(scope="module")
def undecided(tmp_path_factory):
    d = tmp_path_factory.mktemp("undecided")
    return _run("--outdir", str(d)).stdout, d


@pytest.fixture(scope="module")
def decided(tmp_path_factory):
    d = tmp_path_factory.mktemp("decided")
    out = _run("--outdir", str(d), "--decision", "REJECT",
               "--decided-by", "Test PM", "--rationale", "because").stdout
    return out, d


# ---------------------------------------------------------------- unit level
def test_a_fresh_gate_result_is_undecided():
    assert GateResult("G", "owner").decision == "PENDING"


def test_gate_a_does_not_decide():
    card = load_card(CARD)

    class _Feas:
        verdict, blocking, signoff_required = "GO", [], []
        can_proceed = True
    assert gate_a(card, _Feas()).decision == "PENDING"


def test_gate_b_does_not_decide_however_the_evidence_reads():
    """Neither a clean sweep nor a total failure may produce a ruling."""
    card = load_card(CARD)
    strong = {"deflated_sharpe": {"deflated_sharpe_prob": 0.99, "interpretation": ""},
              "oos_min_sharpe": 1.5, "bootstrap_p_not_positive": 0.001}
    weak = {"deflated_sharpe": {"deflated_sharpe_prob": 0.00, "interpretation": ""},
            "oos_min_sharpe": -0.5, "bootstrap_p_not_positive": 0.9}
    port_ok = {"max_corr_to_book": 0.1, "best_delta_ir": 0.5, "alpha_t_hac": 9.0,
               "mandate": {"passes": True, "violations": []}, "annual_turnover": 0.2}
    port_bad = {"max_corr_to_book": 0.99, "best_delta_ir": -0.5, "alpha_t_hac": 0.01,
                "mandate": {"passes": False, "violations": ["cash"]}, "annual_turnover": 9.0}

    best = gate_b(card, strong, port_ok)
    worst = gate_b(card, weak, port_bad)
    assert best.passed and not worst.passed          # the checklist still works
    assert best.decision == "PENDING"                 # but neither rules
    assert worst.decision == "PENDING"


def test_criteria_are_mechanical_but_separate_from_the_ruling():
    g = GateResult("G", "PM", [Criterion("c", False, blocking=True)])
    assert g.passed is False
    assert g.decision == "PENDING"                    # a failed checklist is not a REJECT


# ------------------------------------------------------------ end to end
def test_pipeline_leaves_the_decision_pending_by_default(undecided):
    out, _ = undecided
    assert "decision recorded : PENDING" in out
    assert "NO DECISION HAS BEEN MADE" in out
    # The evidence is still summarised -- withholding the ruling is not
    # withholding the analysis.
    assert "evidence supports" in out


def test_a_decision_requires_a_named_human():
    r = _run("--decision", "APPROVE")
    assert r.returncode != 0
    assert "requires --decided-by" in (r.stdout + r.stderr)


def test_a_recorded_decision_is_stored_with_its_owner(decided):
    out, d = decided
    assert "decision recorded : REJECT  by Test PM" in out

    e = _latest(d)
    assert e["reviewer"] == "Test PM"
    assert e["outcome"] == "REJECTED"
    gb = [g for g in e["gates"] if "GATE B" in g["gate"]][0]
    assert gb["decision"] == "REJECT" and "because" in gb["rationale"]


def test_undecided_runs_are_identifiable_in_the_library(undecided):
    _, d = undecided
    e = _latest(d)
    # A run nobody has ruled on must be findable as such, not silently filed
    # alongside decisions a person actually made.
    assert e["outcome"] == "PENDING_HUMAN"
    assert e["reviewer"] == ""


def test_no_module_derives_a_decision_from_evidence():
    """Structural guard: only the CLI flag may assign a gate decision."""
    import pathlib
    import re
    offenders = []
    for p in pathlib.Path(".").rglob("*.py"):
        if "test" in p.parts or ".git" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\b(ga|gb|gate\w*)\.decision\s*=", line):
                if "args.decision" not in line and '"PENDING"' not in line:
                    offenders.append(f"{p}:{i}: {line.strip()}")
    assert not offenders, "a decision is being assigned from evidence:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# A checklist that silently gets SHORTER is the other way a gate stops governing.
#
# Every Gate B criterion used to be appended only `if <evidence> is not None`.
# So when the factor regression could not run -- statsmodels absent, or too
# little overlap -- the row "alpha survives the factor fingerprint" did not fail;
# it disappeared. GateResult.passed is all() over the criteria present, and
# all() over a shorter list is easier to satisfy. The gate could therefore
# report PASS *because* the test that would have blocked it never ran, and the
# human signing the sheet had nothing on the page telling them so.
# ---------------------------------------------------------------------------

_FULL_PORT = {"alpha_t_hac": 4.0, "max_corr_to_book": 0.10, "best_delta_ir": 0.20}
_FULL_RESEARCH = {"deflated_sharpe": {"deflated_sharpe_prob": 0.99},
                  "oos_min_sharpe": 0.80, "bootstrap_p_not_positive": 0.01}


def _names(gr):
    return [c.name for c in gr.criteria]


def test_a_passing_sheet_is_possible_at_all():
    """Guard the guard: if this fails the negative controls below prove nothing."""
    gr = gate_b(load_card(CARD), _FULL_RESEARCH, _FULL_PORT)
    assert gr.passed, [c.name for c in gr.criteria if not c.passed and c.blocking]


@pytest.mark.parametrize("drop", ["alpha_t_hac", "max_corr_to_book", "best_delta_ir"])
def test_missing_portfolio_evidence_never_shortens_the_checklist(drop):
    port = {k: v for k, v in _FULL_PORT.items() if k != drop}
    full = gate_b(load_card(CARD), _FULL_RESEARCH, _FULL_PORT)
    thin = gate_b(load_card(CARD), _FULL_RESEARCH, port)
    assert _names(thin) == _names(full), (
        f"dropping {drop} removed a row from the sheet instead of failing it")


@pytest.mark.parametrize("drop", ["deflated_sharpe", "oos_min_sharpe",
                                  "bootstrap_p_not_positive"])
def test_missing_research_evidence_never_shortens_the_checklist(drop):
    research = {k: v for k, v in _FULL_RESEARCH.items() if k != drop}
    full = gate_b(load_card(CARD), _FULL_RESEARCH, _FULL_PORT)
    thin = gate_b(load_card(CARD), _FULL_RESEARCH if False else research, _FULL_PORT)
    assert _names(thin) == _names(full), (
        f"dropping {drop} removed a row from the sheet instead of failing it")


def test_an_uncomputed_fingerprint_blocks_gate_b():
    """The planted regression: statsmodels missing must not buy a free pass."""
    port = {k: v for k, v in _FULL_PORT.items() if k != "alpha_t_hac"}
    port["alpha_t_hac_error"] = "statsmodels unavailable -- ModuleNotFoundError"
    gr = gate_b(load_card(CARD), _FULL_RESEARCH, port)
    assert not gr.passed, "a gate passed without ever running the factor regression"
    row = next(c for c in gr.criteria if c.name == "alpha survives the factor fingerprint")
    assert row.blocking and not row.passed
    assert "statsmodels" in row.evidence, "the reason it did not run must reach the human"


def test_uncomputed_evidence_is_never_reported_as_a_pass():
    gr = gate_b(load_card(CARD), {}, {})
    assert not gr.passed
    for c in gr.criteria:
        if c.value == "NOT COMPUTED":
            assert not c.passed, f"{c.name!r} was scored as passing without evidence"
