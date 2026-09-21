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
from ros.governance.gates import (Criterion, gate_a, gate_a_document,
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
    return gate_a_document(card, gate_a(card, _Feas()))


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
    out = gate_a_document(card, gr)
    assert out.index("STOP.") < out.index("THE JUDGEMENT CALLS")
    assert "this must be impossible to miss" in out


def test_the_brief_says_nothing_is_decided(brief):
    assert "NOTHING ABOVE IS DECIDED" in brief


def test_an_unverified_security_list_is_surfaced(card):
    card.selection.explicit_securities = ["RELIANCE", "TCS"]
    card.selection.verified_against = "UNVERIFIED"
    out = gate_a_document(card, gate_a(card, _Feas()))
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
    return gate_a_document(card, gate_a(card, feas, translation_check=tc),
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
    out = gate_a_document(card, gate_a(card, _Feas()), translation_check=tc)
    assert "nifty_500_membership_history" in out
    assert "supplied before anything runs" in out


def test_the_dataset_the_paper_deserves_is_in_the_brief(card, full):
    assert "THE DATASET THIS PAPER DESERVES" in full
    for d in card.data_plan.ideal:
        assert d.field in full, f"{d.field} is something to buy and it is not shown"


def test_minimum_viable_is_distinguished_from_nice_to_have(full):
    """The labels come from plan_data() now -- one renderer, not two.

    The document used to carry its own summary of the data plan alongside the
    full rendering, with a second set of labels. That summary was the largest
    single source of duplication and it is gone; the distinction it made is not.
    """
    assert "MINIMUM VIABLE" in full and "improves the claim" in full


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
    out = gate_a_document(card, gate_a(card, _Feas()), india=_derive(card))
    assert "NOBODY HAS LOOKED" in out
    assert "analyst revision breadth score" in out


def test_a_model_note_is_marked_as_a_reading_in_the_brief(card):
    """A reader must always be able to tell a reading from a consequence."""
    from ros.india_requirements import derive as _derive
    out = gate_a_document(card, gate_a(card, _Feas()), india=_derive(card))
    assert "read from the paper by a model" in out
    assert "from the paper, by a model" in out


def test_the_brief_degrades_cleanly_without_the_extra_arguments(card):
    """The three new arguments are optional, so old callers do not break.

    What the card carries itself still renders -- the data plan is on the card.
    What needs the fund's registry does not, and must simply be absent rather
    than guessed at: a brief that invented a data position would be worse than
    one that omits it.
    """
    out = gate_a_document(card, gate_a(card, _Feas()))
    assert "THE JUDGEMENT CALLS" in out
    assert "THE DATASET THIS PAPER DESERVES" in out     # on the card
    assert "WHERE YOU STAND:" not in out                # needs the registry
    assert "WHAT INDIA DEMANDS" not in out              # needs the derivation


# ---------------------------------------------------------------------------
# Two shortfalls, not one
#
# Feasibility answers "does every NAMED series resolve", and says GO when
# proxies and degraded series stand in. `data_plan.ideal` is the dataset the
# paper deserves. Nothing compared them, so a card could design a dataset, hold
# none of it, and the report would print "Nothing. Every series this card needs
# is already held." Every series it NAMED. Not the dataset it designed.
# ---------------------------------------------------------------------------
from ros.cards.schema import reconcile_data_plan


def test_a_minimum_viable_field_the_card_asks_for_is_not_in_hand(card):
    registry = build_firm_registry()
    rec = reconcile_data_plan(card, feasibility_assess(card, registry))
    assert rec["need"], "the exemplar marks minimum-viable fields"
    assert rec["not_in_hand"] == rec["need"], (
        "the exemplar holds price-return series and a constant cash proxy; "
        "both of its minimum-viable fields are substituted for")


def test_the_link_is_declared_not_guessed(card):
    """A fuzzy match would mark the gap closed, which is the failure to catch."""
    card.data_requests[0].satisfies = []
    rec = reconcile_data_plan(card, None)
    assert "Indian overnight or 91-day T-bill rate, daily" not in rec["not_in_hand"]


def test_the_brief_says_which_dataset_is_actually_being_run(card, full):
    assert "ARE WE RUNNING ON THAT DATASET" in full
    assert "MINIMUM-VIABLE" in full
    assert "not the test this card specified" in full.lower() or \
           "NOT in hand" in full


def test_gate_a_carries_a_row_for_it(card):
    registry = build_firm_registry()
    gr = gate_a(card, feasibility_assess(card, registry))
    row = next(c for c in gr.criteria
               if c.name == "the run uses the dataset the card designed")
    assert not row.passed
    assert not row.blocking, "running on a declared proxy is legitimate, not a fault"


def test_a_card_whose_design_is_satisfied_passes(card):
    for r in card.data_requests:
        r.satisfies = []
    rec = reconcile_data_plan(card, None)
    assert not rec["not_in_hand"]
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria
               if c.name == "the run uses the dataset the card designed")
    assert row.passed


def test_a_card_with_no_data_plan_is_not_judged_on_one():
    from ros.cards.schema import (CostSpec, Intent, Paper, PortfolioSpec,
                                  Signal, StrategyCard, Universe)
    bare = StrategyCard(
        paper=Paper(id="x", title="x"),
        intent=Intent(mode="adaptation", transferred_mechanism="m"),
        universe=Universe(assets=["A"]), signal=Signal(template="fixed_weight"),
        portfolio=PortfolioSpec(), costs=CostSpec(spread_bps=30.0))
    rec = reconcile_data_plan(bare, None)
    assert not rec["checked"]
    names = [c.name for c in gate_a(bare, _Feas()).criteria]
    assert "the run uses the dataset the card designed" not in names


# ---------------------------------------------------------------------------
# THE CONTRACT: Gate A is the card, rendered ONCE.
#
# Measured on the worked example before this change, across 888 lines: the
# universe rationale appeared twice, the convertibility weakest link three
# times, a minimum-viable data field five times. The brief quoted sections, then
# plan() and asks() printed the same sections again below, then the criteria
# list carried the same text a third time as "evidence". A reader who has
# already read a paragraph does not read it again -- they skim, and skimming is
# how a gate becomes a rubber stamp.
# ---------------------------------------------------------------------------
def _count(text, phrase):
    return " ".join(text.split()).count(" ".join(phrase.split()))


def test_the_card_is_not_repeated(card, full):
    """Every substantial card field appears exactly once in the document."""
    once = {
        "universe rationale": card.universe_translation.rationale,
        "why not the alternatives": card.universe_translation.why_not_alternatives,
        "signal definition": card.strategy.signal_definition,
        "granularity verdict": card.data_plan.granularity_verdict,
        "optimality argument": card.data_plan.optimality_argument,
        "selection rule": card.selection.rule,
        "why this window": card.backtest_plan.why_this_window,
        "failure looks like": card.backtest_plan.failure_looks_like,
        "weakest link": card.convertibility.weakest_link,
    }
    repeated = {}
    for label, text in once.items():
        probe = " ".join(str(text).split())[:70]
        if not probe:
            continue
        n = _count(full, probe)
        if n != 1:
            repeated[label] = n
    assert not repeated, f"card text rendered more than once: {repeated}"


def test_each_open_question_appears_once(card, full):
    """They are judgement calls, not asks. Section 7 only."""
    for q in card.open_questions:
        assert _count(full, " ".join(q.question.split())[:60]) == 1


def test_each_data_request_appears_once(card, full):
    for r in card.data_requests:
        assert _count(full, " ".join(r.without_it.split())[:60]) == 1


def test_a_passing_criterion_does_not_repeat_its_evidence(card, full):
    """The evidence for a PASS is the card text rendered above it.

    A failing criterion keeps its evidence in full -- that is the one place the
    reason is not written anywhere else.
    """
    gr = gate_a(card, _Feas())
    passing = [c for c in gr.criteria if c.passed and len(c.evidence) > 120]
    assert passing, "the exemplar has long-evidence passing criteria"
    terse = gr.render(terse=True)
    for c in passing:
        assert " ".join(c.evidence.split())[:70] not in " ".join(terse.split())
    full_render = gr.render()
    assert " ".join(passing[0].evidence.split())[:70] in " ".join(full_render.split())


def test_a_failing_criterion_keeps_its_evidence():
    gr_evidence = "this is exactly why it failed and it is written nowhere else"
    from ros.governance.gates import GateResult
    gr = GateResult(gate="X", owner="y",
                    criteria=[Criterion("a", False, evidence=gr_evidence)])
    assert gr_evidence in " ".join(gr.render(terse=True).split())


def test_every_section_is_present_and_numbered(full):
    for n, title in SECTIONS:
        assert f"{n}. {title}" in full, f"section {n} ({title}) is missing"


SECTIONS = ((1, "WHERE THIS RUNS"), (2, "WHAT THE STRATEGY IS"),
            (3, "THE DATASET THIS PAPER DESERVES"), (4, "WHICH SECURITIES"),
            (5, "WHAT WILL BE RUN"),
            (6, "CAN THIS BECOME SOMETHING WE COULD HOLD"),
            (7, "THE JUDGEMENT CALLS"),
            (8, "WHAT THE MODEL IS ASKING YOU FOR"), (9, "THE CHECKLIST"))


def test_the_sections_are_in_decision_order(full):
    # Anchor on the full header. A bare "2. " also matches a numbered list
    # inside the card's own prose, which is where the first version of this
    # test went wrong.
    marks = [full.index(f"{n}. {title}") for n, title in SECTIONS]
    assert marks == sorted(marks)


def test_provenance_is_at_the_top(card, full):
    head = full[:full.index("1. WHERE THIS RUNS")]
    assert card.paper.source_sha256[:16] in head
    assert card.paper.id in head


def test_plan_still_composes_the_three_parts(card):
    """plan() is kept for callers that want the whole Stage 02 block."""
    whole = card.plan()
    for part in (card.plan_data(), card.plan_selection(), card.plan_run()):
        body = [l for l in part.splitlines() if l.strip() and set(l.strip()) != {"="}]
        assert body[-1] in whole


# ---------------------------------------------------------------------------
# THE ONE-PAGE SHEET
#
# Rendering the card once was the right fix for saying things three times, and
# still ran to seven hundred lines -- because the card is seven hundred lines of
# argued work. A reviewer does not need the argument to decide. They need to
# know WHAT they are deciding, WHO owns it, and WHERE the argument is if a line
# looks wrong.
# ---------------------------------------------------------------------------
from ros.governance.gates import gate_a_summary


@pytest.fixture
def sheet(card):
    registry = build_firm_registry()
    tc = check_translation(card.universe_translation, registry,
                           long_only=card.portfolio.long_only)
    feas = feasibility_assess(card, registry)
    return gate_a_summary(card, gate_a(card, feas, translation_check=tc),
                          translation_check=tc, feasibility=feas,
                          india=derive_india(card, tc),
                          completeness=card_completeness(card))


def test_the_sheet_fits_on_a_screen(sheet):
    """Not a hard limit -- a card with forty ambiguities earns forty rows.
    But one line per item is the contract, and this catches a regression that
    starts printing paragraphs again."""
    assert len(sheet.splitlines()) < 80, (
        f"the sheet is {len(sheet.splitlines())} lines; it is meant to be the "
        f"thing you read INSTEAD of the document")


def test_every_decidable_item_is_on_the_sheet(card, sheet):
    """Compressed, not dropped. A summary that omits an item is worse than none."""
    for a in card.material_ambiguities:
        assert a.field in sheet, f"ambiguity {a.field} is missing from the sheet"
    for q in card.open_questions:
        probe = " ".join((q.headline or q.question).split())[:40]
        assert probe in " ".join(sheet.split())
    for r in card.data_requests:
        probe = " ".join((r.headline or r.item).split())[:40]
        assert probe in " ".join(sheet.split())


def test_every_row_names_who_owns_it(sheet):
    body = sheet.split("WHAT YOU ARE RULING ON")[1]
    rows = [l for l in body.splitlines() if l.strip().startswith(tuple("123456789"))]
    assert rows
    for r in rows:
        assert any(w in r for w in ("pm", "researcher", "data_owner", "STOP")), r


def test_every_row_points_into_the_document(sheet, full):
    """A pointer that resolves nowhere is worse than no pointer."""
    import re
    targets = set(re.findall(r"\bS[1-9]\b", sheet))
    assert targets, "no section pointers on the sheet"
    for t in targets:
        assert f"{t}. " in full, f"the sheet points at {t} and the document has no {t}"


def test_blocking_items_sort_first(card):
    card.data_requests[0].priority = "blocking"
    out = gate_a_summary(card, gate_a(card, _Feas()))
    body = out.split("WHAT YOU ARE RULING ON")[1]
    first = next(l for l in body.splitlines() if l.strip().startswith("1."))
    assert "STOP" in first or "data_owner" in first


def test_a_low_confidence_call_outranks_a_high_confidence_one(card, sheet):
    body = " ".join(sheet.split())
    low = next(a for a in card.material_ambiguities if a.confidence == "low")
    high = next(a for a in card.material_ambiguities if a.confidence == "high")
    assert body.index(low.field) < body.index(high.field), (
        "a low-confidence material call is the thing most likely to be wrong "
        "and must not sit below the settled ones")


def test_the_model_writes_the_line_and_the_code_writes_the_order(card):
    """The split that matters.

    Compressing an argument is a judgement, so the headline is the model's.
    RANKING is not given to it: a model that ordered its own work would put the
    item it was most pleased with first. The order is mechanical.
    """
    card.convertibility.headline = "ZZZ unique probe text"
    out = gate_a_summary(card, gate_a(card, _Feas()))
    assert "ZZZ unique probe text" in out


def test_a_card_with_no_headlines_falls_back_visibly(card):
    """Truncation must announce itself rather than pass as a written line."""
    for a in card.ambiguities:
        a.headline = ""
    card.convertibility.headline = ""
    out = gate_a_summary(card, gate_a(card, _Feas()))
    assert "..." in out, "a cut clause must show that it was cut"


def test_a_headline_that_is_a_paragraph_is_rejected():
    from ros.cards.schema import Ambiguity
    errs = Ambiguity(field="f", issue="i", resolution="r",
                     headline="word " * 40).validate("ctx")
    assert any("one line" in e for e in errs)


def test_completeness_asks_for_the_headlines(card):
    for a in card.ambiguities:
        a.headline = ""
    r = card_completeness(card)
    row = next(c for c in r.checks
               if c.name == "every decision item has a one-line headline")
    assert not row.passed


def test_the_sheet_decides_nothing(sheet):
    assert "NOTHING HERE IS DECIDED" in sheet
