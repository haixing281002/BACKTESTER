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

CARD = "cards/devanathan_2026_india_factor_adaptation.yaml"


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


def test_an_unrecorded_target_is_a_divergence(registry):
    ut = UniverseTranslation(
        source_universe="S&P 500", target_universe="NIFTY Smallcap 250 constituents",
        grade="close", resolution="direct", transfer_risks=["x"])
    chk = check_translation(ut, registry)
    assert any("not a recorded correspondence" in d for d in chk.divergences)


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
    for path in ("cards/devanathan_2026_india_factor_adaptation.yaml",
                 "cards/moskowitz_2012_tsmom_india.yaml"):
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
