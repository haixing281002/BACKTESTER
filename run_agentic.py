#!/usr/bin/env python3
"""Agentic front half of the pipeline: paper in, validated Strategy Card proposal out.

    python run_agentic.py --pdf docs/paper.pdf --mode adaptation
    python run_agentic.py --pdf docs/paper.pdf --mode adaptation \
        --replay ros/agents/fixtures/devanathan_2026.json     # no API key needed

It stops at Gate A. A human reviews the queue, then the deterministic pipeline
runs unchanged:

    python run_pipeline.py --card outputs/agentic/<card>.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from ros.agents.orchestrator import AgenticPipeline, reconcile_feasibility
from ros.cards.schema import load_card
from ros.data.firm_registry import build_firm_registry
from ros.feasibility import assess


def _fixtures(path: Optional[str]) -> Optional[Dict[str, Any]]:
    return json.load(open(path)) if path else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the agentic interpretation stages")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--mode", choices=["replication", "adaptation"], default="adaptation")
    ap.add_argument("--outdir", default="outputs/agentic")
    ap.add_argument("--replay", help="JSON fixture file; runs with no API calls")
    ap.add_argument("--card-name")
    args = ap.parse_args(argv)

    if not os.path.exists(args.pdf) and not args.replay:
        print(f"paper not found: {args.pdf}", file=sys.stderr)
        return 1

    mode = "replay" if args.replay else "auto"
    pipe = AgenticPipeline(mode=mode, fixtures=_fixtures(args.replay))
    transport = type(pipe.transport).__name__

    print("=" * 96)
    print(f"AGENTIC INTERPRETATION  |  transport: {transport}  |  mode: {args.mode}")
    print("=" * 96)

    res = pipe.run_interpretation(args.pdf, args.mode, args.outdir, args.card_name)
    a, p, c, m, t = (res.analysis, res.proposal, res.critique,
                     res.data_mapping, res.template_match)

    print(f"\nSTEP 01  PAPER ANALYSIS   (confidence: {a.overall_confidence.value})")
    print(f"  {a.title}  ({a.year})")
    print(f"  mechanism      : {a.core_mechanism}")
    print(f"  universe       : {a.asset_class} / {a.geography} / {a.assets_studied}")
    print(f"  holds cash     : {a.holds_cash}   long-only: {a.long_only}   "
          f"costs assumed: {a.costs_assumed_bps}bp")
    print(f"  data needed    : {len(a.data_requirements)} series")
    print(f"  results found  : {len(a.reported_results)} "
          f"({sum(1 for r in a.reported_results if r.is_headline)} headline)")
    print(f"  ACCOUNTING BASES ({len(a.accounting_bases_present)}):")
    for b in a.accounting_bases_present:
        print(f"    - {b}")
    print("  IN-SAMPLE SELECTION ADMITTED:")
    for h in a.hyperparameters_selected_in_sample:
        print(f"    - {h}")
    print("  EQUATIONS READ FROM THE RENDERED PAGE:")
    for eq in a.equations:
        print(f"    [{eq.confidence.value:>6}] {eq.label} (p{eq.evidence_page}) -> governs {eq.governs}")
        print(f"             {eq.plain_statement}")

    print(f"\nSTEP 02  CARD DRAFT + ADVERSARIAL CRITIQUE")
    print(f"  mode            : {p.mode}")
    print(f"  template chosen : {t.template or 'NONE -- needs a new one'}")
    print(f"  n_configs (paper): {p.n_configs_estimate}")
    print(f"  card validates  : {res.card_valid}")
    if not res.card_valid:
        for e in res.card_errors:
            print(f"    X {e}")
    print(f"  critic findings : {len(c.findings)} "
          f"({sum(1 for f in c.findings if f.materiality.value == 'high')} material)")
    for f in c.findings:
        if f.materiality.value == "high":
            print(f"    [{f.materiality.value}] {f.field}")
            print(f"        issue  : {f.issue}")
            print(f"        matters: {f.why_it_matters}")
    if c.missed_by_first_pass:
        print("  CRITIC CAUGHT THE DRAFTER WAVING THINGS THROUGH:")
        for x in c.missed_by_first_pass:
            print(f"    ! {x}")

    print(f"\nSTEP 03  DATA MAPPING (advisory) vs DETERMINISTIC GATE (binding)")
    if res.card_valid:
        card = load_card(res.card_path)
        det = assess(card, build_firm_registry())
        rec = reconcile_feasibility(det, m)
        print(f"  deterministic verdict : {det.verdict}")
        print(f"  model/gate disagreements: {rec['n_disagreements']}")
        for d in rec["disagreements"]:
            print(f"    ? {d['requirement']}: gate={d['deterministic']} model={d['llm']}")
            print(f"      {d['llm_reasoning']}")
        print(f"  {rec['note']}")
    print("  PROCUREMENT SUGGESTIONS (ranked):")
    for s in m.procurement_suggestions:
        print(f"    - {s}")

    print(f"\nGATE A  |  HUMAN REVIEW QUEUE ({len(res.human_review_queue)} items)")
    print("  Nothing below was decided by a model. These are the decisions a human owns.")
    for i, q in enumerate(res.human_review_queue, 1):
        print(f"  {i:>2}. {q}")

    usage = res.ledger.totals()
    print(f"\nLLM USAGE")
    print(f"  calls {usage['n_calls']}   in {usage['input_tokens']:,}   "
          f"out {usage['output_tokens']:,}   cache-read {usage['cache_read_tokens']:,}   "
          f"cache-hit-rate {usage['cache_hit_rate']:.0%}")
    if usage["errors"]:
        print(f"  errors: {usage['errors']}")

    os.makedirs(args.outdir, exist_ok=True)
    trace = os.path.join(args.outdir, "agentic_trace.json")
    with open(trace, "w") as fh:
        json.dump(res.to_dict(), fh, indent=2, default=str)
    print(f"\n  card written  : {res.card_path}")
    print(f"  trace written : {trace}")
    print(f"\n  NEXT: a human clears the queue above, then\n"
          f"    python run_pipeline.py --card {res.card_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
