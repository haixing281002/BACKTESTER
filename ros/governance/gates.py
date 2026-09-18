"""Gates A and B, and the promotion ladder.

The board replaced 'promising / rejected' with a governed ladder:

    REPLICATED > INDIA_VALIDATED > ROBUST > ORTHOGONAL > PORTFOLIO_USEFUL
              > PAPER_TRADED > LIVE_CANDIDATE

Rules that make the ladder mean something:
  - rungs are strictly ordered; a strategy sits at the HIGHEST rung whose every
    criterion passes AND all lower rungs pass. No skipping.
  - an adaptation card can never claim REPLICATED. Different question, different
    evidence. It enters at INDIA_VALIDATED.
  - every rung stores its evidence; a rung with no evidence is a fail, not a pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

LADDER = ["REPLICATED", "INDIA_VALIDATED", "ROBUST", "ORTHOGONAL",
          "PORTFOLIO_USEFUL", "PAPER_TRADED", "LIVE_CANDIDATE"]


@dataclass
class Criterion:
    name: str
    passed: bool
    evidence: str = ""
    value: Any = None
    threshold: Any = None
    blocking: bool = True

    def render(self) -> str:
        mark = "PASS" if self.passed else ("FAIL" if self.blocking else "warn")
        val = "" if self.value is None else f"  [{self.value} vs {self.threshold}]"
        return f"    [{mark:>4}] {self.name}{val}" + (f"\n           {self.evidence}" if self.evidence else "")


@dataclass
class GateResult:
    gate: str
    owner: str
    criteria: List[Criterion] = field(default_factory=list)
    decision: str = "PENDING"        # APPROVE | REJECT | FIX | OBSERVE | PENDING
    rationale: str = ""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria if c.blocking)

    @property
    def warnings(self) -> List[Criterion]:
        return [c for c in self.criteria if not c.passed and not c.blocking]

    def render(self) -> str:
        head = f"  {self.gate} (owner: {self.owner}) -> {'PASS' if self.passed else 'BLOCKED'}"
        body = "\n".join(c.render() for c in self.criteria)
        tail = f"\n    decision: {self.decision}" + (f" -- {self.rationale}" if self.rationale else "")
        return head + "\n" + body + tail

    def to_dict(self) -> Dict[str, Any]:
        return {"gate": self.gate, "owner": self.owner, "decision": self.decision,
                "passed": self.passed, "rationale": self.rationale,
                "criteria": [asdict(c) for c in self.criteria]}


def gate_a(card, feasibility, extraction_quality=None,
           translation_check=None) -> GateResult:
    """GATE A -- HUMAN INTERPRETATION CONTROL.

    Owned by the researcher. Confirms we understand the paper before we spend a
    day coding it. Everything here is cheap; everything after it is not.

    Two questions dominate the rest and are asked first: WHICH UNIVERSE will
    this be tested on, and WHAT EXACTLY is the strategy? Both are Stage 01
    interpretation, both are wrong often enough to matter, and both are far
    cheaper to correct here than after a run.
    """
    c: List[Criterion] = []

    c.append(Criterion(
        "card validates against schema", not card.validate(),
        evidence="; ".join(card.validate()) or "schema clean"))

    # ---- what are we testing this on? ------------------------------------
    ut = getattr(card, "universe_translation", None)
    if ut is None:
        c.append(_missing(
            "universe translation recorded", "a source and a target universe",
            "the card does not say which universe the paper studied or which "
            "Indian universe replaces it. Without that, the choice of tickers "
            "is an unrecorded judgement nobody signed for"))
    else:
        c.append(Criterion(
            "universe translation recorded", True,
            value=f"{ut.source_universe} -> {ut.target_universe or '(none)'}",
            evidence=" ".join((ut.rationale or "no rationale given").split())))

        if translation_check is not None:
            tc = translation_check
            c.append(Criterion(
                "source universe is a recorded correspondence",
                tc.recognised_source and not tc.divergences,
                value=("recognised" if tc.recognised_source else "UNKNOWN"),
                evidence="; ".join(tc.divergences) or
                         "matches ros/data/universes.py",
                blocking=False))
            c.append(Criterion(
                "the fund can obtain this universe",
                not tc.missing,
                value=tc.computed_resolution,
                threshold="direct or sleeve_proxy",
                evidence=(f"missing: {', '.join(tc.missing)}" if tc.missing
                          else f"{len(tc.held)} instruments held")))
            c.append(Criterion(
                "translation risks acknowledged", bool(tc.caveats),
                value=len(tc.caveats), threshold=">=1", blocking=False,
                evidence="a translation with nothing to lose has not been examined"))

    # ---- is Gate A verifying, or designing? ------------------------------
    # These three exist so a human at Gate A confirms a plan rather than filling
    # one in. Stage 02 is where the work happens; if the card cannot say what
    # dataset it wants, which securities, and what will be run, it is not done.
    dp = getattr(card, "data_plan", None)
    if dp is None:
        c.append(_missing(
            "dataset designed from the paper", "a data plan",
            "the card names no dataset of its own, so it can only shop from what "
            "the fund already holds -- and a paper reshaped to fit the available "
            "data is a different paper"))
    else:
        errs = dp.validate()
        c.append(Criterion(
            "dataset designed from the paper", not errs,
            value=f"{len(dp.ideal)} field(s), "
                  f"{sum(1 for d in dp.ideal if d.minimum_viable)} minimum-viable",
            evidence="; ".join(errs) or
                     " ".join(dp.granularity_verdict.split())[:140]))
        c.append(Criterion(
            "alternatives were rejected, not skipped",
            len(dp.rejected_alternatives) >= 1,
            value=len(dp.rejected_alternatives), threshold=">=1", blocking=False,
            evidence="; ".join(r.get("option", "?") for r in
                               dp.rejected_alternatives)
                     or "a dataset with no rejected alternative was assumed"))

    sel = getattr(card, "selection", None)
    if sel is None or not sel.rule.strip():
        c.append(_missing(
            "securities selection stated", "a rule",
            "a selection nobody can re-derive on another date is not a strategy"))
    else:
        c.append(Criterion(
            "securities selection stated", True,
            value=(f"{len(sel.explicit_securities)} named"
                   if sel.explicit_securities else "rule only"),
            evidence=" ".join(sel.rule.split())[:150]))
        if sel.explicit_securities:
            verified = sel.verified_against not in ("", "UNVERIFIED")
            c.append(Criterion(
                "named securities are verified", verified,
                value=sel.verified_against or "NOTHING",
                threshold="not UNVERIFIED",
                evidence=(f"{len(sel.explicit_securities)} names as of "
                          f"{sel.as_of or 'no date'}") if verified else
                         "a list recalled rather than checked is plausible and "
                         "unverifiable, which is worse than no list"))

    bp = getattr(card, "backtest_plan", None)
    if bp is None:
        c.append(_missing(
            "the run is specified", "a backtest plan",
            "without it Gate A is designing the run rather than verifying it: "
            "the window, the warmup, the benchmarks and the failure criteria are "
            "all still open"))
    else:
        errs = bp.validate()
        c.append(Criterion(
            "the run is specified", not errs,
            value=f"{bp.sample_start} -> {bp.sample_end}",
            evidence="; ".join(errs) or
                     f"{len(bp.benchmarks)} benchmark(s), "
                     f"{len(bp.must_beat)} must-beat"))
        c.append(Criterion(
            "failure is defined before the run",
            bool(bp.failure_looks_like.strip()),
            evidence=" ".join(bp.failure_looks_like.split())[:150] or
                     "a plan that cannot fail is not a test, and a criterion "
                     "written after the numbers is not a criterion"))

    # ---- what is the model asking a human for? ---------------------------
    reqs = getattr(card, "data_requests", []) or []
    qs = getattr(card, "open_questions", []) or []
    blocking_reqs = [r for r in reqs if r.priority == "blocking"]
    blocking_qs = [q for q in qs if q.blocks_run]

    c.append(Criterion(
        "data requests carry a fallback",
        all(r.without_it.strip() for r in reqs),
        value=f"{len(reqs)} request(s)",
        evidence="; ".join(r.item for r in reqs if not r.without_it.strip())
                 or "every request says what happens if it is declined"))
    c.append(Criterion(
        "no request is blocking", not blocking_reqs,
        value=f"{len(blocking_reqs)} blocking", threshold=0,
        evidence="; ".join(r.item for r in blocking_reqs)
                 or "nothing is being waited on"))
    c.append(Criterion(
        "open questions carry a working assumption",
        all(q.what_i_assumed.strip() or q.blocks_run for q in qs),
        value=f"{len(qs)} question(s)", blocking=False,
        evidence="; ".join(q.question[:70] for q in qs
                           if not q.what_i_assumed.strip() and not q.blocks_run)
                 or "the run can proceed under stated assumptions"))
    c.append(Criterion(
        "no question blocks the run", not blocking_qs,
        value=f"{len(blocking_qs)} blocking", threshold=0,
        evidence="; ".join(q.question[:70] for q in blocking_qs)
                 or "no question stops work"))

    # ---- what exactly is the strategy? -----------------------------------
    st = getattr(card, "strategy", None)
    if st is None:
        c.append(_missing(
            "strategy reconstructed", "an executable restatement",
            "the card names a template but never states, in words a second "
            "person could implement from, what the paper's strategy IS"))
    else:
        errs = st.validate()
        c.append(Criterion(
            "strategy reconstructed to an executable level", not errs,
            value=st.signal_name or "(unnamed)",
            evidence="; ".join(errs) or " ".join(st.signal_definition.split())[:200]))
        c.append(Criterion(
            "long-only adaptation stated",
            not st.is_long_short or bool(st.long_only_adaptation.strip()),
            value="long-short source" if st.is_long_short else "already long-only",
            evidence=(" ".join(st.long_only_adaptation.split()) if st.is_long_short
                      else "paper is long-only; nothing to adapt")))
        c.append(Criterion(
            "the engine can express this strategy",
            st.engine_template != "NEEDS_NEW_TEMPLATE",
            value=st.engine_template or "(unset)",
            evidence=(" ".join(st.template_gap.split())
                      if st.engine_template == "NEEDS_NEW_TEMPLATE"
                      else "maps to a registered allocator template")))
        c.append(Criterion(
            "strategy read with confidence", st.confidence == "high",
            value=st.confidence, threshold="high", blocking=False,
            evidence=f"pages {st.evidence_pages}" if st.evidence_pages
                     else "no page citations -- unverifiable"))

    unresolved = card.unresolved_ambiguities
    c.append(Criterion(
        "all ambiguities resolved", not unresolved,
        value=len(unresolved), threshold=0,
        evidence="unresolved: " + ", ".join(a.field for a in unresolved) if unresolved
                 else f"{len(card.ambiguities)} ambiguities logged and resolved"))

    low = [a for a in card.material_ambiguities if a.confidence == "low"]
    c.append(Criterion(
        "no low-confidence material interpretation", not low,
        value=len(low), threshold=0, blocking=False,
        evidence="low-confidence: " + ", ".join(a.field for a in low) if low else "none"))

    c.append(Criterion(
        "data feasibility resolved", feasibility.can_proceed,
        value=feasibility.verdict, threshold="GO or GO_WITH_PROXY",
        evidence="; ".join(feasibility.blocking) or "no blocking data gaps"))

    if card.intent.mode == "replication":
        c.append(Criterion(
            "replication targets defined", bool(card.replication_targets),
            value=len(card.replication_targets), threshold=">=1",
            evidence="targets pinned to a single accounting basis"))
    else:
        c.append(Criterion(
            "transferred mechanism stated", bool(card.intent.transferred_mechanism),
            evidence=card.intent.transferred_mechanism or "MISSING"))
        c.append(Criterion(
            "broken source assumptions enumerated", bool(card.intent.broken_assumptions),
            value=len(card.intent.broken_assumptions), threshold=">=1", blocking=False,
            evidence="; ".join(card.intent.broken_assumptions) or "none listed -- suspicious"))

    if extraction_quality is not None:
        c.append(Criterion(
            "source text is machine-readable", extraction_quality.usable,
            evidence="; ".join(extraction_quality.warnings) or "clean extraction",
            blocking=True))
        c.append(Criterion(
            "equations verified against rendered page",
            extraction_quality.mean_math_density < 0.05,
            value=f"{extraction_quality.mean_math_density:.1%}", threshold="<5%",
            blocking=False,
            evidence="high math density: formulas were hand-checked, not trusted from text"))

    return GateResult("GATE A -- interpretation", "researcher", c)


def _missing(name: str, threshold: Any, why: str) -> Criterion:
    """A criterion whose evidence never arrived.

    It fails, and it fails *visibly*. The alternative -- omitting the row --
    makes GateResult.passed an `all()` over a shorter list, so a gate can report
    PASS precisely because the test that would have blocked it never ran. That
    is the one failure mode this whole file exists to prevent.
    """
    return Criterion(name, False, value="NOT COMPUTED", threshold=threshold,
                     evidence=f"NO EVIDENCE: {why}")


def gate_b(card, research: Dict[str, Any], portfolio: Dict[str, Any],
           thresholds: Optional[Dict[str, float]] = None) -> GateResult:
    """GATE B -- INVESTMENT DECISION. Owned by PM / IC.

    Deliberately strict on orthogonality and incremental IR: those are the two
    criteria that separate 'a real effect' from 'a real effect we are already paid for'.
    """
    t = {"min_oos_sharpe": 0.30, "max_corr_to_book": 0.80, "min_delta_ir": 0.05,
         "min_dsr": 0.95, "max_turnover": 4.0, "min_alpha_t": 2.0}
    t.update(thresholds or {})
    c: List[Criterion] = []

    # Every criterion below appears on the sheet whether or not its evidence
    # arrived. See _missing(): a checklist that quietly gets shorter is worse
    # than one that fails, because a human signing it cannot see what is absent.
    dsr = research.get("deflated_sharpe", {})
    if "deflated_sharpe_prob" in dsr:
        c.append(Criterion(
            "deflated Sharpe clears selection bias",
            dsr["deflated_sharpe_prob"] >= t["min_dsr"],
            value=f"{dsr['deflated_sharpe_prob']:.2f}", threshold=t["min_dsr"],
            evidence=dsr.get("interpretation", "")))
    else:
        c.append(_missing("deflated Sharpe clears selection bias", t["min_dsr"],
                          dsr.get("error", "the deflated Sharpe calculation did not run")))

    oos = research.get("oos_min_sharpe")
    if oos is not None:
        c.append(Criterion(
            "positive Sharpe in every out-of-sample window",
            oos >= t["min_oos_sharpe"],
            value=f"{oos:.2f}", threshold=t["min_oos_sharpe"],
            evidence="worst walk-forward window"))
    else:
        c.append(_missing("positive Sharpe in every out-of-sample window",
                          t["min_oos_sharpe"],
                          "the walk-forward analysis did not run"))

    sig = research.get("bootstrap_p_not_positive")
    if sig is not None:
        c.append(Criterion(
            "advantage over benchmark is significant",
            sig <= 0.05, value=f"{sig:.3f}", threshold="<=0.05",
            evidence="paired stationary-bootstrap P(Sharpe difference <= 0)"))
    else:
        c.append(_missing("advantage over benchmark is significant", "<=0.05",
                          "the paired bootstrap did not run"))

    # These two compare against what the fund already runs. With an empty book
    # there is genuinely nothing to compare to -- that is not a failure, but it
    # is also not a pass, so it is shown as an unmet warning rather than left
    # off the sheet for a human to not notice.
    corr = portfolio.get("max_corr_to_book")
    if corr is not None:
        c.append(Criterion(
            "differentiated from existing book",
            corr <= t["max_corr_to_book"],
            value=f"{corr:.2f}", threshold=f"<={t['max_corr_to_book']}",
            evidence="max correlation to any existing signal"))
    else:
        c.append(Criterion(
            "differentiated from existing book", False, blocking=False,
            value="NO COMPARISON", threshold=f"<={t['max_corr_to_book']}",
            evidence="nothing else in the book to compare against"))

    dir_ = portfolio.get("best_delta_ir")
    if dir_ is not None:
        c.append(Criterion(
            "improves the book's information ratio",
            dir_ >= t["min_delta_ir"],
            value=f"{dir_:+.3f}", threshold=f">={t['min_delta_ir']}",
            evidence="incremental IR at a realistic sleeve size"))
    else:
        c.append(Criterion(
            "improves the book's information ratio", False, blocking=False,
            value="NO COMPARISON", threshold=f">={t['min_delta_ir']}",
            evidence="nothing else in the book to measure an increment against"))

    at = portfolio.get("alpha_t_hac")
    if at is not None:
        c.append(Criterion(
            "alpha survives the factor fingerprint",
            abs(at) >= t["min_alpha_t"],
            value=f"{at:.2f}", threshold=f"|t|>={t['min_alpha_t']}",
            evidence="HAC t-stat of alpha vs known factor sleeves"))
    else:
        # A test that could not be run is NOT a test that passed. Dropping the
        # row would shrink the checklist silently and let `passed` go True
        # having never asked the question that matters most on this desk --
        # whether the alpha is anything more than sleeves the fund already owns.
        c.append(Criterion(
            "alpha survives the factor fingerprint", False,
            value="NOT COMPUTED", threshold=f"|t|>={t['min_alpha_t']}",
            evidence=portfolio.get("alpha_t_hac_error",
                                   "the factor regression did not run")))

    mand = portfolio.get("mandate", {})
    if mand:
        c.append(Criterion(
            "implementable within mandate", bool(mand.get("passes")),
            evidence="; ".join(mand.get("violations", [])) or "no mandate violations"))

    to = portfolio.get("annual_turnover")
    if to is not None:
        c.append(Criterion(
            "turnover within operational tolerance", to <= t["max_turnover"],
            value=f"{to:.0%}", threshold=f"<={t['max_turnover']:.0%}", blocking=False,
            evidence="annualised two-way turnover"))

    return GateResult("GATE B -- investment decision", "PM / IC", c)


@dataclass
class PromotionRung:
    rung: str
    criteria: List[Criterion] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.criteria) and all(c.passed for c in self.criteria if c.blocking)


def evaluate_ladder(card, rung_criteria: Dict[str, List[Criterion]]) -> Dict[str, Any]:
    """Walk the ladder in order, stopping at the first rung that fails.

    An adaptation card starts at INDIA_VALIDATED: REPLICATED is marked N/A rather
    than passed, so an adaptation can never be reported as a replication.
    """
    results: List[Dict[str, Any]] = []
    attained: Optional[str] = None
    stopped_at: Optional[str] = None

    for rung in LADDER:
        if rung == "REPLICATED" and card.intent.mode == "adaptation":
            results.append({"rung": rung, "status": "N/A",
                            "note": "adaptation card: replication is a different question",
                            "criteria": []})
            continue
        crits = rung_criteria.get(rung)
        if crits is None:
            results.append({"rung": rung, "status": "NOT_EVALUATED", "criteria": []})
            if stopped_at is None:
                stopped_at = rung
            break
        r = PromotionRung(rung, crits)
        results.append({
            "rung": rung, "status": "PASS" if r.passed else "FAIL",
            "criteria": [asdict(c) for c in crits],
            "failed": [c.name for c in crits if not c.passed and c.blocking],
        })
        if r.passed:
            attained = rung
        else:
            stopped_at = rung
            break

    return {
        "card_id": card.paper.id,
        "mode": card.intent.mode,
        "attained_rung": attained,
        "stopped_at": stopped_at,
        "ladder": results,
    }


def render_ladder(lad: Dict[str, Any]) -> str:
    lines = ["STEP 08 -- PROMOTION LADDER",
             f"  card: {lad['card_id']} ({lad['mode']})",
             f"  attained: {lad['attained_rung'] or 'NONE'}   stopped at: {lad['stopped_at'] or '--'}",
             ""]
    for r in lad["ladder"]:
        lines.append(f"  {r['rung']:<18} {r['status']}")
        if r.get("note"):
            lines.append(f"      {r['note']}")
        for c in r.get("criteria", []):
            mk = "PASS" if c["passed"] else ("FAIL" if c["blocking"] else "warn")
            v = "" if c["value"] is None else f"  [{c['value']} vs {c['threshold']}]"
            lines.append(f"      [{mk:>4}] {c['name']}{v}")
            if c.get("evidence"):
                lines.append(f"             {c['evidence']}")
    return "\n".join(lines)
