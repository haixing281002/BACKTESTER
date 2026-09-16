#!/usr/bin/env python3
"""Is this machine ready, and has the LLM half actually run?

    python check_setup.py

Two independent halves, checked separately on purpose:

  DETERMINISTIC  the backtest, validation and gates. Pure Python. Works with no
                 Claude, no account, no key. If this is red, nothing else matters.

  INTERPRETATION the seven LLM-owned stages. In VS Code these are performed by
                 Claude Code in session. You cannot tell they ran by looking at a
                 chat window -- you tell by the ARTIFACTS they leave behind, which
                 is what the second half of this report shows.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys

OK, BAD, WARN = "  ok  ", "  XX  ", "  !!  "

# The LLM-owned and LLM-advising stages from the pipeline chart, with the command
# that performs each and the artifact that proves it happened.
LLM_STAGES = [
    ("00_triage", "/triage", "screen the paper for relevance"),
    ("01_ingest", "/ingest", "read the rendered PDF, page-anchored analysis"),
    ("02_card", "/draft-card", "write the Strategy Card"),
    ("02_critique", "/critique-card", "attack the draft"),
    ("03_data_mapping", "/map-data", "semantic data feasibility (advisory)"),
    ("gate_a", "/gate-a", "assemble the human review queue"),
    ("06_results_critique", "/critique-results", "attack our own backtest"),
    ("gate_b", "/gate-b", "assemble the IC briefing"),
    ("08_librarian", "/librarian", "has this been asked before?"),
]


def main() -> int:
    print("=" * 74)
    print("  RESEARCH OS -- SETUP CHECK")
    print("=" * 74)
    problems, warnings = [], []

    # ---------------------------------------------------- half 1: deterministic
    print("\nDETERMINISTIC HALF  (needs no Claude, no account, no API key)")
    print("-" * 74)

    v = sys.version_info
    good = v >= (3, 10)
    print(f"{OK if good else BAD}python {v.major}.{v.minor}.{v.micro}")
    if not good:
        problems.append("Python 3.10 or newer is required.")

    missing, broken = [], []
    for m in ("pandas", "numpy", "scipy", "statsmodels", "cvxpy", "clarabel",
              "pdfplumber", "openpyxl", "yaml", "pydantic", "pytest"):
        try:
            importlib.import_module(m)
        except ModuleNotFoundError as e:
            # A package that is genuinely absent names ITSELF. One that is
            # installed but broken names something underneath it -- a different
            # problem with a different fix, so do not merge the two.
            (missing if getattr(e, "name", m) == m else broken).append((m, e))
        except Exception as e:                                   # noqa: BLE001
            broken.append((m, e))
    print(f"{OK if not (missing or broken) else BAD}dependencies"
          + ("  all present" if not (missing or broken) else ""))
    for m, _ in missing:
        print(f"        NOT INSTALLED  {m}")
    for m, e in broken:
        print(f"        INSTALLED BUT BROKEN  {m} -> {type(e).__name__}: {e}")
    if missing:
        problems.append("Run: python -m pip install -r requirements.txt")
    if broken:
        problems.append(
            "A package is installed but its dependencies are broken. Repair the "
            "chain, do not reinstall the top-level package:\n"
            "      python -m pip install --upgrade --force-reinstall cffi cryptography\n"
            "      python -m pip install --upgrade --force-reinstall pdfminer.six pdfplumber")

    xlsx = "data/raw/Factor_Indices_Historical_Price_Data.xlsx"
    have_data = os.path.exists(xlsx)
    print(f"{OK if have_data else BAD}price data"
          + (f"  {os.path.getsize(xlsx):,} bytes" if have_data else "  MISSING"))
    if not have_data:
        problems.append(f"{xlsx} is missing -- are you in the repo root?")

    pdfs = [f for f in os.listdir("docs") if f.endswith(".pdf")] if os.path.isdir("docs") else []
    papers = [f for f in os.listdir("docs/papers") if f.endswith(".pdf")] if os.path.isdir("docs/papers") else []
    print(f"{OK if pdfs else WARN}papers       {len(pdfs)} in docs/, {len(papers)} in docs/papers/")

    if not missing and have_data:
        try:
            from ros.cards.schema import load_card
            c = load_card("cards/devanathan_2026_india_factor_adaptation.yaml")
            print(f"{OK}engine       card loads, fingerprint {c.fingerprint()}")
        except Exception as e:                                   # noqa: BLE001
            print(f"{BAD}engine       {type(e).__name__}: {e}")
            problems.append("The engine could not load a card. Run from the repo root.")

    # ------------------------------------------------- half 2: interpretation
    print("\nINTERPRETATION HALF  (the LLM-owned stages)")
    print("-" * 74)

    have_md = os.path.exists("CLAUDE.md")
    print(f"{OK if have_md else BAD}CLAUDE.md    "
          + ("project rules will load automatically" if have_md
             else "MISSING -- Claude will start with no project context"))
    if not have_md:
        problems.append("CLAUDE.md missing. Open the BACKTESTER FOLDER as your "
                        "VS Code workspace, not a parent directory.")

    cmd_dir = ".claude/commands"
    cmds = sorted(f[:-3] for f in os.listdir(cmd_dir)) if os.path.isdir(cmd_dir) else []
    print(f"{OK if len(cmds) >= 10 else BAD}commands     {len(cmds)} found"
          + (f": {', '.join('/' + c for c in cmds)}" if cmds else " -- MISSING"))
    if len(cmds) < 10:
        problems.append(f"{cmd_dir} is missing or incomplete. Wrong workspace root?")

    claude_bin = shutil.which("claude")
    if claude_bin:
        try:
            ver = subprocess.run([claude_bin, "--version"], capture_output=True,
                                 text=True, timeout=20).stdout.strip()[:40]
        except Exception:                                        # noqa: BLE001
            ver = "present"
        print(f"{OK}Claude Code  CLI on PATH: {ver}")
    else:
        print(f"{WARN}Claude Code  no `claude` on PATH")
        print("             The VS Code EXTENSION does not need to be on PATH, so this")
        print("             is not proof of anything. Confirm inside the editor instead:")
        print("             ask Claude 'what commands does this repo define?'")

    # ---- did the LLM stages actually run? the artifacts are the evidence ----
    print("\nHAS THE LLM WORK ACTUALLY RUN HERE?")
    print("-" * 74)
    try:
        from ros.interpretation import history
        recs = history()
    except Exception:                                            # noqa: BLE001
        recs = []
    done = {r["stage"]: r for r in recs}

    print(f"  {'stage':<22}{'command':<20}{'status'}")
    for stage, cmd, what in LLM_STAGES:
        r = done.get(stage)
        if r:
            valid = r.get("schema_valid")
            mark = "DONE" if valid is not False else "DONE (SCHEMA INVALID)"
            extra = f"  by {r['produced_by']}/{r['operator'][:16]}"
        else:
            mark, extra = "not run", ""
        print(f"  {stage:<22}{cmd:<20}{mark}{extra}")
    print(f"\n  {len(done)} of {len(LLM_STAGES)} interpretation stages have produced an artifact.")
    if not done:
        print("""
  NOTHING has been interpreted on this machine yet. That is expected on a fresh
  clone -- a clone carries the ENGINE and the COMMANDS, never the judgement.
  The LLM work is not a file you copy; it is done per paper, in session.

  To do it: open this folder in VS Code with Claude Code and run
      /paper docs/devanathan_2026_simple_dynamic_sbg.pdf
  then re-run this check. Stages will flip to DONE as artifacts appear.""")
    else:
        bad_schema = [s for s, r in done.items() if r.get("schema_valid") is False]
        if bad_schema:
            warnings.append(f"artifacts failing their schema: {bad_schema}")

    # ------------------------------------------------------------- verdict
    print("\n" + "=" * 74)
    if problems:
        print("  NOT READY")
        for p in problems:
            print(f"    - {p}")
    else:
        print("  DETERMINISTIC HALF: READY")
        print("    python run_pipeline.py --card cards/devanathan_2026_india_factor_adaptation.yaml")
        if done:
            print(f"  INTERPRETATION HALF: {len(done)} stage(s) recorded on this machine")
        else:
            print("  INTERPRETATION HALF: nothing run here yet (see above)")
    for w in warnings:
        print(f"    ! {w}")
    print("=" * 74)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
