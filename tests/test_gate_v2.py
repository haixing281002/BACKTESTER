# Quant AI Researcher
"""Gate v2 on fixtures with known answers. Thresholds here are the test's own, so no result depends on what is approved."""
import ast
import os
import pathlib

import numpy as np
import pandas as pd
import pytest

from ros.governance import gate_v2 as g
from ros.metrics import core
from ros.validation import gate_evidence as ev

REPO = pathlib.Path(__file__).resolve().parent.parent
TH = {"status": "test", "capacity": {"p95_adv_participation_max": 0.10}, "data_integrity": {"min_priced_coverage": 0.95}, "bootstrap": {"p_max": 0.05},
      "deflated_sharpe": {"enabled": False, "green_min": 0.90, "amber_min": 0.70}, "sub_period": {"min_windows_ahead_share": 0.5, "window_floor": -1.0, "window_floor_amber": -1.5},
      "factor_alpha": {"t_green_min": 2.0, "t_amber_min": 1.0}, "book": {"corr_green_max": 0.80, "corr_amber_max": 0.90, "ir_gain_green_min": 0.05, "ir_gain_amber_min": 0.0},
      "post_publication": {"edge_green_min": 0.0, "edge_amber_min": -0.02}}
LIMITS = {"long_only": True, "max_cash_share": 0.25, "max_single_weight": 0.10}


def _good(**kw):
    e = {"mandate_observed": {"max_cash_share": 0.05, "max_single_weight": 0.05, "min_weight": 0.0},
         "capacity": {"status": "computed", "p95": 0.02, "names_above_limit": [], "n_no_adv": 0},
         "checks": [{"check": "look-ahead", "passed": True}], "reconciles": True, "priced_coverage": 0.99, "unpriced": [],
         "net_edge": 0.03, "bootstrap_p": 0.01, "dsr": 0.97, "sub_period_n": 4, "sub_period_positive": 4, "sub_period_worst": 0.1,
         "alpha": 0.04, "alpha_t": 3.0, "book_corr": 0.5, "book_ir_gain": 0.1, "post_publication_edge": None}
    e.update(kw)
    return e


def _row(res, key):
    return next(r for r in res.hard_blocks + res.scorecard if r.key == key)


def test_a_clean_result_passes_and_the_decision_stays_pending():
    res = g.evaluate(_good(), TH, LIMITS)
    assert res.status == g.PASS and res.decision == "PENDING" and res.gate_version == "v2"
    assert g.all_green(res)


def test_a_negative_alpha_fails_the_factor_test_however_large_its_t():
    res = g.evaluate(_good(alpha=-0.05, alpha_t=-5.0), TH, LIMITS)
    assert _row(res, "factor_alpha").status == g.RED
    assert not g.all_green(res)


def test_a_positive_alpha_below_the_bar_is_not_green():
    assert _row(g.evaluate(_good(alpha=0.02, alpha_t=1.5), TH, LIMITS), "factor_alpha").status == g.AMBER


def test_a_missing_book_is_shown_as_not_run_and_does_not_hold_the_gate_up():
    res = g.evaluate(_good(book_corr=None, book_ir_gain=None), TH, LIMITS)
    assert res.status == g.PASS
    assert _row(res, "book_correlation").status == g.NOT_RUN
    assert "Correlation to the existing book" in res.tests_not_run


def test_a_failed_hard_block_fails_with_no_book():
    assert g.evaluate(_good(book_corr=None, book_ir_gain=None, bootstrap_p=0.4), TH, LIMITS).status == g.FAIL


def test_the_deflated_sharpe_is_out_of_the_gate_until_it_is_enabled():
    res = g.evaluate(_good(dsr=0.0), TH, LIMITS)
    assert not [r for r in res.scorecard if r.key == "deflated_sharpe"] and g.all_green(res)
    th = {**TH, "deflated_sharpe": {"enabled": True, "green_min": 0.9, "amber_min": 0.7}}
    assert _row(g.evaluate(_good(dsr=0.0), th, LIMITS), "deflated_sharpe").status == g.RED


def test_a_card_override_without_a_named_approval_fails():
    high_cash = _good(mandate_observed={"max_cash_share": 1.0, "max_single_weight": 0.05, "min_weight": 0.0})
    assert _row(g.evaluate(high_cash, TH, LIMITS), "mandate").status == g.FAIL
    assert _row(g.evaluate(high_cash, TH, LIMITS, [{"limit": "max_cash_share", "approved_by": "", "approved_at": ""}]), "mandate").status == g.FAIL


def test_a_named_timestamped_override_passes_and_is_shown():
    high_cash = _good(mandate_observed={"max_cash_share": 1.0, "max_single_weight": 0.05, "min_weight": 0.0})
    r = _row(g.evaluate(high_cash, TH, LIMITS, [{"limit": "max_cash_share", "approved_by": "A Person", "approved_at": "2026-11-05T10:00:00+05:30"}]), "mandate")
    assert r.status == g.PASS and "A Person" in r.evidence and "2026-11-05" in r.evidence


def test_blank_mandate_limits_or_capacity_are_not_run_and_listed():
    blank = g.evaluate(_good(), TH, {"long_only": None, "max_cash_share": None, "max_single_weight": None})
    assert blank.status == g.PASS and _row(blank, "mandate").status == g.NOT_RUN and "Implementable within the fund's mandate" in blank.tests_not_run
    no_aum = g.evaluate(_good(capacity={"status": "not computed", "why": "no AUM"}), TH, LIMITS)
    assert no_aum.status == g.PASS and _row(no_aum, "capacity").status == g.NOT_RUN


def test_a_gate_with_nothing_run_cannot_pass():
    empty = g.evaluate({}, TH, {"long_only": None, "max_cash_share": None, "max_single_weight": None})
    assert empty.status == g.FAIL


@pytest.mark.parametrize("kw", [{"net_edge": -0.01}, {"bootstrap_p": 0.2}, {"capacity": {"status": "computed", "p95": 0.5}}, {"priced_coverage": 0.5},
                                {"reconciles": False}, {"checks": [{"check": "look-ahead", "passed": False}]}])
def test_each_hard_block_can_fail_alone(kw):
    assert g.evaluate(_good(**kw), TH, LIMITS).status == g.FAIL


def test_the_scorecard_alone_never_blocks():
    bad = _good(sub_period_positive=0, sub_period_worst=-3.0, alpha=-0.1, alpha_t=-4.0, book_corr=0.99, book_ir_gain=-1.0)
    res = g.evaluate(bad, TH, LIMITS)
    assert res.status == g.PASS and not g.all_green(res)


def _series(mean, sd, seed, n=3000):
    return pd.Series(np.random.default_rng(seed).normal(mean, sd, n), index=pd.bdate_range("2012-01-01", periods=n))


def test_effective_trials_counts_correlated_versions_as_fewer():
    assert core.effective_trials(10, 0.0) == 10
    assert core.effective_trials(10, 1.0) == 1
    assert core.effective_trials(10, 0.5) == pytest.approx(5.5)


def test_near_identical_versions_cannot_make_the_bar_trivial():
    b = _series(4e-4, 0.01, 1)
    base = _series(5e-4, 0.012, 2)
    versions = pd.DataFrame({f"v{i}": base + _series(0, 1e-4, 10 + i) for i in range(8)})
    x = ev.version_inputs(versions, b, 0.0, 8, v_floor=0.08)
    assert x["v_observed"] < 0.08 and x["v"] == 0.08
    assert x["n_eff"] == pytest.approx(core.effective_trials(8, x["mean_corr"]))


def test_rules_fixed_in_print_mean_n_of_one():
    x = ev.version_inputs(None, _series(4e-4, 0.01, 1), 0.0, 1, v_floor=0.08)
    assert x["n_eff"] == 1.0
    assert core.expected_max_sharpe(1.0, 0.08) == 0.0


def test_deflated_sharpe_bar_starts_at_the_benchmark_when_asked():
    b = _series(5e-4, 0.01, 1)
    r = _series(5e-4, 0.01, 2)
    z, m = ev.deflated_sharpe(r, b, 0.0, 1.0, 0.08, null="zero"), ev.deflated_sharpe(r, b, 0.0, 1.0, 0.08, null="benchmark")
    assert z["bar"] == 0.0 and m["bar"] == pytest.approx(core.sharpe(b, 0.0))
    assert m["dsr"] < z["dsr"]


def test_sub_period_is_named_for_what_it_is():
    b, r = _series(4e-4, 0.01, 1), _series(6e-4, 0.01, 2)
    assert ev.sub_period(r, b, 0.0)["name"] == "Sub-period stability"
    wf = ev.sub_period(r, b, 0.0, fits_parameters=True)
    assert wf["name"] == "Walk-forward" and wf["windows"][0]["window"] > ev.sub_period(r, b, 0.0)["windows"][0]["window"]
    w = ev.sub_period(r, b, 0.0)["windows"][0]
    assert w["gap"] == pytest.approx(w["sharpe"] - w["benchmark_sharpe"])


def test_bootstrap_finds_a_real_edge_and_rejects_none_and_is_repeatable():
    b = _series(4e-4, 0.01, 1)
    strong = b + _series(1e-3, 0.003, 2)
    none = b + _series(0, 0.003, 3)
    assert ev.paired_bootstrap(strong, b, 0.0, n_boot=500)["p"] < 0.05
    assert ev.paired_bootstrap(none, b, 0.0, n_boot=500)["p"] > 0.05
    assert ev.paired_bootstrap(strong, b, 0.0, n_boot=200)["p"] == ev.paired_bootstrap(strong, b, 0.0, n_boot=200)["p"]


def test_factor_alpha_is_zero_for_a_pure_factor_mix_and_reports_each_factor_left_out():
    f = pd.DataFrame({"market": _series(4e-4, 0.01, 1), "size": _series(5e-4, 0.012, 2)})
    r = 0.6 * f["market"] + 0.4 * f["size"] + _series(0, 2e-4, 3)
    out = ev.factor_alpha(r, f, 0.0)
    assert abs(out["alpha_t_hac"]) < 3
    assert set(out["leave_one_out"]) == {"market", "size"}
    assert ev.factor_alpha(r, f, 0.0, product_cost_bp={"market": 10, "size": 50})["alpha_net_of_products"] > out["alpha_ann"]


def test_a_strategy_that_is_a_factor_is_not_regressed_on_itself():
    f = pd.DataFrame({"market": _series(4e-4, 0.01, 1), "momentum": _series(5e-4, 0.012, 2)})
    out = ev.factor_alpha(f["momentum"], f, 0.0)
    assert out["left_out_as_identical"] == ["momentum"] and abs(out["alpha_t_hac"]) < 5


def test_no_book_gives_no_book_numbers():
    assert ev.book_tests(_series(4e-4, 0.01, 1), None, _series(4e-4, 0.01, 2))["book_corr"] is None


def test_nothing_in_gate_v2_assigns_a_decision():
    tree = ast.parse((REPO / "ros" / "governance" / "gate_v2.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                assert not (isinstance(t, ast.Attribute) and t.attr == "decision"), "gate v2 must not assign a decision"


def test_the_shipped_thresholds_load_and_are_marked_with_their_status():
    import yaml
    with open(os.path.join(REPO, "config", "gate_thresholds.yaml"), encoding="utf-8") as fh:
        th = yaml.safe_load(fh)
    assert th["gate_version"] == "v2" and th["status"]
    for k in TH:
        assert k in th
    assert th["deflated_sharpe"]["enabled"] is False and th["deflated_sharpe"]["bar_starts_at"] == "benchmark"
    assert "Approved" in th["status"]


def _load_script(name):
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "gate_v2" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_one_simulated_strategy_is_reproducible_from_its_seed():
    cal = _load_script("calibrate")
    a, b = cal.one_sim(("level", 0.5, 1, 3, 123)), cal.one_sim(("level", 0.5, 1, 3, 123))
    pd.testing.assert_series_equal(pd.Series(a), pd.Series(b))
    assert cal.one_sim(("level", 0.5, 1, 4, 123))["sharpe"] != a["sharpe"]


def test_the_calibration_tables_and_the_gate_give_the_same_answer():
    """The power curves are computed on a table for speed. The gate itself must agree on every row."""
    an = _load_script("analyse")
    cal = _load_script("calibrate")
    rows = pd.DataFrame([cal.one_sim(("level", lv, 1, s, 77)) for lv in (0.0, 1.0) for s in range(12)])
    c = {"window_floor": -1.0, "t_min": 2.0, "boot_p": 0.10, "min_windows": 2, "corr_max": 0.8, "ir_gain_min": 0.05}
    th = {**TH, "bootstrap": {"p_max": 0.10}}
    table = an.v2_pass(rows, c, book=True)
    for i, r in rows.iterrows():
        e = _good(net_edge=r["edge"], bootstrap_p=r["boot_p"], sub_period_n=r["sp_n"], sub_period_positive=r["sp_pos"], sub_period_worst=r["sp_worst"],
                  alpha=r["alpha"], alpha_t=r["alpha_t"], book_corr=r["book_corr"], book_ir_gain=r["book_ir_gain"])
        res = g.evaluate(e, th, LIMITS)
        assert (res.status == g.PASS and g.all_green(res)) == bool(table[i]), i


def _run_folder(tmp_path, strategy, bench):
    from lightyear import gate_run
    card = tmp_path / "card.yaml"
    card.write_text("x", encoding="utf-8")
    df = pd.DataFrame({"date": strategy.index, "strategy": strategy.to_numpy(), "benchmark": bench.to_numpy()})
    return gate_run, str(card), df


def test_a_run_folder_scores_at_the_cards_cost_and_no_other(tmp_path, monkeypatch):
    from types import SimpleNamespace
    b = _series(4e-4, 0.01, 1)
    strong = b + _series(1.2e-3, 0.003, 2)
    gate_run, card, df = _run_folder(tmp_path, strong, b)
    fake = SimpleNamespace(universe=SimpleNamespace(cash_asset="CASH_PROXY_CONSTANT_6PCT"), fits_parameters=False, paper=SimpleNamespace(date="2015"), costs=SimpleNamespace(spread_bps=0.0))
    monkeypatch.setattr(gate_run, "load_card", lambda p: fake)
    monkeypatch.setattr(gate_run.ev, "factor_returns", lambda idx: pd.DataFrame({"market": b.reindex(idx), "size": _series(5e-4, 0.012, 9).reindex(idx)}))
    heavy = pd.DataFrame({"date": list(b.index[:500]), "isin": ["A"] * 500, "weight_before": [0.0] * 500, "weight_after": [1.0] * 500})
    res = gate_run.score(str(tmp_path), card, df, heavy)
    light = gate_run.score(str(tmp_path), card, df)
    assert res["status"] == "PASS" and res["decision"] == "PENDING" and res["gate_version"] == "v2"
    assert "0bp" in res["basis"]
    assert res["summary"]["net_edge"] == light["summary"]["net_edge"]     # however heavy the trading, a 0bp card is charged nothing
    assert any("book" in x for x in res["tests_not_run"])
    gate_run2, card2, df2 = _run_folder(tmp_path, b - 2e-4, b)
    assert gate_run2.score(str(tmp_path), card2, df2)["status"] == "FAIL"


def test_gate_b_sharpes_read_the_hurdle_not_the_cards_cash_rate(tmp_path, monkeypatch):
    """Wave 4: the bootstrap, sub-period and post-publication Sharpes subtract the 5% hurdle in config/fund.yaml. The card's
    cash rate (6% here, so the two cannot be confused) reaches only factor alpha."""
    from types import SimpleNamespace

    from ros import config
    from ros.metrics import core
    b = _series(4e-4, 0.01, 1)
    strong = b + _series(1.2e-3, 0.003, 2)
    gate_run, card, df = _run_folder(tmp_path, strong, b)
    fake = SimpleNamespace(universe=SimpleNamespace(cash_asset="CASH_PROXY_CONSTANT_6PCT"), fits_parameters=False, paper=SimpleNamespace(date="2015"), costs=SimpleNamespace(spread_bps=0.0))
    monkeypatch.setattr(gate_run, "load_card", lambda p: fake)
    monkeypatch.setattr(gate_run.ev, "factor_returns", lambda idx: pd.DataFrame({"market": b.reindex(idx), "size": _series(5e-4, 0.012, 9).reindex(idx)}))
    seen = {}
    real = {k: getattr(gate_run.ev, k) for k in ("paired_bootstrap", "sub_period", "factor_alpha")}
    real_pp = gate_run.core.post_publication

    def spy(name):
        def f(r, x, rate, *a, **k):
            seen.setdefault(name, []).append(rate)
            return real[name](r, x, rate, *a, **k)
        return f

    def spy_pp(r, x, cash, date, hurdle=None):
        seen["post_publication"] = hurdle
        return real_pp(r, x, cash, date, hurdle=hurdle)

    for k in real:
        monkeypatch.setattr(gate_run.ev, k, spy(k))
    monkeypatch.setattr(gate_run.core, "post_publication", spy_pp)
    res = gate_run.score(str(tmp_path), card, df)
    hurdle, cash = config.hurdle_daily(), core.daily_cash(0.06)
    assert config.hurdle_annual() == 0.05 and hurdle != cash
    assert seen["paired_bootstrap"] == [hurdle] and seen["sub_period"] == [hurdle] and seen["post_publication"] == hurdle
    assert seen["factor_alpha"] == [cash, hurdle]          # the gate row at the card's rate, then the reported one at the hurdle
    assert res["summary"]["sharpe_hurdle"] == 0.05 and "risk-free rate 5%" in res["basis"] and "arithmetic" in res["basis"]
    # and the numbers are the hurdle's: the bootstrap p equals a direct call at the hurdle
    df_i = pd.DatetimeIndex(df["date"])
    r = pd.Series(df["strategy"].to_numpy(), index=df_i)
    bb = pd.Series(df["benchmark"].to_numpy(), index=df_i)
    assert res["summary"]["bootstrap_p"] == real["paired_bootstrap"](r, bb, hurdle)["p"]


def test_rule_specific_rows_are_diagnostics():
    from lightyear.jobs import DIAGNOSTIC_LABEL
    for x in ("Sells forced by a name leaving the NIFTY 500 list", "Share of 15%-gap exits that were in profit", "Buys on days the stock closed up more than 9.5% (band proxy)", "Share of signals with buying shut by the index filter"):
        assert DIAGNOSTIC_LABEL.search(x), x
    for x in ("CAGR, strategy", "Two-way turnover a year (x capital)", "Mean cash share of NAV"):
        assert not DIAGNOSTIC_LABEL.search(x), x


def test_a_value_with_no_finite_answer_shows_blank_and_cannot_break_the_page():
    import json

    from lightyear.jobs import finite_rows
    rows = finite_rows([{"label": "Breakeven", "value": float("inf")}, {"label": "CAGR", "value": 0.1}, {"label": "Note", "value": "text"}])
    assert rows[0]["value"] is None and rows[1]["value"] == 0.1 and rows[2]["value"] == "text"
    json.dumps(rows, allow_nan=False)


def test_no_row_can_name_a_house_cost():
    from lightyear.jobs import HOUSE_COST_LABEL
    assert HOUSE_COST_LABEL.search("CAGR at the 30bp house floor (Appendix cost sweep, 30bp round trip)")
    assert not HOUSE_COST_LABEL.search("Breakeven round-trip cost vs NIFTY 500")


def test_capacity_needs_no_aum_and_says_aum_not_set():
    import pandas as pd

    from ros.governance import gate_v2
    from ros.metrics import core
    days = pd.bdate_range("2024-01-01", periods=40)
    adv = core.adv_20(pd.DataFrame({"A": [100.0] * 40, "B": [10.0] * 40}, index=days))   # Rs crore a day
    trades = pd.DataFrame({"execution_date": [days[30], days[31]], "isin": ["A", "B"],
                           "weight_before": [0.0, 0.0], "weight_after": [0.05, 0.02]})
    u = core.capacity_unit(trades, adv, 0.10)
    assert abs(u["per_cr_median"] - (0.05 / 100 + 0.02 / 10) / 2) < 1e-12
    assert abs(u["capital_at_limit_cr"] - 0.10 / u["per_cr_p95"]) < 1e-9
    row = gate_v2.capacity_row({"status": "AUM not set at Gate A", "why": "AUM not set at Gate A", "unit": u}, 0.10)
    assert row.status == gate_v2.NOT_RUN and "AUM not set at Gate A" in row.evidence and "None" not in row.evidence


def test_a_missing_value_or_threshold_is_never_shown_as_none():
    from lightyear import gates
    r = gates.rows([{"name": "implementable within mandate", "passed": True, "blocking": True,
                     "value": None, "threshold": None}])[0]
    assert r["value_raw"] == "" and r["threshold_raw"] == ""
