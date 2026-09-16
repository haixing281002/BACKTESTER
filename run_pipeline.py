#!/usr/bin/env python3
"""AI Research Operating System -- pipeline driver.

    python run_pipeline.py --card cards/<card>.yaml

Runs steps 01-08 for ANY Strategy Card. Nothing below is specific to a paper:
strategy construction comes from the card's template + params, benchmarks from its
benchmark_templates, and data from the firm registry + snapshot.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ros.cards.extract import (
    detect_target_conflicts, extract_document, parse_text_tables,
    propose_replication_targets, summarize)
from ros.cards.schema import load_card
from ros.data.firm_registry import build_firm_registry
from ros.data.loaders import audit_frame, load_nse_factor_workbook
from ros.data.snapshot import SnapshotBuilder
from ros.engine.backtest import LookaheadError, assert_causal
from ros.feasibility import assess
from ros.governance.gates import (
    Criterion, evaluate_ladder, gate_a, gate_b, render_ladder)
from ros.governance.library import LibraryEntry, StrategyLibrary, make_entry_id
from ros.runner import align_runs, execute_card
from ros.validation import portfolio as pv
from ros.validation import research as rv
from ros.validation.metrics import (
    ANN, metrics_table, render_table, sharpe_geometric)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)


class Report:
    """Accumulates the run's narrative so it can be printed and saved together."""

    def __init__(self):
        self.lines: List[str] = []

    def h(self, title: str) -> None:
        self.lines += ["", "=" * 100, title, "=" * 100]

    def p(self, text: str = "") -> None:
        self.lines.append(text)

    def block(self, text: str) -> None:
        self.lines.append(str(text))

    def text(self) -> str:
        return "\n".join(self.lines)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(self.text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the research pipeline for a Strategy Card")
    ap.add_argument("--card", required=True)
    ap.add_argument("--data", default="data/raw/Factor_Indices_Historical_Price_Data.xlsx")
    ap.add_argument("--outdir", default="outputs")
    ap.add_argument("--cash-rate", type=float, default=0.06)
    ap.add_argument("--book", default="Equal-weight sleeves",
                    help="name of the run representing the fund's EXISTING book")
    ap.add_argument("--aum-cr", type=float, default=1000.0, help="AUM in INR crore")
    ap.add_argument("--adv-cr", type=float, default=300.0,
                    help="tradable ADV of the sleeve basket, INR crore")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--no-charts", action="store_true")
    # Gate B is a human decision. These flags are how a named person records it;
    # without them the run ends at PENDING and the library says so.
    ap.add_argument("--decision", choices=["APPROVE", "OBSERVE", "FIX", "REJECT"],
                    help="Gate B ruling. Requires --decided-by.")
    ap.add_argument("--decided-by", help="Name of the human who owns this decision.")
    ap.add_argument("--rationale", help="Why. Stored with the decision.")
    args = ap.parse_args(argv)

    R = Report()
    card = load_card(args.card)
    os.makedirs(args.outdir, exist_ok=True)

    R.h(f"AI RESEARCH OPERATING SYSTEM  |  card: {card.paper.id}")
    R.p(f"  title  : {card.paper.title}")
    R.p(f"  mode   : {card.intent.mode.upper()}"
        + (f"   (parent: {card.intent.parent_card})" if card.intent.parent_card else ""))
    R.p(f"  hash   : {card.fingerprint()}")
    R.p(f"  rationale: {' '.join(card.intent.rationale.split())}")

    # ---------------- STEP 01 : INGEST -----------------------------------
    R.h("STEP 01  |  INGEST")
    doc = None
    if card.paper.source_file and os.path.exists(card.paper.source_file):
        doc = extract_document(card.paper.source_file)
        R.block(summarize(doc))
        tables = parse_text_tables(doc)
        props = propose_replication_targets(tables)
        conflicts = detect_target_conflicts(props)
        R.p("")
        R.p(f"  text-geometry tables recovered : {len(tables)}")
        R.p(f"  candidate replication targets  : {len(props)}")
        R.p(f"  CONFLICTING targets            : {len(conflicts)}")
        for c in conflicts[:6]:
            vals = ", ".join(f"{v:.3g}" for v in c["values"])
            R.p(f"    ! {c['portfolio']:<20} {c['metric']:<8} = [{vals}]  pages {c['pages']}")
        if conflicts:
            R.p("    -> The paper reports the same metric on several accounting bases "
                "(pre-tax / inflation-adjusted / post-tax). Harvesting all of them "
                "yields a replication test that can never fail. A human pins ONE basis "
                "at Gate A; the card's targets are pre-pinned to Table 1, page 11.")
    else:
        R.p("  no source PDF attached to this card -- ingestion skipped")

    # ---------------- STEP 02 : STRATEGY CARD ----------------------------
    R.h("STEP 02  |  STRATEGY CARD")
    R.p(f"  template   : {card.signal.template}   rebalance: {card.portfolio.rebalance}   "
        f"lag: {card.signal.lag_days}d   lookback: {card.signal.lookback_days}d")
    R.p(f"  universe   : {len(card.universe.assets)} assets, benchmark {card.universe.benchmark}")
    R.p(f"  costs      : {card.costs.spread_bps:.0f} bps round trip ({card.costs.cost_model})")
    R.p(f"  ambiguities: {len(card.ambiguities)} logged, "
        f"{len(card.unresolved_ambiguities)} unresolved, "
        f"{len(card.material_ambiguities)} material")
    R.p("")
    for a in card.ambiguities:
        R.p(f"  [{a.confidence:>6}] {a.field}"
            + (f"  (p{a.evidence_page})" if a.evidence_page else ""))
        R.p(f"           issue   : {' '.join(a.issue.split())}")
        R.p(f"           resolved: {' '.join(a.resolution.split())}")
    if card.intent.broken_assumptions:
        R.p("")
        R.p("  ASSUMPTIONS THE SOURCE PAPER MAKES THAT DO NOT HOLD HERE:")
        for b in card.intent.broken_assumptions:
            R.p(f"    - {' '.join(b.split())}")

    # ---------------- STEP 03 : DATA FEASIBILITY -------------------------
    registry = build_firm_registry()
    feas = assess(card, registry)
    R.h("STEP 03  |  DATA FEASIBILITY")
    R.block(feas.render())

    ga = gate_a(card, feas, doc.quality if doc else None)
    R.h("GATE A  |  HUMAN INTERPRETATION CONTROL")
    R.block(ga.render())

    if not feas.can_proceed:
        # Mechanically blocked, but the CALL is still a human's: reject the paper,
        # or buy the data. The pipeline must not pre-empt that.
        ga.decision = "PENDING"
        ga.rationale = ("evidence supports REJECT or FIX-DATA; mandatory data unavailable. "
                        "This is a procurement question, not a research question. "
                        "A named human records the decision.")
        R.h("PIPELINE HALTED AT STEP 03 (FAIL FAST)")
        R.p("  No code was written against this card and no backtest was run.")
        R.p("  Blocking requirements:")
        for b in feas.blocking:
            R.p(f"    X {b}")
        R.p("")
        R.p("  This is a SUCCESSFUL outcome for the pipeline: the paper was screened,")
        R.p("  carded, and rejected on data grounds in minutes rather than days.")
        R.p("  The finding is stored so nobody re-derives it.")

        lib = StrategyLibrary(os.path.join(args.outdir, "library"))
        eid = make_entry_id(card.paper.id, card.fingerprint())
        lib.write(LibraryEntry(
            entry_id=eid, card_id=card.paper.id, mode=card.intent.mode,
            created_utc=pd.Timestamp.now('UTC').isoformat(),
            card_fingerprint=card.fingerprint(),
            outcome="FAIL_FAST_DATA", stopped_at="STEP_03_FEASIBILITY",
            gates=[ga.to_dict()],
            headline_metrics={"n_configs_tried": card.n_configs_tried},
            lessons=[f"{b}" for b in feas.blocking],
            reuse_notes=[
                "Reusable if US ETF prices + FRED + Kenneth French data are ever licensed.",
                "The mechanism was carded successfully; only the data is missing.",
                "An adaptation card testing the same mechanism on held data is the cheaper path.",
            ]))
        R.p(f"  library entry: {eid}")
        _finish(R, args, card)
        return 0

    # ---------------- STEP 04 : POINT-IN-TIME SNAPSHOT -------------------
    R.h("STEP 04  |  POINT-IN-TIME DATA + LINEAGE")
    frame, prov = load_nse_factor_workbook(args.data)
    needed = list(dict.fromkeys(
        [a for a in card.universe.assets]
        + ([card.universe.benchmark] if card.universe.benchmark else [])
        + [d.name for d in card.data_requirements
           if d.kind == "price" and d.name in frame.columns]))
    sb = (SnapshotBuilder(f"{card.paper.id}__{card.fingerprint()}",
                          pit_status="backfilled")
          .add_source(frame, prov)
          .restrict(start=card.portfolio.start, end=card.portfolio.end, columns=needed)
          .require_complete(needed))
    for r in feas.resolutions:
        for c in r.caveats:
            sb.add_caveat(f"{r.requirement}: {c}")
        if r.status == "PROXY":
            sb.proxies_used.append(
                {"series": r.resolved_to, "proxy_for": r.requirement, "rationale": r.reason})
    snap = sb.freeze()
    snap.save(os.path.join(args.outdir, "snapshots"))

    R.p(f"  snapshot_id   : {snap.snapshot_id}")
    R.p(f"  content_hash  : {snap.content_hash[:32]}")
    R.p(f"  engine_code   : {snap.engine_code_hash[:32]}")
    R.p(f"  git_commit    : {(snap.git_commit or 'n/a')[:12]}")
    R.p(f"  shape         : {snap.frame.shape}  "
        f"{snap.frame.index.min().date()} -> {snap.frame.index.max().date()}")
    R.p(f"  pit_status    : {snap.pit_status}")
    R.p(f"  verify()      : {snap.verify()}")
    R.p("")
    R.p("  DATA AUDIT:")
    R.block("    " + audit_frame(snap.frame).to_string(index=False).replace("\n", "\n    "))
    if snap.proxies_used:
        R.p("")
        R.p("  PROXIES IN USE (recorded, never silent):")
        for p_ in snap.proxies_used:
            R.p(f"    - {p_['series']} standing in for {p_['proxy_for']}")

    # ---------------- STEP 05 : BUILD + EXECUTE --------------------------
    R.h("STEP 05  |  BUILD + EXECUTE")
    refs = [c for c in ["NIFTY 500", "NIFTY500 MULTIFACTOR MQVLV 50"] if c in snap.frame.columns]
    runset = align_runs(execute_card(card, snap, cash_rate=args.cash_rate,
                                     reference_assets=refs))
    rf = runset.inputs["rf"]
    results = runset.all_results()

    R.p(f"  configurations executed : {runset.n_configs_run}")
    R.p(f"  aligned common start    : {pd.Timestamp(runset.inputs['aligned_start']).date()}")
    R.p("    (all runs truncated to the last first-rebalance date and rebased to 1.0, so a")
    R.p("     252-day EWMA warm-up cannot hand the benchmarks a free year of returns)")
    diag = runset.primary.meta.get("allocator_diagnostics")
    if diag:
        R.p(f"  solver                  : {diag['solves']} solves, "
            f"{diag['solver_failures']} failures")

    R.p("")
    R.p("  LOOK-AHEAD TRIPWIRES (signal[t] vs return[t] and return[t+1]):")
    inp = runset.inputs
    checks = [("alpha", inp.get("alpha")),
              ("sigma_bench", inp.get("sigma_bench"))]
    for nm, sig in checks:
        if sig is None:
            continue
        s = sig.shift(1 + inp["lag_days"])
        if isinstance(s, pd.Series):
            s = pd.DataFrame({c: s for c in inp["returns"].columns})
        try:
            assert_causal(s, inp["returns"], label=nm)
            R.p(f"    PASS  {nm}")
        except LookaheadError as e:
            R.p(f"    FAIL  {e}")
    for lbl, planted in [("planted same-bar leak", inp["returns"]),
                         ("planted next-bar leak", inp["returns"].shift(-1))]:
        try:
            assert_causal(planted, inp["returns"], label=lbl)
            R.p(f"    BROKEN  negative control '{lbl}' was NOT caught")
        except LookaheadError:
            R.p(f"    PASS  negative control '{lbl}' correctly caught")

    tbl = metrics_table(results, rf_daily=rf)
    cols = ["cagr", "vol", "sharpe", "sharpe_conventional", "max_dd", "mean_dd",
            "turnover", "cvar_95_monthly", "hit_rate_monthly"]
    R.p("")
    R.p("  PERFORMANCE (net of costs; 'sharpe' is the paper's geometric definition):")
    R.block("    " + render_table(tbl[cols]).replace("\n", "\n    "))

    # ---------------- STEP 06 : RESEARCH VALIDATION ----------------------
    R.h("STEP 06  |  RESEARCH VALIDATION")
    research: Dict[str, Any] = {}
    primary = runset.mandate if runset.mandate is not None else runset.primary
    R.p(f"  Strategy under test: {primary.name}")
    R.p("  (the mandate-compliant variant governs the decision where one exists)")

    if card.intent.mode == "replication" and card.replication_targets:
        gap = rv.replication_gap(card, tbl)
        R.p("")
        R.p("  REPLICATION GAP vs printed values:")
        R.block("    " + gap.to_string(index=False).replace("\n", "\n    "))
        research["replication_pass_rate"] = float(gap["passed"].mean())
    else:
        R.p("")
        R.p("  REPLICATION GAP: N/A -- this is an ADAPTATION card. It is not scored")
        R.p("  against the source paper's numbers, and it may never claim REPLICATED.")

    sub = rv.subperiod_table(results, rf_daily=rf, n_periods=4, metric="sharpe")
    R.p("")
    R.p("  SHARPE BY SUB-PERIOD (regime dependence):")
    R.block("    " + sub.round(2).to_string().replace("\n", "\n    "))

    splits = rv.walk_forward_split(primary.value.index, n_folds=4, min_train_years=5.0)
    oos = rv.oos_summary(primary, splits, rf_daily=rf)
    if not oos.empty:
        R.p("")
        R.p("  ANCHORED WALK-FORWARD (out-of-sample windows):")
        R.block("    " + oos.round(3).to_string(index=False).replace("\n", "\n    "))
        research["oos_min_sharpe"] = float(oos["sharpe"].min())

    ret_map = {r.name: r.returns for r in results}
    boot = rv.stationary_bootstrap(ret_map, rf_daily=rf, n_boot=args.n_boot,
                                   mean_block=21, baseline=primary.name)
    research["bootstrap"] = boot
    if "intervals" in boot:
        R.p("")
        R.p(f"  STATIONARY BLOCK BOOTSTRAP  ({boot['n_boot']} reps, mean block "
            f"{boot['mean_block']}d, paired draws):")
        rows = [{"portfolio": k,
                 "sharpe_ci95": f"[{v['sharpe'][0]:.2f}, {v['sharpe'][1]:.2f}]",
                 "cagr_ci95": f"[{v['cagr'][0]:.1%}, {v['cagr'][1]:.1%}]",
                 "maxdd_ci95": f"[{v['max_dd'][0]:.1%}, {v['max_dd'][1]:.1%}]"}
                for k, v in boot["intervals"].items()]
        R.block("    " + pd.DataFrame(rows).to_string(index=False).replace("\n", "\n    "))

        key = "paired_sharpe_diff_vs_" + primary.name
        if key in boot:
            R.p("")
            R.p(f"  PAIRED SHARPE DIFFERENCE: ({primary.name}) minus each comparator")
            rows = [{"comparator": k, "mean_diff": f"{v['mean_diff']:+.2f}",
                     "ci95": f"[{v['ci95'][0]:+.2f}, {v['ci95'][1]:+.2f}]",
                     "P(diff<=0)": f"{v['p_not_positive']:.3f}"}
                    for k, v in boot[key].items()]
            dfp = pd.DataFrame(rows)
            R.block("    " + dfp.to_string(index=False).replace("\n", "\n    "))
            worst = max(v["p_not_positive"] for v in boot[key].values())
            research["bootstrap_p_not_positive"] = float(worst)
            R.p(f"    worst-case P(no advantage) across comparators = {worst:.3f}")

    lib = StrategyLibrary(os.path.join(args.outdir, "library"))
    prior = lib.trials_for_family(card.paper.id.split("__")[0],
                                  exclude_fingerprint=card.fingerprint())
    n_trials = max(card.n_configs_tried, runset.n_configs_run) + prior
    dsr = rv.deflated_sharpe(primary.returns, n_trials=n_trials, rf_daily=rf)
    research["deflated_sharpe"] = dsr
    R.p("")
    R.p("  DEFLATED SHARPE RATIO (Bailey & Lopez de Prado):")
    for k in ("sharpe_ann", "n_trials", "selection_threshold_sharpe",
              "deflated_sharpe_prob", "skew", "kurtosis"):
        if k in dsr:
            v = dsr[k]
            R.p(f"    {k:<28}: {v:.4f}" if isinstance(v, float) else f"    {k:<28}: {v}")
    if "interpretation" in dsr:
        R.p(f"    -> {dsr['interpretation']}")
    R.p(f"    trial budget = card({card.n_configs_tried}) + this run({runset.n_configs_run})"
        f" + library history({prior})")

    # ---- sensitivities ----
    run_one = inp["run_one"]
    allow_cash = (card.portfolio.mandate_allow_cash
                  if card.portfolio.mandate_allow_cash is not None
                  else card.portfolio.allow_cash)

    def at_cost(bps: float):
        # The swept spread must also enter the allocator's objective, not just the
        # engine's charge. Otherwise the optimiser keeps trading as if costs were
        # 30bp while being billed 100bp, and the sweep measures the wrong thing.
        pr = dict(card.signal.params or {})
        if "spread_bps" in pr:
            pr["spread_bps"] = bps
        return run_one(card.signal.template, pr, "cost",
                       card.portfolio.rebalance, allow_cash, spread_bps=bps)

    def at_lag(L: int):
        return run_one(card.signal.template, card.signal.params, "lag",
                       card.portfolio.rebalance, allow_cash, lag_days=L)

    cs = rv.cost_sensitivity(at_cost, [0, 5, 15, 30, 50, 75, 100], rf_daily=rf)
    R.p("")
    R.p("  COST SENSITIVITY (breakeven analysis):")
    R.block("    " + cs.round(4).to_string(index=False).replace("\n", "\n    "))

    ls = rv.lag_sensitivity(at_lag, [0, 1, 2, 5, 10], rf_daily=rf)
    R.p("")
    R.p("  IMPLEMENTATION-LAG SENSITIVITY (a real signal decays gently):")
    R.block("    " + ls.round(4).to_string(index=False).replace("\n", "\n    "))

    # target-vol sweep
    sweep_rows = []
    base_params = dict(card.signal.params or {})
    for tv in [0.12, 0.15, 0.18, 0.21, 0.24, 0.26]:
        if "target_vol" not in base_params:
            break
        pr = dict(base_params); pr["target_vol"] = tv
        res = run_one(card.signal.template, pr, f"tv{tv}", card.portfolio.rebalance, allow_cash)
        from ros.validation.metrics import cagr as _c, ann_vol as _v, max_drawdown as _m
        sweep_rows.append({"target_vol": tv, "cagr": _c(res.value), "vol": _v(res.returns),
                           "sharpe": sharpe_geometric(res.value, res.returns, rf),
                           "max_dd": _m(res.value)})
    if sweep_rows:
        R.p("")
        R.p("  TARGET-VOLATILITY SWEEP (how much of the result is this one knob?):")
        R.block("    " + pd.DataFrame(sweep_rows).round(4).to_string(index=False).replace("\n", "\n    "))

    # cash-rate sweep (the declared proxy)
    if any(p_["proxy_for"] == "india_cash_rate" for p_ in snap.proxies_used):
        rows = []
        for cr in [0.04, 0.05, 0.06, 0.07, 0.08]:
            rs2 = align_runs(execute_card(card, snap, cash_rate=cr, reference_assets=[]))
            tgt = rs2.mandate if rs2.mandate is not None else rs2.primary
            rows.append({"cash_rate": cr,
                         "sharpe_primary": sharpe_geometric(
                             rs2.primary.value, rs2.primary.returns, rs2.inputs["rf"]),
                         "sharpe_mandate": sharpe_geometric(
                             tgt.value, tgt.returns, rs2.inputs["rf"])})
        R.p("")
        R.p("  CASH-RATE PROXY SWEEP (the proxy is an assumption, so it gets swept):")
        R.block("    " + pd.DataFrame(rows).round(4).to_string(index=False).replace("\n", "\n    "))

    # ---------------- STEP 07 : PORTFOLIO VALIDATION ---------------------
    R.h("STEP 07  |  PORTFOLIO VALIDATION")
    port: Dict[str, Any] = {}
    bench_name = card.universe.benchmark
    bench = runset.by_name(bench_name)
    book = runset.by_name(args.book)

    if bench is not None:
        br = pv.benchmark_relative(primary.returns, bench.returns, rf_daily=rf)
        port.update(br)
        R.p(f"  VERSUS FUND BENCHMARK ({bench_name}):")
        for k, v in br.items():
            R.p(f"    {k:<22}: {v:.4f}" if isinstance(v, float) else f"    {k:<22}: {v}")

    sleeves = pd.DataFrame({a: snap.frame[a].pct_change() for a in card.universe.assets}).dropna()
    fp = pv.factor_fingerprint(primary.returns, sleeves, rf_daily=rf)
    if "error" not in fp:
        port["alpha_t_hac"] = fp["alpha_t_hac"]
        R.p("")
        R.p("  FACTOR FINGERPRINT (HAC / Newey-West):")
        R.p(f"    R^2                  : {fp['r_squared']:.4f}")
        R.p(f"    alpha (annualised)   : {fp['alpha_ann']:+.2%}")
        R.p(f"    alpha t-stat (HAC)   : {fp['alpha_t_hac']:+.2f}   p = {fp['alpha_p_hac']:.3f}")
        R.p(f"    residual vol         : {fp['residual_vol_ann']:.2%}")
        R.p("    loadings:")
        for k, v in fp["loadings"].items():
            R.p(f"      {k:<32} {v:+.3f}   (t = {fp['t_stats_hac'][k]:+.1f})")

    existing = {r.name: r.returns for r in results if r.name != primary.name}
    sim = pv.signal_similarity(primary.returns, existing)
    if not sim.empty:
        port["max_corr_to_book"] = float(sim["correlation"].max())
        R.p("")
        R.p("  SIGNAL SIMILARITY vs everything the fund can already run:")
        R.block("    " + sim.round(3).to_string(index=False).replace("\n", "\n    "))

    if book is not None and bench is not None:
        iir = pv.incremental_ir(primary.returns, book.returns, bench.returns,
                                weights=(0.05, 0.10, 0.20, 0.35), rf_daily=rf)
        if "error" not in iir.columns:
            port["best_delta_ir"] = float(iir["delta_ir"].max())
            R.p("")
            R.p(f"  INCREMENTAL INFORMATION RATIO (existing book = '{args.book}'):")
            R.block("    " + iir.round(4).to_string(index=False).replace("\n", "\n    "))

    mand = pv.mandate_check(
        primary, long_only=card.portfolio.long_only,
        allow_cash=bool(card.portfolio.mandate_allow_cash
                        if card.portfolio.mandate_allow_cash is not None
                        else card.portfolio.allow_cash),
        max_cash=0.0)
    port["mandate"] = mand
    R.p("")
    R.p("  MANDATE CHECK (run on realised positions, not on the config):")
    R.p(f"    max cash {mand['max_cash']:.1%}   mean cash {mand['mean_cash']:.1%}   "
        f"days in cash {mand['pct_days_holding_cash']:.0%}")
    R.p(f"    passes: {mand['passes']}")
    for v in mand["violations"]:
        R.p(f"    X {v}")
    if runset.mandate is not None:
        m2 = pv.mandate_check(runset.primary, allow_cash=False, max_cash=0.0)
        R.p(f"    (faithful cash-holding variant would violate: {not m2['passes']} -- "
            f"max cash {m2['max_cash']:.0%})")

    cap = pv.turnover_capacity(primary, aum_inr_cr=args.aum_cr, adv_inr_cr=args.adv_cr)
    port["annual_turnover"] = cap["annual_turnover"]
    R.p("")
    R.p(f"  CAPACITY (AUM Rs{args.aum_cr:,.0f}cr, tradable ADV Rs{args.adv_cr:,.0f}cr, "
        f"10% participation):")
    R.p(f"    annual turnover              : {cap['annual_turnover']:.0%}")
    R.p(f"    notional per rebalance       : Rs{cap['notional_per_rebalance_inr_cr']:,.0f} cr")
    R.p(f"    days to execute a rebalance  : {cap['days_to_execute_rebalance']:.1f}")

    # ---------------- GATE B ---------------------------------------------
    gb = gate_b(card, research, port)
    R.h("GATE B  |  INVESTMENT DECISION")
    R.block(gb.render())

    # ---------------- STEP 08 : LADDER + LIBRARY -------------------------
    rungs = _build_ladder(card, research, port, tbl, primary, runset, fp if "error" not in fp else {})
    lad = evaluate_ladder(card, rungs)
    R.h("STEP 08  |  PROMOTION LADDER + STRATEGY LIBRARY")
    R.block(render_ladder(lad))

    # The ladder is mechanical: it reports which criteria passed. The DECISION
    # is not mechanical and is never derived from it. A machine that both scores
    # the evidence and rules on it is not a governed pipeline, whatever its
    # criteria say. So the pipeline states what the evidence supports and stops.
    recommendation = ("PROMOTE" if lad["attained_rung"] in ("PORTFOLIO_USEFUL",
                                                            "PAPER_TRADED", "LIVE_CANDIDATE")
                      else "REJECT" if lad["attained_rung"] is None else "OBSERVE")
    if args.decision:
        if not args.decided_by:
            raise SystemExit("--decision requires --decided-by (a named human owns every decision)")
        gb.decision = args.decision
        gb.rationale = args.rationale or f"recorded by {args.decided_by}"
        outcome = {"APPROVE": "PROMOTED", "OBSERVE": "HELD",
                   "REJECT": "REJECTED", "FIX": "HELD"}[args.decision]
        decided_by = args.decided_by
    else:
        gb.decision = "PENDING"
        outcome = "PENDING_HUMAN"
        decided_by = ""

    R.h("GATE B DECISION")
    R.p(f"  evidence supports : {recommendation}")
    R.p(f"  decision recorded : {gb.decision}"
        + (f"  by {decided_by}" if decided_by else ""))
    if gb.decision == "PENDING":
        R.p("")
        R.p("  NO DECISION HAS BEEN MADE. The pipeline scored the evidence and stopped.")
        R.p("  A named human records the call by re-running with, for example:")
        R.p(f"    python run_pipeline.py --card {args.card} \\")
        R.p(f"        --decision REJECT --decided-by \"N. Ganesh\" --rationale \"...\"")

    eid = make_entry_id(card.paper.id, card.fingerprint())
    entry = LibraryEntry(
        entry_id=eid, card_id=card.paper.id, mode=card.intent.mode,
        created_utc=pd.Timestamp.now('UTC').isoformat(),
        card_fingerprint=card.fingerprint(),
        snapshot_id=snap.snapshot_id, content_hash=snap.content_hash,
        engine_code_hash=snap.engine_code_hash, git_commit=snap.git_commit,
        outcome=outcome, attained_rung=lad["attained_rung"], stopped_at=lad["stopped_at"],
        reviewer=decided_by,
        headline_metrics={
            "strategy": primary.name,
            "n_configs_tried": n_trials,
            **{k: float(tbl.loc[primary.name, k]) for k in
               ["cagr", "vol", "sharpe", "max_dd", "turnover"] if k in tbl.columns},
            "deflated_sharpe_prob": dsr.get("deflated_sharpe_prob"),
            "max_corr_to_book": port.get("max_corr_to_book"),
            "best_delta_ir": port.get("best_delta_ir"),
        },
        factor_fingerprint=fp.get("fingerprint", {}) if isinstance(fp, dict) else {},
        gates=[ga.to_dict(), gb.to_dict()],
        lessons=_lessons(card, research, port, tbl, primary, lad),
        reuse_notes=[
            "Snapshot + code hash stored: this run is re-derivable.",
            f"Factor fingerprint stored for similarity search ({len(fp.get('fingerprint', {}))} loadings).",
        ])
    lib.write(entry)
    R.p("")
    R.p(f"  library entry : {eid}")
    dups = lib.find_duplicate_experiment(card.fingerprint(), exclude=eid)
    if dups:
        R.p(f"  ! this exact experiment has been run {len(dups)} time(s) before; "
            f"the trial budget above already counts them")
    similar = lib.similar_by_fingerprint(entry.factor_fingerprint, threshold=0.90,
                                         exclude=eid)
    if similar:
        R.p(f"  ! {len(similar)} prior entr(ies) share this factor fingerprint (cos >= 0.90):")
        for s_ in similar[:5]:
            R.p(f"      {s_['card_id']}  cos={s_['cosine']}  outcome={s_['outcome']}")

    if not args.no_charts:
        _charts(runset, rf, args.outdir, card.paper.id)
        R.p(f"  charts written to {args.outdir}/charts_{card.paper.id}.png")

    tbl.to_csv(os.path.join(args.outdir, f"metrics_{card.paper.id}.csv"))
    _finish(R, args, card)
    return 0


def _build_ladder(card, research, port, tbl, primary, runset, fp) -> Dict[str, List[Criterion]]:
    """Criteria for each rung. Ordered, strict, evidence-bearing."""
    rungs: Dict[str, List[Criterion]] = {}

    if card.intent.mode == "replication":
        pr = research.get("replication_pass_rate", 0.0)
        rungs["REPLICATED"] = [Criterion(
            "all replication targets within tolerance", pr >= 1.0,
            value=f"{pr:.0%}", threshold="100%",
            evidence="every printed target reproduced on the pinned accounting basis")]

    beat = []
    for nm in ["NIFTY 500", "NIFTY500 MULTIFACTOR MQVLV 50", "Equal-weight sleeves"]:
        if nm in tbl.index and primary.name in tbl.index:
            beat.append((nm, float(tbl.loc[primary.name, "sharpe"]) - float(tbl.loc[nm, "sharpe"])))
    worst_beat = min((d for _, d in beat), default=float("nan"))
    rungs["INDIA_VALIDATED"] = [
        Criterion("runs on held Indian data within mandate",
                  bool(port.get("mandate", {}).get("passes")),
                  evidence="; ".join(port.get("mandate", {}).get("violations", [])) or "clean"),
        Criterion("beats every free alternative the fund already has",
                  bool(np.isfinite(worst_beat)) and worst_beat > 0,
                  value=f"{worst_beat:+.2f}", threshold="> 0 Sharpe",
                  evidence="worst Sharpe margin vs " + ", ".join(n for n, _ in beat)),
    ]

    oos = research.get("oos_min_sharpe")
    dsr = research.get("deflated_sharpe", {}).get("deflated_sharpe_prob")
    rungs["ROBUST"] = [
        Criterion("positive Sharpe in every walk-forward window",
                  oos is not None and oos > 0, value=f"{oos:.2f}" if oos is not None else "n/a",
                  threshold="> 0", evidence="anchored out-of-sample"),
        Criterion("survives selection-bias deflation",
                  dsr is not None and dsr >= 0.95,
                  value=f"{dsr:.2f}" if dsr is not None else "n/a", threshold=">= 0.95",
                  evidence=research.get("deflated_sharpe", {}).get("interpretation", "")),
    ]

    corr = port.get("max_corr_to_book")
    at = port.get("alpha_t_hac")
    rungs["ORTHOGONAL"] = [
        Criterion("differentiated from the existing book",
                  corr is not None and corr <= 0.80,
                  value=f"{corr:.2f}" if corr is not None else "n/a", threshold="<= 0.80",
                  evidence="max correlation to any runnable alternative"),
        Criterion("alpha survives the factor fingerprint",
                  at is not None and abs(at) >= 2.0,
                  value=f"{at:.2f}" if at is not None else "n/a", threshold="|t| >= 2.0",
                  evidence=f"R^2 = {fp.get('r_squared', float('nan')):.2f} against known sleeves"),
    ]

    dir_ = port.get("best_delta_ir")
    rungs["PORTFOLIO_USEFUL"] = [
        Criterion("improves the book's information ratio",
                  dir_ is not None and dir_ >= 0.05,
                  value=f"{dir_:+.3f}" if dir_ is not None else "n/a", threshold=">= +0.05",
                  evidence="best incremental IR across realistic sleeve sizes")]
    return rungs


def _lessons(card, research, port, tbl, primary, lad) -> List[str]:
    out = [f"Stopped at {lad['stopped_at'] or 'completion'}; attained {lad['attained_rung'] or 'nothing'}."]
    if port.get("max_corr_to_book") is not None:
        out.append(f"Max correlation to an already-available alternative: "
                   f"{port['max_corr_to_book']:.2f}.")
    if port.get("alpha_t_hac") is not None:
        out.append(f"Alpha vs factor sleeves: t = {port['alpha_t_hac']:.2f} (HAC).")
    d = research.get("deflated_sharpe", {})
    if "deflated_sharpe_prob" in d:
        out.append(f"Deflated Sharpe P(skill) = {d['deflated_sharpe_prob']:.2f} "
                   f"at {d['n_trials']} trials.")
    for b in card.intent.broken_assumptions[:3]:
        out.append("Source assumption broken: " + " ".join(b.split())[:160])
    return out


def _charts(runset, rf, outdir, tag):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    res = runset.all_results()
    fig, ax = plt.subplots(2, 2, figsize=(16, 10))
    for r in res:
        ax[0, 0].plot(r.value.index, r.value.values, lw=1.2, label=r.name[:36])
    ax[0, 0].set_yscale("log"); ax[0, 0].set_title("Cumulative return (log)")
    ax[0, 0].legend(fontsize=6, loc="upper left"); ax[0, 0].grid(alpha=.3)

    for r in res:
        dd = r.value / r.value.cummax() - 1
        ax[0, 1].plot(dd.index, dd.values, lw=1.0, label=r.name[:36])
    ax[0, 1].set_title("Drawdown"); ax[0, 1].grid(alpha=.3); ax[0, 1].legend(fontsize=6)

    p = runset.primary
    w = p.weights.copy(); w["CASH"] = p.cash_weight
    ax[1, 0].stackplot(w.index, *[w[c].values for c in w.columns],
                       labels=[c[:24] for c in w.columns])
    ax[1, 0].set_title(f"Weights: {p.name[:44]}"); ax[1, 0].legend(fontsize=6, loc="lower left")
    ax[1, 0].set_ylim(0, 1)

    for r in res:
        cy = r.returns.groupby(r.returns.index.year).std() * np.sqrt(252)
        ax[1, 1].plot(cy.index, cy.values, marker="o", ms=3, lw=1, label=r.name[:36])
    ax[1, 1].set_title("Realised calendar-year volatility"); ax[1, 1].grid(alpha=.3)
    ax[1, 1].legend(fontsize=6)

    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"charts_{tag}.png"), dpi=110)
    plt.close(fig)


def _finish(R: Report, args, card):
    path = os.path.join(args.outdir, f"report_{card.paper.id}.txt")
    R.save(path)
    print(R.text())
    print(f"\n[report saved to {path}]")


if __name__ == "__main__":
    sys.exit(main())
