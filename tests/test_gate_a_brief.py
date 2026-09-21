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


# ---------------------------------------------------------------------------
# WHERE IT RUNS, WHAT IT NEEDS, WHAT INDIA DEMANDS
#
# All three existed and none was in the brief: the universe printed ABOVE the
# gate header so the most consequential Stage 01 call read as preamble, the
# India requirements printed 440 lines below it, and the data position was the
# last block of a 759-line report. A reviewer deciding whether to buy data had
# to assemble three sections themselves.
# ---------------------------------------------------------------------------
from ros.data.firm_registry import build_firm_registry
from ros.data.universes import check_translation
from ros.feasibility import assess as feasibility_assess
from ros.india_requirements import derive as derive_india


@pytest.fixture
def full(card):
    """The brief as run_interpret.py actually builds it."""
    registry = build_firm_registry()
    tc = check_translation(card.universe_translation, registry,
                           long_only=card.portfolio.long_only)
    feas = feasibility_assess(card, registry)
    return gate_a_brief(card, gate_a(card, feas, translation_check=tc),
                        translation_check=tc, feasibility=feas,
                        india=derive_india(card, tc))


def test_the_brief_says_where_this_runs(card, full):
    assert "WHERE THIS RUNS" in full
    assert card.universe_translation.target_universe in full


def test_the_instruments_are_named_not_counted(full):
    """"5 instruments held" is not an answer to "which five"."""
    for name in ("NIFTY500 MOMENTUM 50", "NIFTY ALPHA 50"):
        assert name in full


def test_what_the_mechanism_needs_is_shown(full):
    assert "needs" in full and "cap" in full


def test_the_ranking_shows_names_not_dataclass_reprs(full):
    """UniverseFit.universe is a UniverseDef, not a string."""
    assert "UniverseDef(" not in full, (
        "the ranked list dumped whole dataclass reprs into the brief")
    assert "NIFTY 500 constituents" in full
    assert "OUT OF MANDATE" in full, (
        "a universe the fund may test on but not hold is a fact about what a "
        "result MEANS, and it cannot sit in a notes list further down")


def test_missing_instruments_are_named_and_flagged(card):
    registry = build_firm_registry()
    tc = check_translation(card.universe_translation, registry,
                           long_only=card.portfolio.long_only)
    tc.missing = ["nifty_500_membership_history"]
    out = gate_a_brief(card, gate_a(card, _Feas()), translation_check=tc)
    assert "nifty_500_membership_history" in out
    assert "supplied before anything runs" in out


def test_the_dataset_the_paper_deserves_is_in_the_brief(card, full):
    assert "THE DATASET THIS PAPER DESERVES" in full
    for d in card.data_plan.ideal:
        assert d.field in full, f"{d.field} is something to buy and it is not shown"


def test_minimum_viable_is_distinguished_from_nice_to_have(full):
    assert "MUST HAVE" in full and "would help" in full


def test_where_you_stand_today_is_in_the_brief(full):
    """A reviewer asked to buy data needs the current position next to the ask."""
    assert "WHERE YOU STAND:" in full
    assert "GO_WITH_PROXY" in full
    assert "CASH_PROXY_CONSTANT_6PCT" in full, (
        "a substituted proxy changes what the result means and must be visible")
    assert "backfilled" in full


def test_what_india_demands_is_in_the_brief(full):
    assert "WHAT INDIA DEMANDS" in full
    assert "lag_days >= 1" in full
    assert "30bp" in full


def test_unrecognised_strategy_inputs_are_surfaced(card):
    """Keyword matching is shallow; the brief must admit what it skipped.

    The exemplar no longer demonstrates this -- its cash input is recognised by
    a rule now -- so use an input no pattern in the module can read.
    """
    from ros.india_requirements import derive as _derive
    card.strategy.inputs_required = card.strategy.inputs_required + [
        "analyst revision breadth score"]
    out = gate_a_brief(card, gate_a(card, _Feas()), india=_derive(card))
    assert "NOBODY HAS LOOKED" in out
    assert "analyst revision breadth score" in out


def test_a_model_note_is_marked_as_a_reading_in_the_brief(card):
    """A reader must always be able to tell a reading from a consequence."""
    from ros.india_requirements import derive as _derive
    out = gate_a_brief(card, gate_a(card, _Feas()), india=_derive(card))
    assert "read from the paper by a model" in out
    assert "from the paper, by a model" in out


def test_the_brief_degrades_cleanly_without_the_extra_arguments(card):
    """The three new arguments are optional, so old callers do not break.

    What the card carries itself still renders -- the data plan is on the card.
    What needs the fund's registry does not, and must simply be absent rather
    than guessed at: a brief that invented a data position would be worse than
    one that omits it.
    """
    out = gate_a_brief(card, gate_a(card, _Feas()))
    assert "THE JUDGEMENT CALLS" in out
    assert "THE DATASET THIS PAPER DESERVES" in out     # on the card
    assert "WHERE YOU STAND:" not in out                # needs the registry
    assert "WHAT INDIA DEMANDS" not in out              # needs the derivation
