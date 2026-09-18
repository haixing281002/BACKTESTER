"""Stage 01 now decides two things that dominate everything downstream: which
universe a paper is tested on, and what the strategy actually is.

Both are interpretation, so both are wrong sometimes. These tests pin the
places where a wrong answer must be caught rather than absorbed.
"""
import pytest

from ros.cards.schema import (CardValidationError, StrategyReconstruction,
                              UniverseTranslation, load_card)
from ros.data.firm_registry import build_firm_registry
from ros.data.intake import ManifestError, describe_shortfall, manifest_stanza
from ros.data.universes import (DIRECT, GRADES, INFEASIBLE, NEEDS_DATA,
                                SLEEVE_PROXY, canonical_source,
                                check_translation, known_sources,
                                translations_for)
from ros.governance.gates import gate_a

CARD = "examples/cards/devanathan_2026_india_factor_adaptation.yaml"


@pytest.fixture(scope="module")
def registry():
    return build_firm_registry()


# ---------------------------------------------------------------------------
# The table is looked up, never guessed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spelling,expected", [
    ("SPY", "S&P 500"), ("s&p 500", "S&P 500"), ("SPX", "S&P 500"),
    ("russell 2000", "Russell 2000"), ("Nikkei", "Nikkei 225"),
    ("58 futures markets", "Global futures (multi-asset)"),
    ("stock/bond/gold", "US multi-asset (equity / bond / gold)"),
])
def test_known_spellings_resolve(spelling, expected):
    assert canonical_source(spelling) == expected


@pytest.mark.parametrize("unknown", [
    "the CRSP universe of everything",     # near-miss on a real entry
    "Bovespa", "KOSPI 200", "", "US equities maybe",
])
def test_an_unrecognised_universe_returns_none_rather_than_guessing(unknown):
    """A near-miss that silently picks the wrong universe backtests a different
    question and nobody finds out. An honest None goes to a human instead."""
    assert canonical_source(unknown) is None


def test_every_recorded_translation_states_what_it_costs():
    """A translation with nothing to lose has not been examined."""
    bare = []
    for src in known_sources():
        for t in translations_for(src):
            if not t.transfer_risks:
                bare.append(f"{t.source} -> {t.target}")
            assert t.grade in GRADES
            assert not t.validate(), t.validate()
    assert not bare, f"translations with no stated risk: {bare}"


# ---------------------------------------------------------------------------
# The code computes the resolution; the card only claims one
# ---------------------------------------------------------------------------
def test_a_sleeve_paper_resolves_against_what_we_hold(registry):
    ut = UniverseTranslation(
        source_universe="stock/bond/gold", target_universe="NSE factor sleeves",
        grade="loose", resolution="sleeve_proxy", transfer_risks=["x"])
    chk = check_translation(ut, registry)
    assert chk.computed_resolution == SLEEVE_PROXY
    assert not chk.missing
    assert not chk.divergences


def test_a_cross_sectional_paper_names_the_data_we_lack(registry):
    """The case that matters: most equity research needs stock-level data."""
    ut = UniverseTranslation(
        source_universe="S&P 500", target_universe="NIFTY 500 constituents",
        grade="loose", resolution="direct", transfer_risks=["x"])
    chk = check_translation(ut, registry)
    assert chk.computed_resolution == NEEDS_DATA
    assert "nifty500_constituent_prices" in chk.missing
    assert "nifty500_membership_history" in chk.missing
    assert chk.needs_human


def test_an_overclaimed_resolution_is_reported_not_reconciled(registry):
    """The card said `direct`; the fund holds none of it. The registry decides
    and the disagreement reaches a human rather than being silently resolved."""
    ut = UniverseTranslation(
        source_universe="S&P 500", target_universe="NIFTY 500 constituents",
        grade="loose", resolution="direct", transfer_risks=["x"])
    chk = check_translation(ut, registry)
    assert chk.claimed_resolution == DIRECT
    assert chk.computed_resolution == NEEDS_DATA
    assert any("claims resolution" in d for d in chk.divergences)


def test_a_model_chosen_target_is_allowed_not_rejected(registry):
    """The recorded pairs are defaults, not a whitelist.

    The same S&P 500 paper belongs on NIFTY 100 for large-cap purity, NIFTY 500
    for breadth, or Microcap 250 if the question is whether the effect is an
    artefact. Forcing one answer would make the pipeline test the wrong thing
    confidently, which is worse than testing the right thing with a caveat.
    """
    ut = UniverseTranslation(
        source_universe="S&P 500", target_universe="NIFTY Smallcap 250 constituents",
        grade="close", resolution="needs_data", transfer_risks=["x"])
    chk = check_translation(ut, registry)
    assert not chk.divergences, chk.divergences
    assert chk.target_is_known and not chk.recorded_pair
    assert any("model-chosen" in n for n in chk.notes)


def test_a_target_that_is_not_an_indian_universe_is_a_divergence(registry):
    """Open choice still means choosing from somewhere real."""
    ut = UniverseTranslation(
        source_universe="S&P 500", target_universe="FTSE All-Share",
        grade="close", resolution="direct", transfer_risks=["x"])
    chk = check_translation(ut, registry)
    assert any("not an Indian universe" in d for d in chk.divergences)


def test_no_analogue_is_infeasible_not_silently_empty(registry):
    ut = UniverseTranslation(source_universe="MSCI World", target_universe="",
                             grade="none", resolution="infeasible")
    chk = check_translation(ut, registry)
    assert chk.computed_resolution == INFEASIBLE


def test_long_only_caveats_reach_the_human(registry):
    ut = UniverseTranslation(
        source_universe="Russell 1000", target_universe="NIFTY 500 constituents",
        grade="close", resolution="needs_data", transfer_risks=["x"])
    chk = check_translation(ut, registry, long_only=True)
    assert any("cannot short" in c for c in chk.caveats)
    assert any("SHORT-LEG ALPHA" in c for c in chk.caveats)


# ---------------------------------------------------------------------------
# A long-short paper cannot enter a long-only fund unexamined
# ---------------------------------------------------------------------------
def test_a_long_short_strategy_must_state_its_adaptation():
    st = StrategyReconstruction(
        signal_name="s", signal_definition="rank on B/M, long top decile, "
                                           "short bottom decile",
        is_long_short=True, long_only_adaptation="", engine_template="fixed_weight")
    errs = st.validate()
    assert any("cannot short" in e for e in errs), errs


def test_a_stated_adaptation_passes():
    st = StrategyReconstruction(
        signal_name="s", signal_definition="rank on B/M",
        is_long_short=True, engine_template="fixed_weight", confidence="high",
        long_only_adaptation="Long leg only; the short leg is dropped, which "
                             "removes roughly half the published spread.")
    assert not st.validate()


def test_prose_is_not_a_strategy():
    st = StrategyReconstruction(signal_name="value", signal_definition="  ")
    assert any("signal_definition is required" in e for e in st.validate())


def test_a_missing_template_must_say_what_to_build():
    st = StrategyReconstruction(
        signal_name="s", signal_definition="rank on B/M",
        engine_template="NEEDS_NEW_TEMPLATE", template_gap="")
    assert any("template_gap" in e for e in st.validate())


def test_a_translation_with_no_risks_fails_validation():
    ut = UniverseTranslation(source_universe="S&P 500",
                             target_universe="NIFTY 500 constituents",
                             grade="loose", transfer_risks=[])
    assert any("transfer_risks" in e for e in ut.validate())


# ---------------------------------------------------------------------------
# Gate A must be able to BLOCK on these, or adding them changed nothing
# ---------------------------------------------------------------------------
class _Feas:
    can_proceed, verdict, blocking, resolutions = True, "GO", [], []


def test_gate_a_blocks_a_card_with_no_universe_translation():
    card = load_card(CARD)
    card.universe_translation = None
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria if c.name == "universe translation recorded")
    assert row.blocking and not row.passed
    assert not gr.passed


def test_gate_a_blocks_a_card_with_no_strategy():
    card = load_card(CARD)
    card.strategy = None
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria if c.name == "strategy reconstructed")
    assert row.blocking and not row.passed
    assert not gr.passed


def test_gate_a_blocks_when_the_engine_cannot_express_the_strategy():
    card = load_card(CARD)
    card.strategy.engine_template = "NEEDS_NEW_TEMPLATE"
    card.strategy.template_gap = "a cross-sectional decile sorter"
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria
               if c.name == "the engine can express this strategy")
    assert row.blocking and not row.passed


def test_gate_a_blocks_when_the_fund_cannot_obtain_the_universe(registry):
    card = load_card(CARD)
    card.universe_translation.source_universe = "S&P 500"
    card.universe_translation.target_universe = "NIFTY 500 constituents"
    chk = check_translation(card.universe_translation, registry)
    gr = gate_a(card, _Feas(), translation_check=chk)
    row = next(c for c in gr.criteria if c.name == "the fund can obtain this universe")
    assert row.blocking and not row.passed
    assert "nifty500_constituent_prices" in row.evidence


def test_the_shipped_cards_clear_gate_a_on_these_criteria(registry):
    """If the repo's own worked examples cannot pass, the criteria are wrong."""
    for path in ("examples/cards/devanathan_2026_india_factor_adaptation.yaml",
                 "examples/cards/moskowitz_2012_tsmom_india.yaml"):
        card = load_card(path)
        chk = check_translation(card.universe_translation, registry,
                                long_only=card.portfolio.long_only)
        gr = gate_a(card, _Feas(), translation_check=chk)
        failed = [c.name for c in gr.criteria if c.blocking and not c.passed]
        assert not failed, f"{path}: {failed}"


# ---------------------------------------------------------------------------
# Supplying data at Gate A
# ---------------------------------------------------------------------------
def test_the_shortfall_block_names_every_missing_series():
    txt = describe_shortfall(["nifty500_constituent_prices",
                              "nifty500_membership_history"])
    assert "nifty500_constituent_prices" in txt
    assert "nifty500_membership_history" in txt
    assert "MANIFEST.yaml" in txt
    assert "pit_status" in txt, "the honesty field must be in the paste-able stanza"


def test_a_membership_series_is_offered_the_right_kind():
    assert "kind: membership" in manifest_stanza("x_membership_history",
                                                 kind="membership")


def test_supplied_data_may_not_shadow_the_firms_own(tmp_path, registry):
    """A dropped file silently overriding a firm feed is how an unauditable
    result gets made."""
    import os
    from ros.data import intake
    m = tmp_path / "MANIFEST.yaml"
    csv = tmp_path / "x.csv"
    csv.write_text("Date,v\n2020-01-01,1\n", encoding="utf-8")
    m.write_text(
        "series:\n"
        "  - name: NIFTY 500\n"
        "    kind: price\n"
        "    frequency: daily\n"
        "    file: x.csv\n"
        "    pit_status: backfilled\n"
        '    licence: "test"\n', encoding="utf-8")
    old = intake.RAW_DIR
    try:
        intake.RAW_DIR = str(tmp_path)
        with pytest.raises(ManifestError, match="collides"):
            intake.extend_registry(registry, str(m))
    finally:
        intake.RAW_DIR = old


def test_a_manifest_missing_the_honesty_fields_is_refused(tmp_path, registry):
    from ros.data import intake
    m = tmp_path / "MANIFEST.yaml"
    (tmp_path / "x.csv").write_text("Date,v\n2020-01-01,1\n", encoding="utf-8")
    m.write_text("series:\n  - name: foo\n    kind: price\n    frequency: daily\n"
                 "    file: x.csv\n", encoding="utf-8")
    old = intake.RAW_DIR
    try:
        intake.RAW_DIR = str(tmp_path)
        with pytest.raises(ManifestError) as e:
            intake.read_manifest(str(m))
        assert "pit_status" in str(e.value) and "licence" in str(e.value)
    finally:
        intake.RAW_DIR = old


# ---------------------------------------------------------------------------
# Choosing a universe by FIT, rather than looking one up
#
# The catalogue is open: any Indian equity universe may be chosen, including one
# the fund cannot hold, because establishing that a mechanism is REAL is a
# different question from being allowed to run it. What is not open is choosing
# without justification -- the fit is recomputed by code and shown at Gate A.
# ---------------------------------------------------------------------------
from ros.cards.schema import MechanismNeeds
from ros.data.universes import (INDIAN_UNIVERSES, MechanismRequirements,
                                propose_universes, score_universe)


def test_the_catalogue_spans_the_indian_market():
    """Cap segments and sectors both, or the choice is not really open."""
    segs = {u.cap_segment for u in INDIAN_UNIVERSES.values()}
    assert {"mega", "large", "mid", "small", "micro", "all"} <= segs, segs
    assert any(u.sector for u in INDIAN_UNIVERSES.values()), "no sector universes"
    assert any(not u.in_mandate for u in INDIAN_UNIVERSES.values()), (
        "every universe is in-mandate, so the fund could never test whether an "
        "effect it cannot hold is nonetheless real")
    for u in INDIAN_UNIVERSES.values():
        assert u.market == "IN"
        assert u.required_instruments, f"{u.name} names no instruments"


@pytest.mark.parametrize("req,expected", [
    # a decile sort on large caps wants the large-cap cross-section
    (MechanismRequirements(min_names=100, cap_segment="large"),
     "NIFTY 100 constituents"),
    # a bank-specific signal wants a financials universe
    (MechanismRequirements(min_names=10, cap_segment="large", sector="financials"),
     "NIFTY Financial Services constituents"),
    # a small-cap anomaly wants small caps
    (MechanismRequirements(min_names=100, cap_segment="small"),
     "NIFTY Smallcap 250 constituents"),
    # "is this just a micro-cap artefact?" wants micro caps
    (MechanismRequirements(min_names=100, cap_segment="micro"),
     "NIFTY Microcap 250 constituents"),
    # a time-series mechanism over a handful of streams wants what we hold
    (MechanismRequirements(needs_cross_section=False, min_names=5),
     "NSE factor sleeves"),
])
def test_the_best_fitting_universe_is_the_obvious_one(req, expected):
    assert propose_universes(req)[0].universe.name == expected


def test_a_universe_too_thin_for_the_sort_is_disqualified():
    req = MechanismRequirements(min_names=100, cap_segment="large")
    fit = score_universe(INDIAN_UNIVERSES["NIFTY IT constituents"], req)
    assert fit.disqualifying and not fit.usable
    assert "cannot support a sort" in fit.disqualifying[0]


def test_a_broad_paper_is_steered_away_from_sector_universes():
    req = MechanismRequirements(min_names=10, cap_segment="large", sector=None)
    broad = score_universe(INDIAN_UNIVERSES["NIFTY 100 constituents"], req)
    sector = score_universe(INDIAN_UNIVERSES["NIFTY Pharma constituents"], req)
    assert broad.score > sector.score
    assert any("narrows a broad-market mechanism" in r
               for r in sector.reasons_against)


def test_a_sector_paper_will_not_accept_the_wrong_sector():
    req = MechanismRequirements(min_names=5, cap_segment="large", sector="financials")
    fit = score_universe(INDIAN_UNIVERSES["NIFTY Pharma constituents"], req)
    assert fit.disqualifying and "wrong sector" in fit.disqualifying[0]


def test_out_of_mandate_is_testable_but_flagged():
    """The distinction the fund needs: real, versus runnable here."""
    req = MechanismRequirements(min_names=100, cap_segment="micro")
    fits = propose_universes(req)
    micro = next(f for f in fits
                 if f.universe.name == "NIFTY Microcap 250 constituents")
    assert micro.usable, "a fund must be able to test what it cannot hold"
    assert any("OUTSIDE the mandate" in r for r in micro.reasons_against)


def test_requiring_a_holdable_run_removes_out_of_mandate_universes():
    req = MechanismRequirements(min_names=100, cap_segment="all",
                                must_be_in_mandate=True)
    names = [f.universe.name for f in propose_universes(req)]
    assert "NIFTY Total Market constituents" not in names
    assert "NIFTY Microcap 250 constituents" not in names
    assert "NIFTY 500 constituents" in names


def test_a_disqualified_choice_is_a_divergence(registry):
    """Open choice does not mean unchecked choice."""
    ut = UniverseTranslation(
        source_universe="S&P 500", target_universe="NIFTY IT constituents",
        grade="loose", resolution="needs_data", transfer_risks=["x"],
        mechanism_needs=MechanismNeeds(min_names=100, cap_segment="large"))
    chk = check_translation(ut, registry)
    assert any("disqualified" in d for d in chk.divergences), chk.divergences


def test_a_clearly_better_alternative_is_surfaced(registry):
    """Not an error -- but the card should say why it was passed over."""
    ut = UniverseTranslation(
        source_universe="S&P 500", target_universe="NIFTY Metal constituents",
        grade="loose", resolution="needs_data", transfer_risks=["x"],
        mechanism_needs=MechanismNeeds(min_names=10, cap_segment="large"))
    chk = check_translation(ut, registry)
    assert any("scores" in n and "passed over" in n for n in chk.notes), chk.notes


def test_the_chosen_universe_is_always_shown_against_its_rivals(registry):
    ut = UniverseTranslation(
        source_universe="S&P 500",
        target_universe="NIFTY Midcap 150 constituents",
        grade="loose", resolution="needs_data", transfer_risks=["x"],
        mechanism_needs=MechanismNeeds(min_names=100, cap_segment="large"))
    chk = check_translation(ut, registry)
    assert any(f.universe.name == ut.target_universe for f in chk.ranked), (
        "the chosen universe fell off the ranked list, so a reviewer cannot "
        "compare it to the alternatives")
    assert "<- chosen" in chk.render()


def test_the_catalogue_knows_what_data_each_universe_needs(registry):
    """A chosen universe names its own instruments, so Stage 03 can resolve it
    and Gate A can print exactly what to supply."""
    ut = UniverseTranslation(
        source_universe="Russell 1000",
        target_universe="NIFTY Midcap 150 constituents",
        grade="loose", resolution="needs_data", transfer_risks=["x"])
    chk = check_translation(ut, registry)
    assert "nifty_midcap_150_constituent_prices" in chk.missing
    assert "nifty_midcap_150_membership_history" in chk.missing


def test_mechanism_needs_reject_an_unknown_segment():
    assert any("cap_segment" in e
               for e in MechanismNeeds(cap_segment="enormous").validate())


# ---------------------------------------------------------------------------
# A paper about an asset the fund cannot hold
#
# "There is a paper about gold." You cannot buy gold. You CAN buy the listed
# businesses whose earnings track it -- and that is a different bet whose sign
# may be inverted. The translation exists so that trade-off is recorded rather
# than either refused outright or waved through.
# ---------------------------------------------------------------------------
from ros.data.universes import EXPOSURE_PROXY, EXPOSURE_SECTORS, caveats_for


@pytest.mark.parametrize("spelling", ["gold", "Gold", "bullion", "XAU", "GLD",
                                      "gold futures", "gold price"])
def test_gold_resolves_to_a_source_universe(spelling):
    assert canonical_source(spelling) == "Gold (spot or futures)"


@pytest.mark.parametrize("spelling,expected", [
    ("Brent", "Crude oil"), ("WTI", "Crude oil"), ("crude oil", "Crude oil"),
    ("usdinr", "FX (USD)"), ("dollar", "FX (USD)"),
    ("gsec", "Government bonds / duration"),
    ("treasuries", "Government bonds / duration"),
])
def test_other_non_equity_assets_resolve(spelling, expected):
    assert canonical_source(spelling) == expected


def test_a_gold_paper_routes_to_gold_linked_equities():
    t = translations_for("gold")[0]
    assert t.target == "Gold-linked Indian equities"
    assert t.grade == "loose", "this is never a close correspondence"


def test_the_gold_translation_still_requires_the_gold_price():
    """The equities are what you HOLD; the commodity is what you SIGNAL on.
    Supplying only the equities tests nothing."""
    t = translations_for("gold")[0]
    assert any("gold_price" in i for i in t.required_instruments)
    assert any("constituent_prices" in i for i in t.required_instruments)
    assert any("membership_history" in i for i in t.required_instruments)


def test_the_inverted_sign_is_stated_not_left_to_be_discovered():
    """Rising gold helps a lender's collateral and hurts a jeweller's volumes.
    A basket of both can net to noise while each half has a strong effect."""
    t = translations_for("gold")[0]
    risks = " ".join(t.transfer_risks).lower()
    assert "opposite" in risks or "hurts" in risks
    assert "separately" in risks or "uninterpretable" in risks


def test_an_exposure_proxy_carries_its_own_caveats(registry):
    cav = " ".join(caveats_for("Gold-linked Indian equities")).lower()
    assert "an equity is not the asset" in cav
    assert "sign can invert" in cav
    assert "too few names for a sort" in cav


def test_an_exposure_proxy_is_resolved_as_such_not_as_direct(registry):
    from ros.data.registry import DataCapability
    ut = UniverseTranslation(
        source_universe="gold", target_universe="Gold-linked Indian equities",
        grade="loose", transfer_risks=["x"])
    # pretend the three series were supplied
    for name in translations_for("gold")[0].required_instruments:
        registry.add(DataCapability(name=name, kind="price", frequency="daily",
                                    pit_status="point_in_time", licence="test"))
    chk = check_translation(ut, registry)
    assert chk.computed_resolution == EXPOSURE_PROXY, chk.computed_resolution
    assert not chk.missing


def test_a_gold_timing_mechanism_ranks_the_gold_basket_first():
    req = MechanismRequirements(needs_cross_section=False, min_names=5,
                                cap_segment="large_mid", sector="gold_linked")
    assert propose_universes(req)[0].universe.name == "Gold-linked Indian equities"


def test_a_gold_cross_sectional_sort_is_disqualified():
    """Eight names cannot support a decile sort, whatever the paper did."""
    req = MechanismRequirements(min_names=100, cap_segment="large_mid",
                                sector="gold_linked")
    fit = score_universe(INDIAN_UNIVERSES["Gold-linked Indian equities"], req)
    assert fit.disqualifying and "cannot support a sort" in fit.disqualifying[0]


def test_every_exposure_universe_names_its_underlying_series():
    """An exposure proxy without the underlying is untestable by construction."""
    for u in INDIAN_UNIVERSES.values():
        if u.sector in EXPOSURE_SECTORS:
            inst = " ".join(u.required_instruments)
            assert "constituent_prices" in inst, u.name
            assert any(k in inst for k in ("price_inr", "spot", "rate", "yield")), (
                f"{u.name} names no underlying series to signal on")


# ---------------------------------------------------------------------------
# The card at a glance -- the nine fields a reviewer checks first
# ---------------------------------------------------------------------------
def test_at_a_glance_shows_every_field_a_reviewer_needs():
    card = load_card("examples/cards/moskowitz_2012_tsmom_india.yaml")
    txt = card.at_a_glance()
    for label in ("universe", "signal", "lookback", "lag", "weights",
                  "rebalance", "benchmark", "costs", "ambiguities", "confidence"):
        assert label in txt, label


def test_at_a_glance_names_both_ends_of_the_translation():
    card = load_card("examples/cards/moskowitz_2012_tsmom_india.yaml")
    txt = card.at_a_glance()
    assert "NSE factor sleeves" in txt
    assert "from: Global futures" in txt


def test_at_a_glance_flags_a_long_short_source_and_a_cash_conflict():
    card = load_card("examples/cards/moskowitz_2012_tsmom_india.yaml")
    txt = card.at_a_glance()
    assert "SOURCE IS LONG-SHORT" in txt
    assert "mandate forbids cash" in txt


def test_at_a_glance_says_not_stated_rather_than_inventing_a_default():
    """A blank is a Gate A item, not something to fill in politely."""
    card = load_card("examples/cards/moskowitz_2012_tsmom_india.yaml")
    card.signal.lookback_days = None
    card.universe.benchmark = None
    txt = card.at_a_glance()
    assert txt.count("not stated") >= 2


def test_at_a_glance_shouts_when_no_template_fits():
    card = load_card("examples/cards/moskowitz_2012_tsmom_india.yaml")
    card.strategy.engine_template = "NEEDS_NEW_TEMPLATE"
    assert "NO TEMPLATE FITS" in card.at_a_glance()


def test_at_a_glance_surfaces_unresolved_ambiguities():
    card = load_card("examples/cards/moskowitz_2012_tsmom_india.yaml")
    card.ambiguities[0].resolution = ""
    assert "UNRESOLVED" in card.at_a_glance()


# ---------------------------------------------------------------------------
# The card's two outward-facing sections
#
# Everything else on a card describes the paper. These describe what is still
# needed to do it justice: what the model would ask the fund for, and what the
# paper does not settle. Both are easy to leave empty, so both are checked.
# ---------------------------------------------------------------------------
from ros.cards.schema import DataRequest, OpenQuestion
from ros.cards.completeness import assess as card_completeness

EXEMPLAR = "examples/cards/devanathan_2026_india_factor_adaptation.yaml"


def test_a_request_without_a_fallback_is_refused():
    """A request with no fallback is a demand, and a demand at Gate A stops the
    work instead of informing it."""
    r = DataRequest(item="an Indian T-bill series", why="numeraire",
                    unlocks="a defensible Sharpe", without_it="")
    assert any("without_it" in e for e in r.validate("data_requests[0]"))


def test_a_request_with_a_fallback_passes():
    r = DataRequest(item="x", why="y", unlocks="z",
                    without_it="flat 6% proxy, swept 4-8%, reported as "
                               "rate-dependent")
    assert not r.validate("data_requests[0]")


def test_an_unknown_priority_is_refused():
    r = DataRequest(item="x", without_it="y", priority="urgent")
    assert any("priority" in e for e in r.validate("d"))


def test_a_question_needs_an_assumption_or_must_declare_it_blocks():
    """Otherwise it stalls the run for no reason -- the model asking someone
    else to do its job."""
    q = OpenQuestion(question="what vol target?", why_it_matters="it binds",
                     what_i_assumed="", blocks_run=False)
    assert any("what_i_assumed" in e for e in q.validate("open_questions[0]"))
    q.blocks_run = True
    assert not q.validate("open_questions[0]")


def test_a_question_is_addressed_to_someone():
    q = OpenQuestion(question="q", what_i_assumed="a", ask_of="the board")
    assert any("ask_of" in e for e in q.validate("q"))


def test_the_exemplar_card_asks_for_things_and_says_what_it_would_do_instead():
    card = load_card(EXEMPLAR)
    assert len(card.data_requests) >= 3
    assert len(card.open_questions) >= 2
    assert all(r.without_it.strip() for r in card.data_requests)
    assert all(q.what_i_assumed.strip() for q in card.open_questions)
    assert not card.blocking_requests and not card.blocking_questions


def test_the_asks_block_shows_priority_fallback_and_who_to_ask():
    txt = load_card(EXEMPLAR).asks()
    assert "WHAT WOULD MAKE THIS TEST BETTER" in txt
    assert "if declined" in txt, "the fallback must reach the reader"
    assert "for the PM" in txt, "a PM should not read the data owner's queue"
    assert "I assumed" in txt


def test_an_empty_asks_block_says_so_rather_than_printing_nothing():
    """Silence reads as nobody having looked."""
    card = load_card(EXEMPLAR)
    card.data_requests, card.open_questions = [], []
    txt = card.asks()
    assert "NOTHING IS BEING ASKED FOR" in txt
    assert "strong claim" in txt


def test_gate_a_blocks_on_a_blocking_request(registry):
    card = load_card(EXEMPLAR)
    card.data_requests[0].priority = "blocking"
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria if c.name == "no request is blocking")
    assert row.blocking and not row.passed
    assert card.data_requests[0].item in row.evidence


def test_gate_a_blocks_on_a_blocking_question(registry):
    card = load_card(EXEMPLAR)
    card.open_questions[0].blocks_run = True
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria if c.name == "no question blocks the run")
    assert row.blocking and not row.passed


def test_a_fallback_less_request_never_reaches_gate_a_at_all(registry, tmp_path):
    """This used to be a Gate A criterion, and it could not fail.

    The old test mutated a loaded card to empty a `without_it`, then asserted
    that Gate A caught it. It did -- but no card in that state can ever reach
    Gate A, because DataRequest.validate() rejects it and load_card() raises. A
    criterion that only fires on a hand-mutated object is a green row on every
    real run. Assert the real contract instead: the schema stops it upstream.
    """
    import yaml
    from ros.cards.schema import CardValidationError
    blob = yaml.safe_load(open(EXEMPLAR, encoding="utf-8"))
    blob["data_requests"][0]["without_it"] = ""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(blob), encoding="utf-8")
    with pytest.raises(CardValidationError) as e:
        load_card(str(bad))
    assert "without_it" in str(e.value)


def test_gate_a_flags_a_card_that_asked_for_nothing(registry):
    """The case the old criterion silently passed.

    `all()` over an empty list is True, so a card that asked for nothing scored
    exactly like one that asked well.
    """
    card = load_card(EXEMPLAR)
    card.data_requests = []
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria
               if c.name == "the card asked for something, or argued it need not")
    assert not row.passed
    assert "silen" in row.evidence.lower() or "nothing" in row.evidence.lower()


def test_an_argued_silence_is_accepted(registry):
    """Asking for nothing is legitimate -- as a claim, not as a blank."""
    card = load_card(EXEMPLAR)
    card.data_requests = []
    card.no_further_data_needed = (
        "The five sleeve series are the whole mechanism; no further series "
        "would change the verdict, only what we may claim from it.")
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria
               if c.name == "the card asked for something, or argued it need not")
    assert row.passed


def test_gate_a_catches_a_placeholder_fallback(registry):
    """Non-empty satisfies the schema. 'N/A' satisfies nobody."""
    card = load_card(EXEMPLAR)
    card.data_requests[0].without_it = "N/A"
    gr = gate_a(card, _Feas())
    row = next(c for c in gr.criteria
               if c.name == "fallbacks are decisions you could take")
    assert not row.passed and row.blocking


# ---------------------------------------------------------------------------
# Completeness: a card that validates is not a card that is any good
# ---------------------------------------------------------------------------
def test_the_exemplar_scores_near_full():
    r = card_completeness(load_card(EXEMPLAR))
    assert r.score > 0.95, [m.name for m in r.missing]
    assert not r.serious, [m.name for m in r.serious]


def test_a_card_that_merely_validates_scores_badly():
    """The whole point: the schema cannot tell six cited ambiguities from none."""
    from ros.cards.schema import (CostSpec, Intent, Paper, PortfolioSpec,
                                  Signal, StrategyCard, Universe)
    bare = StrategyCard(
        paper=Paper(id="x", title="x"),
        intent=Intent(mode="adaptation", transferred_mechanism="m"),
        universe=Universe(assets=["A"]), signal=Signal(template="fixed_weight"),
        portfolio=PortfolioSpec(), costs=CostSpec(spread_bps=5.0))
    assert not bare.validate(), "this card is structurally valid"
    r = card_completeness(bare)
    assert r.score < 0.35, r.score
    assert len(r.serious) >= 8


def test_completeness_catches_a_cost_copied_from_the_paper():
    card = load_card(EXEMPLAR)
    card.costs.spread_bps = 5.0
    r = card_completeness(card)
    bad = [c for c in r.missing if "cost not copied" in c.name]
    assert bad and bad[0].weight >= 3


def test_completeness_catches_a_zero_lag():
    card = load_card(EXEMPLAR)
    card.signal.lag_days = 0
    assert any("lag" in c.name for c in card_completeness(card).missing)


def test_completeness_catches_a_translation_with_no_argument():
    card = load_card(EXEMPLAR)
    card.universe_translation.rationale = "seems right"
    card.universe_translation.why_not_alternatives = ""
    missing = [c.name for c in card_completeness(card).missing]
    assert "rationale for the target" in missing
    assert "why not the alternatives" in missing


def test_every_completeness_check_says_what_it_prevents():
    """A check that cannot say why it exists is a house-style rule."""
    r = card_completeness(load_card(EXEMPLAR))
    for c in r.checks:
        assert c.matters.strip(), f"{c.section}/{c.name} has no stated rationale"
        assert 1 <= c.weight <= 3
