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
