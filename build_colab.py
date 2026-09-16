#!/usr/bin/env python3
"""Generate the self-contained Colab notebook.

Re-run this after changing the `ros` package so the notebook carries current code:
    tar czf /tmp/ros_bundle.tgz --exclude=__pycache__ ros run_pipeline.py cards tests
    python build_colab.py
"""
import base64, json, os, subprocess

BUNDLE = "/tmp/ros_bundle.tgz"
OUT = "colab/Research_OS_Colab.ipynb"

def md(src):  return {"cell_type": "markdown", "metadata": {}, "source": src.split("\n")}
def code(src, hide=False):
    m = {"cellView": "form"} if hide else {}
    return {"cell_type": "code", "execution_count": None, "metadata": m,
            "outputs": [], "source": src.split("\n")}

subprocess.run(["tar", "czf", BUNDLE, "--exclude=__pycache__",
                "ros", "run_pipeline.py", "run_agentic.py", "cards", "tests"], check=True)
b64 = base64.b64encode(open(BUNDLE, "rb").read()).decode()
chunks = [b64[i:i+100] for i in range(0, len(b64), 100)]
bundle_literal = "_B64 = (\n" + "\n".join(f'    "{c}"' for c in chunks) + "\n)"

cells = []

cells.append(md(r"""# Research Operating System — paper → backtest → governed decision

**A pipeline that reads a quant finance paper and tells you whether it is worth your money.**

Long-only Indian equities, NIFTY500 universe.

---

## Read this first: what problem this actually solves

You can already backtest. That is not the bottleneck.

The bottleneck is that **most backtests that look good are wrong**, and the ways they are wrong
are systematic and boring:

| How a backtest lies | What it looks like | Where this pipeline catches it |
|---|---|---|
| The signal saw the bar it traded | Beautiful Sharpe, dies in production | Step 05, planted look-ahead controls |
| Strategy and benchmark started on different dates | Benchmark banks a free year | Step 05, `align_runs()` |
| You tried 40 variants and reported the best | Sharpe 0.9 that is really noise | Step 06, deflated Sharpe |
| The data was reconstructed after the fact | Factor index backfilled to 2005 | Step 03, `pit_status` |
| It is 0.97 correlated with what you already own | Real alpha, zero value | Step 07, orthogonality |
| The paper meant something different from what you coded | Silent divergence | Step 02, Strategy Card |

Every one of those is a *process* failure, not a coding failure. So the system is built as a
**process with gates**, and the code exists to make the gates unavoidable.

The governing rule: **AI interprets. Deterministic systems compute. Humans govern.**

A paper enters as a **Strategy Card** — a YAML file. Never as code. That single constraint is
what makes 20 papers a day possible: the surface area a paper can touch is bounded, so the
implementation risk is bounded too.

---

## What you will see when you run this

Three papers go through the pipeline. **All three are rejected.** That is the system working.

1. **The source paper** (US stocks/bonds/gold) — halted in seconds at Step 03. We hold none of
   the required data. That is a procurement question, not a research question.
2. **The same mechanism adapted to your NIFTY500 factor sleeves** — runs fully, then dies at
   Step 07 when we control for the factors you already own.
3. **A completely different paper** (trend following) — included to prove the engine is
   paper-agnostic, not tuned to one paper.

**You need two files, and the notebook will refuse to continue without both:**

| File | Why it is required |
|---|---|
| `Factor_Indices_Historical_Price_Data.xlsx` | the price history every backtest runs on |
| the research paper `.pdf` | Step 01 ingests it; without it there is no page evidence, no recovered results tables and no auditable Strategy Card |

Total runtime: roughly 5–8 minutes on a free Colab CPU runtime. No GPU needed."""))

cells.append(md(r"""---
# SECTION 0 — Setup

**Runtime → Run all works.** Cell 0.3 defaults to `SOURCE = "repo"`, which downloads both
input files automatically — no clicking, no upload dialog.

Run these three in order: **0.1** installs libraries (~90s), **0.2** unpacks the engine,
**0.3** fetches the data.

> If a cell fails instantly with *"SETUP INCOMPLETE"*, it means an earlier setup cell did not
> finish. Scroll up, run 0.1 → 0.2 → 0.3 in order, then continue.
>
> If cell 0.1 reports imports that failed, do **Runtime → Restart session** and run it again —
> installing `cvxpy` can swap `numpy` out from under a live kernel."""))

cells.append(code(r'''#@title 0.1 — Install dependencies  { display-mode: "form" }
# Colab already ships pandas, numpy, scipy, matplotlib, statsmodels and PyYAML.
# We add: cvxpy + clarabel (the convex solver the source paper itself uses),
# pdfplumber (PDF ingestion), openpyxl (your .xlsx).
import subprocess, sys

PKGS = ["cvxpy>=1.5", "clarabel>=0.9", "pdfplumber>=0.10", "openpyxl>=3.1",
        "PyYAML>=6.0", "anthropic>=1.6", "pydantic>=2.0"]
print("Installing (60-90s on a cold runtime)...")
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PKGS],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout[-2000:]); print(r.stderr[-2000:])
    raise SystemExit("install failed -- see output above")

import importlib
failed = []
for m in ["pandas", "numpy", "scipy", "statsmodels", "cvxpy", "pdfplumber", "yaml",
          "matplotlib", "anthropic", "pydantic"]:
    try:
        mod = importlib.import_module(m)
        print(f"  ok  {m:<14} {getattr(mod, '__version__', '')}")
    except Exception as e:
        failed.append(m)
        print(f"  XX  {m:<14} {type(e).__name__}: {e}")
if failed:
    raise SystemExit(
        f"\nThese failed to import: {failed}\n"
        "Installing cvxpy can replace numpy/scipy underneath a running kernel.\n"
        "Fix: Runtime > Restart session, then run this cell again (the install is\n"
        "already done, so it will be quick), then carry on.")

# Confirm the solver actually solves, not just imports.
import cvxpy as cp, numpy as np
w = cp.Variable(3)
cp.Problem(cp.Maximize(np.array([.1, .2, .05]) @ w), [w >= 0, cp.sum(w) <= 1]).solve(solver=cp.CLARABEL)
print(f"\n  solver check: CLARABEL returned {np.round(w.value, 3)}  (expected [0. 1. 0.])")
print("\nSetup complete.")'''))

cells.append(code(bundle_literal + r'''

#@title 0.2 — Unpack the Research OS engine  { display-mode: "form" }
# The whole package is embedded above as a base64 tarball so this notebook is
# self-contained: no GitHub access, no external downloads, nothing to go stale.
import base64, io, os, sys, tarfile

WORK = "/content/research_os"
os.makedirs(WORK, exist_ok=True)
os.chdir(WORK)

with tarfile.open(fileobj=io.BytesIO(base64.b64decode(_B64)), mode="r:gz") as tf:
    tf.extractall(WORK)

for d in ["data/raw", "docs", "outputs"]:
    os.makedirs(os.path.join(WORK, d), exist_ok=True)
if WORK not in sys.path:
    sys.path.insert(0, WORK)

# Drop any stale imports so re-running this cell picks up edits you make later.
for m in [m for m in list(sys.modules) if m == "ros" or m.startswith("ros.")]:
    del sys.modules[m]

from ros.engine.primitives import list_primitives
from ros.engine.templates import list_templates

print(f"engine unpacked to {WORK}\n")
print("allocator templates :", ", ".join(list_templates()))
print("signal primitives   :", ", ".join(list_primitives()))
print("\nstrategy cards:")
for f in sorted(os.listdir("cards")):
    print("   cards/" + f)'''))

cells.append(md(r"""### 0.3 — Load your data (both files required)

Upload **both**:

1. **`Factor_Indices_Historical_Price_Data.xlsx`** — your NSE factor index price history
2. **the research paper `.pdf`** — the paper being evaluated

The cell hard-fails if either is missing. That is deliberate: a Strategy Card with no source
document cannot cite page evidence, so Gate A has nothing to check the interpretation against.
An uncitable card is exactly the failure mode this system exists to prevent.

In the upload dialog you can select both files at once (ctrl-click / cmd-click). Option B
(Google Drive) is better if you will re-run this often."""))

cells.append(code(r'''#@title 0.3 — Load your data  { display-mode: "form" }
# Default is "repo": both inputs download automatically from the public
# repository, so Runtime > Run all works with no interaction. Switch to
# "upload" only when you want to run YOUR OWN paper or data.
SOURCE = "repo"  #@param ["repo", "upload", "google_drive", "already_here"]
DRIVE_FOLDER = "/content/drive/MyDrive/quant_research"  #@param {type:"string"}

import os, shutil, glob, urllib.request

WORK = "/content/research_os"
if not os.path.isdir(WORK):
    raise SystemExit("SETUP INCOMPLETE -- run cell 0.2 first (it unpacks the engine).")
os.chdir(WORK)
XLSX = "data/raw/Factor_Indices_Historical_Price_Data.xlsx"
PDF = "docs/devanathan_2026_simple_dynamic_sbg.pdf"

RAW = ("https://raw.githubusercontent.com/haixing281002/BACKTESTER/"
       "claude/sleepy-hypatia-if6kj5/")

def _place(path):
    """Route a file to the right folder by extension."""
    low = path.lower()
    if low.endswith((".xlsx", ".xls")):
        shutil.copy(path, XLSX); return f"prices  -> {XLSX}"
    if low.endswith(".pdf"):
        shutil.copy(path, PDF); return f"paper   -> {PDF}"
    return f"ignored -> {os.path.basename(path)} (not .xlsx or .pdf)"

if SOURCE == "repo":
    for dst in (XLSX, PDF):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        url = RAW + ("data/raw/Factor_Indices_Historical_Price_Data.xlsx"
                     if dst == XLSX else "docs/devanathan_2026_simple_dynamic_sbg.pdf")
        try:
            urllib.request.urlretrieve(url, dst)
            print(f"  downloaded -> {dst}  ({os.path.getsize(dst):,} bytes)")
        except Exception as e:
            raise SystemExit(
                f"Could not download {dst}: {type(e).__name__}: {e}\n"
                "Set SOURCE = 'upload' above and provide the files yourself.")

elif SOURCE == "upload":
    from google.colab import files
    print("NOTE: this option needs you to pick files, so it does NOT work with")
    print("'Run all'. Run this cell on its own.\n")
    print("Select BOTH your .xlsx AND the paper .pdf (ctrl-click / cmd-click to")
    print("multi-select), then wait for the upload to finish.\n")
    got = files.upload()
    if not got:
        raise SystemExit(
            "No files were uploaded. If you used 'Run all', the upload widget is\n"
            "skipped -- set SOURCE = 'repo' above, or run this cell by itself.")
    for name in got:
        print("  " + _place(name))

elif SOURCE == "google_drive":
    from google.colab import drive
    drive.mount("/content/drive")
    hits = glob.glob(os.path.join(DRIVE_FOLDER, "*.xlsx")) + glob.glob(os.path.join(DRIVE_FOLDER, "*.pdf"))
    if not hits:
        raise FileNotFoundError(f"No .xlsx or .pdf found in {DRIVE_FOLDER}")
    for h in hits:
        print("  " + _place(h))

print()
PDF = "docs/devanathan_2026_simple_dynamic_sbg.pdf"
missing = []
if not os.path.exists(XLSX):
    missing.append("  - the price workbook  (Factor_Indices_Historical_Price_Data.xlsx)")
if not os.path.exists(PDF):
    missing.append("  - the research paper  (any .pdf)")
if missing:
    raise FileNotFoundError(
        "BOTH input files are required. Missing:\n" + "\n".join(missing) +
        "\n\nRe-run this cell and select both at once (ctrl-click / cmd-click "
        "in the upload dialog).")

# Validate the file before anything downstream trusts it.
from ros.data.loaders import load_nse_factor_workbook, audit_frame
import pandas as pd
pd.set_option("display.width", 200)

frame, prov = load_nse_factor_workbook(XLSX)
print(f"loaded {prov['n_series']} series x {prov['n_rows']} rows   "
      f"{prov['date_min']} -> {prov['date_max']}")
print(f"source sha256: {prov['sha256'][:32]}\n")
print("DATA AUDIT (runs before any backtest touches the frame):")
print(audit_frame(frame).to_string(index=False))

# Validate the PDF too -- a file with a .pdf extension is not necessarily readable.
from ros.cards.extract import extract_document
doc = extract_document(PDF)
print(f"\npaper loaded : {doc.quality.n_pages} pages, {doc.quality.n_chars:,} chars, "
      f"sha256 {doc.sha256[:16]}")
if doc.quality.is_scanned:
    raise ValueError(
        "This PDF is scanned (near-zero extractable text). It cannot be carded "
        "without OCR -- which is itself a Step 01 finding, not a bug.")
print("both inputs present and readable.")'''))

cells.append(md(r"""#### What just happened, and why the audit matters

`audit_frame` is not decoration. It checks the things that silently corrupt a backtest:

- **`gaps`** — missing days *inside* a series' coverage. A gap means the engine would be
  interpolating or dropping days without telling you.
- **`n_stale_5d`** — five consecutive zero returns. That is a dead feed, not a quiet market.
- **`n_gt_20pct`** — daily moves above 20%. Almost always a bad print or an unadjusted split.
- **`neg_or_zero_px`** — a non-positive price makes every return calculation meaningless.

Your data comes back clean on all four. That is genuinely good and worth knowing up front.

**But look at `first_value`.** Every factor index starts at exactly **1000.00**. Hold that
thought — it turns out to be the single most important fact about this dataset, and Step 03
is where we deal with it."""))

cells.append(md(r"""---
# SECTION 1 — The pipeline, end to end

Before stepping through it, run the whole thing once so you can see the shape of the output.

## The eight steps

| Step | What it asks | Can it stop the pipeline? |
|---|---|---|
| **01 Ingest** | What does the paper actually say, and can we trust the extraction? | Yes — a scanned PDF is not cardable |
| **02 Strategy Card** | Can we state the strategy unambiguously? | Yes — unresolved ambiguity blocks |
| **Gate A** | *Human:* do we understand the economics? | Yes |
| **03 Feasibility** | Can we get the data? | **Yes — fail fast** |
| **04 PIT snapshot** | Freeze exactly what the run may see | Yes |
| **05 Build + execute** | Run it, honestly | Yes — look-ahead tripwire |
| **06 Research validation** | Is the result real, or manufactured? | No — informs Gate B |
| **07 Portfolio validation** | Does it help *our* book? | No — informs Gate B |
| **Gate B** | *Human:* do we allocate? | Yes |
| **08 Library** | Store it so nobody pays twice | — |

Note where the two human gates sit. **Before** any code is written, and **after** all the
evidence exists. Nowhere in between. That is deliberate: humans are good at judging economics
and terrible at spotting an off-by-one in a shift."""))

cells.append(code(r'''#@title 1.1 — Run the full pipeline on all three cards  { display-mode: "form" }
import os, subprocess, sys, time
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")

CARDS = [
    ("cards/devanathan_2026_replication.yaml",
     "Source paper, replicated as published (US stocks/bonds/gold)"),
    ("cards/devanathan_2026_india_factor_adaptation.yaml",
     "Same mechanism, adapted to your NIFTY500 factor sleeves"),
    ("cards/moskowitz_2012_tsmom_india.yaml",
     "A structurally different paper -- proves the engine is paper-agnostic"),
]

for card, blurb in CARDS:
    print("=" * 96)
    print(f"RUNNING  {card}\n         {blurb}")
    print("=" * 96)
    t0 = time.time()
    r = subprocess.run([sys.executable, "run_pipeline.py", "--card", card, "--n-boot", "2000"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:]); print(r.stderr[-3000:])
        raise SystemExit(f"{card} failed")
    # Print the verdict now; the detail is explored step by step below.
    keep, show = False, []
    for line in r.stdout.splitlines():
        if "PROMOTION LADDER" in line or "PIPELINE HALTED" in line:
            keep = True
        if keep:
            show.append(line)
    print("\n".join(show[:30]) if show else r.stdout[-1500:])
    print(f"\n[{time.time() - t0:.0f}s]\n")

print("All three complete. Reports are in outputs/.")'''))

cells.append(md(r"""### Read that again

Three papers. Three rejections. **Zero strategies promoted.**

If that feels like a failure, it is worth reframing. The alternative — the thing that happens
without a pipeline — is that one of these gets built, allocated to, and quietly loses money
for eighteen months before anyone can prove it was never working.

The board document set the target as *"one portfolio-useful signal every few weeks"*, screening
*"20 papers a day"*. That arithmetic only works if the overwhelming majority die, cheaply, with
the reason recorded. **Rejection is the product.** Promotion is the rare exception.

Now let us look at *why* each one died, because the reasons are the useful part."""))

cells.append(md(r"""---
# SECTION 2 — Step 01: Ingest

## What the AI is allowed to do here, and what it is not

The AI reads the PDF and proposes candidate fields. It does **not** decide anything. Everything
it produces is anchored to a page number so a human can check it in seconds.

This matters because **PDF text extraction destroys mathematics.** Run the next cell and look at
the `math density` number."""))

cells.append(code(r'''#@title 2.1 — Ingest the paper  { display-mode: "form" }
import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
from ros.cards.extract import extract_document, summarize

PDF = "docs/devanathan_2026_simple_dynamic_sbg.pdf"
assert os.path.exists(PDF), "paper PDF missing -- re-run cell 0.3"

doc = extract_document(PDF)
print(summarize(doc))

print("\n" + "=" * 90)
print("WHAT THE EQUATIONS LOOK LIKE AFTER EXTRACTION (page 6, the core constraint):")
print("=" * 90)
for line in doc.page_text(6).splitlines():
    if "wspy" in line or "wagg" in line:
        print("   " + line)
print("""
   In the actual PDF this reads:   w^spy_t + w^agg_t + w^gld_t  <=  1
   Every subscript and superscript is gone. An LLM handed this text will
   reconstruct a formula that is plausible and wrong, with total confidence.""")'''))

cells.append(md(r"""### The table problem, and why it matters more than it looks

`pdfplumber.extract_tables()` found **zero** tables in a paper that is full of them.

Academic papers use LaTeX `booktabs`, which draws almost no ruling lines. Ruled-table detection
needs rules. So the extractor fails on exactly the pages that matter most — **the results tables
that define what "replicated" means.**

The fix is a text-geometry parser: a table row is a label followed by two or more numeric tokens.
Run the next cell."""))

cells.append(code(r'''#@title 2.2 — Recover the results tables, and find the trap  { display-mode: "form" }
import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
from ros.cards.extract import (extract_document, parse_text_tables,
                               propose_replication_targets, detect_target_conflicts)

doc = extract_document("docs/devanathan_2026_simple_dynamic_sbg.pdf")
tables = parse_text_tables(doc)
print(f"tables recovered by text geometry : {len(tables)}   (ruled-table detection found 0)\n")

hit = next((t for t in tables if "Volatility" in (t["header"] or "")), None)
if hit is None:
    print("No portfolio-by-metric table found. Expected for a paper with a different")
    print("results layout -- the parser is generic, not tuned to this paper.")
else:
    print(f"Table 1 (page {hit['page']}) -- the paper's headline results:")
    print(f"   {'portfolio':<20}{'return':>9}{'vol':>8}{'sharpe':>8}{'maxDD':>8}")
    for lbl, vals in hit["rows"].items():
        print(f"   {lbl:<20}{vals[0]:>8.1%}{vals[1]:>8.1%}{vals[2]:>8.2f}{vals[3]:>8.1%}")

props = propose_replication_targets(tables)
conflicts = detect_target_conflicts(props)
print(f"\ncandidate replication targets : {len(props)}")
print(f"CONFLICTING targets           : {len(conflicts)}\n")

for c in conflicts:
    if c["portfolio"] == "Markowitz" and c["metric"] == "sharpe":
        print(f"   Markowitz Sharpe appears as: {c['values']}  on pages {c['pages']}")
print("""
   Those are not parser errors. They are the SAME metric on different bases:
       1.08  pre-tax, nominal        (Table 1, p11)
       0.99  inflation-adjusted      (p17)
       0.83 / 0.67 / 0.64  post-tax  (p19, three tax brackets)
       1.01  lagged-data variant     (p34)

   Harvest all of them and your replication test CAN NEVER FAIL -- some row
   always matches whatever you produce. A human pins ONE basis at Gate A.""")'''))

cells.append(md(r"""### Green flags and red flags for Step 01

**🟢 Green** — machine-readable text (93k chars, no OCR); **published open-source code**, which
is the strongest replication signal there is; explicit data provenance named in the text
(Yahoo Finance, FRED, Kenneth French); clean, complete results tables.

**🔴 Red** — 7.2% of lines carry broken math, so no card field derived from a formula can be
trusted without a human checking the rendered page; rotated figure text extracts *backwards*
(`nruter evitalumuC` = "Cumulative return"), so numbers on those pages are axis ticks, not
results; the same metric is reported on four accounting bases with no canonical table.

**Relevance to you:** when you point this at Indian broker research or SSRN preprints, expect
worse. Scanned PDFs, image-only tables, and regional-language headers are common. The
`is_scanned` check exists so you find that out in two seconds rather than after an afternoon."""))

cells.append(md(r"""---
# SECTION 3 — Step 02: The Strategy Card

## This is the most important idea in the whole system

The Strategy Card is the **only** interface between paper interpretation (AI, fallible) and the
deterministic engine. Nothing in the engine reads the PDF.

Why that constraint earns its keep:

1. **Ambiguity becomes visible before code exists.** You cannot write a card without confronting
   what the paper left unsaid.
2. **Implementation risk is bounded.** A card can only name a registered template and its
   parameters. It cannot smuggle in arbitrary code.
3. **Papers become diffable.** Two cards with the same fingerprint are the same experiment.
4. **A new paper costs a YAML file, not an engineering sprint.** That is what makes 20/day real.

Run the next cell to see the seven ambiguities found in this paper — each one a way a
replication could silently diverge."""))

cells.append(code(r'''#@title 3.1 — Inspect the Strategy Card  { display-mode: "form" }
import os, textwrap
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
from ros.cards.schema import load_card

card = load_card("cards/devanathan_2026_replication.yaml")
print(f"card        : {card.paper.id}")
print(f"mode        : {card.intent.mode.upper()}")
print(f"fingerprint : {card.fingerprint()}   <- same fingerprint = same experiment")
print(f"template    : {card.signal.template}   rebalance: {card.portfolio.rebalance}   "
      f"lag: {card.signal.lag_days}d   lookback: {card.signal.lookback_days}d")
print(f"costs       : {card.costs.spread_bps:.0f} bps round trip\n")

print("=" * 96)
print("SEVEN MATERIAL AMBIGUITIES -- each one resolved BEFORE any code ran")
print("=" * 96)
for i, a in enumerate(card.ambiguities, 1):
    pg = f" (p{a.evidence_page})" if a.evidence_page else ""
    print(f"\n[{i}] {a.field}   confidence={a.confidence}{pg}")
    for ln in textwrap.wrap(" ".join(a.issue.split()), 92):
        print("     ISSUE    " + ln if ln == textwrap.wrap(" ".join(a.issue.split()), 92)[0]
              else "              " + ln)
    for ln in textwrap.wrap(" ".join(a.resolution.split()), 92):
        print("     RESOLVED " + ln if ln == textwrap.wrap(" ".join(a.resolution.split()), 92)[0]
              else "              " + ln)

print("\n" + "=" * 96)
print(f"unresolved ambiguities: {len(card.unresolved_ambiguities)}  "
      "(any unresolved ambiguity BLOCKS the pipeline at Gate A)")'''))

cells.append(md(r"""### The three that would have burned you

**Ambiguity #1 — the Sharpe ratio is not the Sharpe ratio.**
This paper defines Sharpe as *(CAGR − compounded cash CAGR) / annualised vol*. That is a
**geometric** measure. Everyone else — and every risk system you own — uses the arithmetic mean
of periodic excess returns. They differ by roughly half the variance: about 0.5% a year at 10%
vol, which moves a Sharpe by ~0.05.

That is enough to make a *correct* replication look broken, and send you hunting a bug that
does not exist. The engine now always computes **both** and the card states which one it is
replicating.

**Ambiguity #4 — the paper's core mechanism is free by construction.**
Appendix A: *"moving value into or out of cash is not itself a trade."* But volatility control
works **by** moving into and out of cash. Its main activity is therefore uncosted. Not fraud —
a modelling choice, stated plainly — but it flatters the headline result and you must know it.

**Ambiguity #6 — the risk-free asset is on both sides of the trade.**
The fed funds rate is simultaneously the Sharpe numeraire *and* the yield the portfolio earns on
cash. No investor earns the fed funds rate on a cash balance. This flatters every cash-holding
portfolio — which is every winning portfolio in the paper.

**Relevance to you:** none of these are visible from the abstract. They are visible from the
appendix. The card forces someone to read the appendix *before* the engineering starts, which is
the cheapest possible moment to discover them."""))

cells.append(md(r"""---
# SECTION 4 — Step 03: Data feasibility

## The step that pays for the entire system

This is the cheapest gate and the highest-value one. It compares what a paper **needs** against
what you **hold**, and it is allowed to stop everything.

Four possible resolutions per requirement:

- **AVAILABLE** — we hold it, with acceptable point-in-time status
- **PROXY** — we hold a stand-in, and the substitution is recorded (never silent)
- **DEGRADED** — we hold it, but its provenance undermines the claim
- **UNAVAILABLE** — we do not hold it and have no stand-in"""))

cells.append(code(r'''#@title 4.1 — Feasibility: the source paper  { display-mode: "form" }
import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
from ros.cards.schema import load_card
from ros.data.firm_registry import build_firm_registry
from ros.feasibility import assess

registry = build_firm_registry()
rep = assess(load_card("cards/devanathan_2026_replication.yaml"), registry)

print(f"VERDICT: {rep.verdict}")
print(f"counts : {rep.counts()}\n")
print(f"  {'requirement':<26}{'mandatory':<11}{'status'}")
print("  " + "-" * 52)
for r in rep.resolutions:
    print(f"  {r.requirement:<26}{'YES' if r.mandatory else 'no':<11}{r.status}")

print(f"""
The pipeline HALTS here. No strategy code was written. No backtest ran.

We hold zero US ETF prices, zero ETF volumes, zero FRED series, zero
Fama-French factors. {len(rep.blocking)} mandatory requirements are unavailable.

This is a PROCUREMENT question, not a research question -- and the whole
point is that it cost seconds to establish rather than days.""")'''))

cells.append(code(r'''#@title 4.2 — Feasibility: the India adaptation  { display-mode: "form" }
import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
from ros.cards.schema import load_card
from ros.data.firm_registry import build_firm_registry
from ros.feasibility import assess

card = load_card("cards/devanathan_2026_india_factor_adaptation.yaml")
ad = assess(card, build_firm_registry())

print(f"VERDICT: {ad.verdict}")
print(f"counts : {ad.counts()}\n")
print(f"  {'requirement':<34}{'status':<12}{'resolved to'}")
print("  " + "-" * 82)
for r in ad.resolutions:
    print(f"  {r.requirement:<34}{r.status:<12}{r.resolved_to or '--'}")

print(f"\n  SIGN-OFF REQUIRED AT GATE A ({len(ad.signoff_required)} items):")
for s in ad.signoff_required:
    print(f"    ? {' '.join(s.split())[:100]}")'''))

cells.append(md(r"""### 🔴 The red flags in *your own* data

This is the part most relevant to you, so it is worth being blunt.

**1. Every factor index starts at exactly 1000.00 on 2005-04-01.**

That is the signature of a **rebased, backfilled** index. NSE launched these factor indices years
after 2005 and reconstructed the history backwards. The construction rules — how many stocks,
which metric, what rebalance cadence — were chosen by people who could already see what the
2005–2020 returns would be.

**Selection bias is built into the series itself.** No backtest technique removes it. You are not
measuring "what momentum did in India"; you are measuring "what the momentum definition NSE
settled on, having seen the answer, did in India."

This is why the pipeline caps these cards at the `ROBUST` rung and forbids any live claim resting
on backfilled sleeve history.

**2. They are price-return, not total-return.** Roughly 1.3–1.5% a year of dividends missing from
every series. Every equity-versus-cash comparison is biased against equity.

**3. An index is not a portfolio.** No replication tracking error, no rebalance market impact, no
sleeve-level turnover is charged inside the index level. A real sleeve costs more to hold than
the index suggests.

**4. You have no Indian risk-free series at all.** The cash proxy is a declared constant 6%. It is
wrong in level *and in shape* — it cannot represent the 2009 or 2020 easing cycles, which is
exactly when a de-risking strategy is sitting in cash. So the pipeline **sweeps it 4–8%** rather
than assuming it.

### 🟢 The green flags

5,247 complete daily observations, zero internal gaps, zero stale runs, zero bad prints. Twenty-one
years spanning 2008, the 2013 taper, 2020 and 2022 — several genuine regimes. Mechanically, this
is good data. The problems are all provenance problems, and provenance problems are fixed by
purchase orders, not by cleverness."""))

cells.append(md(r"""---
# SECTION 5 — Steps 04 & 05: Snapshot and execution

## Step 04 — why lineage is non-negotiable

Every run freezes a snapshot recording the source file hash, a content hash of the materialised
frame, a hash of the engine source code, and the git commit. A number in the library can be
re-derived years later — or *proven irreproducible*, which is just as valuable.

The engine code hash matters more than people expect: if you change the backtester, prior results
are no longer comparable, and the hash tells you that rather than letting you compare them anyway.

## Step 05 — the two guarantees that make the numbers real"""))

cells.append(code(r'''#@title 5.1 — Build the snapshot and run the backtest  { display-mode: "form" }
import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
import pandas as pd
pd.set_option("display.width", 220)

from ros.cards.schema import load_card
from ros.data.loaders import load_nse_factor_workbook
from ros.data.snapshot import SnapshotBuilder
from ros.runner import execute_card, align_runs
from ros.validation.metrics import metrics_table, render_table

card = load_card("cards/devanathan_2026_india_factor_adaptation.yaml")
frame, prov = load_nse_factor_workbook("data/raw/Factor_Indices_Historical_Price_Data.xlsx")

needed = list(card.universe.assets) + ["NIFTY 500", "NIFTY500 MULTIFACTOR MQVLV 50"]
snap = (SnapshotBuilder(f"{card.paper.id}__{card.fingerprint()}", pit_status="backfilled")
        .add_source(frame, prov)
        .restrict(start=card.portfolio.start, end=card.portfolio.end, columns=needed)
        .require_complete(needed)
        .freeze())

print("STEP 04 -- LINEAGE")
print(f"  snapshot_id  : {snap.snapshot_id}")
print(f"  content hash : {snap.content_hash[:40]}")
print(f"  code hash    : {snap.engine_code_hash[:40]}")
print(f"  shape        : {snap.frame.shape}   {snap.frame.index.min().date()} -> {snap.frame.index.max().date()}")
print(f"  pit_status   : {snap.pit_status}")
print(f"  verify()     : {snap.verify()}   <- re-derives the hash on demand")

runset = align_runs(execute_card(card, snap, cash_rate=0.06, reference_assets=[
    "NIFTY 500", "NIFTY500 MULTIFACTOR MQVLV 50"]))
rf = runset.inputs["rf"]

print(f"\nSTEP 05 -- EXECUTION")
print(f"  configurations run   : {runset.n_configs_run}")
print(f"  common start (aligned): {pd.Timestamp(runset.inputs['aligned_start']).date()}")
d = runset.primary.meta.get("allocator_diagnostics", {})
print(f"  solver               : {d.get('solves')} solves, {d.get('solver_failures')} failures")

tbl = metrics_table(runset.all_results(), rf_daily=rf)
print("\n  PERFORMANCE (net of 30bp costs, common window):")
print(render_table(tbl[["cagr", "vol", "sharpe", "max_dd", "turnover"]]))'''))

cells.append(code(r'''#@title 5.2 — Prove the engine is not cheating  { display-mode: "form" }
# A look-ahead check is only worth anything if you show it CAN fail. So every run
# plants two deliberate leaks and asserts that both are caught.
from ros.engine.backtest import assert_causal, LookaheadError
import pandas as pd

inp = runset.inputs
rets = inp["returns"]

print("LIVE SIGNALS (must pass):")
for nm, sig in [("alpha (return forecast)", inp.get("alpha")),
                ("sigma_bench (risk estimate)", inp.get("sigma_bench"))]:
    if sig is None:
        continue
    s = sig.shift(1 + inp["lag_days"])
    if isinstance(s, pd.Series):
        s = pd.DataFrame({c: s for c in rets.columns})
    try:
        assert_causal(s, rets, label=nm)
        print(f"   PASS  {nm}")
    except LookaheadError as e:
        print(f"   FAIL  {e}")

print("\nPLANTED LEAKS (must be caught, or the tripwire is decoration):")
for lbl, planted in [("signal knows the bar it trades", rets),
                     ("signal knows tomorrow", rets.shift(-1))]:
    try:
        assert_causal(planted, rets, label=lbl)
        print(f"   BROKEN  '{lbl}' was NOT caught")
    except LookaheadError:
        print(f"   PASS    '{lbl}' correctly caught")

print("""
Why both: the engine shifts signals by (1 + lag_days). An off-by-one lets the
signal see the bar it trades (leak 1). A stray negative shift lets it see
tomorrow (leak 2). These are different bugs and a check for one misses the other
-- which is exactly the bug this notebook's own tripwire had before it was fixed.""")'''))

cells.append(md(r"""### The alignment bug — and why it changed the answer

Look at the `common start (aligned)` line above.

The Markowitz strategy cannot rebalance until its 252-day EWMA forecast exists. The equal-weight
benchmark trades from day one. Left unaligned, the strategy carries roughly **250 days of flat,
zero-return NAV** while the benchmark banks a real year of returns.

That is not a small distortion. When this was fixed mid-build, **the ranking reversed**: the
volatility-target overlay went from *beating* equal-weight sleeves (0.60 vs 0.49) to *losing* to
them (0.42 vs 0.45). The earlier, flattering result was an artifact of the start date.

`align_runs()` truncates every strategy and benchmark to a common start and rebases all of them
to 1.0.

**Relevance to you:** this bug is invisible. Nothing errors, nothing looks odd, the equity curves
are all plotted from different dates and nobody notices. If you take one piece of engineering
from this notebook into your own stack, take this one.

### What the results already tell us

| | Sharpe | Turnover |
|---|---|---|
| **NIFTY500 MULTIFACTOR MQVLV 50** — you can just buy this | **0.53** | **0%** |
| Equal-weight sleeves | 0.45 | 5% |
| **The adapted strategy** | **0.44** | **147%** |
| NIFTY 500 | 0.22 | 0% |

Every sleeve strategy beats NIFTY 500. But that is the **factor premium** (and its backfill), not
the paper's contribution. The paper's actual mechanism — the optimiser — is the second-worst
thing in the table, and it loses to an index you can buy tomorrow."""))

cells.append(code(r'''#@title 5.3 — Charts  { display-mode: "form" }
import matplotlib.pyplot as plt
import numpy as np

res = runset.all_results()
fig, ax = plt.subplots(2, 2, figsize=(16, 10))

for r in res:
    ax[0, 0].plot(r.value.index, r.value.values, lw=1.3, label=r.name[:38])
ax[0, 0].set_yscale("log"); ax[0, 0].set_title("Cumulative return (log scale)")
ax[0, 0].legend(fontsize=7); ax[0, 0].grid(alpha=.3)

for r in res:
    dd = r.value / r.value.cummax() - 1
    ax[0, 1].plot(dd.index, dd.values, lw=1.0, label=r.name[:38])
ax[0, 1].set_title("Drawdown"); ax[0, 1].grid(alpha=.3); ax[0, 1].legend(fontsize=7)

p = runset.primary
w = p.weights.copy(); w["CASH"] = p.cash_weight
ax[1, 0].stackplot(w.index, *[w[c].values for c in w.columns],
                   labels=[c[:26] for c in w.columns])
ax[1, 0].set_title("Weights over time (faithful variant -- note the cash in 2008-09)")
ax[1, 0].legend(fontsize=7, loc="lower left"); ax[1, 0].set_ylim(0, 1)

for r in res:
    cy = r.returns.groupby(r.returns.index.year).std() * np.sqrt(252)
    ax[1, 1].plot(cy.index, cy.values, marker="o", ms=3, lw=1, label=r.name[:38])
ax[1, 1].set_title("Realised calendar-year volatility"); ax[1, 1].grid(alpha=.3)
ax[1, 1].legend(fontsize=7)

plt.tight_layout(); plt.show()

print(f"Faithful variant average cash by year (this is the mandate problem, in one table):")
print((p.cash_weight.groupby(p.cash_weight.index.year).mean() * 100).round(1).to_string())'''))

cells.append(md(r"""---
# SECTION 6 — Step 06: Is the result real?

Six tests. Each attacks the result from a different angle. Run the cell, then read the
interpretation below it — the two most important results are not the obvious ones."""))

cells.append(code(r'''#@title 6.1 — Research validation  { display-mode: "form" }
import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
import pandas as pd
from ros.validation import research as rv
from ros.validation.metrics import sharpe_geometric, cagr, ann_vol, max_drawdown

primary = runset.mandate if runset.mandate is not None else runset.primary
print(f"Strategy under test: {primary.name}\n")

print("=" * 90); print("1. SUB-PERIODS -- does it work in every regime, or one lucky decade?")
print("=" * 90)
print(rv.subperiod_table(runset.all_results(), rf_daily=rf, n_periods=4, metric="sharpe").round(2).to_string())

print("\n" + "=" * 90); print("2. ANCHORED WALK-FORWARD -- out of sample by construction")
print("=" * 90)
splits = rv.walk_forward_split(primary.value.index, n_folds=4, min_train_years=5.0)
print(rv.oos_summary(primary, splits, rf_daily=rf).round(3).to_string(index=False))

print("\n" + "=" * 90)
print("3. PAIRED BOOTSTRAP -- is the advantage real, or could it be luck?")
print("=" * 90)
boot = rv.stationary_bootstrap({r.name: r.returns for r in runset.all_results()},
                               rf_daily=rf, n_boot=2000, mean_block=21, baseline=primary.name)
key = "paired_sharpe_diff_vs_" + primary.name
rows = [{"comparator": k, "mean_diff": f"{v['mean_diff']:+.2f}",
         "ci95": f"[{v['ci95'][0]:+.2f}, {v['ci95'][1]:+.2f}]",
         "P(no advantage)": f"{v['p_not_positive']:.3f}"} for k, v in boot[key].items()]
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 90)
print("4. DEFLATED SHARPE -- penalised for how many things we tried")
print("=" * 90)
dsr = rv.deflated_sharpe(primary.returns, n_trials=max(card.n_configs_tried, runset.n_configs_run),
                         rf_daily=rf)
for k in ["sharpe_ann", "n_trials", "selection_threshold_sharpe", "deflated_sharpe_prob", "skew", "kurtosis"]:
    print(f"   {k:<28}: {dsr[k]:.4f}" if isinstance(dsr[k], float) else f"   {k:<28}: {dsr[k]}")
print(f"   -> {dsr['interpretation']}")

allow_cash = card.portfolio.mandate_allow_cash
run_one = runset.inputs["run_one"]

print("\n" + "=" * 90)
print("5. IMPLEMENTATION LAG -- a real signal decays when you trade late")
print("=" * 90)
def at_lag(L):
    return run_one(card.signal.template, card.signal.params, "lag",
                   card.portfolio.rebalance, allow_cash, lag_days=L)
print(rv.lag_sensitivity(at_lag, [0, 1, 2, 5, 10], rf_daily=rf).round(4).to_string(index=False))

print("\n" + "=" * 90)
print("6. CASH-RATE PROXY SWEEP -- the proxy is an assumption, so sweep it")
print("=" * 90)
from ros.runner import execute_card as _ex
rows = []
for cr in [0.04, 0.05, 0.06, 0.07, 0.08]:
    r2 = align_runs(_ex(card, snap, cash_rate=cr, reference_assets=[]))
    t = r2.mandate if r2.mandate is not None else r2.primary
    rows.append({"cash_rate": cr, "sharpe": sharpe_geometric(t.value, t.returns, r2.inputs["rf"])})
print(pd.DataFrame(rows).round(4).to_string(index=False))'''))

cells.append(md(r"""### The two results that actually matter

**The lag test is the most damning thing in this notebook.**

A genuine timing signal **decays** as you delay execution. Trade a day late, earn slightly less.
Trade ten days late, earn much less. That is what having timing information *means*.

This strategy's Sharpe goes **0.43 at lag 0 → 0.47 at lag 10**. It gets *better* when you trade
ten days late.

That is not "a signal with implementation constraints." That is **no timing information at all**.
The strategy is capturing a slow-moving exposure that would have been just as available a
fortnight later. A backtest can look entirely healthy and still fail this test — which is exactly
why it is in the suite.

**The deflated Sharpe explains why "Sharpe 0.5" is not a result.**

With 7 configurations tried, the threshold Sharpe you must clear *just to be distinguishable from
the best of seven coin flips* is **1.39**. Observed: 0.51. P(skill) ≈ **0%**.

The expected maximum Sharpe from N random strategies grows like √(2 ln N). Try 100 variants and
one of them shows Sharpe ~1.0 on pure noise. This is why the trial count is tracked across the
*library*, not just the current session — so iterating across weeks cannot quietly launder a
lucky draw into a promotion.

### And one result to be honest about

**The bootstrap intervals are enormous** — Sharpe CI roughly [−0.12, +1.13] on twenty years of
daily data.

That is not a flaw in the method. That is the truth about Sharpe ratios: even two decades of data
barely distinguishes them from zero. The source paper reports the same problem for its own
comparisons. Anyone quoting a point Sharpe estimate without an interval is not showing you the
uncertainty — and the uncertainty is most of the story."""))

cells.append(md(r"""---
# SECTION 7 — Step 07: Does it help *your* book?

## This is where the decision actually gets made

Step 06 asks "is the result real?". Passing Step 06 is necessary and nowhere near sufficient.

Step 07 asks the only question a PM cares about:

> **Given what we already own, does adding this make the book better, after costs?**

A strategy with a standalone Sharpe of 1.2 that is 0.95-correlated to your existing book adds
nothing. That is the most common way a "validated" signal turns out to be worthless."""))

cells.append(code(r'''#@title 7.1 — Portfolio validation  { display-mode: "form" }
import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")
import pandas as pd
from ros.validation import portfolio as pv

bench = runset.by_name("NIFTY 500")
book = runset.by_name("Equal-weight sleeves")

print("=" * 90); print("A. VERSUS THE FUND BENCHMARK (NIFTY 500) -- looks great in isolation")
print("=" * 90)
br = pv.benchmark_relative(primary.returns, bench.returns, rf_daily=rf)
for k in ["beta", "alpha_ann", "tracking_error", "information_ratio", "correlation"]:
    print(f"   {k:<22}: {br[k]:+.4f}")

print("\n" + "=" * 90)
print("B. FACTOR FINGERPRINT -- now control for the sleeves you ALREADY own")
print("=" * 90)
sleeves = pd.DataFrame({a: snap.frame[a].pct_change() for a in card.universe.assets}).dropna()
fp = pv.factor_fingerprint(primary.returns, sleeves, rf_daily=rf)
print(f"   R-squared            : {fp['r_squared']:.4f}")
print(f"   alpha (annualised)   : {fp['alpha_ann']:+.2%}")
print(f"   alpha t-stat (HAC)   : {fp['alpha_t_hac']:+.2f}    p = {fp['alpha_p_hac']:.3f}")
print("   loadings:")
for k, v in fp["loadings"].items():
    print(f"      {k:<32}{v:+.3f}   (t = {fp['t_stats_hac'][k]:+.1f})")

print("\n" + "=" * 90)
print("C. ORTHOGONALITY -- how different is this from what we can already run?")
print("=" * 90)
sim = pv.signal_similarity(primary.returns, {r.name: r.returns for r in runset.all_results()
                                             if r.name != primary.name})
print(sim.round(3).to_string(index=False))

print("\n" + "=" * 90)
print("D. INCREMENTAL IR -- the actual promotion criterion")
print("=" * 90)
print(pv.incremental_ir(primary.returns, book.returns, bench.returns,
                        weights=(0.05, 0.10, 0.20, 0.35), rf_daily=rf).round(4).to_string(index=False))

print("\n" + "=" * 90); print("E. MANDATE + CAPACITY")
print("=" * 90)
m_ok = pv.mandate_check(primary, allow_cash=False, max_cash=0.0)
m_bad = pv.mandate_check(runset.primary, allow_cash=False, max_cash=0.0)
print(f"   mandate variant  : passes={m_ok['passes']}, max cash {m_ok['max_cash']:.0%}")
print(f"   faithful variant : passes={m_bad['passes']}, max cash {m_bad['max_cash']:.0%}  <- un-runnable for you")
cap = pv.turnover_capacity(primary, aum_inr_cr=1000.0, adv_inr_cr=300.0)
print(f"   turnover {cap['annual_turnover']:.0%}/yr, Rs{cap['notional_per_rebalance_inr_cr']:,.0f}cr "
      f"per rebalance, {cap['days_to_execute_rebalance']:.1f} days to execute at Rs1,000cr AUM")'''))

cells.append(md(r"""### Read panel A, then panel B. That contrast is the whole lesson.

**Panel A** says the strategy earns **+4.9% a year of alpha** over NIFTY 500, with an information
ratio of 0.50. On its own, that is a fundable number. It is the number that ends up on a slide.

**Panel B** controls for the five factor sleeves you already have access to. The alpha becomes
**+0.17% a year with a t-statistic of 0.15** (p = 0.88). R² is **0.95**.

The +4.9% was never alpha. It was **factor beta you were not accounting for.** The strategy is a
0.97-correlated repackaging of an equal-weight sleeve basket — with 147% turnover instead of 5%.

**Panel D closes it.** Blending it into the book at 5%, 10%, 20% or 35% makes the information
ratio **worse at every single size**. Not marginal. Negative throughout.

A standalone Sharpe of 0.44 looked survivable. This is where it dies — and that is precisely why
orthogonality and incremental IR are *gating* criteria in this system rather than footnotes in an
appendix.

### Relevance to your fund, stated plainly

You run long-only NIFTY500. Your existing exposure already contains momentum, quality, value and
low-volatility tilts, whether or not you named them. **Any new strategy built from those same
sleeves is, by construction, mostly something you already own.**

The pipeline's Step 07 is the part you should reuse most aggressively — including on strategies
you did not get from papers. Run your *current* book through the factor fingerprint. The result
is frequently uncomfortable and always useful.

### The mandate trap

Note panel E. The faithful version of this paper's strategy sits in **100% cash** through much of
2008–09. That is excellent risk control and completely outside a long-only fully-invested mandate.

The pipeline runs **both** variants — the faithful one (does the mechanism work?) and the
mandate-compliant one (may we actually run it?) — and the mandate variant governs the decision.
Conflating those two is how an un-runnable strategy reaches an IC deck."""))

cells.append(md(r"""---
# SECTION 8 — Gates, the ladder, and the library

## Why `promising` / `rejected` was replaced

The board document called this out specifically. "Promising" is a word that lets a dead idea
survive in someone's notebook for a year. The ladder replaces it with rungs that have criteria:

```
REPLICATED > INDIA_VALIDATED > ROBUST > ORTHOGONAL > PORTFOLIO_USEFUL > PAPER_TRADED > LIVE
```

Three rules make it mean something:

1. **Strictly ordered.** A strategy sits at the highest rung whose criteria pass *and* all lower
   rungs pass. No skipping.
2. **An adaptation can never claim `REPLICATED`.** Different question, different evidence. It is
   marked N/A, not passed.
3. **A rung with no evidence is a fail, not a pass.**"""))

cells.append(code(r'''#@title 8.1 — Gates, ladder and library  { display-mode: "form" }
import os, json
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")

for name in ["report_devanathan_2026_india_factor_adaptation.txt",
             "report_moskowitz_2012_tsmom_india.txt"]:
    path = os.path.join("outputs", name)
    if not os.path.exists(path):
        continue
    txt = open(path).read()
    print("=" * 96); print(name); print("=" * 96)
    start = txt.find("GATE B")
    print(txt[start:start + 3200] if start > 0 else txt[-3000:])
    print()

from ros.governance.library import StrategyLibrary
lib = StrategyLibrary("outputs/library")
print("=" * 96); print("THE RESEARCH LIBRARY -- negative results are assets"); print("=" * 96)
for e in lib.summary():
    print(f"   {e['card']:<44} {str(e['outcome']):<18} stopped at: {e['stopped_at']}")

print("""
Every entry stores its snapshot hash, engine code hash, gate records, factor
fingerprint and lessons. Two capabilities this unlocks:

  * DUPLICATE DETECTION -- the same experiment cannot be re-run and reported
    as new, which is how a firm accidentally p-hacks itself across months.
  * FINGERPRINT SIMILARITY -- cosine similarity over factor loadings finds the
    same bet submitted under a different name.""")'''))

cells.append(md(r"""---
# SECTION 9 — The agentic layer

## Everything so far used regex. This section replaces that with Claude.

Steps 01 and 02 have been doing string matching over extracted PDF text. It works, and you saw
exactly how badly it fails:

| What the regex version did | What it missed |
|---|---|
| `extract_tables()` found **0 tables** | The results tables that define replication targets |
| Read equations as `wspy +wagg +wgld` | Every subscript and superscript |
| Read figure labels as `nruter evitalumuC` | Which pages are figures vs results |
| Harvested 64 targets, 22 conflicting | That they sit on **7 different accounting bases** |
| Matched keywords | The admission that a parameter was chosen by searching the sample |

That last one matters most. **No regex will ever find "after a modest search over various
values"** — and that phrase is the single most important fact about the paper's headline number,
because it means the result is *selected* rather than estimated.

## The rule this layer follows

> **Models interpret. Code computes. Humans allocate.**

Seven agents plus a cheap triage pass. Every one sits on the side of that line where a model is
genuinely better than code — reading documents, judging whether two things mean the same thing,
spotting a pattern in a diagnostic table. **Arithmetic, portfolio accounting, statistical
inference and both gates stay deterministic.**

| Agent | Model | Step | Job |
|---|---|---|---|
| `TriageAgent` | Haiku 4.5 | 00 | Screen a stack of papers cheaply |
| `PaperAnalystAgent` | Opus 5 | 01 | Read the rendered PDF natively |
| `CardDrafterAgent` | Opus 5 | 02 | Draft the Strategy Card |
| `AmbiguityCriticAgent` | Opus 5 | 02 | **Attack the draft** |
| `DataMapperAgent` | Opus 5 | 03 | Semantic data matching (advisory) |
| `TemplateMatcherAgent` | Opus 5 | 05 | Pick an allocator — never write code |
| `ResultsCriticAgent` | Opus 5 | 06/07 | Attack our own backtest |
| `LibrarianAgent` | Opus 5 | 08 | Recall past failures |

Triage runs on the cheapest model deliberately: a wrong answer costs one unnecessary full read,
and the next stage catches it. That is what makes twenty papers a day affordable."""))

cells.append(md(r"""### 9.1 — Choose how to run this

Two modes, and **replay works with no API key at all**:

- **`replay`** — serves recorded fixtures for this paper. Runs the whole orchestration, schema
  validation, gate logic and review-queue routing with zero API calls. This is what the test
  suite uses, and what CI would use.
- **`live`** — real Claude calls. Needs a key from
  [console.anthropic.com](https://console.anthropic.com/settings/keys).

Start with `replay` to see the shape. Switch to `live` when you want it to read a paper it has
never seen."""))

cells.append(code(r'''#@title 9.1 — Mode and credentials  { display-mode: "form" }
MODE = "replay"  #@param ["replay", "live"]

import os
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")

if MODE == "live":
    from getpass import getpass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # getpass keeps the key out of the notebook's saved output.
        os.environ["ANTHROPIC_API_KEY"] = getpass("Anthropic API key (sk-ant-...): ").strip()
    import anthropic
    try:
        anthropic.Anthropic().models.retrieve("claude-opus-5")
        print("credential OK -- live Claude calls enabled")
    except Exception as e:
        print(f"credential check failed: {type(e).__name__}: {e}")
        print("Falling back to replay mode.")
        MODE = "replay"

FIXTURES = "ros/agents/fixtures/devanathan_2026.json" if MODE == "replay" else None
print(f"\nmode: {MODE}")
if MODE == "replay":
    print("No API calls will be made. The fixtures are hand-written from a real")
    print("reading of this paper, and a MISSING fixture is an error -- the replay")
    print("transport refuses to invent an answer, so a green run here means the")
    print("orchestration genuinely worked rather than a stub returning something.")'''))

cells.append(code(r'''#@title 9.2 — Run the agentic interpretation (steps 01-03)  { display-mode: "form" }
import os, subprocess, sys
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")

cmd = [sys.executable, "run_agentic.py",
       "--pdf", "docs/devanathan_2026_simple_dynamic_sbg.pdf",
       "--mode", "adaptation"]
if FIXTURES:
    cmd += ["--replay", FIXTURES]

r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
if r.returncode != 0:
    print(r.stderr[-3000:])'''))

cells.append(md(r"""### What just happened, and why it differs from Section 2

**The accounting-base problem is solved, not merely detected.** The regex version found 22
conflicting targets and could only tell you *that* they conflicted. The analyst returns each
result's **basis** — pre-tax nominal, inflation-adjusted, post-tax bracket B4 — so the card can
be pinned to exactly one. That turns an unfalsifiable replication test into a falsifiable one.

**In-sample selection is caught from prose.** Both admissions surfaced: the 11-day window chosen
"after a modest search", and the 7% target asserted then swept 19 ways. Both inflate the trial
budget for the deflated Sharpe. A keyword scan finds neither.

**Equations are read off the rendered page**, restated in plain notation, each tagged with the
card field it governs and a confidence rating. Anything below high confidence goes straight to
the human queue.

**The critic caught the drafter.** Two real omissions that would have survived a single pass:
the draft ignored the paper's own parameter sweep when counting trials, and it silently
implemented the *weaker* of the paper's two forecasts while presenting it as the headline
mechanism. That is the case for pairing a drafter with an adversary.

And the run ends at **Gate A with a human review queue** — 14 items on this paper. Nothing was
decided by a model."""))

cells.append(code(r'''#@title 9.3 — Hand the agent-drafted card to the deterministic engine  { display-mode: "form" }
# The point of the whole design: the model's card re-enters through the SAME
# front door a human-written card uses. There is no privileged path into the engine.
import glob, os, subprocess, sys
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")

cards = sorted(glob.glob("outputs/agentic/*.yaml"))
if not cards:
    raise SystemExit("No agent-drafted card found -- run cell 9.2 first.")
card = cards[0]
print(f"agent-drafted card: {card}\n")

from ros.cards.schema import load_card, CardValidationError
try:
    c = load_card(card)
    print(f"validates against the schema: YES   fingerprint {c.fingerprint()}")
    print(f"  mode={c.intent.mode}  template={c.signal.template}  "
          f"assets={len(c.universe.assets)}  lag={c.signal.lag_days}d")
except CardValidationError as e:
    raise SystemExit(f"card does NOT validate -- the pipeline refuses it:\n{e}")

print("\nrunning the unchanged deterministic pipeline on it...\n")
r = subprocess.run([sys.executable, "run_pipeline.py", "--card", card, "--n-boot", "1000"],
                   capture_output=True, text=True)
out = r.stdout
for marker in ["PERFORMANCE (net of costs", "PROMOTION LADDER"]:
    i = out.find(marker)
    if i > 0:
        print(out[i:i + 1900]); print()'''))

cells.append(md(r"""### What keeps the model subordinate

This is the part worth scrutinising, because it separates a governed pipeline from a demo. Six
mechanisms, all in code rather than in prompts:

1. **Every agent output is a Pydantic instance**, never prose that something downstream parses.
   If the model cannot produce a valid instance, the call fails loudly.
2. **The drafted card re-enters through `load_card()`** — the same function the human path uses.
   You just watched that in 9.3. An invalid card stops the run.
3. **`assess()` still owns the feasibility verdict.** The data mapper's opinion is recorded
   *beside* it, and where the two disagree, the disagreement is surfaced — never resolved in the
   model's favour.
4. **The agent layer cannot write to the data registry.** A model claiming a series exists does
   not make it exist. There is a test for exactly this.
5. **Backtesting, bootstrap, deflated Sharpe and both gates never see an LLM.** Every number in
   the report above was computed deterministically.
6. **Non-determinism is contained by freezing the card and hashing *that*.** The card is
   re-derivable even though the model is not — which is the property the engine needs.

The one thing this layer deliberately does **not** do is write engine code. `TemplateMatcherAgent`
selects from eight audited allocators and, when none fits, writes a ~30-line specification for a
human engineer. A model that generates allocators produces the one artefact nobody can review at
twenty papers a day.

Whether that line is correct or merely conservative is the biggest open question in the design."""))

cells.append(code(r'''#@title 9.4 — Prove the containment  { display-mode: "form" }
import os, subprocess, sys
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")

# The safety tests, not the prose-quality ones. Each answers one question:
# can a wrong or hostile model output reach something that matters?
SAFETY = [
    "test_replay_transport_refuses_to_invent_a_missing_answer",
    "test_replay_transport_rejects_a_malformed_answer",
    "test_invalid_drafted_card_is_caught_and_queued_not_executed",
    "test_agent_cannot_widen_data_access",
    "test_disagreement_between_model_and_gate_is_surfaced_not_resolved",
    "test_no_agent_returns_free_text",
    "test_system_prompt_states_the_paper_is_data",
]
r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_agents.py",
                    "-v", "-k", " or ".join(SAFETY)],
                   capture_output=True, text=True)
for line in r.stdout.splitlines():
    if any(k in line for k in ("PASSED", "FAILED", "passed", "failed")):
        print(line)

print("""
The first two matter most for trusting this notebook: the replay transport
REFUSES to invent a missing fixture and REJECTS a malformed one. A green run
in replay mode therefore means the orchestration really worked, rather than a
stub quietly returning something plausible.""")'''))

cells.append(md(r"""---
# SECTION 10 — Running YOUR next paper

## The whole point: a new paper is a YAML file

Edit the cell below and run it. No engine changes, no new modules, no engineering ticket.

The `template` field must name a registered allocator. Today those are:

| Template | What it does |
|---|---|
| `fixed_weight` | constant target weights |
| `vol_target` | dilute a fixed mix with cash to cap volatility |
| `markowitz_l1` | mean-variance with a hard risk cap and an l1 leash to a strategic mix |
| `ts_momentum` | long-only trend following, inverse-vol sized |
| `inverse_vol` | naive risk parity |
| `equal_risk_contribution` | risk parity proper |
| `min_variance` | long-only minimum variance |
| `equal_weight` | 1/N |

If your paper needs a mechanism none of these covers, the extension is deliberately small: a
~30-line allocator class decorated with `@template("your_name")` in `ros/engine/templates.py`,
plus possibly a ~5-line `@primitive(...)` function. **Nothing else changes** — not the accounting
engine, not the validation suite, not the gates, not the ladder.

The third card in this notebook exists to prove exactly that. Supporting a long-short futures
trend-following paper cost one template and one branch."""))

cells.append(code(r'''#@title 10.1 — Write and run your own card  { display-mode: "form" }
import os, subprocess, sys
if not os.path.isdir("/content/research_os"):
    raise SystemExit("SETUP INCOMPLETE -- run cells 0.1, 0.2 and 0.3 first, in order.")
os.chdir("/content/research_os")

MY_CARD = r"""
card_version: "1.0"

paper:
  id: my_first_paper
  title: "Low-volatility tilt within NIFTY500"
  authors: [Your Name]
  date: "2026-01-01"

intent:
  mode: adaptation                      # 'replication' only if running the paper's OWN data
  rationale: First card written by me, to learn the workflow.
  transferred_mechanism: >
    Static overweight to the low-volatility and quality sleeves versus an
    equal-weight sleeve basket, rebalanced annually.
  broken_assumptions:
    - "POINT-IN-TIME: NSE factor indices are backfilled; price-return only."

universe:
  description: NIFTY500 factor sleeves.
  asset_class: equity
  geography: IN
  assets:
    - NIFTY500 MOMENTUM 50
    - NIFTY500 QUALITY 50
    - NIFTY500 VALUE 50
    - NIFTY500 LOW VOLATILITY 50
    - NIFTY ALPHA 50
  benchmark: NIFTY 500
  cash_asset: CASH_PROXY

signal:
  name: low_vol_quality_tilt
  template: fixed_weight                # <- pick from the table above
  lookback_days: 21
  lag_days: 1                           # NSE closes publish after the close
  params:
    weights:
      NIFTY500 MOMENTUM 50: 0.10
      NIFTY500 QUALITY 50: 0.30
      NIFTY500 VALUE 50: 0.10
      NIFTY500 LOW VOLATILITY 50: 0.40
      NIFTY ALPHA 50: 0.10

portfolio:
  rebalance: annual
  long_only: true
  allow_cash: false
  mandate_allow_cash: false             # your fund is fully invested
  start: "2005-04-01"
  end: "2026-05-29"

costs:
  spread_bps: 30.0                      # NOT 5bp. Indian sleeve rotation costs more.

data_requirements:
  - {name: "NIFTY500 MOMENTUM 50", kind: price, mandatory: true, purpose: sleeve}
  - {name: "NIFTY500 QUALITY 50", kind: price, mandatory: true, purpose: sleeve}
  - {name: "NIFTY500 VALUE 50", kind: price, mandatory: true, purpose: sleeve}
  - {name: "NIFTY500 LOW VOLATILITY 50", kind: price, mandatory: true, purpose: sleeve}
  - {name: "NIFTY ALPHA 50", kind: price, mandatory: true, purpose: sleeve}
  - {name: "NIFTY 500", kind: price, mandatory: true, purpose: benchmark}
  - {name: "NIFTY500 MULTIFACTOR MQVLV 50", kind: price, mandatory: true, purpose: free competitor}

ambiguities:
  - field: signal.params.weights
    issue: The tilt sizes are my choice, not derived from anything.
    resolution: Treated as one configuration; counted in the trial budget.
    confidence: low
    material: true

replication_targets: []

benchmark_templates:
  - {name: "Equal-weight sleeves", template: fixed_weight, params: {weights: equal}, rebalance: annual}

n_configs_tried: 1
notes: Must beat NIFTY 500 AND the free MQVLV index after 30bp, or it is not interesting.
"""

with open("cards/my_first_paper.yaml", "w") as fh:
    fh.write(MY_CARD)

# Validate BEFORE running -- the schema refuses unknown keys and unresolved ambiguities.
from ros.cards.schema import load_card, CardValidationError
try:
    c = load_card("cards/my_first_paper.yaml")
    print(f"card valid: {c.paper.id}   fingerprint {c.fingerprint()}\n")
except CardValidationError as e:
    print(e); raise SystemExit("fix the card above, then re-run")

r = subprocess.run([sys.executable, "run_pipeline.py", "--card", "cards/my_first_paper.yaml",
                    "--n-boot", "1000"], capture_output=True, text=True)
out = r.stdout
for marker in ["STEP 05  |  BUILD", "PROMOTION LADDER"]:
    i = out.find(marker)
    if i > 0:
        print(out[i:i + 2600]); print()'''))

cells.append(md(r"""---
# SECTION 11 — What this means for you

## The three findings that should change what you do

**1. Your factor indices are backfilled, and that limits what you can ever claim.**

Every series starts at exactly 1000.00. NSE chose the sleeve construction rules with the benefit
of hindsight. This is not a data-cleaning problem — it is baked into the series. Any result
derived from pre-launch history is a mechanism test, not evidence for live deployment.

*Action:* re-run the interesting cards on **post-launch-only** history. It will shorten your
sample brutally. That shortening is itself the finding.

**2. Your benchmark comparison is probably flattering you.**

The adapted strategy showed +4.9% alpha versus NIFTY 500 and +0.17% versus the factor sleeves.
Both numbers are correct. Only the second one is meaningful.

*Action:* run your **current live book** through `factor_fingerprint()`. If R² against the sleeves
is 0.9+ and the alpha t-stat is below 2, you are being paid for factor beta you could buy in an
index. That is worth knowing before a client asks.

**3. The right benchmark is not NIFTY 500. It is MQVLV.**

Every strategy in this notebook beat NIFTY 500. None beat the NIFTY500 MULTIFACTOR MQVLV 50 index,
which has **zero turnover and costs a management fee**.

*Action:* make "does it beat the free off-the-shelf multifactor index, after costs" the standing
first question for any systematic proposal. It is a much harder bar than NIFTY 500 and it is the
honest one.

## Two data purchases, in priority order

1. **An Indian T-bill / MIBOR series.** The cash-rate sweep moves Sharpe by **0.19** across a
   plausible 4–8% range. Right now that uncertainty sits underneath every cash-holding result.
2. **Total-return versions of these indices.** Price-return costs you 1.3–1.5% a year of
   dividends and biases every equity-versus-cash comparison.

Both are procurement, not research. Both are cheap relative to what they de-risk.

## The one mechanism worth revisiting

Both adaptations cut maximum drawdown substantially **when allowed to hold cash** — 53% and 38%
versus 64% for NIFTY 500. The trend-following variant's 38% is genuinely impressive.

But it is the *cash* doing the work, and your mandate forbids cash.

*Action:* if the fund ever obtains a cash allowance or a hedging overlay, **re-card that specific
question** — as a drawdown-control proposal, not a return proposal. The return question is now
answered and stored in the library. Do not let anyone re-open it without new data.

## What to do with the pipeline itself

- **Run it at volume.** The screening cost is now minutes per paper. The board asked for 20
  papers a day; the constraint is card-writing, not compute.
- **Point it at papers about Indian equities**, cross-sectional ones, on data you actually hold.
  The feasibility gate will kill most foreign papers instantly, which is the correct outcome and
  costs you nothing.
- **Keep the library.** Its value compounds. The duplicate detection and fingerprint similarity
  are what stop the same idea arriving three times under three names.
- **Treat Step 07 as the real gate.** Steps 01–06 establish that a result exists. Step 07
  establishes whether it is worth owning. Most things die there, and they should.

---

### One caveat about my own work

`n_configs_tried` on each card is a floor that I set by hand, and the deflated Sharpe depends on
it. I kept it honest by having the library count **distinct** configurations across sessions — so
re-running an identical card cannot inflate the threshold, but running a genuinely different
variant does, even months later.

If you or a colleague start iterating on these cards, **that number must go up.** If it does not,
the deflation understates the selection bias and the system will start telling you what you want
to hear. That is the one manual discipline this design still requires."""))

nb = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {
        "colab": {"provenance": [], "toc_visible": True,
                  "name": "Research_OS_Colab.ipynb"},
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python"},
    },
    "cells": cells,
}
os.makedirs("colab", exist_ok=True)
with open(OUT, "w") as fh:
    json.dump(nb, fh, indent=1)
print(f"wrote {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB, {len(cells)} cells)")
