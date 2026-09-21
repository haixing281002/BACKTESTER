"""Gate A is the strategy card, displayed. Nothing else.

The output kept drifting into a tour of the pipeline -- which stage produced
what, what the deterministic reader saw, where the audit trail lived, which part
the code scored -- because every card field was bespoke prose behind a bespoke
name and any renderer had to know all of them.

So the card projects to a flat list of Facts, and every surface is a projection
over that list. These tests hold that contract: the projection is complete, the
renderer knows no field names, and what reaches a reviewer is the strategy,
never the machinery.
"""
import os

import pytest

from ros.cards.completeness import assess as card_completeness
from ros.cards.schema import (BLOCK, DECIDE, GROUPS, GUESS, Convertibility,
                              CostSpec, Fact, IndiaNote, Intent, Paper,
                              PortfolioSpec, Signal, StrategyCard, Universe,
                              audit_data_requests, load_card,
                              reconcile_data_plan)
from ros.data.firm_registry import build_firm_registry
from ros.data.universes import check_translation
from ros.feasibility import assess as feasibility_assess
from ros.governance.gates import (Criterion, GateResult, code_facts,
                                  extraction_facts, gate_a, gate_a_document,
                                  gate_a_summary)
from ros.india_requirements import derive as derive_india

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
def wiring(card):
    registry = build_firm_registry()
    tc = check_translation(card.universe_translation, registry,
                           long_only=card.portfolio.long_only)
    feas = feasibility_assess(card, registry)
    return dict(translation_check=tc, feasibility=feas,
                india=derive_india(card, tc),
                completeness=card_completeness(card))


@pytest.fixture
def result(card, wiring):
    return gate_a(card, wiring["feasibility"],
                  translation_check=wiring["translation_check"])


@pytest.fixture
def doc(card, result, wiring):
    return gate_a_document(card, result, **wiring)


@pytest.fixture
def sheet(card, result, wiring):
    return gate_a_summary(card, result, **wiring)


def flat(text):
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# The projection is COMPLETE. A display that silently omits a card field is
# worse than a long one -- the reader cannot tell it happened.
# ---------------------------------------------------------------------------
def test_every_card_section_reaches_the_facts(card):
    groups = {f.group for f in card.facts()}
    for expected in ("PAPER", "UNIVERSE", "SIGNAL", "PORTFOLIO", "COSTS",
                     "DATA", "SECURITIES", "THE RUN", "THE BAR", "RISKS",
                     "VERDICT", "DECIDE", "ASKS"):
        assert expected in groups, f"{expected} never reaches the display"


def test_the_argued_fields_are_all_projected(card):
    """The long prose is what makes the card good. None of it may be dropped."""
    body = flat(" ".join(f"{f.value} {f.detail}" for f in card.facts()))
    for label, text in (
            ("universe rationale", card.universe_translation.rationale),
            ("why not alternatives", card.universe_translation.why_not_alternatives),
            ("signal definition", card.strategy.signal_definition),
            ("weighting rule", card.strategy.weighting_rule),
            ("optimality argument", card.data_plan.optimality_argument),
            ("granularity verdict", card.data_plan.granularity_verdict),
            ("selection rule", card.selection.rule),
            ("why this window", card.backtest_plan.why_this_window),
            ("failure looks like", card.backtest_plan.failure_looks_like),
            ("weakest link", card.convertibility.weakest_link),
            ("if it fails", card.convertibility.if_it_fails)):
        assert flat(text)[:60] in body, f"{label} is missing from the display"


def test_every_transfer_risk_and_broken_assumption_is_carried(card):
    body = flat(" ".join(f.value for f in card.facts()))
    for r in card.universe_translation.transfer_risks:
        assert flat(r)[:50] in body
    for b in card.intent.broken_assumptions:
        assert flat(b)[:50] in body


def test_every_fact_can_be_traced_back_to_a_card_field(card):
    for f in card.facts():
        assert f.ref, f"{f.group}/{f.label} has no ref to trace back to"


def test_the_document_shows_every_fact(card, doc):
    missing = [f"{f.group}/{f.label}" for f in card.facts()
               if flat(f.value)[:50] not in flat(doc)]
    assert not missing, f"facts dropped by the renderer: {missing[:6]}"


# ---------------------------------------------------------------------------
# ... and rendered ONCE. Measured before the projection existed, on 888 lines:
# the universe rationale twice, the weakest link three times, a minimum-viable
# field five times.
# ---------------------------------------------------------------------------
def test_nothing_is_rendered_twice(card, doc):
    body = flat(doc)
    repeated = {}
    for f in card.facts():
        probe = flat(f.value)[:70]
        if len(probe) < 40:
            continue
        n = body.count(probe)
        if n > 1:
            repeated[f"{f.group}/{f.label}"] = n
    assert not repeated, f"rendered more than once: {repeated}"


# ---------------------------------------------------------------------------
# It is the STRATEGY, not the machinery.
# ---------------------------------------------------------------------------
def test_the_display_does_not_narrate_the_pipeline(doc):
    """No stage numbers, no audit-trail tour, no "what the reader saw"."""
    low = doc.lower()
    for phrase in ("step 01", "step 02", "stage 01", "stage 02", "audit trail",
                   "deterministic reader", "the code scored", "rendered once"):
        assert phrase not in low, f"the display narrates the pipeline: {phrase!r}"


def test_the_groups_are_named_after_the_strategy(card):
    """A reviewer thinks in universe/signal/the bar, not in module names."""
    for f in card.facts():
        assert f.group in GROUPS, f"{f.group} is not a group a reviewer thinks in"


def test_computed_facts_sit_with_the_card_facts_they_belong_to(card, wiring):
    """What the fund holds belongs under UNIVERSE, next to what it is tested on
    -- not in a separate section announcing that the code produced it."""
    computed = code_facts(card, wiring["translation_check"],
                          wiring["feasibility"], wiring["india"])
    groups = {f.group for f in computed}
    assert "UNIVERSE" in groups and "DATA" in groups and "RISKS" in groups
    assert all(f.group in GROUPS for f in computed)


# ---------------------------------------------------------------------------
# The one-page sheet is the same projection, filtered.
# ---------------------------------------------------------------------------
def test_the_sheet_carries_only_what_a_human_rules_on(card, sheet, wiring):
    facts = list(card.facts()) + list(code_facts(
        card, wiring["translation_check"], wiring["feasibility"],
        wiring["india"]))
    decidable = [f for f in facts if f.flag in (BLOCK, DECIDE, GUESS)]
    assert decidable
    for f in decidable:
        assert flat(f.value)[:45] in flat(sheet), (
            f"{f.group}/{f.label} is a call and it is not on the sheet")


def test_the_sheet_is_short_enough_to_read(sheet):
    assert len(sheet.splitlines()) < 60, (
        f"{len(sheet.splitlines())} lines; the sheet exists to be read INSTEAD "
        f"of the card")


def test_the_sheet_and_the_card_cannot_disagree(card, sheet, doc):
    """Both are projections of facts(), so anything on one is on the other."""
    for line in sheet.splitlines():
        t = line.strip()
        if len(t) > 60 and not set(t) <= set("=- "):
            continue    # wrapped fragments are not worth probing
    for f in card.facts():
        if f.flag in (BLOCK, DECIDE):
            assert flat(f.value)[:45] in flat(doc)


def test_india_non_negotiables_are_not_on_the_decision_sheet(card, sheet, wiring):
    """lag >= 1 and the 30bp floor are enforced, not decided.

    They were briefly ranked as items 1 and 2 -- padding the sheet with two
    things nobody rules on, above the things they do.
    """
    assert "lag_days >= 1" not in sheet
    assert flat(sheet).count("30bp round trip, the fund's floor") == 0


def _numbered(out):
    """Rows of the sheet. The count line ("17 call(s) | 1 blocking") also
    starts with digits, which is what the first version of this caught."""
    return [l for l in out.splitlines()
            if l.strip().split(" ")[0].rstrip(".").isdigit()
            and l.strip().split(".")[0].isdigit()
            and "call(s)" not in l]


def test_every_call_on_the_sheet_names_who_owns_it(sheet):
    rows = _numbered(sheet)
    assert rows
    for r in rows:
        assert any(w in r for w in ("pm", "researcher", "data_owner", "-")), r


def test_blocking_sorts_above_everything(card):
    card.data_requests[0].priority = "blocking"
    out = gate_a_summary(card, gate_a(card, _Feas()))
    assert "data_owner" in _numbered(out)[0]


# ---------------------------------------------------------------------------
# Flags mean something specific
# ---------------------------------------------------------------------------
def test_an_unverified_security_list_is_a_guess(card):
    card.selection.explicit_securities = ["RELIANCE", "TCS"]
    card.selection.verified_against = "UNVERIFIED"
    f = next(f for f in card.facts()
             if f.group == "SECURITIES" and f.label == "named")
    assert f.flag == GUESS


def test_a_verified_list_is_not(card):
    f = next(f for f in card.facts()
             if f.group == "SECURITIES" and f.label == "named")
    assert f.flag == ""


def test_a_lag_of_zero_blocks(card):
    card.signal.lag_days = 0
    f = next(f for f in card.facts() if f.label == "lag")
    assert f.flag == BLOCK


def test_a_question_that_blocks_the_run_is_flagged_block(card):
    card.open_questions[0].blocks_run = True
    flags = [f.flag for f in card.facts()
             if f.group == "DECIDE" and f.label == "open question"]
    assert BLOCK in flags


def test_a_missing_template_blocks(card):
    card.strategy.engine_template = "NEEDS_NEW_TEMPLATE"
    f = next(f for f in card.facts() if f.label == "engine")
    assert f.flag == BLOCK


def test_a_substituted_series_is_a_guess(card, wiring):
    computed = code_facts(card, wiring["translation_check"],
                          wiring["feasibility"], wiring["india"])
    subs = [f for f in computed if f.label == "substituted"]
    assert subs and subs[0].flag == GUESS


# ---------------------------------------------------------------------------
# Headlines: the model writes the line, the code writes the order
# ---------------------------------------------------------------------------
def test_a_headline_is_used_when_the_model_wrote_one(card):
    card.ambiguities[0].headline = "ZZZ distinctive probe"
    f = next(f for f in card.facts()
             if f.group == "DECIDE" and f.value == "ZZZ distinctive probe")
    assert f.detail == flat(card.ambiguities[0].resolution)


def test_without_a_headline_the_resolution_stands_in(card):
    card.ambiguities[0].headline = ""
    vals = [f.value for f in card.facts() if f.group == "DECIDE"]
    assert flat(card.ambiguities[0].resolution) in vals


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


# ---------------------------------------------------------------------------
# What the card cannot know, merged in
# ---------------------------------------------------------------------------
def test_missing_instruments_block(card, wiring):
    tc = wiring["translation_check"]
    tc.missing = ["nifty_500_membership_history"]
    f = next(f for f in code_facts(card, tc) if f.label == "MISSING")
    assert f.flag == BLOCK and "nifty_500_membership_history" in f.value


def test_out_of_mandate_reaches_the_reader(card, wiring):
    tc = wiring["translation_check"]
    tc.notes = list(tc.notes) + ["OUT OF MANDATE. testing only."]
    labels = [f.label for f in code_facts(card, tc)]
    assert "OUT OF MANDATE" in labels


def test_a_minimum_viable_field_not_in_hand_is_a_decision(card, wiring):
    computed = code_facts(card, wiring["translation_check"],
                          wiring["feasibility"], wiring["india"])
    f = next(f for f in computed if f.label == "NOT IN HAND")
    assert f.flag == DECIDE and f.owner == "pm"


def test_an_unread_strategy_input_surfaces(card, wiring):
    card.strategy.inputs_required = card.strategy.inputs_required + [
        "analyst revision breadth score"]
    computed = code_facts(card, None, None, derive_india(card))
    f = next(f for f in computed if f.label == "unread input")
    assert "analyst revision breadth score" in f.value


def test_extraction_findings_become_facts():
    conflicts = [{"portfolio": "1 day", "metric": "sharpe",
                  "values": [1.01, 1.08], "pages": [34]}]
    f = next(f for f in extraction_facts(conflicts=conflicts)
             if f.label == "basis conflict")
    assert f.flag == DECIDE and "never fail" in f.detail


def test_a_document_that_is_not_a_paper_blocks():
    class _Shape:
        looks_like_a_paper = False
    f = next(f for f in extraction_facts(shape=_Shape())
             if f.label == "NOT A PAPER")
    assert f.flag == BLOCK


# ---------------------------------------------------------------------------
# Degrades without the computed inputs rather than inventing them
# ---------------------------------------------------------------------------
def test_the_card_alone_still_displays(card):
    """What the card knows about itself renders; what needs the registry does not.

    "NOT IN HAND" IS derivable from the card alone -- a request naming a
    minimum-viable field in `satisfies` is the model saying it lacks it. What
    cannot be known without the fund's registry is which series are proxied or
    backfilled, and inventing that would be worse than omitting it.
    """
    out = gate_a_document(card, gate_a(card, _Feas()))
    assert "STRATEGY CARD" in out
    assert flat(card.strategy.signal_definition)[:50] in flat(out)
    assert "NOT IN HAND" in out
    # Anchor on the computed fact's own wording: "backfilled" alone also
    # appears in the card's prose about NSE history, which is not what this
    # is checking for.
    assert "not the real series" not in out
    assert "not knowable as-was on past dates" not in out


def test_nothing_is_decided(doc, sheet):
    assert "Nothing here is decided" in doc
    assert "Nothing here is decided" in sheet


# ---------------------------------------------------------------------------
# Schema-level guarantees the display rests on
# ---------------------------------------------------------------------------
def test_a_minimum_viable_field_the_card_asks_for_is_not_in_hand(card):
    rec = reconcile_data_plan(card, feasibility_assess(card, build_firm_registry()))
    assert rec["need"] and rec["not_in_hand"] == rec["need"]


def test_the_data_link_is_declared_not_guessed(card):
    card.data_requests[0].satisfies = []
    rec = reconcile_data_plan(card, None)
    assert "Indian overnight or 91-day T-bill rate, daily" not in rec["not_in_hand"]


def test_silence_and_a_weak_fallback_are_different_findings(card):
    card.data_requests = []
    a = audit_data_requests(card)
    assert a["stance"] == "silent" and a["ok"] and not a["complete"]


def test_a_short_fallback_is_caught(card):
    card.data_requests[0].without_it = "we cope"
    assert not audit_data_requests(card)["ok"]


def test_a_one_link_convertibility_chain_is_rejected():
    cv = Convertibility(verdict="convertible", what_must_be_true=["it works"],
                        weakest_link="x")
    assert any("at least 2" in e for e in cv.validate())


def test_convertibility_never_blocks_the_gate(card):
    card.convertibility.verdict = "not_convertible"
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria if c.name == "convertibility assessed")
    assert not row.blocking and gr.passed


def test_the_exemplar_still_scores_near_full():
    r = card_completeness(load_card(EXEMPLAR))
    assert r.score > 0.95, [m.name for m in r.missing]
    assert not r.serious, [m.name for m in r.serious]


def test_a_card_that_merely_validates_still_scores_badly():
    bare = StrategyCard(
        paper=Paper(id="x", title="x"),
        intent=Intent(mode="adaptation", transferred_mechanism="m"),
        universe=Universe(assets=["A"]), signal=Signal(template="fixed_weight"),
        portfolio=PortfolioSpec(), costs=CostSpec(spread_bps=5.0))
    assert not bare.validate()
    assert card_completeness(bare).score < 0.35


def test_a_failing_criterion_keeps_its_evidence():
    ev = "this is exactly why it failed and it is written nowhere else"
    gr = GateResult(gate="X", owner="y",
                    criteria=[Criterion("a", False, evidence=ev)])
    assert ev in flat(gr.render(terse=True))
