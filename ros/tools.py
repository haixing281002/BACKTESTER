# Quant AI Researcher
"""Named, read-only entry points for the stage commands (.claude/commands/*.md) and Lightyear's headless sessions.

A headless session reads an untrusted paper, so it may not run arbitrary Python (`python -c ...`). Every snippet the
stage commands used is a subcommand here instead, and the session's allowlist names `python -m ros.tools` only.

    python -m ros.tools templates | primitives
    python -m ros.tools card-validate <card>          valid + fingerprint + plain summary
    python -m ros.tools card-summary <card>           plain summary + absolute card path (Gate A)
    python -m ros.tools card-completeness <card> [--only-missing]
    python -m ros.tools card-review <card>            at a glance, plan, asks, convertibility, completeness
    python -m ros.tools gate-a-view <card>            Gate A: at a glance, plan, missing items, convertibility, asks
    python -m ros.tools translation-check <card>
    python -m ros.tools data-plan <card>              data plan reconciled with the feasibility verdict
    python -m ros.tools feasibility <card>
    python -m ros.tools india-requirements <card>
    python -m ros.tools universe-proposal [--min-names N] [--cap-segment S] [--sector S] [--min-history-years Y]
                                          [--no-cross-section] [--in-mandate]
    python -m ros.tools diversification [--k 8] [--exclude "NIFTY 500"]
    python -m ros.tools library-summary | library-all
    python -m ros.tools paper-ask | paper-identity <pdf>
"""
import argparse
import json
import os
import sys

from ros.data import sources


def _card(path):
    from ros.cards.schema import load_card
    return load_card(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ros.tools", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("templates", "primitives", "library-summary", "library-all", "paper-ask"):
        sub.add_parser(name)
    for name in ("card-validate", "card-summary", "card-review", "gate-a-view", "translation-check", "data-plan",
                 "feasibility", "india-requirements"):
        sub.add_parser(name).add_argument("card")
    p = sub.add_parser("card-completeness")
    p.add_argument("card")
    p.add_argument("--only-missing", action="store_true")
    p = sub.add_parser("universe-proposal")
    p.add_argument("--min-names", type=int, default=100)
    p.add_argument("--cap-segment", default="all")
    p.add_argument("--sector", default=None)
    p.add_argument("--min-history-years", type=float, default=10.0)
    p.add_argument("--no-cross-section", action="store_true")
    p.add_argument("--in-mandate", action="store_true")
    p = sub.add_parser("diversification")
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--exclude", action="append", default=None, help="column to leave out (default: NIFTY 500)")
    sub.add_parser("paper-identity").add_argument("pdf")
    a = ap.parse_args(argv)

    if a.cmd == "templates":
        from ros.engine.templates import list_templates
        print(list_templates())
    elif a.cmd == "primitives":
        from ros.engine.primitives import list_primitives
        print(list_primitives())
    elif a.cmd == "card-validate":
        c = _card(a.card)
        print("valid", c.fingerprint())
        print(c.plain_summary())
    elif a.cmd == "card-summary":
        print(_card(a.card).plain_summary())
        print()
        print("CARD FILE:", os.path.abspath(a.card))
    elif a.cmd == "card-completeness":
        from ros.cards.completeness import assess
        print(assess(_card(a.card)).render(only_missing=a.only_missing))
    elif a.cmd == "card-review":
        from ros.cards.completeness import assess
        c = _card(a.card)
        print(c.at_a_glance())
        print(c.plan())
        print(c.asks())
        print(c.convertibility_block())
        print(assess(c).render())
    elif a.cmd == "gate-a-view":
        from ros.cards.completeness import assess
        c = _card(a.card)
        print(c.at_a_glance())
        print(c.plan())
        print(assess(c).render(only_missing=True))
        print(c.convertibility_block())
        print(c.asks())
    elif a.cmd == "translation-check":
        from ros.data.firm_registry import build_firm_registry
        from ros.data.intake import extend_registry
        from ros.data.universes import check_translation
        c = _card(a.card)
        r, _ = extend_registry(build_firm_registry())
        print(check_translation(c.universe_translation, r, long_only=c.portfolio.long_only).render())
    elif a.cmd == "data-plan":
        from ros.cards.schema import reconcile_data_plan
        from ros.data.firm_registry import build_firm_registry
        from ros.feasibility import assess
        c = _card(a.card)
        print(reconcile_data_plan(c, assess(c, build_firm_registry())))
    elif a.cmd == "feasibility":
        from ros.data.firm_registry import build_firm_registry
        from ros.feasibility import assess
        print(assess(_card(a.card), build_firm_registry()).render())
    elif a.cmd == "india-requirements":
        from ros.india_requirements import derive
        print(derive(_card(a.card)).render())
    elif a.cmd == "universe-proposal":
        from ros.data.universes import MechanismRequirements, render_proposal
        print(render_proposal(MechanismRequirements(
            needs_cross_section=not a.no_cross_section, min_names=a.min_names, cap_segment=a.cap_segment,
            sector=a.sector, min_history_years=a.min_history_years, must_be_in_mandate=a.in_mandate)))
    elif a.cmd == "diversification":
        from ros.data.diversification import (
            diversification_report,
            greedy_diverse_subset,
        )
        from ros.data.loaders import load_nse_workbook_combined
        frame, _ = load_nse_workbook_combined(sources.NSE_INDEX_WORKBOOK)
        exclude = set(a.exclude or ["NIFTY 500"])
        best = greedy_diverse_subset(frame, [c for c in frame.columns if c not in exclude], k=a.k)
        print(diversification_report(frame, best).render())
    elif a.cmd in ("library-summary", "library-all"):
        from ros.governance.library import StrategyLibrary
        lib = StrategyLibrary(os.path.join("outputs", "library"))
        if a.cmd == "library-summary":
            for e in lib.summary():
                print(e)
        else:
            for e in lib.all():
                print(json.dumps({k: e.get(k) for k in ("entry_id", "card_id", "mode", "outcome", "attained_rung",
                                                         "stopped_at", "lessons")}, indent=1))
    elif a.cmd == "paper-ask":
        from ros.papers import ask_for_a_paper
        print(ask_for_a_paper())
    elif a.cmd == "paper-identity":
        from ros.papers import require_paper
        p = require_paper(a.pdf)
        print(f"{p.path}\n  {p.size:,} bytes   sha256 {p.short_sha}   slug: {p.slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
