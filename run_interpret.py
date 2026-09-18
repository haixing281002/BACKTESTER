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
from ros.cards.schema import CardValidationError, load_card
from ros.data.firm_registry import build_firm_registry
from ros.data.intake import MANIFEST, describe_shortfall, extend_registry
from ros.data.universes import INDIAN_UNIVERSES, check_translation
from ros.feasibility import UNAVAILABLE, assess
from ros.cards.completeness import assess as card_completeness
from ros.governance.gates import gate_a, gate_a_brief
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
    head("STEP 01a  |  WHAT THE DETERMINISTIC READER CAN SEE")
    doc = extract_document(paper.path)
    para(summarize(doc))
    tables = parse_text_tables(doc)

    # Before anything else: is this a paper at all? Stage 00 screens a paper for
    # relevance and assumes it is reading one. A deck or a factsheet read by an
    # obliging model becomes a strategy that was never in the document.
    shape = classify_document(doc, len(tables))
    print()
    print(shape.render())
    if not shape.looks_like_a_paper:
        print()
        print("    " + "!" * 76)
        print("    STOPPING HERE. Confirm this is the document you meant.")
        print("    " + "!" * 76)

    props = propose_replication_targets(tables)
    conflicts = detect_target_conflicts(props)
    print()
    print(f"    text-geometry tables recovered : {len(tables)}")
    print(f"    candidate replication targets  : {len(props)}")
    print(f"    CONFLICTING targets            : {len(conflicts)}")
    for c in conflicts[:6]:
        vals = ", ".join(f"{v:.3g}" for v in c["values"])
        print(f"      ! {c['portfolio']:<20} {c['metric']:<8} = [{vals}]  pages {c['pages']}")
    if conflicts:
        print("      -> The same metric is reported on several accounting bases.")
        print("         Harvesting all of them yields a replication test that can")
        print("         never fail. A human pins ONE basis at Gate A.")
    print()
    print("    This is the FLOOR, not the reading. The reader finds zero tables in")
    print("    many LaTeX papers and mangles every equation. Stage 01 proper is a")
    print("    model reading the rendered pages, which is the next step below.")

    # ---- STEP 01b : has the model read it yet? -------------------------
    head("STEP 01b  |  INTERPRETATION")
    have_analysis = os.path.exists(paths["analysis"])
    print(f"    analysis : {paths['analysis']}"
          f"   {'FOUND' if have_analysis else 'not yet written'}")
    print(f"    card     : {card_path}"
          f"   {'FOUND' if os.path.exists(card_path) else 'not yet written'}")

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

    head("STEP 02c  |  UNIVERSE  --  where should this be tested?")
    tc = None
    if card.universe_translation is not None:
        tc = check_translation(card.universe_translation, registry,
                               long_only=card.portfolio.long_only)
        para(tc.render(), indent="")
    else:
        print("    NO UNIVERSE TRANSLATION ON THIS CARD.")
        print(f"    {len(INDIAN_UNIVERSES)} Indian universes are catalogued and none")
        print("    has been chosen. Add a `universe_translation:` section, or run")
        print(f"    /ingest {paper.path} to have it read from the paper.")

    head("STEP 02  |  STRATEGY  --  what exactly is it?")
    st = card.strategy
    if st is None:
        print("    NO STRATEGY RECONSTRUCTION ON THIS CARD.")
        print("    The card names a template but never states what the paper's")
        print("    strategy IS in terms a second person could implement from.")
    else:
        print(f"    name        : {st.signal_name or '(unnamed)'}")
        print(f"    definition  : {' '.join(st.signal_definition.split())}")
        print(f"    type        : "
              f"{'cross-sectional (ranks securities)' if st.cross_sectional else 'time-series (times one stream)'}")
        for label, val in (("formation", st.formation_rule),
                           ("weighting", st.weighting_rule)):
            if val:
                print(f"    {label:<12}: {' '.join(val.split())}")
        print(f"    rebalance   : {st.rebalance_frequency or card.portfolio.rebalance}"
              f"   holding: {st.holding_period or 'n/a'}")
        print(f"    inputs      : {', '.join(st.inputs_required) or '(none listed)'}")
        if st.is_long_short:
            print("    LONG-SHORT SOURCE -- this fund cannot short.")
            print(f"    adaptation  : {' '.join(st.long_only_adaptation.split()) or 'NOT STATED'}")
            print("    A DIFFERENT strategy from the paper's. Never scored against it.")
        for k in st.constraints:
            print(f"    constraint  : {' '.join(k.split())}")
        print(f"    engine      : {st.engine_template or '(unset)'}"
              f"   confidence: {st.confidence}   pages: {st.evidence_pages or 'none cited'}")
        if st.engine_template == "NEEDS_NEW_TEMPLATE":
            print("    NO REGISTERED TEMPLATE FITS. A human implements this first:")
            print(f"      {' '.join(st.template_gap.split())}")

    # ---- GATE A ---------------------------------------------------------
    # The nine fields first. A reviewer who reads only this should be able to
    # say "that is not the strategy I expected" -- cheap here, expensive later.
    print()
    print(card.at_a_glance())
    print()
    print(card_completeness(card).render(only_missing=True))

    feas = assess(card, registry)
    ga = gate_a(card, feas, doc.quality, translation_check=tc)

    # The brief FIRST, the audit trail after. A reviewer gets five minutes; they
    # should be spent on the judgement calls and what the asks cost, not on
    # reading twenty-four green rows to discover that nothing tripped.
    head("GATE A  |  HUMAN INTERPRETATION CONTROL")
    para(gate_a_brief(card, ga, translation_check=tc), indent="")
    print()
    print(card.convertibility_block())
    print()
    para("  " + "-" * 96, indent="")
    para("  THE FULL CHECKLIST -- the audit trail behind the brief above",
         indent="")
    para("  " + "-" * 96, indent="")
    para(ga.render(), indent="")

    # ---- what would you have to supply? --------------------------------
    shortfall = list(tc.missing) if tc else []
    shortfall += [r.requirement for r in feas.resolutions
                  if r.status == UNAVAILABLE and r.requirement not in shortfall]

    head("STAGE 02  |  THE PLAN GATE A VERIFIES")
    para(card.plan(), indent="")

    head("WHAT THE MODEL IS ASKING YOU FOR")
    para(card.asks(), indent="")

    head("WHAT IT TAKES TO RUN THIS IN INDIA")
    para(derive(card, tc).render(), indent="")

    head("WHAT THIS PAPER WOULD NEED FROM YOU")
    if not shortfall:
        print("    Nothing. Every series this card needs is already held, so it can")
        print("    go straight to a full run:")
        print()
        print(f"        python run_pipeline.py --card {card_path}")
    else:
        print(f"    {len(shortfall)} series are missing. That is the deliverable of")
        print("    this script, not a failure: it says precisely what to buy or")
        print("    supply so this specific paper becomes testable.")
        print()
        para(describe_shortfall(shortfall), indent="")

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
