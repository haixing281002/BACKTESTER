"""Gate A must say what it takes to run THIS strategy in India.

"You are missing nifty500_constituent_prices" names a file, not a specification.
Two vendors will sell you something with that name and only one will let you run
the strategy. These tests pin the requirements that actually decide that, and --
more importantly -- pin the false positives out.

A spurious MUST is worse than a missing one. It sends someone to a vendor for a
field the strategy never reads, and the next reader trusts the whole block less.
Half of this file exists because the first draft did exactly that.
"""
import pytest

from ros.cards.schema import (CostSpec, Intent, MechanismNeeds, Paper,
                              PortfolioSpec, Signal, StrategyCard,
                              StrategyReconstruction, Universe,
                              UniverseTranslation, load_card)
from ros.india_requirements import (COST, DATA, EXECUTION, TIMING, VALIDITY,
                                    derive)


def _card(**strategy_kw):
    """A minimal card whose strategy fields the tests vary."""
    seg = strategy_kw.pop("cap_segment", "all")
    target = strategy_kw.pop("target", "NIFTY 500 constituents")
    defaults = dict(
        signal_name="s", signal_definition="rank on something",
        inputs_required=["daily adjusted close"], cross_sectional=True,
        formation_rule="decile sort", weighting_rule="equal weight",
        rebalance_frequency="monthly", engine_template="cross_sectional",
        confidence="high")
    defaults.update(strategy_kw)
    return StrategyCard(
        paper=Paper(id="t", title="t"),
        intent=Intent(mode="adaptation", transferred_mechanism="m"),
        universe=Universe(assets=["A"]), signal=Signal(template="x", lag_days=1),
        portfolio=PortfolioSpec(rebalance="monthly"), costs=CostSpec(),
        universe_translation=UniverseTranslation(
            source_universe="Russell 1000", target_universe=target,
            grade="close", transfer_risks=["r"],
            mechanism_needs=MechanismNeeds(min_names=100, cap_segment=seg)),
        strategy=StrategyReconstruction(**defaults))


def _items(req, category=None):
    return [r.item for r in req.requirements
            if category is None or r.category == category]


def _says(req, text, category=None):
    return any(text.lower() in i.lower() for i in _items(req, category))


# ---------------------------------------------------------------------------
# A cross-section demands the three things that decide whether it is honest
# ---------------------------------------------------------------------------
def test_a_cross_section_demands_pit_membership():
    r = derive(_card())
    assert _says(r, "point-in-time membership", DATA)
    assert all(x.blocking for x in r.requirements
               if "point-in-time membership" in x.item.lower())


def test_a_cross_section_demands_adjusted_prices_and_delisting_values():
    r = derive(_card())
    assert _says(r, "adjusted for bonuses", DATA)
    assert _says(r, "name that left", DATA)


def test_a_cross_section_names_the_chosen_universe_not_a_generic_one():
    r = derive(_card(target="NIFTY Midcap 150 constituents"))
    assert _says(r, "NIFTY Midcap 150", DATA), _items(r, DATA)


def test_survivorship_and_unadjusted_prices_are_named_as_invalidators():
    r = derive(_card())
    assert _says(r, "survivor-only", VALIDITY)
    assert _says(r, "unadjusted", VALIDITY)


# ---------------------------------------------------------------------------
# A fundamental signal is the look-ahead case
# ---------------------------------------------------------------------------
def test_a_fundamental_signal_demands_publication_dates():
    r = derive(_card(inputs_required=["daily adjusted close", "book equity"],
                     signal_definition="rank on book-to-market"))
    assert _says(r, "date it became public", DATA)
    assert _says(r, "filing lag", TIMING)
    assert _says(r, "fiscal period end", VALIDITY)


def test_a_price_only_signal_does_not_demand_publication_dates():
    r = derive(_card(inputs_required=["daily adjusted close"],
                     signal_definition="rank on 12-month trailing return"))
    assert not _says(r, "date it became public")
    assert not _says(r, "filing lag")


# ---------------------------------------------------------------------------
# FALSE POSITIVES -- each of these shipped in the first draft
# ---------------------------------------------------------------------------
def test_scaling_the_book_is_not_a_fundamental_read():
    """"scales the book to a volatility target" matched bare `book`."""
    r = derive(_card(
        cross_sectional=False,
        inputs_required=["daily close of each sleeve"],
        signal_definition="size each position inverse to trailing volatility, "
                          "then scale the book to a volatility target"))
    assert not _says(r, "date it became public"), \
        "'scale the book' was read as a fundamental input"


def test_a_capped_weight_is_not_cap_weighting():
    """"capped at unlevered" matched bare `cap`."""
    r = derive(_card(
        cross_sectional=False,
        weighting_rule="inverse volatility, scaled to target, capped at unlevered",
        signal_definition="trailing return filter"))
    assert not _says(r, "free-float market cap"), \
        "'capped at unlevered' was read as cap weighting"


def test_a_turnover_cost_term_is_not_a_volume_input():
    """"half-spread turnover cost" is an objective term, not a data read."""
    r = derive(_card(
        cross_sectional=False,
        inputs_required=["daily close of each sleeve"],
        signal_definition="maximise forecast return net of half-spread "
                          "turnover cost"))
    adv = [x for x in r.requirements if "traded value" in x.item.lower()]
    assert not adv, "a turnover-cost term demanded ADV data"


def test_the_block_says_what_it_matched_on():
    """So a human can spot a spurious MUST instead of going shopping."""
    r = derive(_card(inputs_required=["daily adjusted close", "book equity"],
                     weighting_rule="free-float market cap weighted"))
    assert r.matched_on
    text = r.render()
    assert "Raised by:" in text and "spurious" in text


def test_unrecognised_inputs_are_surfaced_not_swallowed():
    """The failure mode of keyword matching is SILENCE, not a wrong answer.

    An input no pattern can read raises no requirement and says nothing, so the
    report has to say it looked and failed. With no india_notes covering it, it
    is reported as read by nobody.
    """
    r = derive(_card(inputs_required=["analyst revision breadth score"]))
    assert "analyst revision breadth score" in r.unmatched_inputs
    assert r.unaddressed_inputs == ["analyst revision breadth score"]
    text = r.render()
    assert "analyst revision breadth score" in text
    assert "NOBODY HAS LOOKED" in text


# ---------------------------------------------------------------------------
# Strategy shape drives the India-specific hazards
# ---------------------------------------------------------------------------
def test_a_momentum_signal_raises_circuit_limits():
    r = derive(_card(signal_definition="rank on 12-1 momentum",
                     formation_rule="top decile by momentum"))
    assert _says(r, "circuit-limit", EXECUTION)


def test_a_value_signal_does_not_raise_circuit_limits():
    r = derive(_card(signal_definition="rank on book-to-market",
                     formation_rule="decile sort", weighting_rule="equal"))
    assert not _says(r, "circuit-limit")


@pytest.mark.parametrize("seg", ["small", "mid_small", "micro"])
def test_thin_segments_demand_an_impact_model(seg):
    r = derive(_card(cap_segment=seg))
    assert _says(r, "impact model", EXECUTION)


def test_a_fast_rebalance_is_flagged():
    r = derive(_card(rebalance_frequency="daily"))
    assert _says(r, "execution modelling", EXECUTION)


def test_a_long_short_source_asks_what_the_short_leg_earned():
    r = derive(_card(is_long_short=True, long_only_adaptation="long leg only"))
    assert _says(r, "leg-level returns", EXECUTION)


# ---------------------------------------------------------------------------
# Costs: named components, not a stale number
# ---------------------------------------------------------------------------
def test_sleeve_trading_carries_the_thirty_bp_floor():
    r = derive(_card(cross_sectional=False, target="NSE factor sleeves"))
    assert _says(r, "30bp", COST)


def test_single_stock_costs_name_components_rather_than_a_rate():
    """A statutory rate baked into a repo goes stale and is trusted anyway."""
    r = derive(_card())
    stack = [x for x in r.requirements if x.category == COST
             and "stt" in x.item.lower()]
    assert stack, _items(r, COST)
    why = stack[0].why.lower()
    assert "desk" in stack[0].item.lower() or "supplies" in stack[0].item.lower()
    assert "impact" in why
    import re
    assert not re.search(r"\d+\s*(bp|basis|%)", stack[0].item), \
        "a specific statutory rate was baked in; it will go stale"


def test_breakeven_cost_is_always_requested():
    for kw in ({}, {"cross_sectional": False}, {"rebalance_frequency": "daily"}):
        assert _says(derive(_card(**kw)), "breakeven", COST)


# ---------------------------------------------------------------------------
# It works for ANY strategy, including one the engine cannot yet run
# ---------------------------------------------------------------------------
def test_a_strategy_with_no_template_still_gets_its_requirements():
    """The point of asking: what would it take, whether or not we can run it."""
    r = derive(_card(engine_template="NEEDS_NEW_TEMPLATE",
                     template_gap="a cross-sectional decile sorter with "
                                  "sector neutralisation"))
    assert len(r.blocking) >= 5
    assert _says(r, "point-in-time membership", DATA)


def test_the_shipped_cards_produce_a_coherent_block():
    for path in ("examples/cards/devanathan_2026_india_factor_adaptation.yaml",
                 "examples/cards/moskowitz_2012_tsmom_india.yaml"):
        r = derive(load_card(path))
        assert r.requirements
        assert "WHAT IT TAKES" in r.render()
        # Sleeve strategies must NOT demand a stock-level cross-section.
        assert not _says(r, "point-in-time membership"), path


def test_a_card_with_no_strategy_still_returns_the_universal_rules():
    """Degrades rather than crashing: lag and cost apply to everything."""
    card = _card()
    card.strategy = None
    r = derive(card)
    assert _says(r, "lag_days", TIMING)
    assert _says(r, "breakeven", COST)
