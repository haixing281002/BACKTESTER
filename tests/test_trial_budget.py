"""The deflated Sharpe trial budget must count the same bet under any name.

This file exists because of a real miss, not a hypothetical one. A run reported
seven library entries sharing its factor fingerprint at cosine >= 0.99 -- two of
them already REJECTED -- while its deflated Sharpe was computed as though
nothing had ever been tried. The budget matched on the card id, and the seven
prior experiments were filed under a different card id, so they counted zero.

That is the exact leak trials_for_family's own docstring warns about: a firm
p-hacking itself across months, one plausibly-renamed card at a time. The
deflation threshold rises with n, so under-counting n makes a strategy look
MORE skilful than the evidence supports. It fails in the flattering direction,
which is why it survived unnoticed.
"""
import ast
import io
import os

from ros.governance.library import LibraryEntry, StrategyLibrary, make_entry_id


MOMENTUM = {"MOMENTUM 30": 0.82, "QUALITY 30": 0.11, "LOW VOL 30": -0.06,
            "VALUE 50": 0.04}


def _entry(lib, card_id, fp_loadings, card_fp=None, outcome="REJECTED"):
    card_fp = card_fp or f"fp_{card_id}"
    eid = make_entry_id(card_id, card_fp)
    lib.write(LibraryEntry(entry_id=eid, card_id=card_id, mode="full",
                           created_utc="2026-01-01T00:00:00Z",
                           card_fingerprint=card_fp, outcome=outcome,
                           factor_fingerprint=dict(fp_loadings)))
    return eid


def test_the_same_bet_under_another_name_counts(tmp_path):
    """The regression. Two cards, different names, economically one experiment."""
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "tripathi_2009_momentum_adaptation", MOMENTUM)
    _entry(lib, "moskowitz_2012_tsmom_india",
           {k: v * 1.02 for k, v in MOMENTUM.items()})

    # What the pipeline used to ask, and the answer that let the leak through.
    assert lib.trials_for_family("padhy_2024") == 0

    got = lib.prior_trials("padhy_2024", factor_fingerprint=MOMENTUM)
    assert got["n_trials"] == 2, (
        "Two prior experiments on this bet must count against the trial budget "
        "however they were named. Counting them as zero is what made a "
        "re-discovered momentum sleeve look like a first attempt.")
    assert got["from_same_paper"] == 0
    assert got["from_same_bet"] == 2


def test_a_different_bet_is_not_counted(tmp_path):
    """Negative control: the fix must not be 'count the whole library'.

    Over-counting is the safe direction but it is not free -- it deflates every
    genuine result toward zero, and a budget that always says 'everything is a
    trial' carries no information. A low-vol sleeve is not a momentum trial.
    """
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "some_low_vol_paper",
           {"MOMENTUM 30": -0.71, "QUALITY 30": 0.12,
            "LOW VOL 30": 0.88, "VALUE 50": 0.05})

    got = lib.prior_trials("padhy_2024", factor_fingerprint=MOMENTUM)
    assert got["n_trials"] == 0, (
        f"An unrelated bet was counted as a prior trial: {got['matches']}")


def test_the_same_paper_route_still_works(tmp_path):
    """The card-id route is not replaced, it is unioned with."""
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "padhy_2024_adaptation", {}, card_fp="cfg_a")
    _entry(lib, "padhy_2024_adaptation", {}, card_fp="cfg_b")

    got = lib.prior_trials("padhy_2024")
    assert got["n_trials"] == 2
    assert got["from_same_paper"] == 2
    assert got["from_same_bet"] == 0


def test_a_config_counted_by_both_routes_counts_once(tmp_path):
    """A prior config on this paper that is also the same bet is ONE trial.

    Double-counting would inflate n and over-deflate, and the union is the only
    reading of 'distinct prior configurations' that is arithmetically honest.
    """
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "padhy_2024_adaptation", MOMENTUM, card_fp="cfg_a")

    got = lib.prior_trials("padhy_2024", factor_fingerprint=MOMENTUM)
    assert got["n_trials"] == 1
    assert got["from_same_paper"] == 1
    assert got["from_same_bet"] == 0


def test_rerunning_an_identical_config_is_not_a_new_trial(tmp_path):
    """No selection happened, so nothing was searched over."""
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "a_card", MOMENTUM, card_fp="same_config")
    _entry(lib, "a_card_run_again", MOMENTUM, card_fp="same_config")

    got = lib.prior_trials("nothing", factor_fingerprint=MOMENTUM)
    assert got["n_trials"] == 1, "Distinct CONFIGURATIONS, not distinct entries."


def test_this_run_does_not_count_itself(tmp_path):
    """The pipeline writes its own entry before searching."""
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "padhy_2024_adaptation", MOMENTUM, card_fp="me")

    got = lib.prior_trials("padhy_2024", factor_fingerprint=MOMENTUM,
                           exclude_fingerprint="me")
    assert got["n_trials"] == 0


def test_no_fingerprint_falls_back_without_crashing(tmp_path):
    """A run whose factor regression failed still gets the card-id route.

    It is then a LOWER BOUND, and the pipeline says so in the report rather
    than presenting a partial budget as complete.
    """
    lib = StrategyLibrary(str(tmp_path))
    _entry(lib, "padhy_2024_adaptation", MOMENTUM, card_fp="cfg_a")

    got = lib.prior_trials("padhy_2024", factor_fingerprint={})
    assert got["n_trials"] == 1
    assert got["matches"] == []


def test_the_threshold_is_stricter_than_the_report_threshold(tmp_path):
    """0.95 to COUNT, 0.90 to SHOW a human.

    The Gate B report surfaces neighbours so a human can look; the budget must
    only count experiments that really were the same one. If the counting
    threshold ever drifted down to the reporting one, near-misses would silently
    start deflating results.
    """
    assert StrategyLibrary.SAME_BET_COSINE == 0.95


# ---------------------------------------------------------------------------
# The wiring, not just the function. The function was correct on the day the
# leak fired -- similar_by_fingerprint already existed. What was missing was
# that the pipeline called it. And the ordering matters: the fingerprint is
# produced in STEP 07 but the budget is needed in STEP 06, so a naive fix
# computes the budget before the evidence it depends on exists.
# ---------------------------------------------------------------------------
_PIPELINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "run_pipeline.py")


def _call_lines(tree, attr):
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr]


def test_the_pipeline_asks_for_the_union_budget():
    tree = ast.parse(io.open(_PIPELINE, encoding="utf-8").read())
    assert _call_lines(tree, "prior_trials"), (
        "run_pipeline.py must use prior_trials(); trials_for_family() alone "
        "counts a renamed re-run of the same bet as zero.")
    assert not _call_lines(tree, "trials_for_family"), (
        "The card-id-only budget is the bug. It is unioned inside "
        "prior_trials(), not called from the pipeline.")


def test_the_fingerprint_is_computed_before_the_budget_needs_it():
    tree = ast.parse(io.open(_PIPELINE, encoding="utf-8").read())
    fp = _call_lines(tree, "factor_fingerprint")
    budget = _call_lines(tree, "prior_trials")
    dsr = _call_lines(tree, "deflated_sharpe")
    assert fp and budget and dsr
    assert min(fp) < min(budget) < min(dsr), (
        f"Ordering broke: factor_fingerprint at {fp}, prior_trials at "
        f"{budget}, deflated_sharpe at {dsr}. The budget needs the factor "
        f"loadings, so the fingerprint must be computed first and reused -- "
        f"not recomputed later in STEP 07.")


def test_the_fingerprint_is_computed_once():
    """Two calls would mean two objects that can silently disagree."""
    tree = ast.parse(io.open(_PIPELINE, encoding="utf-8").read())
    assert len(_call_lines(tree, "factor_fingerprint")) == 1
