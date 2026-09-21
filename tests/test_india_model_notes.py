"""The India rules are a floor a model may build on, never one it may lower.

The requirements module derives what India demands from PROPERTIES of the
reconstructed strategy -- does it rank securities, does it read a fundamental,
how fast does it trade. That is mechanical on purpose: the model's job is to say
what the strategy IS, and the consequences follow without it.

The matching is keyword-based, so it is deaf to anything particular to one paper
that nobody wrote a pattern for. Closing that gap with a model is right. Letting
a model derive the requirements INSTEAD would not be: a model that misread a
strategy as low-turnover would then also not demand ADV, and both errors point
the same way -- toward a cheaper, easier test that clears its own bar.

So: the rules always fire, a model may only ADD, and every added requirement is
marked as a reading rather than a consequence.
"""
import pytest

from ros.cards.completeness import assess as card_completeness
from ros.cards.schema import IndiaNote, load_card
from ros.governance.gates import gate_a
from ros.india_requirements import MODEL, RULES, derive

EXEMPLAR = "examples/cards/devanathan_2026_india_factor_adaptation.yaml"


class _Feas:
    verdict = "GO"; can_proceed = True; blocking = []; resolutions = []


@pytest.fixture
def card():
    return load_card(EXEMPLAR)


# ---------------------------------------------------------------------------
# A model may add. It may not lower the floor.
# ---------------------------------------------------------------------------
def test_a_model_note_can_never_block(card):
    card.india_notes = [IndiaNote(category="cost", item="x", why="y",
                                  triggered_by="z")]
    added = [r for r in derive(card).requirements if r.item == "x"]
    assert added and not added[0].blocking, (
        "a model may not invent a hard stop any more than it may remove one")


def test_a_model_note_cannot_displace_a_rules_requirement(card):
    """The obvious attack: restate a rule more weakly and hope it wins."""
    before = {r.item for r in derive(card).requirements if r.blocking}
    card.india_notes = [IndiaNote(
        category="timing", item="lag_days >= 1 on any signal built from a close",
        why="actually lag 0 is fine for this paper",
        triggered_by="the paper trades at the signal close")]
    after = derive(card)
    assert before <= {r.item for r in after.requirements if r.blocking}
    weak = [r for r in after.requirements if "lag 0 is fine" in r.why]
    assert weak and not weak[0].blocking and weak[0].source == MODEL


def test_the_non_negotiables_fire_whatever_the_model_says(card):
    card.india_notes = []
    items = [r.item for r in derive(card).blocking]
    assert any("lag_days >= 1" in i for i in items)
    assert any("30bp" in i for i in items)


def test_provenance_is_never_lost(card):
    card.india_notes = [IndiaNote(category="data", item="x", why="y",
                                  triggered_by="z")]
    out = derive(card)
    assert {r.source for r in out.requirements} <= {RULES, MODEL}
    assert all(r.source == RULES for r in out.blocking), (
        "a blocking requirement is a mechanical consequence, never a reading")


def test_a_model_requirement_is_marked_when_rendered(card):
    card.india_notes = [IndiaNote(category="data", item="unique-item-xyz",
                                  why="because", triggered_by="something")]
    text = derive(card).render()
    line = next(l for l in text.splitlines() if "unique-item-xyz" in l)
    assert "by a model" in line


# ---------------------------------------------------------------------------
# The gap the notes exist to close, and the check that it was closed
# ---------------------------------------------------------------------------
def test_an_unreadable_input_is_tracked_not_just_narrated(card):
    card.strategy.inputs_required = card.strategy.inputs_required + [
        "the issuer's promoter pledge disclosures"]
    out = derive(card)
    assert "the issuer's promoter pledge disclosures" in out.unaddressed_inputs
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria
               if c.name == "every strategy input reached the India rules")
    assert not row.passed
    assert not row.blocking, "a gap in coverage is not a proven fault"


def test_addressing_it_clears_the_row(card):
    card.strategy.inputs_required = card.strategy.inputs_required + [
        "the issuer's promoter pledge disclosures"]
    card.india_notes = card.india_notes + [IndiaNote(
        category="data", item="Promoter pledge disclosures, with disclosure dates",
        why="Pledge levels move on disclosure, not on the pledge.",
        triggered_by="the signal reads promoter pledge",
        addresses=["promoter pledge disclosures"])]
    out = derive(card)
    assert not out.unaddressed_inputs
    assert "the issuer's promoter pledge disclosures" in out.addressed_inputs
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria
               if c.name == "every strategy input reached the India rules")
    assert row.passed


def test_completeness_flags_an_unaddressed_input(card):
    card.strategy.inputs_required = card.strategy.inputs_required + [
        "the issuer's promoter pledge disclosures"]
    r = card_completeness(card)
    bad = [c for c in r.checks
           if c.name == "inputs the rules could not read are addressed"]
    assert bad and not bad[0].passed and bad[0].weight >= 3


# ---------------------------------------------------------------------------
# A rule the rules were missing outright
# ---------------------------------------------------------------------------
def test_a_cash_holding_strategy_demands_a_short_rate_series(card):
    """CLAUDE.md fixes this as a standing fact and no rule raised it.

    The exemplar's whole drawdown-control mechanism de-risks into cash, against
    a declared constant 6% proxy, and nothing in the India block mentioned the
    series that mechanism runs on.
    """
    items = " ".join(r.item for r in derive(card).requirements)
    assert "short-rate" in items or "T-bill" in items


def test_the_cash_rule_does_not_fire_on_a_fully_invested_card(card):
    """Over-raising sends someone to a vendor for a field nothing reads."""
    card.portfolio.allow_cash = False
    card.strategy.inputs_required = ["daily adjusted close"]
    card.strategy.signal_definition = (
        "Rank the five sleeves by trailing 12-month return, skipping the most "
        "recent month, and hold the top two at equal weight.")
    card.strategy.weighting_rule = "equal weight across the selected sleeves"
    card.strategy.formation_rule = "top two by trailing return"
    items = " ".join(r.item for r in derive(card).requirements)
    assert "short-rate" not in items


def test_a_cash_input_is_recognised_rather_than_reported_as_unread(card):
    """It was reported unread while the cash rule was firing from it."""
    out = derive(card)
    assert not any("cash" in i.lower() for i in out.unmatched_inputs)


# ---------------------------------------------------------------------------
# The exemplar demonstrates the mechanism
# ---------------------------------------------------------------------------
def test_the_exemplar_carries_notes_the_rules_could_not_derive(card):
    out = derive(card)
    assert len(out.from_model) >= 3
    # Each must be something no pattern in the module could have produced.
    items = " ".join(r.item.lower() for r in out.from_model)
    assert "methodology" in items and "tracking error" in items


def test_a_note_without_a_reason_is_rejected():
    errs = IndiaNote(category="data", item="x", triggered_by="y").validate("n")
    assert any("WHY" in e for e in errs)


def test_a_note_that_cannot_be_traced_to_the_strategy_is_rejected():
    errs = IndiaNote(category="data", item="x", why="y").validate("n")
    assert any("raised it" in e for e in errs)


def test_an_unknown_category_is_rejected():
    errs = IndiaNote(category="vibes", item="x", why="y",
                     triggered_by="z").validate("n")
    assert any("category" in e for e in errs)


def test_coverage_is_not_claimed_by_a_shared_word(card):
    """The first version of this matcher failed in the worst direction.

    It scanned each note's item and triggered_by for any shared word over four
    characters, so a note about index METHODOLOGY-REVISION history silently
    covered an input called "analyst REVISION breadth score" -- marking a gap
    closed that nobody had looked at. Only a declared `addresses` counts.
    """
    card.strategy.inputs_required = card.strategy.inputs_required + [
        "analyst revision breadth score"]
    out = derive(card)
    assert "analyst revision breadth score" in out.unaddressed_inputs, (
        "an accidental word overlap must not close a coverage gap")


def test_a_declared_address_still_matches_loosely_within_itself(card):
    """Naming "promoter pledge" covers "the issuer's promoter pledge disclosures"."""
    card.strategy.inputs_required = card.strategy.inputs_required + [
        "the issuer's promoter pledge disclosures"]
    card.india_notes = [IndiaNote(category="data", item="x", why="y",
                                  triggered_by="z",
                                  addresses=["promoter pledge"])]
    assert not derive(card).unaddressed_inputs
