"""Stage 02 is where the work happens. Gate A only verifies.

If a human at Gate A has to work out the sample window, the warmup, the
benchmarks or what would count as failure, then Stage 02 did not finish and the
gate is doing the design. Three card sections exist to stop that, and these
tests pin the parts that would otherwise be left blank politely.

The one that matters most is `selection.verified_against`. A model naming Indian
stocks from memory produces a plausible, unverifiable list -- and that is worse
than no list, because it looks checked and a reviewer skips it.
"""
import pytest

from ros.cards.completeness import assess as card_completeness
from ros.cards.schema import (BacktestPlan, DataPlan, DataSpec,
                              SecuritySelection, load_card)
from ros.governance.gates import gate_a

EXEMPLAR = "examples/cards/devanathan_2026_india_factor_adaptation.yaml"
TSMOM = "examples/cards/moskowitz_2012_tsmom_india.yaml"


class _Feas:
    can_proceed, verdict, blocking, resolutions = True, "GO", [], []


def _row(card, name):
    return next(c for c in gate_a(card, _Feas()).criteria if c.name == name)


# ---------------------------------------------------------------------------
# data_plan: design the dataset, do not shop for it
# ---------------------------------------------------------------------------
def _spec(**kw):
    base = dict(field="daily adjusted close", granularity="daily",
                history_from="2005-04-01", why="the signal reads it",
                why_granularity="the window is 11 days; monthly cannot form it",
                why_history="earliest common date", adjustments="corporate actions",
                minimum_viable=True)
    base.update(kw)
    return DataSpec(**base)


def test_a_spec_must_argue_its_granularity():
    """The choice that decides what data costs, and it is made by habit."""
    errs = _spec(why_granularity="").validate("d")
    assert any("granularity" in e and "coarser" in e for e in errs)


def test_a_spec_must_say_what_the_mechanism_needs_it_for():
    assert any("mechanism needs" in e for e in _spec(why="").validate("d"))


@pytest.mark.parametrize("bad", ["hourly", "annual", "realtime", ""])
def test_an_unknown_granularity_is_refused(bad):
    assert any("granularity" in e for e in _spec(granularity=bad).validate("d"))


def test_a_plan_with_no_minimum_viable_subset_is_refused():
    """Without a smallest honest subset every request reads as essential and
    none can be traded against cost."""
    dp = DataPlan(ideal=[_spec(minimum_viable=False)],
                  optimality_argument="x" * 100)
    assert any("minimum_viable" in e for e in dp.validate())


def test_a_plan_must_argue_that_it_is_optimal():
    dp = DataPlan(ideal=[_spec()], optimality_argument="")
    assert any("right way to test" in e for e in dp.validate())


def test_a_plan_with_no_fields_is_refused():
    assert any("ideal is empty" in e for e in
               DataPlan(optimality_argument="x" * 100).validate())


def test_a_rejected_alternative_needs_a_reason():
    dp = DataPlan(ideal=[_spec()], optimality_argument="x" * 100,
                  rejected_alternatives=[{"option": "monthly closes"}])
    assert any("why_not" in e for e in dp.validate())


def test_the_exemplar_designs_a_dataset_rather_than_listing_what_we_hold():
    dp = load_card(EXEMPLAR).data_plan
    assert dp is not None and len(dp.ideal) >= 3
    assert sum(1 for d in dp.ideal if d.minimum_viable) >= 1
    assert len(dp.rejected_alternatives) >= 2
    # The honest tell: it rejects the data we already have, with reasons.
    assert any("already hold" in r["why_not"] or "actually run on" in r["why_not"]
               for r in dp.rejected_alternatives), (
        "a plan that never questions the data on the shelf was not designed")
    assert dp.what_would_change_the_answer.strip()


def test_both_example_cards_rule_out_finer_granularity_explicitly():
    """The user asked whether tick or minute data is needed. A card should
    answer that, per paper, rather than leaving it open."""
    for path in (EXEMPLAR, TSMOM):
        dp = load_card(path).data_plan
        blob = (dp.granularity_verdict + " " +
                " ".join(d.why_granularity for d in dp.ideal) + " " +
                " ".join(r["why_not"] for r in dp.rejected_alternatives)).lower()
        assert "intraday" in blob or "tick" in blob or "minute" in blob, path


# ---------------------------------------------------------------------------
# selection: a named list is a liability unless it says who checked it
# ---------------------------------------------------------------------------
def test_a_selection_always_needs_a_rule():
    """A named list without a rule cannot be re-derived on any other date."""
    sel = SecuritySelection(rule="", explicit_securities=["HDFCBANK"],
                            verified_against="index_factsheet", as_of="2026-01-01")
    assert any("rule is required" in e for e in sel.validate())


def test_a_named_list_must_say_what_verified_it():
    sel = SecuritySelection(rule="top decile", explicit_securities=["A", "B"])
    errs = sel.validate()
    assert any("verified_against" in e for e in errs)
    assert any("as_of" in e for e in errs)


def test_unverified_is_a_legal_and_visible_answer():
    """Better an honest UNVERIFIED than a source nobody checked."""
    sel = SecuritySelection(rule="top decile", explicit_securities=["A"],
                            verified_against="UNVERIFIED", as_of="2026-01-01")
    assert not sel.validate()


def test_an_unverified_list_is_flagged_by_completeness_and_by_gate_a():
    card = load_card(EXEMPLAR)
    card.selection.verified_against = "UNVERIFIED"
    bad = [c for c in card_completeness(card).missing
           if c.name == "named securities are verified"]
    assert bad and bad[0].weight >= 3
    row = _row(card, "named securities are verified")
    assert row.blocking and not row.passed
    assert "recalled rather than checked" in row.evidence


def test_a_rule_only_selection_raises_no_verification_criterion():
    """Stating the rule and stopping is the correct move when you cannot verify."""
    card = load_card(EXEMPLAR)
    card.selection.explicit_securities = []
    names = [c.name for c in gate_a(card, _Feas()).criteria]
    assert "named securities are verified" not in names
    assert _row(card, "securities selection stated").passed


def test_the_examples_verify_their_lists_against_something_checkable():
    for path in (EXEMPLAR, TSMOM):
        sel = load_card(path).selection
        assert sel.verified_against == "firm_registry", path
        assert sel.as_of, path


# ---------------------------------------------------------------------------
# backtest_plan: Gate A verifies a run, it does not design one
# ---------------------------------------------------------------------------
def _plan(**kw):
    base = dict(sample_start="2005-04-01", sample_end="2026-05-29",
                why_this_window="common start of every series",
                warmup_days=16, why_warmup="the window must fill",
                rebalance_rule="last trading day of the month",
                weights_rule="optimiser output, long-only",
                benchmarks=[{"name": "NIFTY 500", "why_this": "do nothing"}],
                must_beat=["NIFTY 500"], success_looks_like="beats both",
                failure_looks_like="ties with equal weight")
    base.update(kw)
    return BacktestPlan(**base)


@pytest.mark.parametrize("field", ["sample_start", "sample_end",
                                   "rebalance_rule", "weights_rule"])
def test_the_run_must_be_fully_specified(field):
    assert any(field in e for e in _plan(**{field: ""}).validate())


def test_an_unargued_sample_window_is_refused():
    """The easiest place to pick a period that flatters the result."""
    assert any("why this window" in e for e in
               _plan(why_this_window="").validate())


def test_a_benchmark_needs_a_reason():
    errs = _plan(benchmarks=[{"name": "NIFTY 500"}]).validate()
    assert any("why_this" in e for e in errs)


def test_a_plan_with_no_benchmark_is_refused():
    assert any("benchmark" in e for e in _plan(benchmarks=[]).validate())


@pytest.mark.parametrize("kw", [{"success_looks_like": ""},
                                {"failure_looks_like": ""}])
def test_a_plan_that_cannot_fail_is_not_a_test(kw):
    assert any("failure_looks_like" in e for e in _plan(**kw).validate())


def test_levered_explicit_weights_are_refused():
    errs = _plan(explicit_weights={"A": 0.7, "B": 0.6}).validate()
    assert any("unlevered" in e for e in errs)


def test_a_negative_explicit_weight_is_refused():
    errs = _plan(explicit_weights={"A": 0.7, "B": -0.2}).validate()
    assert any("cannot short" in e for e in errs)


def test_gate_a_blocks_when_the_run_is_not_specified():
    card = load_card(EXEMPLAR)
    card.backtest_plan = None
    row = _row(card, "the run is specified")
    assert row.blocking and not row.passed
    assert "designing the run" in row.evidence


def test_gate_a_blocks_when_no_dataset_was_designed():
    card = load_card(EXEMPLAR)
    card.data_plan = None
    row = _row(card, "dataset designed from the paper")
    assert row.blocking and not row.passed
    assert "shop from what" in row.evidence


def test_gate_a_blocks_when_there_is_no_selection_rule():
    card = load_card(EXEMPLAR)
    card.selection = None
    row = _row(card, "securities selection stated")
    assert row.blocking and not row.passed


def test_both_examples_clear_every_new_criterion():
    for path in (EXEMPLAR, TSMOM):
        card = load_card(path)
        failed = [c.name for c in gate_a(card, _Feas()).criteria
                  if c.blocking and not c.passed]
        for name in ("dataset designed from the paper", "the run is specified",
                     "securities selection stated", "named securities are verified",
                     "failure is defined before the run"):
            assert name not in failed, f"{path}: {name}"


# ---------------------------------------------------------------------------
# The rendered plan is what a human reads
# ---------------------------------------------------------------------------
def test_the_plan_block_shows_everything_a_reviewer_must_confirm():
    txt = load_card(EXEMPLAR).plan()
    for heading in ("THE DATASET THIS PAPER DESERVES", "CONSIDERED AND REJECTED",
                    "WHY THIS IS THE RIGHT DATASET", "WHICH SECURITIES",
                    "WHAT WILL BE RUN", "BENCHMARKS", "MUST BEAT",
                    "SUCCESS LOOKS LIKE", "FAILURE LOOKS LIKE"):
        assert heading in txt, heading
    assert "MINIMUM VIABLE" in txt


def test_the_plan_block_shouts_about_an_unverified_list():
    card = load_card(EXEMPLAR)
    card.selection.verified_against = "UNVERIFIED"
    assert "NOT VERIFIED" in card.plan()


def test_the_plan_block_degrades_rather_than_crashing():
    card = load_card(EXEMPLAR)
    card.data_plan = card.selection = card.backtest_plan = None
    txt = card.plan()
    assert "NO DATA PLAN" in txt and "NO SELECTION RULE" in txt
    assert "NO BACKTEST PLAN" in txt
