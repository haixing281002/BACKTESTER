"""One-line bootstrap for Google Colab.

Paste this into ONE cell of a brand-new Colab notebook and run it:

    import urllib.request as u; exec(u.urlopen(
        "https://raw.githubusercontent.com/haixing281002/BACKTESTER/"
        "claude/sleepy-hypatia-if6kj5/colab_bootstrap.py").read())

Why this exists rather than "just open the notebook":

A .ipynb reaches Colab through a chain that can silently serve stale content --
Colab caches GitHub notebooks, and offers a "Copy to Drive" that then reopens
in place of the original. Fixing the source does nothing for someone running
their saved copy, and the symptom (a cell that no longer exists still failing)
looks like the fix never landed.

This file is fetched live over https every single time it runs. There is no
notebook to cache, no saved copy to go stale, no cell ordering to get wrong,
and no upload widget to skip. If you can run one line, you get a correct run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

VERSION = "2026-09-17.1"
REPO = "https://github.com/haixing281002/BACKTESTER.git"
BRANCH = "claude/sleepy-hypatia-if6kj5"

PKGS = [
    "cvxpy>=1.5", "clarabel>=0.9", "pdfplumber>=0.10",
    "openpyxl>=3.1", "PyYAML>=6.0", "anthropic>=1.6", "pydantic>=2.0",
]


def _run(cmd, cwd=None, timeout=1800):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _hr(ch="="):
    print(ch * 74)


def bootstrap(run_pipeline: bool = False, card: str = None) -> str:
    """Install, fetch the repo and data, verify, and stop.

    It deliberately does NOT run a paper. There is no default paper: the whole
    point of the pipeline is that it analyses the one YOU bring, and a bootstrap
    that helpfully backtests a bundled example teaches the wrong habit -- the
    output looks like a result about your research when it is a result about
    somebody else's.

    Pass a card explicitly (bootstrap(run_pipeline=True, card="cards/x.yaml"))
    if you want the old behaviour.

    Returns the working directory. Safe to re-run: the clone is refreshed rather
    than duplicated, so a second run picks up any new commits.
    """
    t0 = time.time()
    # A previous run may have deleted the directory this process is standing in,
    # in which case os.getcwd() itself raises. Step somewhere real first.
    try:
        os.getcwd()
    except (FileNotFoundError, OSError):
        os.chdir("/")
    base = "/content" if os.path.isdir("/content") else os.getcwd()
    work = os.path.join(base, "BACKTESTER")

    _hr()
    print(f"  RESEARCH OS BOOTSTRAP   version {VERSION}")
    print(f"  fetched live from GitHub -- this cannot be a stale copy")
    _hr()

    # -- 1. dependencies ---------------------------------------------------
    print("\n[1/5] installing dependencies (60-90s on a cold runtime)...")
    r = _run([sys.executable, "-m", "pip", "install", "-q", *PKGS])
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit("pip install failed -- output above.")
    print("      done")

    # -- 2. source + data --------------------------------------------------
    # A shallow clone brings the engine, the strategy cards, the price workbook
    # and the paper in one step, so there is nothing left to upload.
    print(f"\n[2/5] cloning the repository (branch {BRANCH})...")
    # Step OUT of the tree before deleting it. On a re-run this process is
    # sitting inside `work` from last time, and removing the directory you are
    # standing in leaves the process with no working directory at all -- git
    # then fails with "Unable to read current working directory", which looks
    # like a network problem and is not one.
    os.chdir(base)
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)   # always start clean
    r = _run(["git", "clone", "--depth", "1", "--branch", BRANCH, REPO, work], cwd=base)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise SystemExit("git clone failed -- check the runtime has internet.")
    os.chdir(work)
    if work not in sys.path:
        sys.path.insert(0, work)
    for m in [m for m in list(sys.modules) if m == "ros" or m.startswith("ros.")]:
        del sys.modules[m]
    commit = _run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    print(f"      done -> {work}   commit {commit}")

    # -- 3. confirm the inputs are present ---------------------------------
    # The workbook ships with the repo. The PAPER does not default to anything:
    # whichever paper you are analysing is the one you upload below.
    print("\n[3/5] checking inputs...")
    xlsx = "data/raw/Factor_Indices_Historical_Price_Data.xlsx"
    if not os.path.exists(xlsx):
        raise SystemExit(f"expected input missing from the repo: {xlsx}")
    print(f"      {os.path.getsize(xlsx):>9,} bytes  {xlsx}")

    # -- 4. verify the environment actually works --------------------------
    print("\n[4/5] verifying...")
    failed = []
    import importlib
    for m in ("pandas", "numpy", "scipy", "statsmodels", "cvxpy",
              "pdfplumber", "yaml", "matplotlib", "anthropic", "pydantic"):
        try:
            importlib.import_module(m)
        except Exception as e:                       # noqa: BLE001
            failed.append(f"{m} ({type(e).__name__})")
    if failed:
        raise SystemExit(
            f"      these failed to import: {failed}\n\n"
            "Installing cvxpy can replace numpy underneath a running kernel.\n"
            "FIX: Runtime > Restart session, then run this one line again.")

    import cvxpy as cp
    import numpy as np
    w = cp.Variable(3)
    cp.Problem(cp.Maximize(np.array([.1, .2, .05]) @ w),
               [w >= 0, cp.sum(w) <= 1]).solve(solver=cp.CLARABEL)
    assert np.allclose(w.value, [0, 1, 0], atol=1e-6), "solver check failed"

    from ros.data.loaders import load_nse_factor_workbook
    from ros.papers import find_papers
    from ros.engine.primitives import list_primitives
    from ros.engine.templates import list_templates

    frame, prov = load_nse_factor_workbook(xlsx)
    print("      solver  : CLARABEL OK")
    print(f"      prices  : {prov['n_series']} series x {prov['n_rows']} rows  "
          f"{prov['date_min']} -> {prov['date_max']}")
    print(f"      engine  : {len(list_templates())} templates, "
          f"{len(list_primitives())} primitives")
    print(f"      papers  : {len(find_papers())} PDFs in the repo; "
          f"the one you analyse is the one you upload")

    if not run_pipeline:
        _hr()
        print(f"  READY in {time.time() - t0:.0f}s.  Working directory: {work}")
        _hr()
        return work

    # -- 5. hand over -------------------------------------------------------
    if not run_pipeline or not card:
        _hr()
        print(f"  READY in {time.time() - t0:.0f}s.  Working directory: {work}")
        _hr()
        print("""
  NOW UPLOAD THE PAPER YOU WANT TO ANALYSE

    from google.colab import files
    import shutil, os
    os.makedirs("docs/papers", exist_ok=True)
    up = files.upload()                      # pick your .pdf
    paper = "docs/papers/" + list(up)[0]
    shutil.move(list(up)[0], paper)
    print("uploaded ->", paper)

  THEN TAKE IT TO GATE A -- this needs NO market data at all

    !python run_interpret.py --pdf "$paper"

  It prints what the deterministic reader can see, the universe the card
  chose against its ranked alternatives, the strategy, the Gate A checklist,
  and exactly which data series would have to be supplied for THIS paper to
  become testable. A shortfall there is the deliverable, not a failure.

  The interpretation itself -- reading the paper, choosing the universe,
  reconstructing the strategy -- is a model's job. Open this folder in VS Code
  with Claude Code and run:

    /paper docs/papers/<your_paper>.pdf

  WHAT ELSE IS HERE

    !python -m pytest tests/ -q              # the engine's own correctness tests
    !python validate/cross_check.py          # engine vs a clean-room reimplementation
    !python check_setup.py                   # what is ready, what is not

    # the worked examples that ship with the repo, if you want a reference run
    !ls cards/
""")
        return work

    print(f"\n[5/5] running the pipeline on {card}")
    print("      (this takes 2-4 minutes and prints nothing until it finishes)\n")
    r = _run([sys.executable, "run_pipeline.py", "--card", card, "--n-boot", "2000"])
    if r.returncode != 0:
        print(r.stdout[-4000:]); print(r.stderr[-4000:])
        raise SystemExit("pipeline failed -- output above.")
    print(r.stdout)

    _hr()
    print(f"  DONE in {time.time() - t0:.0f}s.  Working directory: {work}")
    print(f"  Reports, charts and the research library are in {work}/outputs/")
    _hr()
    return work


# Executing this file (which is what the one-liner does) runs the whole thing.
bootstrap()
