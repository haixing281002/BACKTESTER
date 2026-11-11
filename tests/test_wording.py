# Quant AI Researcher
"""Comparison words follow the numbers: 'lower volatility (16.8% against 15.9%)' is corrected to 'higher'."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from lightyear import wording


def test_the_reported_bug_is_corrected():
    s = "Beat the index by +8.3 points a year (21.2% against 12.8%) with lower volatility (16.8% against 15.9%) and a shallower worst fall (22.1% against 38.3%)."
    out, ch = wording.fix_sentence(s)
    assert "higher volatility (16.8% against 15.9%)" in out
    assert "shallower worst fall (22.1% against 38.3%)" in out          # already right, untouched
    assert ch == [("lower volatility (16.8% against 15.9%)", "higher volatility (16.8% against 15.9%)")]


def test_right_words_are_left_alone_and_equal_numbers_say_so():
    assert wording.fix_sentence("lower turnover (3.1% vs 4.0%)") == ("lower turnover (3.1% vs 4.0%)", [])
    assert wording.fix_sentence("a bigger fall (40% against 20%)") == ("a bigger fall (40% against 20%)", [])
    out, ch = wording.fix_sentence("smaller drawdown (20% against 40%)")
    assert out.startswith("smaller") and not ch
    out, _ = wording.fix_sentence("Lower cost (5% against 5%)")
    assert out.startswith("The same cost")


def test_no_extra_risk_claim_must_agree_with_the_volatility_numbers():
    s = ("Returned 21.2% a year against 12.8% for the NIFTY 500 price index with volatility of 16.8% against 15.9%, "
         "so the extra return did not come from extra risk.")
    out, ch = wording.fix_sentence(s)
    assert "came with more volatility" in out and "did not come from extra risk" not in out
    assert ch == [("did not come from extra risk", "came with more volatility")]
    ok = "with volatility of 14.0% against 15.9%, so the extra return did not come from extra risk."
    assert wording.fix_sentence(ok) == (ok, [])        # the claim is true when the strategy's volatility is lower


def test_fix_results_records_what_it_changed():
    res = {"headline": "x", "strengths": ["less risk (9% against 7%)"], "weaknesses": ["more turnover (10% against 4%)"],
           "notes": [], "paper_vs_backtest": [{"why_different": "higher return (12% against 21%)"}]}
    ch = wording.fix_results(res)
    assert res["strengths"] == ["more risk (9% against 7%)"]
    assert res["weaknesses"] == ["more turnover (10% against 4%)"]
    assert res["paper_vs_backtest"][0]["why_different"] == "lower return (12% against 21%)"
    assert len(ch) == 2 and res["wording_corrections"][0]["field"] == "strengths[0]"
    assert wording.check_results(res) == []
