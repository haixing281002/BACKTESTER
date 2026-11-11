# Quant AI Researcher
"""Stand-in for the Claude Code CLI in Lightyear's tests: reads the prompt on stdin, writes the hand-off
files the prompt asks for, and emits stream-json events like the real CLI. No model, no network.

It also RECORDS the exact prompt each phase received (prompt_<phase>.txt in the run folder) and echoes the
operator notes it can see into the files it writes, so the Gate A -> Gate B hand-off tests can tell at every
hop whether a change made at Gate A arrived through the prompt, through the card file, or not at all.

Prompt kinds (phrases from lightyear/prompts.py):
  "stages 00 through Gate A"   phase A : writes a card (with the fields Lightyear cross-checks), a Gate A doc, phase_a.json
  "revise the card"            revision: appends the operator notes to the card and phase_a.json;
                               notes containing SENTINEL-STALE -> error result, nothing written (a session that died);
                               notes containing SENTINEL-NOOP  -> success result, nothing written (a session that did nothing)
  "stages 03 through Gate B"   phase B : daily_returns.csv, results.json (notes echo the prompt's operator block and the
                               card text) and manifest.json whose card sha and params match the card
"""
import hashlib
import json
import os
import re
import sys

import numpy as np
import pandas as pd

prompt = sys.stdin.read()
run_dir = os.path.join(os.environ["LIGHTYEAR_RUNS"], os.environ["LIGHTYEAR_RUN"])
slug = re.search(r"slug:? ([a-z0-9_]+)", prompt).group(1)
cards = os.environ["LY_TEST_CARDS"]
os.makedirs(run_dir, exist_ok=True)
os.makedirs(cards, exist_ok=True)

CARD_TEXT = ("name: test card\nsignal:\n  params: {regression_days: 90, gap_limit: 0.15, signal_weekday: Tuesday}\n"
             "costs: {spread_bps: 30}\nbacktest_plan: {sample_start: '2014-01-01', sample_end: '2026-09-18'}\n"
             "n_configs_tried: 3\n")


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def emit(ev):
    print(json.dumps(ev), flush=True)


def say(txt):
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}})


def notes_block(text):
    m = re.search(r"<<<\n(.*?)\n>>>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


emit({"type": "system", "subtype": "init", "session_id": "fake-session-0001", "model": "fake"})
card = os.path.join(cards, f"{slug}.yaml")
gate_a = os.path.join(cards, f"{slug}__gate_a_queue.md")

if "stages 00 through Gate A" in prompt:
    write(os.path.join(run_dir, "prompt_phase_a.txt"), prompt)
    for sid in ["00", "01", "02", "03m", "GA"]:
        say(f"LIGHTYEAR-STAGE: {sid}\nworking")
    write(card, CARD_TEXT)
    write(gate_a, "# Gate A\n\n| fact | value |\n|---|---|\n| universe | NIFTY 500 |\n")
    dump({"status": "ok", "reason": "", "paper_title": "A Test Paper", "slug": slug, "card_path": card,
               "gate_a_path": gate_a, "plain_summary": "Buys winners.", "one_line": "baseline one_line",
               "universe": "NIFTY 500", "data_verdict": "the Ace file covers it", "open_questions": ["is 12-1 right?"],
               "files": [card]}, os.path.join(run_dir, "phase_a.json"))

elif "revise the card" in prompt:
    write(os.path.join(run_dir, "prompt_revise.txt"), prompt)
    notes = notes_block(prompt)
    if "SENTINEL-STALE" in notes:
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
              "result": "session crashed before writing", "total_cost_usd": 0.0, "num_turns": 1, "duration_ms": 10})
        sys.exit(1)
    if "SENTINEL-NOOP" not in notes:
        say("LIGHTYEAR-STAGE: GA\nrevising")
        with open(card, "a", encoding="utf-8") as fh:
            fh.write(f"operator_note: {json.dumps(notes)}\n")
        pa = json.loads(read(os.path.join(run_dir, "phase_a.json")))
        pa["one_line"] = f"revised: {notes}"
        dump(pa, os.path.join(run_dir, "phase_a.json"))
        with open(gate_a, "a", encoding="utf-8") as fh:
            fh.write(f"\nRevised with: {notes}\n")

elif "stages 03 through Gate B" in prompt:
    write(os.path.join(run_dir, "prompt_phase_b.txt"), prompt)
    for sid in ["03", "04", "05", "06", "07", "GB"]:
        emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
              "input": {"command": f"echo LIGHTYEAR-STAGE: {sid}"}}]}})
    notes = notes_block(prompt)
    m = re.search(r"for the card\s+(\S+)\s", prompt)
    card_path = m.group(1) if m else card
    card_text = read(card_path) if os.path.exists(card_path) else "(card not readable)"
    rng = np.random.default_rng(0)
    d = pd.bdate_range("2022-01-03", periods=400)
    pd.DataFrame({"date": d.strftime("%Y-%m-%d"), "strategy": rng.normal(4e-4, 0.01, 400),
                  "benchmark": rng.normal(3e-4, 0.011, 400)}).to_csv(os.path.join(run_dir, "daily_returns.csv"), index=False)
    tab = os.path.join(run_dir, "sens.csv")
    pd.DataFrame({"lookback": [6, 12], "CAGR": [0.05, 0.07], "Sharpe": [0.3, 0.5]}).to_csv(tab, index=False)
    os.makedirs(os.path.join(run_dir, "out"), exist_ok=True)      # the fixed output template a script may write
    dump([{"label": "Fixed row", "value": 1.0, "format": "num", "source": "test", "group": "other"}], os.path.join(run_dir, "out", "validation_rows.json"))
    dump([{"title": "Fixed table", "csv": tab, "note": "test"}], os.path.join(run_dir, "out", "tables.json"))
    dump({"strategy_name": "Test momentum", "benchmark_name": "NIFTY 500", "sleeve_name": None, "headline_cost_bp": 30,
               "headline": "A test.", "evidence_supports": "OBSERVE", "decisive_criterion": "deflated Sharpe",
               "gate_b": {"decision": "PENDING", "criteria": [
                   {"name": "deflated Sharpe clears selection bias", "passed": False, "blocking": True, "value": 0.4, "threshold": 0.95},
                   {"name": "turnover within tolerance", "passed": True, "blocking": True, "value": "120%", "threshold": "<=400%"},
                   {"name": "differentiated from existing book", "passed": False, "blocking": False, "value": "NO COMPARISON", "threshold": "<=0.8"}]},
               "validation": [{"label": "Bootstrap Sharpe low", "value": -0.2, "format": "num", "source": "test"}],
               "tables": [{"title": "Sensitivity", "csv": tab, "note": "test"}],
               "assumptions": [{"label": "Cost", "value": 0.003, "format": "pct", "note": "test"}],
               "notes": ["synthetic", f"PROMPT-NOTES: {notes}", f"CARD-TEXT: {card_text}"], "files": []},
              os.path.join(run_dir, "results.json"))
    dump({"schema": "lightyear-run-manifest/1", "script": {"path": "tests/fake_claude.py", "sha256": "0" * 64},
               "inputs": {"card": {"path": card_path, "kind": "file", "sha256": sha(card_path) if os.path.exists(card_path) else None}},
               "params": {"regression_days": 90, "gap_limit": 0.15, "signal_weekday": 1, "start": "2014-01-01",
                          "end": "2026-09-18", "cost_bp": 30, "n_trials": 5},
               "outputs": {}}, os.path.join(run_dir, "manifest.json"))

emit({"type": "result", "subtype": "success", "is_error": False, "result": "done", "total_cost_usd": 0.01,
      "num_turns": 3, "duration_ms": 1000})
