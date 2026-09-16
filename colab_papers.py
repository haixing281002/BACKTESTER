"""Analyse YOUR OWN paper instead of the bundled baseline. No LLM, no API key.

In Colab, after the bootstrap has run:

    from colab_papers import upload_pdf, analyse, compare

    p = upload_pdf()        # pick any .pdf
    analyse(p)              # what the deterministic reader finds in it
    compare(p)              # your paper vs the baseline, side by side

The dataset does not change. Your NIFTY factor indices stay exactly as they are;
only the PAPER changes. This is deliberate: it isolates one variable, so what you
see is the difference the document makes, not the data.

WHAT THIS CAN AND CANNOT DO WITHOUT AN LLM
------------------------------------------
Step 01 (ingest) is fully deterministic and runs on any PDF: extraction quality,
recovered results tables, candidate fields, conflicting replication targets.
That is what these functions do.

Step 02 (writing the Strategy Card) is where the pipeline currently needs either
a human or a model. The deterministic reader finds *candidates* -- it cannot
decide that "11 days" is a volatility window rather than a sample period, or that
a Sharpe of 1.08 is pre-tax while 0.99 is inflation-adjusted. Seeing exactly
where the deterministic reader runs out of road is the point of this module, and
the best possible preparation for deciding what to hand an LLM.
"""
from __future__ import annotations

import os
import shutil
from typing import Optional

BASELINE = "docs/devanathan_2026_simple_dynamic_sbg.pdf"
PAPER_DIR = "docs/papers"


def upload_pdf() -> Optional[str]:
    """Upload one PDF and return its path.

    Interactive, so it does not work under Runtime > Run all. Run it on its own.
    """
    os.makedirs(PAPER_DIR, exist_ok=True)
    try:
        from google.colab import files
    except ImportError:
        raise SystemExit(
            "upload_pdf() only works inside Colab. Elsewhere, pass a path: "
            "analyse('/path/to/paper.pdf')")

    print("Pick a .pdf file.\n")
    got = files.upload()
    for name in got:
        if not name.lower().endswith(".pdf"):
            print(f"  ignored {name} (not a PDF)")
            continue
        dst = os.path.join(PAPER_DIR, os.path.basename(name))
        shutil.move(name, dst)
        print(f"  saved -> {dst}  ({os.path.getsize(dst):,} bytes)")
        return dst
    print("Nothing uploaded. If you used Run all, the widget is skipped -- "
          "run this cell alone.")
    return None


def _read(pdf: str):
    from ros.cards.extract import (detect_target_conflicts, extract_document,
                                   parse_text_tables, propose_replication_targets)
    doc = extract_document(pdf)
    tables = parse_text_tables(doc)
    props = propose_replication_targets(tables)
    return doc, tables, props, detect_target_conflicts(props)


def _uniq(doc, kind, n=6):
    seen, out = set(), []
    for h in doc.hits_of(kind):
        k = h.value.lower()
        if k not in seen:
            seen.add(k)
            out.append(f"{h.value} (p{h.page})")
        if len(out) >= n:
            break
    return out


def analyse(pdf: str = BASELINE):
    """Run the deterministic Step 01 reader over one PDF and explain what it found."""
    if not os.path.exists(pdf):
        cand = os.path.join(PAPER_DIR, os.path.basename(pdf))
        if not os.path.exists(cand):
            raise SystemExit(f"not found: {pdf}")
        pdf = cand

    doc, tables, props, conflicts = _read(pdf)
    q = doc.quality

    print("=" * 78)
    print(f"  STEP 01 -- INGEST (deterministic; no model was called)")
    print(f"  {pdf}")
    print("=" * 78)
    print(f"\n  sha256        : {doc.sha256[:32]}")
    print(f"  pages         : {q.n_pages}     characters: {q.n_chars:,}")
    print(f"  scanned       : {q.is_scanned}")
    print(f"  math density  : {q.mean_math_density:.1%} of lines carry mathematics")
    print(f"  figure pages  : {q.reversed_pages or 'none'}  (rotated text = unreadable)")

    if q.warnings:
        print("\n  EXTRACTION WARNINGS")
        for w in q.warnings:
            print(f"    ! {w}")

    print(f"\n  RESULTS TABLES RECOVERED : {len(tables)}")
    print(f"  CANDIDATE TARGETS        : {len(props)}")
    print(f"  CONFLICTING TARGETS      : {len(conflicts)}")
    if tables:
        t = max(tables, key=lambda x: len(x["rows"]))
        print(f"\n  largest table (page {t['page']}, header: {(t['header'] or '?')[:56]!r})")
        for lbl, vals in list(t["rows"].items())[:5]:
            print(f"    {lbl[:28]:<28} {['%.3g' % v for v in vals[:6]]}")

    print("\n  CANDIDATE FIELDS (regex scanners, page-anchored)")
    for kind in ("ticker", "benchmark", "rebalance", "lookback", "target_vol",
                 "cost_bps", "constraint", "data_source", "code_url", "sharpe"):
        vals = _uniq(doc, kind, 4)
        print(f"    {kind:<13}: {', '.join(vals) if vals else '-- none found --'}")

    # The honest boundary. This is the whole reason to run this before adding an LLM.
    print("\n" + "-" * 78)
    print("  WHERE THE DETERMINISTIC READER STOPS")
    print("-" * 78)
    blockers = []
    if q.is_scanned:
        blockers.append("The file is images. Nothing can be read without OCR.")
    if not tables:
        blockers.append("No results table recovered -- there is nothing to hold a "
                        "replication to. Results may live only in figures.")
    if conflicts:
        blockers.append(f"{len(conflicts)} metrics appear with more than one value. The "
                        "reader cannot tell which accounting basis each belongs to, so "
                        "every replication target is ambiguous.")
    if q.mean_math_density > 0.05:
        blockers.append("Equations are mangled by text extraction, so no card field "
                        "derived from a formula can be trusted from this output.")
    if not _uniq(doc, "ticker", 1):
        blockers.append("No instruments identified -- the universe would have to be "
                        "read out of prose.")
    for b in blockers:
        print(f"    - {b}")
    if not blockers:
        print("    Nothing blocking. Unusually clean.")
    print("""
    Everything above is a CANDIDATE, not a decision. The reader found the number
    11 on page 7; it cannot tell you that 11 is a volatility window rather than a
    sample length. That judgement is Step 02, and today it needs either a human
    writing the Strategy Card by hand, or the LLM layer reading the rendered page.
""")
    return doc


def compare(pdf: str, baseline: str = BASELINE):
    """Your paper against the bundled baseline, side by side.

    The comparison is the useful part: it shows how much of what the pipeline
    achieved on the baseline was the pipeline, and how much was that paper being
    unusually well behaved.
    """
    import pandas as pd

    rows = []
    for label, path in (("BASELINE (Devanathan)", baseline), ("YOUR PAPER", pdf)):
        if not os.path.exists(path):
            cand = os.path.join(PAPER_DIR, os.path.basename(path))
            path = cand if os.path.exists(cand) else path
        if not os.path.exists(path):
            print(f"skipping {label}: not found ({path})")
            continue
        doc, tables, props, conflicts = _read(path)
        q = doc.quality
        rows.append({
            "": label,
            "file": os.path.basename(path)[:34],
            "pages": q.n_pages,
            "chars": q.n_chars,
            "scanned": q.is_scanned,
            "math%": round(q.mean_math_density * 100, 1),
            "tables": len(tables),
            "targets": len(props),
            "conflicts": len(conflicts),
            "code?": bool(doc.hits_of("code_url")),
            "tickers": len({h.value for h in doc.hits_of("ticker")}),
        })

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))
    print("""
  HOW TO READ IT

    tables    0 means no results table was recovered, so a replication has no
              target to hit. The baseline gives 19; most papers give fewer.
    conflicts the same metric reported at several values. High is not a parser
              bug -- it is the paper reporting on several accounting bases, and
              it is the single thing a regex reader cannot resolve.
    code?     True means the paper publishes replication code. It is the
              strongest signal that a replication is actually feasible.
    math%     high means extracted equations are unreliable and a human must
              check them against the rendered page.

  If your paper scores worse than the baseline on tables and tickers, that is
  normal. The baseline is a well-structured arXiv paper with published code --
  close to the best case. What the pipeline did with it is an upper bound, not
  a typical result.
""")
    return df


# ---------------------------------------------------------------------------
# Step 02 without an LLM: turn a paper into a runnable Strategy Card skeleton.
# ---------------------------------------------------------------------------
def _hits(doc, kind):
    """Raw (value, page) pairs for a scanner, most frequent first."""
    from collections import Counter
    c = Counter()
    page = {}
    for h in doc.hits_of(kind):
        v = h.value.strip()
        c[v] += 1
        page.setdefault(v, h.page)
    return [(v, page[v]) for v, _ in c.most_common()]


def _first_num(doc, kind, lo, hi, default):
    """First scanner hit that parses as a number inside a plausible range."""
    for v, p in _hits(doc, kind):
        try:
            x = float(str(v).replace("%", "").strip())
        except ValueError:
            continue
        if lo <= x <= hi:
            return x, p
    return default, None


def _guess_template(doc):
    """Pick a registered allocator by what the paper talks about.

    Deliberately crude and deliberately visible: the guess is written into the
    card with the evidence next to it, so a human overrules it in one line
    rather than trusting it.
    """
    txt = doc.text().lower()
    scores = {
        "markowitz_l1": sum(txt.count(k) for k in
                            ("mean-variance", "mean variance", "markowitz",
                             "convex optimi", "efficient frontier")),
        "vol_target": sum(txt.count(k) for k in
                          ("volatility target", "vol target", "volatility control",
                           "volatility-managed", "risk control")),
        "ts_momentum": sum(txt.count(k) for k in
                           ("time series momentum", "time-series momentum",
                            "trend following", "trend-following", "moving average")),
        "min_variance": txt.count("minimum variance") + txt.count("minimum-variance"),
        "equal_risk_contribution": txt.count("risk parity") + txt.count("equal risk"),
        "inverse_vol": txt.count("inverse volatility") + txt.count("inverse-volatility"),
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "fixed_weight", scores, "no mechanism keywords found -- defaulting to a static tilt"
    return best, scores, f"'{best}' scored highest on mechanism keywords"


def _title(doc, fallback):
    for line in doc.page_text(1).splitlines():
        s = line.strip()
        if 12 < len(s) < 160 and not s.lower().startswith(("abstract", "http", "arxiv")):
            return s
    return fallback


def draft_card(pdf: str, out: Optional[str] = None,
               template: Optional[str] = None,
               target_vol: Optional[float] = None,
               spread_bps: float = 30.0) -> str:
    """Write a RUNNABLE Strategy Card skeleton from any paper. No LLM.

    Every field the scanners guessed is written with the page it came from, so
    the card is a starting point you correct rather than a result you trust.
    The dataset is fixed to your NIFTY sleeves: the paper supplies the MECHANISM,
    your data supplies the universe. That is what makes an arbitrary paper
    testable on your book at all.
    """
    import hashlib
    import re

    if not os.path.exists(pdf):
        cand = os.path.join(PAPER_DIR, os.path.basename(pdf))
        if not os.path.exists(cand):
            raise SystemExit(f"not found: {pdf}")
        pdf = cand

    doc, tables, props, conflicts = _read(pdf)
    stem = re.sub(r"[^a-z0-9]+", "_", os.path.basename(pdf).lower().replace(".pdf", "")).strip("_")[:48]
    out = out or f"cards/{stem}_adaptation.yaml"
    os.makedirs(os.path.dirname(out), exist_ok=True)

    tmpl, scores, why = _guess_template(doc)
    if template:
        tmpl, why = template, "template supplied by you, overriding the keyword guess"

    lb, lb_p = _first_num(doc, "lookback", 5, 300, 63)
    tv, tv_p = _first_num(doc, "target_vol", 1, 40, 18)
    if target_vol is not None:
        tv, tv_p = target_vol * 100, None
    paper_cost, cost_p = _first_num(doc, "cost_bps", 0.1, 200, None)
    rb = "monthly"
    for v, _ in _hits(doc, "rebalance"):
        lv = v.lower()
        if lv in ("monthly", "quarterly", "annual", "annually", "weekly", "daily"):
            rb = {"annually": "annual"}.get(lv, lv)
            break

    def ev(p):
        return f"found on p{p}" if p else "not found in the paper -- default used"

    needs_alpha = tmpl in ("markowitz_l1", "ts_momentum")
    params = [f"    target_vol: {tv / 100:.2f}"]
    if tmpl == "markowitz_l1":
        params = ["    strategic_weights: equal",
                  f"    target_vol: {tv / 100:.2f}",
                  "    l1_budget: 1.0",
                  f"    spread_bps: {spread_bps}",
                  "    alpha_source: ewma",
                  "    alpha_halflife: 252",
                  "    alpha_scale: 21"]
    elif tmpl == "ts_momentum":
        params = [f"    target_vol: {tv / 100:.2f}",
                  "    vol_weighted: true",
                  "    min_positive: 1",
                  "    alpha_source: momentum",
                  "    alpha_window: 252",
                  "    alpha_skip: 21"]
    elif tmpl == "vol_target":
        params = ["    weights: equal", f"    target_vol: {tv / 100:.2f}"]
    elif tmpl == "fixed_weight":
        params = ["    weights: equal"]

    yaml_text = f"""card_version: "1.0"

# ===========================================================================
#  AUTO-DRAFTED from {os.path.basename(pdf)} by colab_papers.draft_card()
#  No model was used. Every guess below is a regex scanner hit with the page
#  it came from. It RUNS as-is so you can see a result immediately, but each
#  line marked CONFIRM is a guess, not a finding.
#
#  Template keyword scores: {scores}
#  -> {why}
# ===========================================================================

paper:
  id: {stem}
  title: "{_title(doc, stem).replace('"', "'")[:120]}"
  authors: []
  source_file: {pdf}
  source_sha256: "{doc.sha256[:16]}"

intent:
  mode: adaptation
  rationale: >
    Auto-drafted skeleton. The paper supplies the MECHANISM; the fund's own
    NIFTY500 factor sleeves supply the universe. Nothing here is scored against
    the paper's own numbers.
  transferred_mechanism: >
    CONFIRM: '{tmpl}' was inferred from mechanism keywords, not from reading the
    paper. Replace this with one sentence describing what actually generates the
    excess return, then check the template still fits.
  broken_assumptions:
    - "CONFIRM: the source paper's universe is not ours. Check what its result depends on that our five correlated equity sleeves cannot provide."
    - "POINT-IN-TIME: NSE factor indices are backfilled and price-return only."
    - "MANDATE: this fund is long-only and fully invested; any cash-holding mechanism is out of mandate."

universe:
  description: Five NSE single-factor sleeves from the NIFTY500 universe.
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
  name: {stem}_mechanism
  template: {tmpl}          # CONFIRM -- {why}
  lookback_days: {int(lb)}         # CONFIRM -- {ev(lb_p)}
  lag_days: 1                # NSE closes publish after the close
  description: Auto-drafted from {os.path.basename(pdf)}. Not yet human-verified.
  params:
{chr(10).join(params)}

portfolio:
  rebalance: {rb}            # CONFIRM -- from the paper's own wording
  long_only: true
  max_gross: 1.0
  allow_cash: true
  mandate_allow_cash: false  # the fund is fully invested
  target_vol: {tv / 100:.2f}          # CONFIRM -- {ev(tv_p)}
  start: "2005-04-01"
  end: "2026-05-29"

costs:
  # The paper assumed {f'{paper_cost:g}bp ({ev(cost_p)})' if paper_cost else 'no stated cost'}.
  # We use {spread_bps:g}bp: Indian factor-sleeve rotation costs more than a US ETF.
  spread_bps: {spread_bps}
  cost_model: half_spread

data_requirements:
  - {{name: "NIFTY500 MOMENTUM 50", kind: price, mandatory: true, purpose: sleeve}}
  - {{name: "NIFTY500 QUALITY 50", kind: price, mandatory: true, purpose: sleeve}}
  - {{name: "NIFTY500 VALUE 50", kind: price, mandatory: true, purpose: sleeve}}
  - {{name: "NIFTY500 LOW VOLATILITY 50", kind: price, mandatory: true, purpose: sleeve}}
  - {{name: "NIFTY ALPHA 50", kind: price, mandatory: true, purpose: sleeve}}
  - {{name: "NIFTY 500", kind: price, mandatory: true, purpose: benchmark}}
  - {{name: "NIFTY500 MULTIFACTOR MQVLV 50", kind: price, mandatory: true, purpose: free competitor}}
  - {{name: india_cash_rate, kind: risk_free_rate, mandatory: true, purpose: cash accrual}}

ambiguities:
  - field: signal.template
    issue: >
      The template was inferred from keyword counts, not from reading the paper.
      Keyword scores were {scores}.
    resolution: >
      PROVISIONAL. Runs so you can see a result. Read the paper's method section
      and either confirm '{tmpl}' or pass template= to draft_card().
    confidence: low
    material: true
  - field: signal.lookback_days
    issue: "Lookback taken from a regex hit ({ev(lb_p)}). The scanner cannot tell a volatility window from a sample length."
    resolution: "PROVISIONAL -- confirm against the paper before trusting any result."
    confidence: low
    material: true
  - field: portfolio.target_vol
    issue: "Target volatility taken from a regex hit ({ev(tv_p)}), or defaulted."
    resolution: "PROVISIONAL -- the pipeline sweeps this, so check the sensitivity table."
    confidence: low
    material: true
  - field: data.pit_status
    issue: NSE factor indices are backfilled; construction rules were set knowing the history.
    resolution: Accept for mechanism testing only. No live claim may rest on it.
    confidence: high
    material: true

replication_targets: []

benchmark_templates:
  - {{name: "Equal-weight sleeves", template: fixed_weight, params: {{weights: equal}}, rebalance: annual}}
  - {{name: "Vol-target overlay", template: vol_target, params: {{weights: equal, target_vol: {tv / 100:.2f}}}}}
  - {{name: "Inverse vol", template: inverse_vol, params: {{}}}}

n_configs_tried: 1

notes: >
  Auto-drafted skeleton, not a researched card. The bar is unchanged: it must
  beat NIFTY 500 AND the free MQVLV index after costs, with alpha that survives
  the factor fingerprint.
"""
    with open(out, "w") as fh:
        fh.write(yaml_text)

    from ros.cards.schema import CardValidationError, load_card
    try:
        c = load_card(out)
    except CardValidationError as e:
        raise SystemExit(f"drafted card failed validation -- this is a bug:\n{e}")

    print(f"drafted -> {out}")
    print(f"  template     : {tmpl}   ({why})")
    print(f"  lookback     : {int(lb)}d   {ev(lb_p)}")
    print(f"  target vol   : {tv / 100:.0%}   {ev(tv_p)}")
    print(f"  rebalance    : {rb}")
    print(f"  fingerprint  : {c.fingerprint()}")
    print(f"\n  {len(c.ambiguities)} ambiguities logged, "
          f"{sum(1 for a in c.ambiguities if str(a.confidence).endswith('low'))} at LOW confidence.")
    print("  Open the file and fix the CONFIRM lines before believing any number.")
    return out


def backtest(pdf: str, template: Optional[str] = None, n_boot: int = 1000,
             **kw) -> str:
    """Whole chain on YOUR paper: read it, draft a card, run the backtest.

    No LLM anywhere. The dataset is your NIFTY sleeves throughout, so the only
    thing that changes between papers is the mechanism being tested.
    """
    print("=" * 78)
    print(f"  BACKTESTING YOUR OWN PAPER: {os.path.basename(pdf)}")
    print("=" * 78)
    analyse(pdf)
    print("\n" + "=" * 78)
    print("  STEP 02 -- DRAFTING A STRATEGY CARD (no model used)")
    print("=" * 78)
    card = draft_card(pdf, template=template, **kw)
    print("\n" + "=" * 78)
    print("  STEPS 03-08 -- THE DETERMINISTIC PIPELINE")
    print("=" * 78)
    run(card, n_boot=n_boot)
    return card


def run(card: str, n_boot: int = 2000, show: bool = True):
    """Run the deterministic pipeline on any Strategy Card. No LLM involved."""
    import glob
    import subprocess
    import sys
    if not os.path.exists(card):
        raise SystemExit(f"card not found: {card}\n"
                         f"Available: {sorted(glob.glob('cards/*.yaml'))}")
    r = subprocess.run([sys.executable, "run_pipeline.py", "--card", card,
                        "--n-boot", str(n_boot)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-4000:]); print(r.stderr[-4000:])
        raise SystemExit("pipeline failed -- output above.")
    if show:
        print(r.stdout)
    return r.stdout
