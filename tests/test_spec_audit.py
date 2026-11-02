# Quant AI Researcher by Harshil Pahuja
"""lightyear.spec_audit: the run's own files are checked against the card's Gate A rules, and a rule the files break
is reported as FAIL (never silently dropped)."""
import json
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from lightyear import spec_audit

CARD = """signal:
  lag_days: 1
  params: {gap_limit: 0.15, stock_trend_days: 100, index_filter_days: 200, hold_band_quantile: 0.2, risk_factor: 0.001, signal_weekday: Tuesday}
costs: {spread_bps: 0}
portfolio: {allow_cash: true, mandate_allow_cash: true}
backtest_plan: {sample_start: '2024-01-01', sample_end: '2024-03-28'}
"""


def _world(tmp_path, break_rules=False):
    card = tmp_path / "card.yaml"
    card.write_text(CARD, encoding="utf-8")
    rd = tmp_path / "run"
    (rd / "out").mkdir(parents=True)
    cal = pd.bdate_range("2024-01-02", "2024-03-28")
    cal = cal[cal != pd.Timestamp("2024-01-23")]                     # a Tuesday holiday
    pd.DataFrame({"date": cal, "strategy": 0.0, "benchmark": 0.0}).to_csv(rd / "daily_returns.csv", index=False)
    tuesdays = [d for d in cal if d.dayofweek == 1]
    sig = tuesdays[:3] + [pd.Timestamp("2024-01-22")]              # the holiday week signals on Monday
    if break_rules:
        sig[0] = sig[0] + pd.Timedelta(days=1)                        # a Wednesday signal
    rows, selrows = [], []
    for s in sig:
        f = cal[cal.get_loc(s) + 1]
        rows.append({"date": f, "symbol": "AAA", "action": "BUY", "weight_before": 0, "weight_after": 0.02, "isin": "INE1",
                     "signal_date": s, "execution_date": f, "price_date": f, "price": 100.0, "shares": 200, "value_rs": 20000.0 + (300 if break_rules else 0)})     # a 1.5% cost hidden in the fill
        selrows.append({"signal_date": s, "execution_date": f, "symbol": "AAA", "isin": "INE1", "decision": "BOUGHT", "why": "x",
                        "rank": 3, "top_n": 90, "biggest_move_90d": 0.21 if break_rules else 0.09, "pct_vs_100d_avg": 0.05,
                        "atr_pct": 0.05, "weight_after": 0.02, "in_nifty500_list": True, "gate_open": True})
    pd.DataFrame(rows).to_csv(rd / "trades.csv", index=False)
    pd.DataFrame(selrows).to_csv(rd / "selection.csv", index=False)
    pd.DataFrame({"date": [r["signal_date"] for r in rows], "symbol": "AAA", "weight": 0.02}).to_csv(rd / "holdings.csv", index=False)
    pd.DataFrame({"signal_date": sig, "fill_date": [r["execution_date"] for r in rows], "n_held": 1, "cash_share": 0.98}).to_csv(rd / "out" / "rebalance_log.csv", index=False)
    res = {"headline_cost_bp": 0, "gate_b": {"criteria": [{"name": "implementable within mandate", "passed": True, "evidence": "ok"}]}}
    return str(rd), str(card), res


def test_a_run_that_follows_the_card_passes_every_check(tmp_path):
    rd, card, res = _world(tmp_path)
    a = spec_audit.run(rd, card, results=res)
    assert a["n_fail"] == 0 and a["n_pass"] >= 9, [c for c in a["checks"] if c["passed"] is False]
    assert os.path.exists(os.path.join(rd, "spec_audit.json"))
    rules = " ".join(c["rule"] for c in a["checks"])
    assert "Tuesday" in rules and "15%" in rules and "Window" in rules and "renormalised" in rules


def test_broken_rules_are_reported_as_fail(tmp_path):
    rd, card, res = _world(tmp_path, break_rules=True)
    a = spec_audit.run(rd, card, results=res)
    failed = {c["rule"] for c in a["checks"] if c["passed"] is False}
    assert any("Tuesday" in r for r in failed)          # a Wednesday signal
    assert any("15%" in r for r in failed)              # a buy with a 21% move
    assert any("shares x price" in r for r in failed)   # a cost hidden in the fill
    with open(os.path.join(rd, "spec_audit.json"), encoding="utf-8") as fh:
        assert json.load(fh)["n_fail"] == len(failed)
