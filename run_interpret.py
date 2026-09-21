#!/usr/bin/env python3
"""Stages 00 through GATE A for one paper. NO MARKET DATA REQUIRED.

    python run_interpret.py --pdf docs/papers/<your_paper>.pdf

Why this exists as its own entry point
--------------------------------------
The expensive half of this pipeline needs data; the half that decides WHAT to
test does not. Reading a paper, choosing the Indian universe, reconstructing the
strategy and assembling the Gate A queue touch no price series at all -- they
need the PDF and the fund's declared capabilities, both of which are already
here.

Separating them means you can take any paper, today, and find out within minutes
which universe it belongs on, what the strategy actually is, and exactly which
data you would have to supply to test it. That last answer is the point: you buy
data because a specific paper needs it, not in the hope that something will.

This script therefore treats a data shortfall as a NORMAL OUTCOME, not a
failure. run_pipeline.py halts at Step 03 when mandatory data is missing, which
is right for a run that intends to produce numbers. Here, "you need these three
series" IS the deliverable.

There is no default paper. See ros/papers.py for why.
"""
from __future__ import annotations

import argparse
import os
import sys

# Pin the streams before anything prints: a paper's Greek letters reach the
# report, and Windows' cp1252 console would otherwise kill the run mid-page.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

from ros.cards.extract import (classify_document, detect_target_conflicts,
                               extract_document, parse_text_tables,
                               propose_replication_targets, summarize)
from ros.cards.schema import (CardValidationError, load_card,
                              reconcile_data_plan)
from ros.data.firm_registry import build_firm_registry
from ros.data.intake import MANIFEST, describe_shortfall, extend_registry
from ros.data.universes import INDIAN_UNIVERSES, check_translation
from ros.feasibility import UNAVAILABLE, assess
from ros.cards.completeness import assess as card_completeness
from ros.governance.gates import (extraction_facts, gate_a,
                                  gate_a_document, gate_a_summary)
from ros.india_requirements import derive
from ros.papers import artifact_paths, require_paper


def hr(ch="="):
    print(ch * 100)


def head(title):
    print()
    hr()
    print(title)
    hr()


def para(text, indent="  "):
    for line in text.rstrip().splitlines():
        print(indent + line if line.strip() else "")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read a paper and take it to Gate A. No market data needed.")
    ap.add_argument("--pdf", help="The paper to analyse. Required; there is no default.")
    ap.add_argument("--card", help="Card to use. Defaults to cards/<paper-slug>.yaml")
    ap.add_argument("--outdir", default="outputs/interpretation")
    args = ap.parse_args()

    paper = require_paper(args.pdf)          # exits with instructions if absent
    paths = artifact_paths(paper, args.outdir)
    card_path = args.card or paths["card"]

    hr()
    print(f"  PAPER TO GATE A   |   {paper.path}")
    print(f"  sha256 {paper.short_sha}   {paper.size:,} bytes   slug: {paper.slug}")
    print("  No market data is read by this script.")
    hr()

    # ---- STEP 01a : deterministic extraction ---------------------------
    # The reader's own findings become FACTS on the card display below. What
    # it saw about itself -- page counts, math density, every candidate field
    # it matched -- is plumbing and is no longer printed.
    doc = extract_document(paper.path)
    tables = parse_text_tables(doc)
    shape = classify_document(doc, len(tables))
    conflicts = detect_target_conflicts(propose_replication_targets(tables))
    extra = extraction_facts(doc, conflicts, shape)

    # BEFORE anything else, and regardless of whether a card exists yet: is
    # this a paper at all? A deck read by an obliging model becomes a strategy
    # that was never in the document. Stripping the reader's self-description
    # briefly took this with it.
    if not shape.looks_like_a_paper:
        print()
        print(shape.render())
        print()
        print("    " + "!" * 76)
        print("    STOPPING HERE. Confirm this is the document you meant.")
        print("    " + "!" * 76)

    # ---- STEP 01b : has the model read it yet? -------------------------
    have_analysis = os.path.exists(paths["analysis"])
    if not os.path.exists(card_path):
        print()
        print("    NOTHING HAS BEEN INTERPRETED FOR THIS PAPER YET.")
        print()
        print("    The universe and the strategy come from reading the paper, which")
        print("    is a model's job, not this script's. In Claude Code, run:")
        print()
        print(f"        /ingest {paper.path}")
        print(f"        /draft-card {paths['analysis']} adaptation")
        print(f"        /critique-card {card_path} {paper.path}")
        print()
        print("    Or run the whole chain and stop at the gate:")
        print()
        print(f"        /paper {paper.path}")
        print()
        print("    Then re-run this script to see the Gate A checklist.")
        hr()
        return 2

    # ---- STEP 02/02c : the card, the universe, the strategy ------------
    try:
        card = load_card(card_path)
    except CardValidationError as e:
        head("THE CARD DOES NOT VALIDATE")
        para(str(e))
        print("\n    Fix the card and re-run. A card that does not validate cannot")
        print("    reach Gate A, which is the schema doing its job.")
        hr()
        return 1

    registry = build_firm_registry()
    registry, supplied = extend_registry(registry)
    if supplied:
        head("DATA SUPPLIED AT INTAKE")
        for name in supplied:
            cap = registry.get(name)
            print(f"    {name:<40} kind={cap.kind:<14} pit={cap.pit_status}")

    # STEP 02c and STEP 02 used to print the universe and the strategy HERE,
    # above the gate header -- so the two most consequential Stage 01 calls read
    # as preamble to the thing being signed, and then appeared again inside the
    # gate. Both are now sections 1 and 2 of the Gate A document, once.
    tc = None
    if card.universe_translation is not None:
        tc = check_translation(card.universe_translation, registry,
                               long_only=card.portfolio.long_only)

    # ---- GATE A ---------------------------------------------------------
    # ONE document: the card, rendered once, in the order a human decides in.
    # It used to be a brief quoting some sections, then plan() and asks()
    # printing those same sections again below, then a criteria list carrying
    # the same text a third time as "evidence".
    feas = assess(card, registry)
    ga = gate_a(card, feas, doc.quality, translation_check=tc)
    india = derive(card, tc)

    comp = card_completeness(card)
    kw = dict(translation_check=tc, feasibility=feas, india=india,
              completeness=comp)
    head("GATE A  |  HUMAN INTERPRETATION CONTROL")
    para(gate_a_summary(card, ga, extra=extra, **kw), indent="")
    print()
    para(gate_a_document(card, ga, extra=extra, **kw), indent="")

    # ---- what would you have to supply? --------------------------------
    shortfall = list(tc.missing) if tc else []
    shortfall += [r.requirement for r in feas.resolutions
                  if r.status == UNAVAILABLE and r.requirement not in shortfall]

    # The dataset, securities, run, asks and the India non-negotiables are all
    # inside the document above, each exactly once. This is the FULL India
    # derivation, which also carries the advisory requirements.
    head("WHAT IT TAKES TO RUN THIS IN INDIA  (full derivation)")
    para(india.render(), indent="")

    # The data position is on the card display above, under DATA. What belongs
    # here is only what to do next.
    head("WHAT THIS PAPER WOULD NEED FROM YOU")
    if shortfall:
        para(describe_shortfall(shortfall), indent="")
    else:
        # The data position itself is on the card display above, under DATA --
        # including which minimum-viable fields are standing on proxies. What
        # belongs here is only what to do next.
        print("    Every series named on this card resolves. See DATA above for")
        print("    which of them are the real thing and which are standing in.")
        print()
        print(f"        python run_pipeline.py --card {card_path}")

    head("NOTHING ABOVE HAS BEEN DECIDED")
    print("    Gate A produces a checklist. The decision belongs to a named human,")
    print("    and no part of this script assigns one.")
    print()
    print(f"    Queue for the reviewer : {paths['gate_a']}")
    print(f"    Record the reading     : python -m ros.interpretation record "
          f"--stage gate_a \\")
    print(f"                                 --output {paths['gate_a']} "
          f"--operator \"<name>\" --input {paper.path}")
    hr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
