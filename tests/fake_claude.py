"""Stand-in for the Claude Code CLI in Lightyear's tests: reads the prompt on stdin, writes the hand-off
files the prompt asks for, and emits stream-json events like the real CLI. No model, no network."""
import json
import os
import re
import sys

import numpy as np
import pandas as pd

prompt = sys.stdin.read()
run_dir = os.path.join(os.environ["LIGHTYEAR_RUNS"], os.environ["LIGHTYEAR_RUN"])
slug = re.search(r"slug:? ([a-z0-9_]+)", prompt).group(1)
os.makedirs(run_dir, exist_ok=True)


def emit(ev):
    print(json.dumps(ev), flush=True)


emit({"type": "system", "subtype": "init", "session_id": "fake-session-0001", "model": "fake"})

if "stages 00 through Gate A" in prompt or "revise the card" in prompt:
    ids = ["00", "01", "02", "03m", "GA"] if "stages 00" in prompt else ["GA"]
    for sid in ids:
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": f"LIGHTYEAR-STAGE: {sid}\nworking"}]}})
    os.makedirs(os.environ["LY_TEST_CARDS"], exist_ok=True)
    card = os.path.join(os.environ["LY_TEST_CARDS"], f"{slug}.yaml")
    open(card, "w").write("name: test card\nsignal: momentum\n")
    gate_a = os.path.join(os.environ["LY_TEST_CARDS"], f"{slug}__gate_a_queue.md")
    open(gate_a, "w").write("# Gate A\n\n| fact | value |\n|---|---|\n| universe | NIFTY 500 |\n")
    json.dump({"status": "ok", "reason": "", "paper_title": "A Test Paper", "slug": slug, "card_path": card,
               "gate_a_path": gate_a, "plain_summary": "Buys winners.", "universe": "NIFTY 500",
               "data_verdict": "bhavcopy covers it", "open_questions": ["is 12-1 right?"], "files": [card]},
              open(os.path.join(run_dir, "phase_a.json"), "w"))
else:
    for sid in ["03", "04", "05", "06", "07", "GB"]:
        emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
              "input": {"command": f"echo LIGHTYEAR-STAGE: {sid}"}}]}})
    rng = np.random.default_rng(0)
    d = pd.bdate_range("2022-01-03", periods=400)
    pd.DataFrame({"date": d.strftime("%Y-%m-%d"), "strategy": rng.normal(4e-4, 0.01, 400),
                  "benchmark": rng.normal(3e-4, 0.011, 400)}).to_csv(os.path.join(run_dir, "daily_returns.csv"), index=False)
    tab = os.path.join(run_dir, "sens.csv")
    pd.DataFrame({"lookback": [6, 12], "CAGR": [0.05, 0.07], "Sharpe": [0.3, 0.5]}).to_csv(tab, index=False)
    json.dump({"strategy_name": "Test momentum", "benchmark_name": "NIFTY 500", "sleeve_name": None,
               "headline": "A test.", "evidence_supports": "OBSERVE", "decisive_criterion": "deflated Sharpe",
               "gate_b": {"decision": "PENDING", "criteria": [
                   {"name": "deflated Sharpe clears selection bias", "passed": False, "blocking": True, "value": 0.4, "threshold": 0.95},
                   {"name": "turnover within tolerance", "passed": True, "blocking": True, "value": "120%", "threshold": "<=400%"},
                   {"name": "differentiated from existing book", "passed": False, "blocking": False, "value": "NO COMPARISON", "threshold": "<=0.8"}]},
               "validation": [{"label": "Bootstrap Sharpe low", "value": -0.2, "format": "num", "source": "test"}],
               "tables": [{"title": "Sensitivity", "csv": tab, "note": "test"}],
               "assumptions": [{"label": "Cost", "value": 0.003, "format": "pct", "note": "test"}],
               "notes": ["synthetic"], "files": []}, open(os.path.join(run_dir, "results.json"), "w"))

emit({"type": "result", "subtype": "success", "is_error": False, "result": "done", "total_cost_usd": 0.01,
      "num_turns": 3, "duration_ms": 1000})
