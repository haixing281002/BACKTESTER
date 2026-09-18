"""Gate A has to CONVERT the card, not merely contain it.

The card was already good. What a reviewer got was twenty-four green rows with
the reasoning truncated mid-word, the model's asks 250 lines further down, and
the judgement calls spread across four sections they had to assemble in their
head. Five minutes of attention were spent discovering that nothing had tripped.

These tests hold the brief to the one standard that matters: everything a human
is being asked to sign appears in it, in full, above the audit trail.
"""
import os

import pytest

from ros.cards.completeness import assess as card_completeness
from ros.cards.schema import (Convertibility, CostSpec, Intent, Paper,
                              PortfolioSpec, Signal, StrategyCard, Universe,
                              audit_data_requests, load_card)
from ros.governance.gates import (Criterion, gate_a, gate_a_brief,
                                  judgement_calls)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEMPLAR = os.path.join(HERE, "examples", "cards",
                        "devanathan_2026_india_factor_adaptation.yaml")


class _Feas:
    verdict = "GO"
    can_proceed = True
    blocking = []
    resolutions = []


@pytest.fixture
def card():
    return load_card(EXEMPLAR)


@pytest.fixture
def brief(card):
    return gate_a_brief(card, gate_a(card, _Feas()))


# ---------------------------------------------------------------------------
# Nothing a human signs may be missing from the brief
# ---------------------------------------------------------------------------
def test_every_material_ambiguity_appears(card, brief):
    for a in card.material_ambiguities:
        assert a.field in brief, f"{a.field} is a call a human owns and it is not shown"


def test_every_open_question_appears_with_the_assumption_taken(card, brief):
    for q in card.open_questions:
        assert q.question.split()[0] in brief
        head = " ".join(q.what_i_assumed.split())[:40]
        assert head in brief, (
            "the assumption is the thing a human overturns; showing the "
            "question without it asks them to guess what was done meanwhile")


def test_every_data_request_shows_what_declining_costs(card, brief):
    for r in card.data_requests:
        assert " ".join(r.without_it.split())[:40] in brief, (
            "a request without its fallback is a demand. The fallback is the "
            "only part a human can weigh")


def test_the_universe_rationale_is_not_truncated(card, brief):
    """The old gate cut evidence at 150 chars, mid-word."""
    tail = " ".join(card.universe_translation.rationale.split())[-40:]
    assert tail in brief


def test_the_cost_and_lag_are_shown_together(brief):
    assert "30bp" in brief and "lag 1d" in brief


def test_the_bar_is_named_before_the_run(card, brief):
    for target in card.backtest_plan.must_beat:
        assert " ".join(target.split())[:30] in brief


# ---------------------------------------------------------------------------
# Ordering: the brief is what the five minutes are for
# ---------------------------------------------------------------------------
def test_blocking_failures_come_first(card):
    card.signal.lag_days = 0                      # anything that blocks
    gr = gate_a(card, _Feas())
    gr.criteria.insert(0, Criterion("a blocking failure", False,
                                    evidence="this must be impossible to miss"))
    out = gate_a_brief(card, gr)
    assert out.index("STOP.") < out.index("THE JUDGEMENT CALLS")
    assert "this must be impossible to miss" in out


def test_the_brief_says_nothing_is_decided(brief):
    assert "NOTHING ABOVE IS DECIDED" in brief


def test_an_unverified_security_list_is_surfaced(card):
    card.selection.explicit_securities = ["RELIANCE", "TCS"]
    card.selection.verified_against = "UNVERIFIED"
    out = gate_a_brief(card, gate_a(card, _Feas()))
    assert "UNVERIFIED" in out and "RELIANCE" in out


def test_a_long_short_paper_surfaces_the_adaptation(card):
    card.strategy.is_long_short = True
    card.strategy.long_only_adaptation = "Long leg only, measured against NIFTY 500."
    calls = judgement_calls(card)
    tags = [c["tag"] for c in calls]
    assert "LONG-ONLY" in tags


# ---------------------------------------------------------------------------
# Evidence is wrapped, not cut
# ---------------------------------------------------------------------------
def test_criterion_evidence_is_wrapped_not_truncated():
    long = "word " * 80
    out = Criterion("x", True, evidence=long).render()
    assert out.count("\n") >= 3, "long evidence must wrap onto several lines"
    assert "word word" in out.splitlines()[-1]


def test_no_threshold_means_no_vs_none():
    """`[sleeve_proxy vs None]` is noise that reads like a failed comparison."""
    out = Criterion("x", True, value="sleeve_proxy").render()
    assert "None" not in out
    assert "[sleeve_proxy]" in out


def test_every_gate_a_criterion_carries_evidence(card):
    for c in gate_a(card, _Feas()).criteria:
        assert c.evidence.strip(), (
            f"{c.name} has no evidence; a row a human cannot disagree with is "
            f"a row that teaches them nothing")


# ---------------------------------------------------------------------------
# The request audit -- the check that used to be unable to fail
# ---------------------------------------------------------------------------
def test_silence_and_a_weak_fallback_are_different_findings(card):
    card.data_requests = []
    a = audit_data_requests(card)
    assert a["stance"] == "silent"
    assert a["ok"], ("no requests means no bad fallbacks; conflating the two "
                     "reports a failure that did not happen")
    assert not a["complete"]


def test_a_short_fallback_is_caught(card):
    card.data_requests[0].without_it = "we cope"
    a = audit_data_requests(card)
    assert not a["ok"] and a["weak"]


def test_a_real_fallback_passes(card):
    assert audit_data_requests(card)["ok"]
    assert audit_data_requests(card)["stance"] == "asked"


# ---------------------------------------------------------------------------
# Convertibility -- the question the fund is paying to have answered
# ---------------------------------------------------------------------------
def test_the_exemplar_carries_a_verdict(card):
    assert card.convertibility is not None
    assert card.convertibility.verdict == "convertible"
    assert len(card.convertibility.what_must_be_true) >= 3


def test_a_one_link_chain_is_rejected():
    cv = Convertibility(verdict="convertible", what_must_be_true=["it works"],
                        weakest_link="x")
    assert any("at least 2" in e for e in cv.validate())


def test_a_chain_with_no_weakest_link_is_rejected():
    cv = Convertibility(verdict="convertible",
                        what_must_be_true=["a", "b"], weakest_link="  ")
    assert any("weakest link" in e for e in cv.validate())


def test_an_unknown_verdict_is_rejected():
    cv = Convertibility(verdict="probably_fine",
                        what_must_be_true=["a", "b"], weakest_link="a")
    assert any("verdict" in e for e in cv.validate())


def test_convertibility_never_blocks_the_gate(card):
    """A `not_convertible` verdict is a finding worth more than most runs."""
    card.convertibility.verdict = "not_convertible"
    gr = gate_a(card, _Feas())
    rows = [c for c in gr.criteria if c.name == "convertibility assessed"]
    assert rows and not rows[0].blocking
    assert gr.passed, "an honest negative verdict must not block the gate"


def test_a_verdict_that_contradicts_the_asks_is_caught(card):
    """Both statements are the model's own. They have to agree."""
    card.convertibility.verdict = "convertible_with_data"
    card.data_requests = []
    gr = gate_a(card, _Feas())
    rows = [c for c in gr.criteria if c.name == "verdict agrees with the asks"]
    assert rows and not rows[0].passed


def test_a_card_with_no_verdict_is_told_so(card):
    card.convertibility = None
    out = card.convertibility_block()
    assert "NO CONVERTIBILITY VERDICT" in out
    r = card_completeness(card)
    assert any(c.name == "verdict recorded" and not c.passed for c in r.checks)


def test_the_verdict_reaches_the_human(card):
    out = card.convertibility_block()
    assert " ".join(card.convertibility.weakest_link.split())[:50] in out
    assert " ".join(card.convertibility.decisive_evidence.split())[:50] in out
    assert " ".join(card.convertibility.if_it_fails.split())[:50] in out


# ---------------------------------------------------------------------------
# The thin card still scores badly -- the scale must not have drifted
# ---------------------------------------------------------------------------
def test_a_card_that_merely_validates_still_scores_badly():
    bare = StrategyCard(
        paper=Paper(id="x", title="x"),
        intent=Intent(mode="adaptation", transferred_mechanism="m"),
        universe=Universe(assets=["A"]), signal=Signal(template="fixed_weight"),
        portfolio=PortfolioSpec(), costs=CostSpec(spread_bps=5.0))
    assert not bare.validate()
    assert card_completeness(bare).score < 0.35


def test_the_exemplar_still_scores_near_full():
    r = card_completeness(load_card(EXEMPLAR))
    assert r.score > 0.95, [m.name for m in r.missing]
    assert not r.serious, [m.name for m in r.serious]
