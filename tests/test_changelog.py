# Quant AI Researcher
"""The 'what changed vs the previous run' block: card field diff classified trade-affecting vs verdict-only, script sha
diff, and a one-line verdict that says whether the trades should have moved."""
import json
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from lightyear import changelog

CARD = {"signal": {"params": {"gap_limit": 0.15, "signal_weekday": "Tuesday"}}, "costs": {"spread_bps": 0},
        "portfolio": {"allow_cash": True, "mandate_allow_cash": False}, "backtest_plan": {"sample_start": "2014-01-01", "why_this_window": "x"},
        "ambiguities": [{"headline": "a"}]}


def _run(root, rid, created, card, returns_seed, script_sha):
    rd = root / rid
    rd.mkdir(parents=True)
    import yaml
    (rd / "state.json").write_text(json.dumps({"id": rid, "slug": "s", "created": created, "phase_a": {"card_path": "cards/s.yaml"}}), encoding="utf-8")
    (rd / "manifest.json").write_text(json.dumps({"inputs": {"card": {"sha256": "c" + str(hash(json.dumps(card, sort_keys=True)) % 10**8)}},
                                                  "script": {"sha256": script_sha}}), encoding="utf-8")
    (rd / "card_approved.yaml").write_text(yaml.safe_dump(card), encoding="utf-8")
    d = pd.bdate_range("2020-01-01", periods=300)
    pd.DataFrame({"date": d, "strategy": [returns_seed] * 300, "benchmark": 0.0}).to_csv(rd / "daily_returns.csv", index=False)
    pd.DataFrame({"action": ["BUY"] * 10}).to_csv(rd / "trades.csv", index=False)
    return str(rd)


def _state(rd):
    with open(os.path.join(rd, "state.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_classification():
    assert changelog.is_trade_affecting("signal.params.gap_limit")
    assert changelog.is_trade_affecting("costs.spread_bps")
    assert changelog.is_trade_affecting("backtest_plan.sample_end")
    assert changelog.is_trade_affecting("portfolio.allow_cash")
    assert not changelog.is_trade_affecting("portfolio.mandate_allow_cash")
    assert not changelog.is_trade_affecting("backtest_plan.why_this_window")
    assert not changelog.is_trade_affecting("ambiguities.0.headline")


def test_verdict_only_change_with_identical_returns(tmp_path):
    root = tmp_path / "runs"
    _run(root, "r1", "2026-10-30T10:00:00", CARD, 0.001, "s1")
    new_card = json.loads(json.dumps(CARD))
    new_card["portfolio"]["mandate_allow_cash"] = True
    rd2 = _run(root, "r2", "2026-10-30T11:00:00", new_card, 0.001, "s2")
    st2 = _state(rd2)
    cl = changelog.build(st2, rd2, search_dirs=[str(root)])
    assert cl["previous_run"] == "r1" and cl["returns_identical"]
    assert cl["changed_trade_affecting"] == [] and cl["changed_verdict_only"] == ["portfolio.mandate_allow_cash"]
    assert any("trades unchanged: no trade-affecting field changed" in line for line in cl["lines"])
    assert any("script changed" in line for line in cl["lines"])


def test_trade_affecting_change_with_different_returns(tmp_path):
    root = tmp_path / "runs"
    _run(root, "r1", "2026-10-30T10:00:00", CARD, 0.001, "s1")
    new_card = json.loads(json.dumps(CARD))
    new_card["costs"]["spread_bps"] = 30
    rd2 = _run(root, "r2", "2026-10-30T11:00:00", new_card, 0.0005, "s1")
    st2 = _state(rd2)
    cl = changelog.build(st2, rd2, search_dirs=[str(root)])
    assert cl["changed_trade_affecting"] == ["costs.spread_bps"] and not cl["returns_identical"]
    assert any("results changed" in line and "CAGR" in line for line in cl["lines"])
